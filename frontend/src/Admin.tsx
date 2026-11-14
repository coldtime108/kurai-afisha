import { useState, type FormEvent } from "react";
import { api } from "./api";
import { fmtDate, fmtTime, KuraiMark } from "./components";
import type { CultureEvent } from "./types";
import { EventEditor } from "./EventEditor";
import { CollectionPanel, type SourceProposal } from "./CollectionPanel";
type Audit = {
  id: number;
  action: string;
  entity_id: string;
  actor: string;
  created_at: string;
  changes: unknown;
};
type Report = {
  added: number;
  updated: number;
  skipped: number;
  rejected: number;
  errors: { row: number; reason: string }[];
};
type Message = {
  id: string;
  event_id: string | null;
  message: string;
  created_at: string;
};
export function Admin() {
  const [token, setToken] = useState(""),
    [connected, setConnected] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [rows, setRows] = useState<CultureEvent[]>([]),
    [audit, setAudit] = useState<Audit[]>([]),
    [messages, setMessages] = useState<Message[]>([]),
    [report, setReport] = useState<Report | null>(null),
    [json, setJson] = useState("");
  const [editing, setEditing] = useState<CultureEvent | null | undefined>(
    undefined,
  );
  const [sourceReview, setSourceReview] = useState<SourceProposal | null>(null);
  const [collectionVersion, setCollectionVersion] = useState(0);
  const headers = { Authorization: `Bearer ${token}` };
  async function refresh() {
    const [events, changes, feedback] = await Promise.all([
      api<CultureEvent[]>("/api/v1/admin/events", { headers }),
      api<Audit[]>("/api/v1/admin/audit", { headers }),
      api<Message[]>("/api/v1/admin/feedback", { headers }),
    ]);
    setRows(events);
    setAudit(changes);
    setMessages(feedback);
  }
  async function login(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await refresh();
      setConnected(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function status(event: CultureEvent, next: string) {
    if (!confirm(`Изменить статус «${event.title}» на «${next}»?`)) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/admin/events/${event.id}/status`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ status: next }),
      });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function importData(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<Report>("/api/v1/admin/import", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ rows: JSON.parse(json) }),
      });
      setReport(result);
      await refresh();
    } catch (e) {
      setError(
        e instanceof SyntaxError
          ? "Проверьте JSON: нужен массив карточек"
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }
  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<Report>("/api/v1/admin/import-file", {
        method: "POST",
        headers,
        body: new FormData(e.currentTarget),
      });
      setReport(result);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function reviewSource(item: SourceProposal) {
    const current = rows.find((row) => row.id === item.event_id);
    if (!current) {
      setError("Карточка не найдена. Обновите кабинет.");
      return;
    }
    const known = Object.fromEntries(
      Object.entries(item.payload).filter(
        ([, value]) => value !== null && value !== undefined,
      ),
    );
    const proposal = {
      ...current,
      ...known,
      status: current.status,
    } as CultureEvent;
    if (
      new Date(proposal.date_start).getTime() !==
        new Date(current.date_start).getTime() &&
      item.payload.date_end == null
    )
      proposal.date_end = null;
    setSourceReview(item);
    setEditing(proposal);
  }
  async function saved() {
    await refresh();
    if (sourceReview) {
      await api(`/api/v1/admin/collection/items/${sourceReview.id}/reviewed`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ fingerprint: sourceReview.fingerprint }),
      });
      setSourceReview(null);
      setCollectionVersion((v) => v + 1);
    }
  }
  return (
    <main className="admin">
      <header>
        <a href="/" className="brand">
          <KuraiMark />
          <span>
            курай<small>КАБИНЕТ МОДЕРАТОРА</small>
          </span>
        </a>
        <a href="/">← К афише</a>
      </header>
      {!connected ? (
        <section className="admin-login">
          <h1>Проверяем, затем публикуем</h1>
          <p>
            Введите ключ модератора, настроенный в окружении сервера. Ключ
            хранится только в памяти этой страницы.
          </p>
          <form onSubmit={login}>
            <label htmlFor="admin-key">Ключ доступа</label>
            <input
              id="admin-key"
              type="password"
              autoComplete="off"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
            <button className="button primary" disabled={busy}>
              Открыть кабинет
            </button>
          </form>
          {error && (
            <p className="admin-error" role="alert">
              {error}
            </p>
          )}
        </section>
      ) : (
        <>
          <div className="admin-row">
            <h1>Кабинет модератора</h1>
            <button
              className="button secondary"
              onClick={() => {
                setToken("");
                setConnected(false);
                setRows([]);
                setAudit([]);
                setMessages([]);
                setJson("");
                setReport(null);
              }}
            >
              Выйти
            </button>
          </div>
          {error && (
            <p className="admin-error" role="alert">
              {error}
            </p>
          )}
          <CollectionPanel
            token={token}
            version={collectionVersion}
            onReview={reviewSource}
            onChanged={refresh}
          />
          <section>
            <div className="admin-row">
              <h2>События · {rows.length}</h2>
              <button
                className="button primary"
                onClick={() => setEditing(null)}
              >
                Добавить событие
              </button>
            </div>
            <p className="admin-section-note">
              Черновики скрыты от посетителей. Отменённые исчезают из поиска и
              остаются по прямой ссылке с пометкой.
            </p>
            <div className="admin-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Событие</th>
                    <th>Время</th>
                    <th>Статус</th>
                    <th>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.title}
                        <small>{row.venue}</small>
                        <a
                          href={row.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Источник ↗
                        </a>
                      </td>
                      <td>
                        {fmtDate(row.date_start)}
                        <br />
                        {fmtTime(row.date_start)}
                      </td>
                      <td>
                        {
                          {
                            published: "Опубликовано",
                            draft: "Черновик",
                            cancelled: "Отменено",
                          }[row.status]
                        }
                      </td>
                      <td>
                        <button onClick={() => setEditing(row)}>
                          Редактировать
                        </button>
                        {(["published", "draft", "cancelled"] as const)
                          .filter((s) => s !== row.status)
                          .map((s) => (
                            <button
                              key={s}
                              disabled={busy}
                              onClick={() => status(row, s)}
                            >
                              {
                                {
                                  published: "Опубликовать",
                                  draft: "В черновики",
                                  cancelled: "Отменить",
                                }[s]
                              }
                            </button>
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section>
            <h2>Импорт CSV / JSON</h2>
            <p>
              До 1000 строк, до 2 МБ, кодировка UTF-8. Повторный импорт не
              создаёт копий.{" "}
              <a
                href="https://github.com/coldtime108/kurai-afisha/blob/main/data/reviewed-events.json"
                target="_blank"
                rel="noopener noreferrer"
              >
                Пример структуры ↗
              </a>
            </p>
            <form onSubmit={upload} className="admin-row">
              <input
                name="file"
                type="file"
                accept=".json,.csv"
                required
                aria-label="Файл событий"
              />
              <button className="button primary" disabled={busy}>
                Импортировать файл
              </button>
            </form>
            {report && (
              <pre role="status">
                Добавлено: {report.added} · Обновлено: {report.updated} ·
                Пропущено: {report.skipped} · Отклонено: {report.rejected}
                {report.errors
                  .map((e) => `\nСтрока ${e.row}: ${e.reason}`)
                  .join("")}
              </pre>
            )}
            <details>
              <summary>Добавить или обновить карточки через JSON</summary>
              <p>
                Вставьте массив карточек. Новые события рекомендуется добавлять
                со статусом draft, затем проверять источник.
              </p>
              <form onSubmit={importData}>
                <label htmlFor="json-input">JSON-массив событий</label>
                <textarea
                  id="json-input"
                  required
                  value={json}
                  onChange={(e) => setJson(e.target.value)}
                  placeholder="[ { …карточка по схеме… } ]"
                />
                <button className="button secondary" disabled={busy}>
                  Проверить и импортировать
                </button>
              </form>
            </details>
          </section>
          <section>
            <h2>Обращения · {messages.length}</h2>
            <p>
              Срок хранения обращений — 30 дней. Очередь доступна только
              модератору.
            </p>
            {messages.map((m) => (
              <article key={m.id}>
                <strong>
                  {m.event_id ? `Событие ${m.event_id}` : "Общее обращение"}
                </strong>
                <p>{m.message}</p>
              </article>
            ))}
            {!messages.length && <p>Новых обращений нет.</p>}
          </section>
          <section>
            <h2>Журнал изменений</h2>
            <div className="admin-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Время</th>
                    <th>Автор</th>
                    <th>Действие</th>
                    <th>Запись</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.map((a) => (
                    <tr key={a.id}>
                      <td>{fmtDate(a.created_at)}</td>
                      <td>{a.actor}</td>
                      <td>{a.action}</td>
                      <td>
                        <details>
                          <summary>{a.entity_id}</summary>
                          <pre>{JSON.stringify(a.changes, null, 2)}</pre>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      {connected && editing !== undefined && (
        <EventEditor
          event={editing}
          token={token}
          onClose={() => {
            setEditing(undefined);
            setSourceReview(null);
          }}
          onSaved={saved}
        />
      )}
    </main>
  );
}
