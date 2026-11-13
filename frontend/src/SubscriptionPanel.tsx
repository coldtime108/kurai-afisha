import { useEffect, useState, type FormEvent } from "react";
import { Bell, ArrowUpRight, Check, Trash2 } from "lucide-react";
import { api } from "./api";
import { Modal, fmtDate } from "./components";
import type { Meta, CultureEvent, EventPage } from "./types";

type Subscription = {
  id: string;
  filters: { city: string; category: string | null; period: string };
  expires_at: string;
};
const keyName = "kurai-subscription-key";
const telegramUrl = "https://t.me/kurai_afisha_rb_bot";
function deviceKey(create = false): string | null {
  const existing = localStorage.getItem(keyName);
  if (existing && /^[a-f0-9]{64}$/.test(existing)) return existing;
  if (!create) return null;
  const value = Array.from(crypto.getRandomValues(new Uint8Array(32)), (v) =>
    v.toString(16).padStart(2, "0"),
  ).join("");
  localStorage.setItem(keyName, value);
  return value;
}

export function SubscriptionPanel({
  meta,
  city,
  category,
}: {
  meta: Meta | null;
  city: string;
  category: string;
}) {
  const [subscription, setSubscription] = useState<Subscription | null>(null),
    [open, setOpen] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [chosenCity, setChosenCity] = useState(city),
    [chosenCategory, setChosenCategory] = useState(category),
    [period, setPeriod] = useState("week"),
    [confirmed, setConfirmed] = useState(false),
    [events, setEvents] = useState<CultureEvent[] | null>(null);
  useEffect(() => {
    try {
      const key = deviceKey();
      if (key)
        api<Subscription[]>("/api/v1/subscriptions", {
          headers: { Authorization: `Bearer ${key}` },
        })
          .then((rows) => setSubscription(rows[0] || null))
          .catch(() => {});
    } catch {
      /* Storage can be unavailable in embedded pages. */
    }
  }, []);
  function show() {
    setError("");
    setConfirmed(false);
    setChosenCity(subscription?.filters.city || city || meta?.cities[0] || "");
    setChosenCategory(
      subscription ? (subscription.filters.category ?? "") : category,
    );
    setPeriod(subscription?.filters.period || "week");
    setOpen(true);
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const key = deviceKey(true);
      const result = await api<Subscription>("/api/v1/subscriptions", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          city: chosenCity,
          category: chosenCategory || null,
          period,
          confirmed,
        }),
      });
      setSubscription(result);
      setOpen(false);
      setEvents(null);
    } catch (e) {
      setError(
        e instanceof DOMException
          ? "Браузер не разрешает сохранить ключ подписки. Откройте афишу в отдельном окне."
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!subscription || !confirm("Удалить подписку и её данные?")) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/subscriptions/${subscription.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${deviceKey()}` },
      });
      localStorage.removeItem(keyName);
      setSubscription(null);
      setEvents(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function view() {
    if (!subscription) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<EventPage>(
        `/api/v1/subscriptions/${subscription.id}/events`,
        { headers: { Authorization: `Bearer ${deviceKey()}` } },
      );
      setEvents(result.items);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="subscription-panel" aria-label="Подписка на афишу">
      <div className="subscription-intro">
        <span className="subscription-symbol">
          <Bell size={27} strokeWidth={1.4} />
        </span>
        <div>
          <p className="eyebrow">ВАШ ГОРОД. ВАШ РИТМ.</p>
          <h3>
            {subscription
              ? `Ваша афиша · ${subscription.filters.city}`
              : "Не теряйте то, что интересно"}
          </h3>
          <p>
            {subscription
              ? "Подборка сохранена для этого устройства. Проверяйте новые события в удобное время."
              : "Сохраните город и любимую категорию — возвращайтесь к своей подборке без повторного поиска."}
          </p>
        </div>
        <button className="button primary" onClick={show} disabled={busy}>
          {subscription ? "Изменить подписку" : "Создать подписку"}
          <ArrowUpRight size={17} />
        </button>
      </div>
      <div className="subscription-telegram">
        <p>
          Получайте новые события в Telegram. Город и категорию выбирайте в
          боте.
        </p>
        <a
          className="text-button"
          href={telegramUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          Открыть бота «Курай» <ArrowUpRight size={16} />
        </a>
      </div>
      {subscription && (
        <div className="subscription-actions">
          <button className="text-button" onClick={view} disabled={busy}>
            Открыть подборку
            <ArrowUpRight size={16} />
          </button>
          <button className="text-button" onClick={remove} disabled={busy}>
            <Trash2 size={14} />
            Удалить подписку
          </button>
          <small>До {fmtDate(subscription.expires_at)}</small>
        </div>
      )}
      {events && (
        <div className="subscription-events" aria-live="polite">
          {events.length ? (
            events.map((event) => (
              <a href={`/events/${event.id}`} key={event.id}>
                <span>{event.title}</span>
                <small>{fmtDate(event.date_start)}</small>
                <ArrowUpRight size={16} />
              </a>
            ))
          ) : (
            <p>
              По выбранным условиям пока нет опубликованных событий. Попробуйте
              расширить период или категорию.
            </p>
          )}
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {open && (
        <Modal
          title={
            subscription
              ? "Изменить вашу подписку"
              : "Оставьте место для культуры"
          }
          onClose={() => setOpen(false)}
        >
          <p className="subscription-explanation">
            Подписка сохраняет подборку на этом устройстве. Уведомления можно
            отдельно включить в{" "}
            <a href={telegramUrl} target="_blank" rel="noopener noreferrer">
              нашем Telegram-боте
            </a>
            .
          </p>
          <form className="subscription-form" onSubmit={save}>
            <label>
              Город
              <select
                required
                value={chosenCity}
                onChange={(e) => setChosenCity(e.target.value)}
              >
                <option value="">Выберите город</option>
                {meta?.cities.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              Категория
              <select
                value={chosenCategory}
                onChange={(e) => setChosenCategory(e.target.value)}
              >
                <option value="">Все категории</option>
                {meta?.categories.map((v) => (
                  <option value={v.id} key={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Период
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
              >
                <option value="week">Ближайшая неделя</option>
                <option value="weekend">Выходные</option>
              </select>
            </label>
            <label className="confirm-subscription">
              <input
                type="checkbox"
                required
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              Подтверждаю сохранение выбранного города и категории. Подписку
              можно удалить в любое время.
            </label>
            <p className="fine-print">
              Храним случайный ключ устройства и фильтры до 180 дней. Имя,
              телефон и email не требуются. Удаление данных браузера лишит
              доступа к этой подписке; она автоматически истечёт.
            </p>
            <button className="button primary" disabled={busy || !confirmed}>
              {busy ? "Сохраняем…" : "Подтвердить подписку"}
              <Check size={17} />
            </button>
            {error && <p role="alert">{error}</p>}
          </form>
        </Modal>
      )}
    </section>
  );
}
