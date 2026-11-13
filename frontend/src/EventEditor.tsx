import { useState, type FormEvent } from "react";
import { api } from "./api";
import { Modal } from "./components";
import type { CultureEvent } from "./types";

function localTime(value: string | null | undefined) {
  return value
    ? new Date(new Date(value).getTime() + 5 * 3600000)
        .toISOString()
        .slice(0, 16)
    : "";
}
type Props = {
  event: CultureEvent | null;
  token: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
};
export function EventEditor({ event, token, onClose, onSaved }: Props) {
  const [form, setForm] = useState({
    title: event?.title || "",
    city: event?.city || "Уфа",
    category: event?.category || "concert",
    venue: event?.venue || "",
    address: event?.address || "",
    date_start: localTime(event?.date_start),
    date_end: localTime(event?.date_end),
    duration_min: event?.duration_min?.toString() || "",
    description: event?.description || "",
    price_min: event?.price_min?.toString() || "",
    price_max: event?.price_max?.toString() || "",
    is_free: event?.is_free == null ? "" : String(event.is_free),
    age_limit: event?.age_limit?.toString() ?? "",
    language: event?.language || "",
    source_url: event?.source_url || "",
    org_link: event?.org_link || "",
    status: event?.status || "draft",
    tags: event?.tags.join(", ") || "",
  });
  const [verified, setVerified] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  function set(key: keyof typeof form, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }
  const numberOrNull = (s: string) => (s === "" ? null : Number(s));
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const values = {
      ...form,
      date_start: `${form.date_start}:00+05:00`,
      date_end: form.date_end ? `${form.date_end}:00+05:00` : null,
      duration_min: numberOrNull(form.duration_min),
      price_min: form.is_free === "true" ? 0 : numberOrNull(form.price_min),
      price_max: form.is_free === "true" ? 0 : numberOrNull(form.price_max),
      is_free: form.is_free === "" ? null : form.is_free === "true",
      age_limit: numberOrNull(form.age_limit),
      language: form.language || null,
      org_link: form.org_link || null,
      tags: form.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      verified_at: verified
        ? new Date().toISOString()
        : event?.verified_at || null,
      source_type: "manual",
      confidence: verified ? 1 : 0,
      lat: event?.lat ?? null,
      lon: event?.lon ?? null,
    };
    try {
      await api(
        event ? `/api/v1/admin/events/${event.id}` : "/api/v1/admin/events",
        {
          method: event ? "PUT" : "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(
            event
              ? { event: values, expected_updated_at: event.updated_at }
              : values,
          ),
        },
      );
      await onSaved();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={event ? "Редактирование события" : "Новое событие"}
      onClose={onClose}
    >
      <form className="event-editor" onSubmit={save}>
        <p>
          Время указывается по Башкортостану, UTC+5. Неизвестные значения
          оставляйте пустыми.
        </p>
        <label className="span-two">
          Название
          <input
            required
            maxLength={240}
            value={form.title}
            onChange={(e) => set("title", e.target.value)}
          />
        </label>
        <label>
          Город
          <input
            required
            maxLength={120}
            value={form.city}
            onChange={(e) => set("city", e.target.value)}
          />
        </label>
        <label>
          Категория
          <select
            value={form.category}
            onChange={(e) => set("category", e.target.value)}
          >
            {Object.entries({
              concert: "Концерт",
              theatre: "Театр",
              exhibition: "Выставка",
              festival: "Фестиваль",
              cinema: "Кино",
              excursion: "Экскурсия",
              other: "Другое",
            }).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="span-two">
          Площадка
          <input
            required
            maxLength={240}
            value={form.venue}
            onChange={(e) => set("venue", e.target.value)}
          />
        </label>
        <label className="span-two">
          Адрес
          <input
            required
            maxLength={400}
            value={form.address}
            onChange={(e) => set("address", e.target.value)}
          />
        </label>
        <label>
          Начало
          <input
            type="datetime-local"
            required
            value={form.date_start}
            onChange={(e) => set("date_start", e.target.value)}
          />
        </label>
        <label>
          Окончание, если известно
          <input
            type="datetime-local"
            value={form.date_end}
            onChange={(e) => set("date_end", e.target.value)}
          />
        </label>
        <label>
          Продолжительность, мин
          <input
            type="number"
            min={1}
            max={1440}
            value={form.duration_min}
            onChange={(e) => set("duration_min", e.target.value)}
          />
        </label>
        <label>
          Возраст
          <select
            value={form.age_limit}
            onChange={(e) => set("age_limit", e.target.value)}
          >
            <option value="">Не указан</option>
            {[0, 6, 12, 16, 18].map((v) => (
              <option key={v} value={v}>
                {v}+
              </option>
            ))}
          </select>
        </label>
        <label>
          Вход
          <select
            value={form.is_free}
            onChange={(e) => set("is_free", e.target.value)}
          >
            <option value="">Неизвестно</option>
            <option value="false">Платный</option>
            <option value="true">Бесплатный</option>
          </select>
        </label>
        <label>
          Язык
          <input
            maxLength={80}
            value={form.language}
            onChange={(e) => set("language", e.target.value)}
          />
        </label>
        <label>
          Минимальная цена, ₽
          <input
            type="number"
            min={0}
            max={10000000}
            disabled={form.is_free === "true"}
            value={form.is_free === "true" ? "0" : form.price_min}
            onChange={(e) => set("price_min", e.target.value)}
          />
        </label>
        <label>
          Максимальная цена, ₽
          <input
            type="number"
            min={0}
            max={10000000}
            disabled={form.is_free === "true"}
            value={form.is_free === "true" ? "0" : form.price_max}
            onChange={(e) => set("price_max", e.target.value)}
          />
        </label>
        <label className="span-two">
          Описание
          <textarea
            required
            minLength={1}
            maxLength={6000}
            value={form.description}
            onChange={(e) => set("description", e.target.value)}
          />
        </label>
        <label className="span-two">
          Метки через запятую
          <input
            value={form.tags}
            onChange={(e) => set("tags", e.target.value)}
          />
        </label>
        <label className="span-two">
          Ссылка на источник
          <input
            type="url"
            required
            value={form.source_url}
            onChange={(e) => set("source_url", e.target.value)}
          />
        </label>
        <label className="span-two">
          Ссылка на организатора или билеты
          <input
            type="url"
            value={form.org_link}
            onChange={(e) => set("org_link", e.target.value)}
          />
        </label>
        <label>
          Статус
          <select
            value={form.status}
            onChange={(e) => set("status", e.target.value)}
          >
            <option value="draft">Черновик</option>
            <option value="published">Опубликовано</option>
            <option value="cancelled">Отменено</option>
          </select>
        </label>
        <label className="editor-confirm">
          <input
            type="checkbox"
            checked={verified}
            required={form.status === "published"}
            onChange={(e) => setVerified(e.target.checked)}
          />
          Сверил(а) сведения с источником
        </label>
        <p className="fine-print span-two">
          При переносе дата изменится в этой же карточке, ссылка сохранится.
          Изменения попадут в журнал; импорт не перезапишет проверенные вручную
          сведения.
        </p>
        {error && (
          <p className="admin-error span-two" role="alert">
            {error}
          </p>
        )}
        <button className="button primary span-two" disabled={busy}>
          {busy ? "Сохраняем…" : "Сохранить карточку"}
        </button>
      </form>
    </Modal>
  );
}
