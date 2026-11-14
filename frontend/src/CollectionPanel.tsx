import { useEffect, useState } from "react";
import { api } from "./api";
import { fmtDate, fmtTime } from "./components";
import type { CultureEvent } from "./types";

export type SourceProposal = {
  id: string;
  source_id: string;
  event_id: string | null;
  payload: Partial<CultureEvent> & {
    title: string;
    date_start: string;
    source_url: string;
  };
  issues: string[];
  fingerprint: string;
};
type SourceResult = {
  source_id: string;
  name: string;
  found: number;
  added: number;
  matched: number;
  proposals: number;
  unchanged: number;
  past: number;
  errors: { url: string; message: string }[];
};
type Run = {
  id: string;
  status: string;
  summary: SourceResult[];
  started_at: string;
  finished_at: string | null;
};
type Status = {
  scheduled: boolean;
  interval_hours: number;
  sources: { id: string; name: string; url: string; cities?: string[] }[];
  latest: Run | null;
};

export function CollectionPanel({
  token,
  version,
  onReview,
  onChanged,
}: {
  token: string;
  version: number;
  onReview: (item: SourceProposal) => void;
  onChanged: () => Promise<void>;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [items, setItems] = useState<SourceProposal[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const headers = { Authorization: `Bearer ${token}` };
  async function refresh() {
    const [next, proposals] = await Promise.all([
      api<Status>("/api/v1/admin/collection", { headers }),
      api<SourceProposal[]>("/api/v1/admin/collection/items", { headers }),
    ]);
    setStatus(next);
    setItems(proposals);
    setRun(next.latest);
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [token, version]);
  const activeId =
    run && ["pending", "running"].includes(run.status) ? run.id : null;
  useEffect(() => {
    if (!activeId) return;
    let stopped = false;
    let timer: number;
    async function poll() {
      try {
        const next = await api<Run>(
          `/api/v1/admin/collection/runs/${activeId}`,
          { headers },
        );
        if (stopped) return;
        setRun(next);
        if (["pending", "running"].includes(next.status))
          timer = window.setTimeout(poll, 2000);
        else {
          await refresh();
          await onChanged();
        }
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    }
    timer = window.setTimeout(poll, 1500);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [activeId, token]);
  async function start() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ id: string }>("/api/v1/admin/collection", {
        method: "POST",
        headers,
      });
      setRun({
        id: result.id,
        status: "pending",
        summary: [],
        started_at: new Date().toISOString(),
        finished_at: null,
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const names: Record<string, string> = {
    pending: "Ожидает запуска",
    running: "Собираем афиши…",
    complete: "Сбор завершён",
    partial: "Сбор завершён с замечаниями",
    interrupted: "Запуск прерван",
    failed: "Не удалось завершить сбор",
  };
  return (
    <section className="collection-panel" aria-label="Сбор афиш">
      <div className="admin-row">
        <h2>Источники афиши</h2>
        <button
          className="button primary"
          disabled={busy || Boolean(activeId)}
          onClick={start}
        >
          {busy || activeId ? "Собираем…" : "Обновить афиши"}
        </button>
      </div>
      <p>
        Новые события поступают в черновики. Изменения проверенных карточек
        нужно сверить перед сохранением. Явная отмена сразу скрывает событие из
        поиска.
      </p>
      <p>
        {status?.scheduled
          ? `Автоматическое обновление — раз в ${status.interval_hours} часов.`
          : "Сейчас включён ручной запуск сбора."}
      </p>
      {status?.sources.map((source) => (
        <p key={source.id}>
          <a href={source.url} target="_blank" rel="noopener noreferrer">
            {source.name} ↗
          </a>
          {source.cities?.length ? (
            <span className="fine-print"> — {source.cities.join(" · ")}</span>
          ) : null}
        </p>
      ))}
      {error && (
        <p className="admin-error" role="alert">
          {error}
        </p>
      )}
      {run && (
        <div role="status">
          <strong>{names[run.status] || run.status}</strong>
          <p>
            {fmtDate(run.started_at)} · {fmtTime(run.started_at)} · время
            Башкортостана
          </p>
          {run.summary.map((result) => (
            <div key={result.source_id}>
              <h3>{result.name}</h3>
              <p>
                Найдено: {result.found} · Новых черновиков: {result.added} ·
                Совпало: {result.matched} · Без изменений: {result.unchanged} ·
                Предложений правки: {result.proposals} · Прошедших:{" "}
                {result.past}
              </p>
              {result.errors.length > 0 && (
                <details>
                  <summary>Замечания: {result.errors.length}</summary>
                  <ul>
                    {result.errors.map((e, i) => (
                      <li key={i}>
                        <a
                          href={e.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Источник
                        </a>
                        : {e.message}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
      <h3>На сверку · {items.length}</h3>
      {!items.length && <p>Новых карточек и изменений для сверки нет.</p>}
      {items.map((item) => (
        <details className="source-proposal" key={item.id}>
          <summary>
            {item.payload.title} · {fmtDate(item.payload.date_start)}
          </summary>
          <p>
            {item.payload.city} · {item.payload.venue} ·{" "}
            {fmtTime(item.payload.date_start)}
          </p>
          <p>
            Цена:{" "}
            {item.payload.price_min == null
              ? "не указана"
              : `${item.payload.price_min} ₽${item.payload.price_max == null ? " и выше" : ` — ${item.payload.price_max} ₽`}`}{" "}
            · Возраст:{" "}
            {item.payload.age_limit == null
              ? "не указан"
              : `${item.payload.age_limit}+`}
          </p>
          {item.issues.length > 0 && (
            <ul>
              {item.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          )}
          <p>
            <a
              href={item.payload.source_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Открыть источник ↗
            </a>
          </p>
          <button className="button secondary" onClick={() => onReview(item)}>
            Сверить в редакторе
          </button>
        </details>
      ))}
    </section>
  );
}
