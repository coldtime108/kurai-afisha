"""A deterministic 2–4 event day plan, with explicit cost and transfer uncertainty."""

from datetime import date as CalendarDate, datetime, time, timedelta
import re
from itertools import combinations
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from .catalog import LOCAL_TZ, day_boundary
from .ingestion import normalize
from .models import Event, utcnow
from .schemas import EventOut


class DayPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    city: str = Field(min_length=1, max_length=120)
    day: CalendarDate
    start_time: time = time(10)
    end_time: time = time(22)
    adults: int = Field(default=1, ge=0, le=30)
    children_ages: list[int] = Field(default_factory=list, max_length=20)
    budget: int | None = Field(default=None, ge=0, le=10_000_000)
    max_events: int = Field(default=3, ge=2, le=4)
    arrival_buffer_min: int = Field(default=15, ge=0, le=90)
    max_transfer_min: int = Field(default=45, ge=0, le=180)
    transfer_minutes: int | None = Field(default=None, ge=0, le=180)
    transfer_cost: int = Field(default=0, ge=0, le=100_000)
    allow_unconfirmed_cost: bool = False

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.start_time.tzinfo
            or self.end_time.tzinfo
            or self.start_time.second
            or self.end_time.second
            or self.start_time.microsecond
            or self.end_time.microsecond
        ):
            raise ValueError(
                "Укажите местное время с точностью до минут, например 10:00"
            )
        if self.end_time <= self.start_time:
            raise ValueError(
                "Конец свободного окна должен быть позже начала в тот же день"
            )
        if (
            self.adults + len(self.children_ages) < 1
            or self.adults + len(self.children_ages) > 30
        ):
            raise ValueError("Укажите от 1 до 30 участников")
        if any(
            isinstance(age, bool) or not 0 <= age <= 17 for age in self.children_ages
        ):
            raise ValueError("Возраст детей — от 0 до 17 лет; взрослые — от 18 лет")
        if self.transfer_minutes is None and self.transfer_cost:
            raise ValueError("Для расходов на переезд укажите и время переезда")
        return self


class PlanStop(BaseModel):
    event: EventOut
    arrive_by: datetime
    start: datetime
    end: datetime
    end_basis: Literal["source_end", "source_duration"]
    transfer_before_min: int
    transfer_basis: Literal["first", "same_place", "user_estimate"]
    group_price_min: int | None
    group_price_max: int | None
    free_before_min: int


class DayRoute(BaseModel):
    status: Literal["ready", "provisional"]
    stops: list[PlanStop]
    cost_min: int | None
    cost_max: int | None
    known_cost_min: int
    transfer_cost: int
    budget_status: Literal["within", "unconfirmed", "not_set"]
    assumptions: list[str]


class DayPlanOut(BaseModel):
    status: Literal["ready", "provisional", "no_plan"]
    message: str
    input: DayPlanInput
    people: int
    timezone: str = "Asia/Yekaterinburg"
    routes: list[DayRoute] = Field(default_factory=list)
    single_options: list[EventOut] = Field(default_factory=list)
    diagnostics: dict[str, int] = Field(default_factory=dict)
    suggestions: list[str] = Field(default_factory=list)
    search_complete: bool = True


def same_place(first, second):
    def key(event):
        return normalize(event.address).removeprefix(normalize(event.city)).strip()

    left, right = key(first), key(second)
    return bool(
        left and right and left == right and not re.search(r"уточн|не указан", left)
    )


def event_end(event):
    if event.date_end:
        return event.date_end, "source_end"
    if event.duration_min:
        return (
            event.date_start + timedelta(minutes=event.duration_min),
            "source_duration",
        )
    return None, None


def price_for(event, people):
    if event.is_free is True:
        return 0, 0
    return (
        event.price_min * people if event.price_min is not None else None,
        event.price_max * people if event.price_max is not None else None,
    )


