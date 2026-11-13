import { useEffect, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowRight,
  ArrowUpRight,
  Bookmark,
  CalendarDays,
  Check,
  ChevronDown,
  Flower2,
  MapPin,
  Search,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { api } from "./api";
import { EventCard, EventDetail, KuraiMark, Modal } from "./components";
import type { CultureEvent, EventPage, Meta } from "./types";
import "@fontsource/fira-sans/latin-400.css";
import "@fontsource/fira-sans/latin-500.css";
import "@fontsource/fira-sans/latin-600.css";
import "@fontsource/fira-sans/cyrillic-400.css";
import "@fontsource/fira-sans/cyrillic-500.css";
import "@fontsource/fira-sans/cyrillic-600.css";
import "@fontsource/fira-sans/cyrillic-ext-400.css";
import "@fontsource/fira-sans/cyrillic-ext-500.css";
import "@fontsource/fira-sans/cyrillic-ext-600.css";
import "./styles.css";
import "./typography.css";
import { Admin } from "./Admin";
import { SubscriptionPanel } from "./SubscriptionPanel";
import "./subscriptions.css";

type FormFilters = {
  q: string;
  city: string;
  date_from: string;
  date_to: string;
  price_max: string;
  age: string;
  category: string;
  is_free: string;
  sort: string;
  venue: string;
};
const eventWord = (n: number) =>
  n % 100 >= 11 && n % 100 <= 14
    ? "событий"
    : n % 10 === 1
      ? "событие"
      : n % 10 >= 2 && n % 10 <= 4
        ? "события"
        : "событий";
const empty: FormFilters = {
  q: "",
  city: "",
  date_from: "",
  date_to: "",
  price_max: "",
  age: "",
  category: "",
  is_free: "",
  sort: "date",
  venue: "",
};
function initialFilters() {
  const p = new URLSearchParams(location.search);
  return Object.fromEntries(
    Object.entries(empty).map(([k, v]) => [k, p.get(k) || v]),
  ) as FormFilters;
}
function readSaved(): string[] {
  try {
    const a = JSON.parse(localStorage.getItem("kurai-saved") || "[]");
    return Array.isArray(a)
      ? a
          .filter((v) => typeof v === "string" && /^[0-9a-f-]{36}$/i.test(v))
          .slice(0, 100)
      : [];
  } catch {
    return [];
  }
}
function App() {
  const [meta, setMeta] = useState<Meta | null>(null),
    [filters, setFilters] = useState<FormFilters>(initialFilters),
    [applied, setApplied] = useState<FormFilters>(initialFilters);
  const [data, setData] = useState<EventPage | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [page, setPage] = useState(1);
  const [pathname, setPathname] = useState(location.pathname),
    [event, setEvent] = useState<CultureEvent | null>(null),
    [saved, setSaved] = useState(readSaved),
    [savedOnly, setSavedOnly] = useState(false);
  const [modal, setModal] = useState<"about" | "feedback" | null>(null),
    [feedback, setFeedback] = useState(""),
    [feedbackStatus, setFeedbackStatus] = useState(""),
    [busy, setBusy] = useState(false),
    [more, setMore] = useState(false),
    [retry, setRetry] = useState(0);
  const widget = pathname === "/widget";
  useEffect(() => {
    api<Meta>("/api/v1/meta")
      .then(setMeta)
      .catch((e) => setError(e.message));
    const handler = () => {
      setPathname(location.pathname);
      setFilters(initialFilters());
      setApplied(initialFilters());
      setPage(1);
    };
    addEventListener("popstate", handler);
    return () => removeEventListener("popstate", handler);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem("kurai-saved", JSON.stringify(saved));
    } catch {
      /* Browser storage can be disabled. */
    }
  }, [saved]);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setLoading(true);
    if (pathname.startsWith("/events/")) {
      setEvent(null);
      api<CultureEvent>("/api/v1/events/" + pathname.split("/")[2], {
        signal: controller.signal,
      })
        .then(setEvent)
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    } else {
      setEvent(null);
      const p = new URLSearchParams();
      Object.entries(applied).forEach(([k, v]) => {
        if (v && !(k === "sort" && v === "date")) p.set(k, v);
      });
      p.set("page", String(page));
      const query = savedOnly
        ? Promise.all(
            saved.map((id) =>
              api<CultureEvent>("/api/v1/events/" + id, {
                signal: controller.signal,
              }).catch((e) => {
                if (e.name === "AbortError") throw e;
                return null;
              }),
            ),
          ).then((items) => ({
            items: items.filter((e): e is CultureEvent => e !== null),
            total: items.filter(Boolean).length,
            page: 1,
            size: 100,
            suggestions: [],
          }))
        : api<EventPage>("/api/v1/events?" + p, { signal: controller.signal });
      query
        .then((next) =>
          setData((prev) =>
            page > 1 && prev
              ? { ...next, items: [...prev.items, ...next.items] }
              : next,
          ),
        )
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }
    return () => controller.abort();
  }, [
    pathname,
    applied,
    page,
    savedOnly,
    retry,
    savedOnly ? saved.join(",") : "",
  ]);
  function go(path: string) {
    if (path === "/") {
      setFilters({ ...empty });
      setApplied({ ...empty });
      setPage(1);
      setData(null);
      setSavedOnly(false);
    }
    history.pushState(null, "", path);
    setPathname(location.pathname);
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  function apply(next = filters) {
    setSavedOnly(false);
    setPage(1);
    setData(null);
    setFilters(next);
    setApplied({ ...next });
    const p = new URLSearchParams();
    Object.entries(next).forEach(([k, v]) => {
      if (v && !(k === "sort" && v === "date")) p.set(k, v);
    });
    history.replaceState(
      null,
      "",
      `${widget ? "/widget" : "/"}${p.size ? "?" + p : ""}`,
    );
    setPathname(widget ? "/widget" : "/");
  }
  function field(k: keyof FormFilters, v: string) {
    setFilters((f) => ({ ...f, [k]: v }));
  }
  function save(id: string) {
    setSaved((values) =>
      values.includes(id)
        ? values.filter((v) => v !== id)
        : [...values, id].slice(-100),
    );
  }
  function period(kind: string) {
    const today = meta?.today || new Date().toLocaleDateString("sv-SE");
    const d = new Date(today + "T12:00:00Z");
    let start = today,
      end = today;
    if (kind === "weekend") {
      d.setUTCDate(d.getUTCDate() + ((6 - d.getUTCDay() + 7) % 7));
      start = d.toISOString().slice(0, 10);
      d.setUTCDate(d.getUTCDate() + 1);
      end = d.toISOString().slice(0, 10);
    }
    if (kind === "week") {
      d.setUTCDate(d.getUTCDate() + 6);
      end = d.toISOString().slice(0, 10);
    }
    apply({ ...filters, date_from: start, date_to: end });
  }
  async function sendFeedback(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setFeedbackStatus("");
    const form = new FormData(e.currentTarget);
    try {
      const result = await api<{ message: string }>("/api/v1/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_id: event?.id || null,
          message: feedback,
          website: form.get("website") || "",
        }),
      });
      setFeedbackStatus(result.message);
      setFeedback("");
    } catch (e) {
      setFeedbackStatus((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const activeCount = Object.entries(applied).filter(
    ([k, v]) => v && k !== "sort",
  ).length;
  return (
    <>
      <a className="skip-link" href="#catalog">
        Перейти к событиям
      </a>
      {!widget && (
        <>
          <div className="tricolor" />
          <header className="header wrap">
            <a
              href="/"
              className="brand"
              aria-label="Курай — главная"
              onClick={(e) => {
                e.preventDefault();
                setSavedOnly(false);
                go("/");
              }}
            >
              <KuraiMark />
              <span>
                курай<small>АФИША БАШКОРТОСТАНА</small>
              </span>
            </a>
            <nav aria-label="Основная навигация">
              <a
                className="active"
                href="/#catalog"
                onClick={() => {
                  if (pathname !== "/") go("/");
                }}
              >
                Афиша
              </a>
              <button onClick={() => setModal("about")}>О проекте</button>
              <button
                onClick={() => {
                  setFeedbackStatus("");
                  setModal("feedback");
                }}
              >
                Организаторам
                <ArrowUpRight size={14} />
              </button>
            </nav>
            <button
              className="favorites"
              onClick={() => {
                const next = !savedOnly;
                go("/");
                setSavedOnly(next);
                setPage(1);
                document
                  .getElementById("catalog")
                  ?.scrollIntoView({ behavior: "smooth" });
              }}
              aria-pressed={savedOnly}
            >
              <Bookmark size={18} />
              <span>Избранное</span>
              <b>{saved.length}</b>
            </button>
          </header>
        </>
      )}
      <main className={widget ? "widget wrap" : "wrap"}>
        {!widget && !pathname.startsWith("/events/") && (
          <>
            <section className="hero">
              <div className="hero-copy">
                <p className="eyebrow">
                  <span className="tiny-diamond" />
                  РЕСПУБЛИКА БАШКОРТОСТАН
                </p>
                <h1>
                  Ближе к своим. <br />
                  <em>Открытее</em> <br />к новому.
                </h1>
                <p className="hero-description">
                  Места, в которые хочется вернуться.
                  <br />
                  События, которые хочется разделить.
                </p>
                <a className="button primary" href="#catalog">
                  Найти своё событие
                  <ArrowUpRight size={20} />
                </a>
                <div className="hero-foot">
                  <span className="little-star">✳</span>
                  <p>
                    Культура родного края —<br />
                    <strong>в ритме вашей жизни</strong>
                  </p>
                </div>
              </div>
              <figure className="hero-art">
                <img
                  src="/assets/bashkortostan-editorial.webp"
                  alt="Художественная иллюстрация: горы, река, всадник и цветущий курай в синих, зелёных и золотых тонах"
                />
                <figcaption>
                  <span>Башҡортостан</span>
                  <span>Вдохновение рядом ↗</span>
                </figcaption>
                <span className="art-caption">
                  Авторская иллюстрация по мотивам республики
                </span>
              </figure>
            </section>
            <div className="values-strip">
              <span>
                <Check size={15} />
                События из афиш учреждений
              </span>
              <span>
                <Flower2 size={17} />
                Культура с местным характером
              </span>
              <span>
                <MapPin size={16} />
                От знакомых сцен к новым открытиям
              </span>
            </div>
          </>
        )}
        {pathname.startsWith("/events/") ? (
          loading ? (
            <div className="state-panel" role="status">
              Загружаем карточку…
            </div>
          ) : error ? (
            <div className="state-panel" role="alert">
              <h2>{error}</h2>
              <button className="button secondary" onClick={() => go("/")}>
                К афише
              </button>
            </div>
          ) : (
            event && (
              <EventDetail
                event={event}
                saved={saved.includes(event.id)}
                onSave={() => save(event.id)}
                onBack={() => go("/" + location.search)}
                onFeedback={() => {
                  setFeedbackStatus("");
                  setModal("feedback");
                }}
              />
            )
          )
        ) : (
          <section
            id="catalog"
            className="catalog"
            aria-labelledby="catalog-title"
          >
            <div className="section-heading">
              <div>
                <p className="eyebrow">01 / ОТКРЫВАЙТЕ БАШКОРТОСТАН</p>
                <h2 id="catalog-title">
                  {savedOnly ? "Сохранено для вас" : "Ваша следующая история"}
                </h2>
              </div>
              <span className="section-note">
                {savedOnly ? "На этом устройстве" : "Выбирайте по настроению"}
              </span>
            </div>
            {!savedOnly && (
              <>
                <form
                  className="search-panel"
                  onSubmit={(e) => {
                    e.preventDefault();
                    apply();
                  }}
                >
                  <div className="search-main">
                    <label className="search-field">
                      <span>Что ищем?</span>
                      <div>
                        <Search size={18} />
                        <input
                          placeholder="Название события"
                          value={filters.q}
                          onChange={(e) => field("q", e.target.value)}
                          maxLength={200}
                        />
                      </div>
                    </label>
                    <label className="city-field">
                      <span>Где</span>
                      <div>
                        <MapPin size={18} />
                        <select
                          value={filters.city}
                          onChange={(e) => field("city", e.target.value)}
                        >
                          <option value="">Вся республика</option>
                          {meta?.cities.map((c) => (
                            <option key={c}>{c}</option>
                          ))}
                        </select>
                      </div>
                    </label>
                    <label>
                      <span>С какого дня</span>
                      <div>
                        <CalendarDays size={18} />
                        <input
                          type="date"
                          value={filters.date_from}
                          onChange={(e) => field("date_from", e.target.value)}
                        />
                      </div>
                    </label>
                    <button
                      className="button primary search-submit"
                      type="submit"
                    >
                      Найти
                      <ArrowRight size={18} />
                    </button>
                  </div>
                  <div className="search-bottom">
                    <div className="quick-dates">
                      <button type="button" onClick={() => period("today")}>
                        Сегодня
                      </button>
                      <button type="button" onClick={() => period("weekend")}>
                        В выходные
                      </button>
                      <button type="button" onClick={() => period("week")}>
                        На неделе
                      </button>
                    </div>
                    <button
                      className="filter-toggle"
                      type="button"
                      onClick={() => setMore((v) => !v)}
                      aria-expanded={more}
                    >
                      <SlidersHorizontal size={15} />
                      Все фильтры
                      <ChevronDown size={14} />
                    </button>
                  </div>
                  {more && (
                    <div className="extra-filters">
                      <label>
                        <span>По какой день</span>
                        <input
                          type="date"
                          value={filters.date_to}
                          min={filters.date_from}
                          onChange={(e) => field("date_to", e.target.value)}
                        />
                      </label>
                      <label>
                        <span>Бюджет на билет, ₽</span>
                        <input
                          type="number"
                          min="0"
                          max="10000000"
                          placeholder="Без ограничения"
                          value={filters.price_max}
                          onChange={(e) => field("price_max", e.target.value)}
                        />
                      </label>
                      <label>
                        <span>Возраст ребёнка</span>
                        <input
                          type="number"
                          min="0"
                          max="17"
                          placeholder="Не ограничивать"
                          value={filters.age}
                          onChange={(e) => field("age", e.target.value)}
                        />
                      </label>
                      <label>
                        <span>Площадка</span>
                        <select
                          value={filters.venue}
                          onChange={(e) => field("venue", e.target.value)}
                        >
                          <option value="">Любая</option>
                          {meta?.venues.map((v) => (
                            <option key={v}>{v}</option>
                          ))}
                        </select>
                      </label>
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={!!filters.is_free}
                          onChange={(e) =>
                            field("is_free", e.target.checked ? "true" : "")
                          }
                        />
                        Только бесплатные
                      </label>
                      <p className="fine-print">
                        Если цена или возраст не указаны источником, событие не
                        проходит соответствующий фильтр.
                      </p>
                    </div>
                  )}
                </form>
                <div className="category-tabs" aria-label="Категории">
                  <button
                    className={!applied.category ? "selected" : ""}
                    onClick={() => apply({ ...filters, category: "" })}
                  >
                    Всё интересное
                  </button>
                  {meta?.categories.map((c) => (
                    <button
                      key={c.id}
                      className={applied.category === c.id ? "selected" : ""}
                      onClick={() => apply({ ...filters, category: c.id })}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
              </>
            )}
            <div className="results-header">
              <p aria-live="polite">
                {loading
                  ? "Ищем события…"
                  : `${data?.total ?? 0} ${eventWord(data?.total ?? 0)}`}{" "}
                {!!activeCount && !savedOnly && (
                  <button
                    className="clear-filters"
                    onClick={() => apply(empty)}
                  >
                    Сбросить фильтры ×
                  </button>
                )}
              </p>
              {!savedOnly && (
                <label className="sort">
                  Порядок
                  <select
                    aria-label="Порядок событий"
                    value={applied.sort}
                    onChange={(e) =>
                      apply({ ...filters, sort: e.target.value })
                    }
                  >
                    <option value="date">Сначала ближайшие</option>
                    <option value="price">Сначала дешевле</option>
                  </select>
                </label>
              )}
            </div>
            {error ? (
              <div className="state-panel" role="alert">
                <h3>{error}</h3>
                <button
                  className="button secondary"
                  onClick={() => setRetry((v) => v + 1)}
                >
                  Попробовать снова
                </button>
              </div>
            ) : (
              <>
                {loading && page === 1 ? (
                  <div
                    className="skeleton-grid"
                    aria-label="Загрузка событий"
                    role="status"
                  >
                    {[1, 2, 3].map((n) => (
                      <div className="skeleton" key={n} />
                    ))}
                  </div>
                ) : data?.items.length ? (
                  <div className="event-grid">
                    {data.items.map((item, i) => (
                      <EventCard
                        key={item.id}
                        index={i}
                        event={item}
                        saved={saved.includes(item.id)}
                        onSave={() => save(item.id)}
                        onOpen={() =>
                          go(`/events/${item.id}` + location.search)
                        }
                      />
                    ))}
                  </div>
                ) : (
                  <div className="state-panel">
                    <Flower2 size={36} />
                    <h3>
                      {savedOnly
                        ? "Здесь будут ваши планы"
                        : "Пока не нашли совпадений"}
                    </h3>
                    <p>
                      {savedOnly
                        ? "Нажмите на закладку понравившегося события — оно появится здесь."
                        : data?.suggestions.join(". ")}
                    </p>
                    {!savedOnly && (
                      <button
                        className="button secondary"
                        onClick={() => apply(empty)}
                      >
                        Посмотреть все события
                      </button>
                    )}
                  </div>
                )}
                {data && data.items.length < data.total && !savedOnly && (
                  <div className="load-more">
                    <button
                      disabled={loading}
                      className="button secondary"
                      onClick={() => setPage((v) => v + 1)}
                    >
                      {loading ? "Загружаем…" : "Показать ещё"}
                      <ArrowRight size={18} />
                    </button>
                  </div>
                )}
              </>
            )}
            {!widget && (
              <SubscriptionPanel
                meta={meta}
                city={applied.city}
                category={applied.category}
              />
            )}
            {!widget && (
              <aside className="trust-panel">
                <KuraiMark />
                <div>
                  <h3>У каждой истории есть источник</h3>
                  <p>
                    Сверяем сведения с афишами учреждений и сохраняем ссылки.
                    Если данных недостаточно, говорим об этом прямо.
                  </p>
                </div>
                <button
                  className="text-button"
                  onClick={() => setModal("about")}
                >
                  Как это работает
                  <ArrowUpRight size={17} />
                </button>
              </aside>
            )}
          </section>
        )}
      </main>
      {!widget && (
        <footer className="footer wrap">
          <div className="footer-top">
            <a className="brand" href="/">
              <KuraiMark />
              <span>
                курай<small>КУЛЬТУРА РЯДОМ</small>
              </span>
            </a>
            <p>
              С любовью к республике.
              <br />С вниманием к вашим планам.
            </p>
            <div>
              <a href="/api/docs" target="_blank" rel="noopener">
                Открытый API ↗
              </a>
              <a href="/admin">Модератору ↗</a>
              <button
                onClick={() => {
                  setFeedbackStatus("");
                  setModal("feedback");
                }}
              >
                Обратная связь ↗
              </button>
            </div>
          </div>
          <div className="footer-bottom">
            <p>
              Независимый проект. Не является официальным сервисом Министерства
              культуры Республики Башкортостан.
            </p>
            <span>КУРАЙ · 2026</span>
          </div>
        </footer>
      )}
      {modal === "about" && (
        <Modal
          title="Афиша, которой можно доверять"
          onClose={() => setModal(null)}
        >
          <p>
            «Курай» помогает открывать культуру Башкортостана. Каждая карточка
            связана с афишей учреждения, а неизвестные цена, возраст и
            длительность явно отмечены.
          </p>
          <p>
            Сейчас доступен первый каталог: поиск, фильтры, источники, избранное
            на устройстве и обращения модератору. География и число событий
            будут расширяться после проверки данных.
          </p>
          <p>
            ИИ-помощник появится на следующем этапе. Каталог работает
            самостоятельно.
          </p>
          <p className="fine-print">
            Это независимый проект, не официальный сервис министерства.
            Иллюстрация на главной создана с помощью ИИ и не является
            документальной фотографией.
          </p>
        </Modal>
      )}
      {modal === "feedback" && (
        <Modal
          title={event ? "Уточнить сведения" : "Организаторам и зрителям"}
          onClose={() => setModal(null)}
        >
          <p>
            Расскажите о событии или сообщите об изменениях. Добавьте ссылку на
            афишу, чтобы модератор мог проверить сведения.
          </p>
          <form className="feedback-form" onSubmit={sendFeedback}>
            <label htmlFor="feedback-message">Ваше сообщение</label>
            <textarea
              id="feedback-message"
              minLength={10}
              maxLength={2000}
              required
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Что нужно добавить или исправить?"
            />
            <div className="honeypot" aria-hidden="true">
              <label>
                Ваш сайт
                <input name="website" autoComplete="off" tabIndex={-1} />
              </label>
            </div>
            <p className="fine-print">
              Не указывайте телефон, домашний адрес и другие личные данные.
              Обращение сохраняется для проверки и не публикуется автоматически.
            </p>
            <button
              className="button primary"
              disabled={busy || feedback.length < 10}
            >
              {busy ? "Сохраняем…" : "Отправить на проверку"}
              <ArrowUpRight size={17} />
            </button>
            <p role="status">{feedbackStatus}</p>
          </form>
        </Modal>
      )}
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  location.pathname === "/admin" ? <Admin /> : <App />,
);
