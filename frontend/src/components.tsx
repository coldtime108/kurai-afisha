import { useEffect, useRef, type ReactNode } from "react";
import { ArrowUpRight, Bookmark, Check, Clock, MapPin, X } from "lucide-react";
import type { CultureEvent } from "./types";

export const labels: Record<string, string> = {
  concert: "Концерт",
  theatre: "Театр",
  exhibition: "Выставка",
  festival: "Фестиваль",
  cinema: "Кино",
  excursion: "Экскурсия",
  other: "Событие",
};
export const fmtDate = (value: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Asia/Yekaterinburg",
  }).format(new Date(value));
export const fmtTime = (value: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Yekaterinburg",
  }).format(new Date(value));
export function price(event: CultureEvent) {
  if (event.is_free) return "Бесплатно";
  if (event.price_min === null) return "Цена у организатора";
  return `${event.price_max === event.price_min ? "" : "от "}${event.price_min.toLocaleString("ru-RU")} ₽`;
}
export function KuraiMark({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={className}
      fill="none"
      aria-hidden="true"
    >
      <circle cx="32" cy="32" r="30.5" stroke="currentColor" />
      <path
        d="M32 51V17M32 43 12 32M32 37 17 20M32 32 24 12M32 32 40 12M32 37 47 20M32 43 52 32"
        stroke="currentColor"
        strokeWidth="2"
      />
      {[
        [12, 32],
        [17, 20],
        [24, 12],
        [32, 10],
        [40, 12],
        [47, 20],
        [52, 32],
      ].map(([x, y]) => (
        <circle key={x} cx={x} cy={y} r="3.3" fill="currentColor" />
      ))}
    </svg>
  );
}
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    el?.showModal();
    return () => el?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby="modal-title"
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-head">
        <h2 id="modal-title">{title}</h2>
        <button
          className="icon-button"
          aria-label="Закрыть окно"
          onClick={onClose}
        >
          <X />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function EventCard({
  event,
  saved,
  onSave,
  onOpen,
}: {
  event: CultureEvent;
  saved: boolean;
  onSave: () => void;
  onOpen: () => void;
}) {
  const genre = event.tags.includes("опера")
    ? "Опера"
    : event.tags.includes("балет")
      ? "Балет"
      : event.category === "theatre"
        ? "Спектакль"
        : labels[event.category] || "Событие";
  const variant = event.tags.includes("балет") ? "ballet" : event.category;
  const dateParts = new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    timeZone: "Asia/Yekaterinburg",
  }).formatToParts(new Date(event.date_start));
  const sourceHost = new URL(event.source_url).hostname.replace(/^www\./, "");
  return (
    <article className="event-card">
      <div className={`event-art poster-${variant}`} aria-hidden="true">
        <span className="poster-genre">{genre}</span>
        <div className="poster-date">
          <span className="poster-day">
            {dateParts.find((part) => part.type === "day")?.value}
          </span>
          <span className="poster-month">
            {dateParts.find((part) => part.type === "month")?.value}
            <span>{event.city}</span>
          </span>
        </div>
        <KuraiMark className="poster-seal" />
      </div>
      <button
        className={`save-button ${saved ? "saved" : ""}`}
        onClick={onSave}
        aria-label={`${saved ? "Убрать из избранного" : "В избранное"}: ${event.title}`}
        aria-pressed={saved}
      >
        <Bookmark size={19} fill={saved ? "currentColor" : "none"} />
      </button>
      <div className="event-body">
        <div className="event-kicker">
          <span>{genre}</span>
          <span>
            {event.age_limit === null
              ? "Возраст уточняется"
              : `${event.age_limit}+`}
          </span>
        </div>
        <h3>
          <a
            href={`/events/${event.id}`}
            onClick={(e) => {
              e.preventDefault();
              onOpen();
            }}
          >
            {event.title}
          </a>
        </h3>
        <p className="event-date">
          <Clock size={14} />
          {fmtDate(event.date_start)}
          <span>·</span>
          {fmtTime(event.date_start)}
        </p>
        <p className="event-venue">
          <MapPin size={14} />
          <span>{event.venue}</span>
        </p>
        <div className="event-bottom">
          <span>{price(event)}</span>
          <button
            className="event-open"
            onClick={onOpen}
            aria-label={`О событии: ${event.title}`}
          >
            О событии
          </button>
        </div>
        <a
          className="source-note"
          href={event.source_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Источник · {sourceHost}
          <ArrowUpRight size={13} />
        </a>
      </div>
    </article>
  );
}
export function EventDetail({
  event,
  onBack,
  onFeedback,
  saved,
  onSave,
}: {
  event: CultureEvent;
  onBack: () => void;
  onFeedback: () => void;
  saved: boolean;
  onSave: () => void;
}) {
  return (
    <section id="catalog" className="detail">
      <button className="text-button" onClick={onBack}>
        ← Вернуться к афише
      </button>
      {event.status === "cancelled" && (
        <div className="cancelled" role="alert">
          Мероприятие отменено. Проверьте информацию у организатора.
        </div>
      )}
      <div className="detail-grid">
        <div className="detail-heading">
          <p className="eyebrow">
            {labels[event.category]} · {event.city}
            {event.age_limit !== null && (
              <span className="detail-age">{event.age_limit}+</span>
            )}
          </p>
          <h1>{event.title}</h1>
        </div>
        <aside className="detail-aside" aria-label="План посещения">
          <p className="eyebrow">Когда и где</p>
          <h2>{fmtDate(event.date_start)}</h2>
          <p className="detail-time">
            {fmtTime(event.date_start)}{" "}
            <small>время Башкортостана, UTC+5</small>
          </p>
          <p className="detail-venue">
            <MapPin size={18} />
            <span>{event.venue}</span>
          </p>
          <div className="detail-booking">
            <span>Стоимость билета</span>
            <strong>
              {event.is_free
                ? "Бесплатно"
                : event.price_min === null
                  ? "Уточните у организатора"
                  : event.price_max && event.price_max !== event.price_min
                    ? `${event.price_min.toLocaleString("ru-RU")}–${event.price_max.toLocaleString("ru-RU")} ₽`
                    : price(event)}
            </strong>
          </div>
          <a
            className="button primary"
            href={event.org_link || event.source_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            К организатору
            <ArrowUpRight size={18} />
          </a>
          <button
            className="button secondary"
            onClick={onSave}
            aria-pressed={saved}
          >
            <Bookmark size={18} fill={saved ? "currentColor" : "none"} />
            {saved ? "Сохранено" : "Сохранить событие"}
          </button>
          <dl>
            <div className="detail-address">
              <dt>Адрес</dt>
              <dd>
                {event.city}, {event.address}
              </dd>
            </div>
            <div>
              <dt>Возраст</dt>
              <dd>
                {event.age_limit === null
                  ? "Не указан в источнике"
                  : `${event.age_limit}+`}
              </dd>
            </div>
            <div>
              <dt>Продолжительность</dt>
              <dd>
                {event.duration_min
                  ? `${event.duration_min} мин`
                  : "Не указана в источнике"}
              </dd>
            </div>
            <div className="detail-language">
              <dt>Язык</dt>
              <dd>{event.language || "Не указан в источнике"}</dd>
            </div>
          </dl>
          <p className="fine-print">
            Цена и наличие билетов могут измениться. Покупка — на сайте
            организатора.
          </p>
        </aside>
        <div className="detail-content">
          <h2>О событии</h2>
          <p className="detail-description">{event.description}</p>
          <div className="tags">
            {event.tags.map((t) => (
              <span key={t}>{t}</span>
            ))}
          </div>
          <div className="detail-source">
            <Check size={18} />
            <div>
              <strong>Факты из афиши учреждения</strong>
              <p>
                Сведения проверены{" "}
                {event.verified_at ? fmtDate(event.verified_at) : "—"}. Перед
                посещением сверьтесь с организатором.
              </p>
            </div>
          </div>
          <h2>Источники</h2>
          {event.sources.map((s) => (
            <a
              className="source-link"
              key={s.url}
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {new URL(s.url).hostname}
              <ArrowUpRight size={17} />
            </a>
          ))}
          <button className="text-button" onClick={onFeedback}>
            Сообщить об изменении или ошибке
          </button>
        </div>
      </div>
    </section>
  );
}
