import { useEffect, useState, type FormEvent } from "react";
import {
  ArrowUpRight,
  CalendarDays,
  ChevronDown,
  Clock,
  MapPin,
} from "lucide-react";
import { api } from "./api";
import { fmtDate, fmtTime } from "./components";
import type { CultureEvent, Meta } from "./types";
import "./planner.css";

type PlanRequest = {
  city: string;
  day: string;
  start_time: string;
  end_time: string;
  adults: number;
  children_ages: number[];
  budget: number | null;
  max_events: number;
  arrival_buffer_min: number;
  max_transfer_min: number;
  transfer_minutes: number | null;
  transfer_cost: number;
  allow_unconfirmed_cost: boolean;
};
type Stop = {
  event: CultureEvent;
  arrive_by: string;
  start: string;
  end: string;
  end_basis: string;
  transfer_before_min: number;
  transfer_basis: string;
  group_price_min: number | null;
  group_price_max: number | null;
  free_before_min: number;
};
type Route = {
  status: string;
  stops: Stop[];
  cost_min: number | null;
  cost_max: number | null;
  known_cost_min: number;
  transfer_cost: number;
  budget_status: string;
  assumptions: string[];
};
export type DayPlanResult = {
  status: string;
  message: string;
  input: PlanRequest;
  people: number;
  routes: Route[];
  single_options: CultureEvent[];
  diagnostics: Record<string, number>;
  suggestions: string[];
  search_complete: boolean;
};

const money = (value: number) => value.toLocaleString("ru-RU") + " ₽";
function costText(lower: number | null, upper: number | null) {
  if (lower === null) return "Стоимость нужно уточнить";
  if (upper === null) return `От ${money(lower)}, верхняя граница неизвестна`;
  return lower === upper ? money(lower) : `${money(lower)} — ${money(upper)}`;
}
function minutes(value: number) {
  return value >= 60
    ? `${Math.floor(value / 60)} ч${value % 60 ? ` ${value % 60} мин` : ""}`
    : `${value} мин`;
}