def build_day_plan(session, request: DayPlanInput, now=None):
    now = now or utcnow()
    if request.day < now.astimezone(LOCAL_TZ).date():
        raise ValueError("Выберите сегодняшний или будущий день")
    start_window = max(datetime.combine(request.day, request.start_time, LOCAL_TZ), now)
    end_window = datetime.combine(request.day, request.end_time, LOCAL_TZ)
    people = request.adults + len(request.children_ages)
    youngest = min(request.children_ages) if request.children_ages else 18
    raw = session.scalars(
        select(Event)
        .where(
            Event.status == "published",
            Event.city == request.city,
            Event.date_start >= day_boundary(request.day),
            Event.date_start < day_boundary(request.day, end=True),
        )
        .order_by(Event.date_start, Event.id)
        .limit(121)
    ).all()
    complete = len(raw) <= 120
    diagnostic = {
        "in_catalog": len(raw),
        "unknown_duration": 0,
        "unknown_age": 0,
        "age_restricted": 0,
        "outside_window": 0,
        "unknown_price": 0,
        "overlap": 0,
        "unknown_transfer": 0,
        "transfer_too_long": 0,
        "budget_rejected": 0,
    }
    candidates, window_alternatives = [], []
    for event in raw[:120]:
        end, basis = event_end(event)
        if end is None:
            diagnostic["unknown_duration"] += 1
            continue
        if event.age_limit is None:
            diagnostic["unknown_age"] += 1
            continue
        if event.age_limit > youngest:
            diagnostic["age_restricted"] += 1
            continue
        arrive = event.date_start - timedelta(minutes=request.arrival_buffer_min)
        lower, upper = price_for(event, people)
        candidate = (event, end, basis, lower, upper)
        if arrive >= now:
            window_alternatives.append(candidate)
        if arrive < start_window or end > end_window:
            diagnostic["outside_window"] += 1
            continue
        if lower is None or upper is None:
            diagnostic["unknown_price"] += 1
        candidates.append(candidate)

    routes = []

    def route_score(route):
        return (
            -len(route.stops),
            route.status != "ready",
            route.cost_max is None,
            route.cost_max if route.cost_max is not None else route.known_cost_min,
            sum(stop.free_before_min for stop in route.stops),
            tuple(stop.event.id for stop in route.stops),
        )

    least_known_budget = None
    checked = 0

    def make_route(path, diagnose=True):
        nonlocal least_known_budget

        def count(reason):
            if diagnose:
                diagnostic[reason] += 1

        stops, estimates, known_min, all_min, all_max, travel_cost = (
            [],
            False,
            0,
            True,
            True,
            0,
        )
        for index, (event, end, basis, lower, upper) in enumerate(path):
            transfer, transfer_basis, free = 0, "first", 0
            arrive = event.date_start - timedelta(minutes=request.arrival_buffer_min)
            if index:
                previous, previous_end = path[index - 1][0], path[index - 1][1]
                if same_place(previous, event):
                    transfer_basis = "same_place"
                elif request.transfer_minutes is None:
                    count("unknown_transfer")
                    return None
                else:
                    transfer, transfer_basis = request.transfer_minutes, "user_estimate"
                    estimates = True
                    travel_cost += request.transfer_cost
                    if transfer > request.max_transfer_min:
                        count("transfer_too_long")
                        return None
                if previous_end + timedelta(minutes=transfer) > arrive:
                    count("overlap")
                    return None
                free = int((arrive - previous_end).total_seconds() // 60) - transfer
            known_min += lower or 0
            all_min = all_min and lower is not None
            all_max = all_max and upper is not None
            stops.append(
                PlanStop(
                    event=EventOut.model_validate(event),
                    arrive_by=arrive,
                    start=event.date_start,
                    end=end,
                    end_basis=basis,
                    transfer_before_min=transfer,
                    transfer_basis=transfer_basis,
                    group_price_min=lower,
                    group_price_max=upper,
                    free_before_min=free,
                )
            )
        minimum = known_min + travel_cost if all_min else None
        maximum = (
            sum(stop.group_price_max for stop in stops) + travel_cost
            if all_max
            else None
        )
        if diagnose and maximum is not None and not estimates:
            least_known_budget = (
                maximum
                if least_known_budget is None
                else min(least_known_budget, maximum)
            )
        fits = (
            request.budget is not None
            and maximum is not None
            and maximum <= request.budget
        )
        if request.budget is not None:
            if known_min + travel_cost > request.budget or (
                not fits and not request.allow_unconfirmed_cost
            ):
                count("budget_rejected")
                return None
        assumptions = [
            "Расчёт: по одному обычному билету на каждого участника, включая детей. Льготы и наличие мест уточняйте у организатора."
        ]
        if not all_max:
            assumptions.append(
                "Часть цен или верхняя граница стоимости не указаны. Полную стоимость нужно уточнить."
            )
        if estimates:
            assumptions.append(
                "Время и расходы между разными площадками взяты из вашей оценки; дорожный маршрут не проверен."
            )
        if request.budget is not None and not fits:
            assumptions.append(
                "Соответствие общему бюджету не подтверждено. Уточните цены перед покупкой."
            )
        return DayRoute(
            status=(
                "provisional"
                if not all_max or estimates or (request.budget is not None and not fits)
                else "ready"
            ),
            stops=stops,
            cost_min=minimum,
            cost_max=maximum,
            known_cost_min=known_min + travel_cost,
            transfer_cost=travel_cost,
            budget_status=(
                "not_set"
                if request.budget is None
                else "within" if fits else "unconfirmed"
            ),
            assumptions=assumptions,
        )

    # Small catalog: examine combinations directly, preserving deterministic ordering.
    for size in range(2, request.max_events + 1):
        for path in combinations(candidates, size):
            checked += 1
            if checked > 20_000:
                complete = False
                break
            route = make_route(path)
            if route:
                routes.append(route)
                routes.sort(key=route_score)
                del routes[3:]
        if not complete and checked > 20_000:
            break
    routes.sort(key=route_score)
    suggestions = []
    if not routes:
        window_change = None
        if diagnostic["outside_window"]:
            for path in combinations(window_alternatives, 2):
                # Keep age, prices and transfers unchanged; relax only the window.
                if not make_route(path, diagnose=False):
                    continue
                arrive = path[0][0].date_start - timedelta(
                    minutes=request.arrival_buffer_min
                )
                end = path[-1][1]
                if (
                    arrive.astimezone(LOCAL_TZ).date() != request.day
                    or end.astimezone(LOCAL_TZ).date() != request.day
                ):
                    continue
                before = max(0, int((start_window - arrive).total_seconds() / 60))
                after = max(0, int((end - end_window).total_seconds() / 60))
                change = (
                    before + after,
                    min(start_window, arrive),
                    max(end_window, end),
                )
                if change[0] and (window_change is None or change < window_change):
                    window_change = change
        if window_change:
            _, new_start, new_end = window_change
            suggestions.append(
                f"Минимальное найденное расширение окна — до {new_start.astimezone(LOCAL_TZ):%H:%M}–{new_end.astimezone(LOCAL_TZ):%H:%M}. Оно позволяет соединить два события с прежним составом и условиями стоимости/переезда."
            )
        if (
            request.budget is not None
            and least_known_budget is not None
            and least_known_budget > request.budget
        ):
            suggestions.append(
                f"Для этого состава группы и окна минимальная найденная верхняя оценка билетов — {least_known_budget} ₽. Можно увеличить бюджет до этой суммы."
            )
        if request.budget is not None and diagnostic["unknown_price"]:
            suggestions.append(
                "Уточните цены у организаторов или явно разрешите варианты с неподтверждённой стоимостью."
            )
        if diagnostic["unknown_duration"]:
            suggestions.append(
                "Для части событий неизвестно время окончания: сначала уточните длительность у организатора."
            )
        if diagnostic["unknown_transfer"]:
            suggestions.append(
                "Укажите свою оценку переезда или выберите события на одной площадке."
            )
        if not window_change and (
            diagnostic["outside_window"] or diagnostic["overlap"]
        ):
            suggestions.append(
                "Попробуйте расширить свободное окно или выбрать другой день."
            )
        if diagnostic["transfer_too_long"]:
            suggestions.append(
                "Ваша оценка переезда превышает выбранный предел. Увеличьте предел или оставьте одну площадку."
            )
        if diagnostic["age_restricted"]:
            suggestions.append(
                "Часть событий не подходит по возрастной маркировке самого младшего участника. Выберите другой день с подходящими событиями."
            )
        if diagnostic["unknown_age"]:
            suggestions.append(
                "Возрастную маркировку части событий нужно уточнить у организатора."
            )
        if not suggestions:
            suggestions.append(
                "Попробуйте другой день: в проверенной афише пока мало совместимых событий для этой группы."
            )
        if not complete:
            suggestions.insert(
                0,
                "Вариантов слишком много для полного перебора; сузьте условия. Отсутствие маршрута не доказано.",
            )
    singles = []
    if not routes:
        for event, _, _, lower, upper in candidates:
            if (
                request.budget is None
                or (upper is not None and upper <= request.budget)
                or (
                    request.allow_unconfirmed_cost
                    and (lower is None or lower <= request.budget)
                )
            ):
                singles.append(EventOut.model_validate(event))
    selected = routes[:3]
    if not complete and selected:
        suggestions.append(
            "Показаны найденные совместимые варианты; полный перебор не завершён. Другие маршруты могут быть лучше."
        )
    status = selected[0].status if selected else "no_plan"
    message = (
        "Маршрут составлен по времени, возрасту и выбранным условиям."
        if status == "ready"
        else (
            "Расписание составлено. Есть неподтверждённые цены или оценки переезда — проверьте их перед посещением."
            if status == "provisional"
            else "Не удалось составить маршрут из двух и более событий по этим условиям."
        )
    )
    return DayPlanOut(
        status=status,
        message=message,
        input=request,
        people=people,
        routes=selected,
        single_options=singles[:3],
        diagnostics=diagnostic,
        suggestions=suggestions,
        search_complete=complete,
    )


def parse_party(value):
    lowered = value.lower().replace("ё", "е")
    adults = re.search(r"(\d{1,2})\s*взросл", lowered)
    children = re.search(
        r"(?:дети|ребенок|ребенка|ребенку)\s*[:—-]?\s*([\d\s,и]+)(?:лет|год\w*)?",
        lowered,
    )
    if not adults:
        raise ValueError(
            "Напишите число взрослых, например «2 взрослых» или «1 взрослый, дети 8 и 12»."
        )
    ages = [int(n) for n in re.findall(r"\d+", children[1])] if children else []
    if re.search(r"дет|ребен", lowered) and not ages:
        raise ValueError(
            "Укажите возраст каждого ребёнка, например «1 взрослый, дети 8 и 12»."
        )
    return {"adults": int(adults[1]), "children_ages": ages}


def format_day_plan(result: DayPlanOut, index=0):
    lines = [
        "Культурный день · " + result.input.city,
        f"{result.input.day:%d.%m.%Y} · {result.input.start_time:%H:%M}–{result.input.end_time:%H:%M} · время Башкортостана",
        f"Участников: {result.people}. " + result.message,
        f"Взрослых: {result.input.adults}. "
        + (
            "Возраст детей: " + ", ".join(map(str, result.input.children_ages)) + ". "
            if result.input.children_ages
            else ""
        )
        + (
            f"Общий бюджет: {result.input.budget} ₽."
            if result.input.budget is not None
            else "Бюджет не задан."
        ),
    ]
    if result.routes:
        route = result.routes[min(index, len(result.routes) - 1)]
        for number, stop in enumerate(route.stops, 1):
            local_start, local_end = stop.start.astimezone(
                LOCAL_TZ
            ), stop.end.astimezone(LOCAL_TZ)
            lines.append(
                f"{number}. {local_start:%H:%M}–{local_end:%H:%M} · {stop.event.title}\n{stop.event.venue}\nПрибыть к {stop.arrive_by.astimezone(LOCAL_TZ):%H:%M}; {stop.event.age_limit}+."
            )
            if stop.transfer_basis == "same_place":
                lines.append("Та же площадка, переезд не нужен.")
            elif stop.transfer_basis == "user_estimate":
                lines.append(
                    f"Переезд: {stop.transfer_before_min} мин по вашей оценке."
                )
            if stop.free_before_min:
                lines.append(
                    f"Свободное время между событиями: {stop.free_before_min} мин."
                )
        if route.cost_max is not None:
            lines.append(
                f"Билеты и заложенные переезды на группу: {route.cost_min}–{route.cost_max} ₽."
            )
        elif route.cost_min is not None:
            lines.append(
                f"На группу — от {route.cost_min} ₽; верхняя граница неизвестна."
            )
        else:
            lines.append(
                "Полная стоимость группы неизвестна."
                + (
                    f" Известная часть — от {route.known_cost_min} ₽."
                    if route.known_cost_min
                    else " Цены билетов нужно уточнить у организатора."
                )
            )
        lines.extend(route.assumptions)
    else:
        lines.extend(result.suggestions)
        if result.single_options:
            lines.append(
                "По отдельности подходят: "
                + ", ".join(e.title for e in result.single_options)
            )
    if result.routes:
        lines.extend(result.suggestions)
    return "\n\n".join(lines)
