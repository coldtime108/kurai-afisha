import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowUpRight,
  Check,
  CornerDownLeft,
  RotateCcw,
  X,
} from "lucide-react";
import { api } from "./api";
import { fmtDate, fmtTime, price, KuraiMark } from "./components";
import { deviceKey } from "./device";
import type { CultureEvent } from "./types";
import "./assistant.css";

type Reply = {
  request_id: string;
  mode: "model" | "fallback" | "confirmation";
  message: string;
  cards: { event: CultureEvent; reasons: string[] }[];
  filters: Record<string, string | number | boolean>;
  total: number;
  has_more: boolean;
  suggestions: string[];
  pending: { token: string; kind: string; summary: string } | null;
};
type Turn = { user?: string; reply?: Reply };

export function AssistantPanel({ onOpen }: { onOpen: (id: string) => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const latest = turns.at(-1)?.reply;

  useEffect(() => {
    api<{ enabled: boolean }>("/api/v1/assistant/status")
      .then((s) => setEnabled(s.enabled))
      .catch(() => setEnabled(false));
  }, []);
  useEffect(() => {
    if (turns.length)
      end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [turns.length]);

  function headers() {
    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${deviceKey(true)}`,
    };
  }
  async function send(e?: FormEvent, override?: string) {
    e?.preventDefault();
    const message = (override ?? text).trim();
    if (!message || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Reply>("/api/v1/assistant/messages", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ message }),
      });
      setTurns((previous) =>
        [...previous, { user: message, reply: result }].slice(-12),
      );
      setText("");
    } catch (e) {
      setError(
        e instanceof DOMException
          ? "Браузер не разрешает сохранить ключ диалога. Откройте сайт в отдельном окне."
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  }
  async function confirmAction(accept: boolean) {
    if (!latest?.pending || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Reply>("/api/v1/assistant/confirm", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ token: latest.pending.token, accept }),
      });
      setTurns((previous) => [...previous, { reply: result }]);
      if (accept) window.dispatchEvent(new Event("kurai-subscription-changed"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function reset() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/v1/assistant/dialog", {
        method: "DELETE",
        headers: headers(),
      });
      setTurns([]);
      setText("");
      input.current?.focus();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      id="assistant"
      className="assistant-panel"
      aria-labelledby="assistant-title"
    >
      <div className="assistant-intro">
        <KuraiMark className="assistant-mark" />
        <p className="eyebrow">Подборка в диалоге</p>
        <h2 id="assistant-title">
          Планы начинаются
          <br />с пожелания
        </h2>
        <p>
          Расскажите, куда хочется сходить. Уточним детали и найдём события в
          проверенной афише.
        </p>
        <span className="assistant-provider">
          {enabled === null
            ? "Проверяем подключение…"
            : enabled
              ? "ИИ-помощник · NVIDIA"
              : "Обычный поиск · резервный режим"}
        </span>
      </div>
      <div className="assistant-workspace">
        <div className="assistant-toolbar">
          <span>Курай · ваш культурный проводник</span>
          <button
            type="button"
            onClick={reset}
            disabled={busy}
            title="Удалить диалог и его диагностические записи"
          >
            <RotateCcw size={14} />
            Новый диалог
          </button>
        </div>
        {turns.length > 0 && (
          <div
            className="assistant-log"
            role="log"
            aria-label="Диалог с помощником"
            aria-live="polite"
            aria-relevant="additions"
          >
            {turns.map((turn, index) => (
              <div
                className="assistant-turn"
                key={turn.reply?.request_id || index}
              >
                {turn.user && (
                  <p className="assistant-user">
                    <span className="sr-only">Вы: </span>
                    {turn.user}
                  </p>
                )}
                {turn.reply && (
                  <div className="assistant-answer">
                    <small>
                      {turn.reply.mode === "fallback"
                        ? "Обычный поиск"
                        : "Курай"}
                    </small>
                    <p>{turn.reply.message}</p>
                    {turn.reply.cards.map(({ event, reasons }) => (
                      <article className="assistant-event" key={event.id}>
                        <div className="assistant-event-date">
                          <b>
                            {new Date(event.date_start).toLocaleDateString(
                              "ru-RU",
                              {
                                day: "numeric",
                                timeZone: "Asia/Yekaterinburg",
                              },
                            )}
                          </b>
                          <span>
                            {new Date(event.date_start).toLocaleDateString(
                              "ru-RU",
                              {
                                month: "short",
                                timeZone: "Asia/Yekaterinburg",
                              },
                            )}
                          </span>
                        </div>
                        <div>
                          <a
                            className="assistant-event-title"
                            href={`/events/${event.id}`}
                            onClick={(e) => {
                              e.preventDefault();
                              onOpen(event.id);
                            }}
                          >
                            {event.title}
                            <ArrowUpRight size={16} />
                          </a>
                          {event.status === "cancelled" && (
                            <strong>Событие отменено</strong>
                          )}
                          <p>
                            {event.city} · {event.venue}
                          </p>
                          <p>
                            {fmtDate(event.date_start)} ·{" "}
                            {fmtTime(event.date_start)} · UTC+5
                          </p>
                          <p>
                            {price(event)} ·{" "}
                            {event.age_limit === null
                              ? "Возраст не указан"
                              : `${event.age_limit}+`}
                          </p>
                          {reasons.length > 0 && (
                            <details>
                              <summary>Почему подходит</summary>
                              <ul>
                                {reasons.map((r) => (
                                  <li key={r}>{r}</li>
                                ))}
                              </ul>
                            </details>
                          )}
                          <a
                            className="assistant-source"
                            href={event.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Источник события <ArrowUpRight size={12} />
                          </a>
                        </div>
                      </article>
                    ))}
                    {turn.reply.suggestions.length > 0 && (
                      <ul className="assistant-suggestions">
                        {turn.reply.suggestions.map((suggestion) => (
                          <li key={suggestion}>{suggestion}</li>
                        ))}
                      </ul>
                    )}
                    {turn.reply === latest && turn.reply.pending && (
                      <div className="assistant-confirm">
                        <p>{turn.reply.pending.summary}</p>
                        <button
                          className="button primary"
                          disabled={busy}
                          onClick={() => confirmAction(true)}
                        >
                          <Check size={16} />
                          Подтвердить
                        </button>
                        <button
                          className="button secondary"
                          disabled={busy}
                          onClick={() => confirmAction(false)}
                        >
                          <X size={16} />
                          Отмена
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            <div ref={end} />
          </div>
        )}
        {!turns.length && (
          <div className="assistant-examples">
            <p>Можно начать, например, так:</p>
            {[
              "Спектакль в Стерлитамаке 14 ноября до 800 рублей",
              "Куда сходить с ребёнком в Уфе?",
            ].map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => {
                  setText(example);
                  input.current?.focus();
                }}
              >
                {example}
                <ArrowUpRight size={15} />
              </button>
            ))}
          </div>
        )}
        {latest?.cards.length ? (
          <div className="assistant-refinements">
            <button
              disabled={busy}
              onClick={() => send(undefined, "Сначала дешёвые")}
            >
              Подешевле
            </button>
            <button
              disabled={busy}
              onClick={() => send(undefined, "Только бесплатные")}
            >
              Бесплатные
            </button>
            {latest.has_more && (
              <button
                disabled={busy}
                onClick={() => send(undefined, "Покажи ещё")}
              >
                Показать ещё
              </button>
            )}
          </div>
        ) : null}
        <form className="assistant-form" onSubmit={send}>
          <label className="sr-only" htmlFor="assistant-message">
            Ваш запрос к афише
          </label>
          <textarea
            id="assistant-message"
            ref={input}
            rows={2}
            maxLength={1000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Город, дата, настроение, бюджет…"
            disabled={busy}
          />
          <button
            className="button primary"
            type="submit"
            disabled={busy || !text.trim()}
          >
            <span>{busy ? "Ищем…" : "Подобрать"}</span>
            <CornerDownLeft size={17} />
          </button>
        </form>
        <p className="assistant-status" role="status">
          {busy
            ? "Разбираем условия и проверяем афишу…"
            : "Можно уточнять пожелания следующим сообщением."}
        </p>
        {error && (
          <p className="assistant-error" role="alert">
            {error}
          </p>
        )}
        <details className="assistant-privacy">
          <summary>О данных и работе помощника</summary>
          <p>
            Модель NVIDIA разбирает текст запроса. Карточки, время и цены берём
            из нашей базы. Не указывайте личные данные и ключи доступа. Память
            диалога хранится до 24 часов, диагностические записи — до 7 дней;
            «Новый диалог» удаляет их сразу. При сбое модели работает обычный
            поиск. Подписка и обращение сохраняются только после отдельного
            подтверждения.
          </p>
        </details>
      </div>
    </section>
  );
}