export function DayPlanResults({
  result,
  onOpen,
  onRelax,
  busy = false,
}: {
  result: DayPlanResult;
  onOpen: (id: string) => void;
  onRelax?: () => void;
  busy?: boolean;
}) {
  const [choice, setChoice] = useState(0);
  useEffect(() => setChoice(0), [result]);
  const route = result.routes[Math.min(choice, result.routes.length - 1)];
  return (
    <div className="day-plan-result" aria-label="Результат планирования">
      <div className="day-plan-result-head">
        <span className={`plan-state ${result.status}`}>
          {result.status === "no_plan"
            ? "Маршрут не сложился"
            : result.status === "ready"
              ? "Без пересечений"
              : "Нужны уточнения"}
        </span>
        <h3>
          {result.input.city} · {fmtDate(result.input.day + "T12:00:00+05:00")}
        </h3>
        <p>
          {result.input.start_time.slice(0, 5)}–
          {result.input.end_time.slice(0, 5)} · время Башкортостана
        </p>
        <p>
          Взрослых: {result.input.adults}
          {result.input.children_ages.length
            ? ` · возраст детей: ${result.input.children_ages.join(", ")}`
            : ""}{" "}
          · всего: {result.people}
        </p>
        <p>{result.message}</p>
      </div>
      {result.routes.length > 1 && (
        <div
          className="plan-choices"
          role="group"
          aria-label="Варианты маршрута"
        >
          {result.routes.map((_, index) => (
            <button
              key={index}
              type="button"
              aria-pressed={choice === index}
              onClick={() => setChoice(index)}
            >
              Вариант {index + 1}
            </button>
          ))}
        </div>
      )}
      {route && (
        <>
          <ol className="plan-timeline">
            {route.stops.map((stop, index) => (
              <li key={stop.event.id}>
                <div className="plan-stop-number">
                  {String(index + 1).padStart(2, "0")}
                </div>
                <div className="plan-stop-content">
                  {index > 0 && (
                    <p className="plan-transfer">
                      {stop.transfer_basis === "same_place"
                        ? "Та же площадка · переезд не нужен"
                        : `На переезд заложено ${stop.transfer_before_min} мин по вашей оценке`}
                      {stop.free_before_min > 0
                        ? ` · свободное время: ${minutes(stop.free_before_min)}`
                        : ""}
                    </p>
                  )}
                  <p className="plan-hours">
                    <Clock size={15} />
                    {fmtTime(stop.start)}–{fmtTime(stop.end)}
                    <span>Прибыть к {fmtTime(stop.arrive_by)}</span>
                  </p>
                  <a
                    href={`/events/${stop.event.id}`}
                    className="plan-event-title"
                    onClick={(e) => {
                      e.preventDefault();
                      onOpen(stop.event.id);
                    }}
                  >
                    {stop.event.title}
                    <ArrowUpRight size={17} />
                  </a>
                  <p>
                    <MapPin size={14} />
                    {stop.event.venue}
                  </p>
                  <p>{stop.event.address}</p>
                  <p>
                    {stop.event.age_limit}+ · на вашу группу:{" "}
                    {costText(stop.group_price_min, stop.group_price_max)}
                  </p>
                  <small>
                    {stop.end_basis === "source_duration"
                      ? "Окончание рассчитано по длительности из источника."
                      : "Время окончания указано в источнике."}
                  </small>
                  <a
                    className="plan-source"
                    href={stop.event.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Официальный источник <ArrowUpRight size={12} />
                  </a>
                </div>
              </li>
            ))}
          </ol>
          <div className="plan-cost">
            <div>
              <span>На всю группу</span>
              <strong>{costText(route.cost_min, route.cost_max)}</strong>
              {route.cost_min === null && route.known_cost_min > 0 && (
                <p>Известная часть: от {money(route.known_cost_min)}</p>
              )}
            </div>
            <div>
              <span>
                {result.input.budget === null
                  ? "Бюджет не задан"
                  : `Ваш бюджет: ${money(result.input.budget)}`}
              </span>
              <p>
                {route.budget_status === "within"
                  ? "Верхняя оценка укладывается в бюджет"
                  : route.budget_status === "unconfirmed"
                    ? "Соответствие бюджету не подтверждено"
                    : "Ценового ограничения нет"}
              </p>
              {route.transfer_cost > 0 && (
                <p>
                  В том числе переезды по вашей оценке:{" "}
                  {money(route.transfer_cost)}
                </p>
              )}
            </div>
          </div>
          <ul className="plan-notes">
            {route.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </>
      )}
      {result.suggestions.length > 0 && (
        <ul className="plan-notes">
          {result.suggestions.map((suggestion) => (
            <li key={suggestion}>{suggestion}</li>
          ))}
        </ul>
      )}
      {!route &&
        onRelax &&
        result.input.budget !== null &&
        !result.input.allow_unconfirmed_cost &&
        result.diagnostics.unknown_price > 0 && (
          <button
            className="button secondary"
            type="button"
            disabled={busy}
            onClick={onRelax}
          >
            Рассмотреть с неподтверждёнными ценами
          </button>
        )}
      {!route && result.single_options.length > 0 && (
        <div className="plan-singles">
          <h4>Отдельные события по вашим условиям</h4>
          {result.single_options.map((event) => (
            <a
              key={event.id}
              href={`/events/${event.id}`}
              onClick={(e) => {
                e.preventDefault();
                onOpen(event.id);
              }}
            >
              {event.title} <ArrowUpRight size={15} />
            </a>
          ))}
        </div>
      )}
      <p className="plan-footnote">
        Подборка на момент расчёта. Перед посещением сверьте статус и наличие
        билетов с организатором.
      </p>
    </div>
  );
}

export function DayPlanner({
  meta,
  city,
  onOpen,
}: {
  meta: Meta | null;
  city: string;
  onOpen: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [chosenCity, setCity] = useState(city);
  const [day, setDay] = useState("");
  const [start, setStart] = useState("10:00"),
    [end, setEnd] = useState("22:00");
  const [adults, setAdults] = useState("2"),
    [children, setChildren] = useState("");
  const [budget, setBudget] = useState(""),
    [maxEvents, setMaxEvents] = useState("3");
  const [buffer, setBuffer] = useState("15"),
    [maxTransfer, setMaxTransfer] = useState("45");
  const [transfer, setTransfer] = useState(""),
    [transferCost, setTransferCost] = useState("0");
  const [allowUnknown, setAllowUnknown] = useState(false);
  const [result, setResult] = useState<DayPlanResult | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    if (!meta) return;
    setCity((previous) => previous || city || meta.cities[0] || "");
    const next = new Date(meta.today + "T12:00:00Z");
    next.setUTCDate(next.getUTCDate() + 1);
    setDay((previous) => previous || next.toISOString().slice(0, 10));
  }, [meta, city]);
  async function submit(e?: FormEvent, override?: PlanRequest) {
    e?.preventDefault();
    if (busy) return;
    setError("");
    if (
      !override &&
      children.trim() &&
      !/^\d{1,2}(?:\s*[,; ]\s*\d{1,2})*$/.test(children.trim())
    ) {
      setError("Укажите возраст каждого ребёнка числами через запятую: 8, 12.");
      return;
    }
    const payload: PlanRequest = override || {
      city: chosenCity,
      day,
      start_time: start,
      end_time: end,
      adults: Number(adults),
      children_ages: children.match(/\d+/g)?.map(Number) || [],
      budget: budget === "" ? null : Number(budget),
      max_events: Number(maxEvents),
      arrival_buffer_min: Number(buffer),
      max_transfer_min: Number(maxTransfer),
      transfer_minutes: transfer === "" ? null : Number(transfer),
      transfer_cost: transfer === "" ? 0 : Number(transferCost),
      allow_unconfirmed_cost: allowUnknown,
    };
    setBusy(true);
    try {
      setResult(
        await api<DayPlanResult>("/api/v1/planner/day", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      id="planner"
      className="day-planner"
      aria-labelledby="planner-title"
    >
      <div className="planner-invitation">
        <span className="planner-symbol">
          <CalendarDays size={28} strokeWidth={1.4} />
        </span>
        <div>
          <p className="eyebrow">Выходной день</p>
          <h2 id="planner-title">Соберём день из впечатлений</h2>
          <p>
            От двух до четырёх событий — с временем на вход, составом группы и
            общим бюджетом.
          </p>
        </div>
        <button
          className="button secondary"
          aria-expanded={open}
          aria-controls="day-planner-form"
          onClick={() => setOpen(!open)}
        >
          {open ? "Свернуть" : "Спланировать день"}
          <ChevronDown size={17} />
        </button>
      </div>
      {open && (
        <div id="day-planner-form">
          <form className="planner-form" onSubmit={submit}>
            <div className="planner-fields">
              <label>
                Город
                <select
                  required
                  value={chosenCity}
                  onChange={(e) => setCity(e.target.value)}
                >
                  <option value="">Выберите город</option>
                  {meta?.cities.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label>
                День
                <input
                  type="date"
                  required
                  min={meta?.today}
                  value={day}
                  onChange={(e) => setDay(e.target.value)}
                />
              </label>
              <label>
                Свободны с
                <input
                  type="time"
                  required
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </label>
              <label>
                Нужно закончить до
                <input
                  type="time"
                  required
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </label>
              <label>
                Взрослых, от 18 лет
                <input
                  type="number"
                  required
                  min="0"
                  max="30"
                  value={adults}
                  onChange={(e) => setAdults(e.target.value)}
                />
              </label>
              <label>
                Возраст детей, через запятую
                <input
                  placeholder="Например: 8, 12"
                  maxLength={80}
                  value={children}
                  onChange={(e) => setChildren(e.target.value)}
                />
              </label>
              <label>
                Общий бюджет, ₽
                <input
                  type="number"
                  min="0"
                  max="10000000"
                  placeholder="Можно не задавать"
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                />
              </label>
              <label>
                Максимум событий
                <select
                  value={maxEvents}
                  onChange={(e) => setMaxEvents(e.target.value)}
                >
                  {[2, 3, 4].map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
            </div>
            <details className="planner-settings">
              <summary>Запас времени и переезды</summary>
              <p>
                Без вашей оценки переезда соединяем события только на одной
                площадке. Оценку между разными площадками покажем как
                неподтверждённое допущение.
              </p>
              <div className="planner-fields">
                <label>
                  Запас на вход, мин
                  <input
                    type="number"
                    required
                    min="0"
                    max="90"
                    value={buffer}
                    onChange={(e) => setBuffer(e.target.value)}
                  />
                </label>
                <label>
                  Предел переезда, мин
                  <input
                    type="number"
                    required
                    min="0"
                    max="180"
                    value={maxTransfer}
                    onChange={(e) => setMaxTransfer(e.target.value)}
                  />
                </label>
                <label>
                  Ваша оценка переезда, мин
                  <input
                    type="number"
                    min="0"
                    max="180"
                    placeholder="Только одна площадка"
                    value={transfer}
                    onChange={(e) => setTransfer(e.target.value)}
                  />
                </label>
                <label>
                  Один переезд на группу, ₽
                  <input
                    type="number"
                    min="0"
                    max="100000"
                    disabled={transfer === ""}
                    value={transferCost}
                    onChange={(e) => setTransferCost(e.target.value)}
                  />
                </label>
              </div>
            </details>
            <label className="planner-checkbox">
              <input
                type="checkbox"
                checked={allowUnknown}
                onChange={(e) => setAllowUnknown(e.target.checked)}
              />
              При заданном бюджете показывать и варианты с неподтверждённой
              стоимостью
            </label>
            <p className="planner-hint">
              Считаем обычный билет на каждого участника, без предположений о
              скидках. Неизвестную длительность не заменяем догадкой.
            </p>
            <button className="button primary" type="submit" disabled={busy}>
              {busy ? "Составляем…" : "Составить день"}
              <ArrowUpRight size={17} />
            </button>
            {error && (
              <p className="planner-error" role="alert">
                {error}
              </p>
            )}
            {busy && (
              <p role="status">
                Проверяем расписание, возраст и стоимость группы…
              </p>
            )}
          </form>
          {result && (
            <DayPlanResults
              result={result}
              onOpen={onOpen}
              busy={busy}
              onRelax={() =>
                submit(undefined, {
                  ...result.input,
                  allow_unconfirmed_cost: true,
                })
              }
            />
          )}
        </div>
      )}
    </section>
  );
}
