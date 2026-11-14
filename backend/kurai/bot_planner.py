"""A compact planner conversation; uses the same calculation as the website."""

from datetime import date, datetime, timedelta
import re
from sqlalchemy import select
from .catalog import LOCAL_TZ
from .models import Event
from .planner import DayPlanInput, build_day_plan, format_day_plan, parse_party
from .query_parser import parse_query


def plan_reply(result, index=0):
    buttons = []
    events = (
        [stop.event for stop in result.routes[min(index, len(result.routes) - 1)].stops]
        if result.routes
        else result.single_options
    )
    for event in events:
        buttons.append(
            [
                (event.title[:42], "e:" + event.id),
                ("Источник", "url:" + str(event.source_url)),
            ]
        )
    if len(result.routes) > 1:
        buttons.append(
            [
                (f"Вариант {i+1}", f"dp:alt:{i}")
                for i in range(len(result.routes))
                if i != index
            ]
        )
    if (
        result.status == "no_plan"
        and result.input.budget is not None
        and not result.input.allow_unconfirmed_cost
        and result.diagnostics.get("unknown_price", 0)
    ):
        buttons.append([("Показать с неподтверждённой ценой", "dp:relax")])
    buttons.append([("Другой день / состав", "planner"), ("К афише", "catalog")])
    return format_day_plan(result, index), buttons


def handle_planner(session, data, text, callback, now):
    if text == "/plan" or callback == "planner":
        data["planner_wizard"] = {"step": "city", "input": {}}
        data.pop("awaiting", None)
        data.pop("pending", None)
        data.pop("feedback_pending", None)
    elif callback and callback.startswith(("dp:alt:", "dp:relax")):
        values = data.get("day_plan_request")
        if not values:
            return "План устарел. Начните заново: /plan.", [
                [("Спланировать день", "planner")]
            ]
        values = dict(values)
        if callback == "dp:relax":
            values["allow_unconfirmed_cost"] = True
        result = build_day_plan(session, DayPlanInput.model_validate(values), now)
        data["day_plan_request"] = result.input.model_dump(mode="json")
        index = int(callback.split(":")[-1]) if callback.startswith("dp:alt:") else 0
        return plan_reply(result, min(max(index, 0), max(len(result.routes) - 1, 0)))
    wizard = data.get("planner_wizard")
    if not wizard:
        return None
    values, step = dict(wizard["input"]), wizard["step"]
    cities = list(
        session.scalars(
            select(Event.city)
            .where(Event.status == "published")
            .distinct()
            .order_by(Event.city)
        )
    )
    if step == "city":
        chosen = None
        if callback and callback.startswith("dp:city:"):
            try:
                chosen = data.get("planner_cities", [])[int(callback[8:])]
            except (ValueError, IndexError):
                pass
        elif text and not text.startswith("/"):
            chosen = parse_query(text, {}, now, cities=cities).get("city")
        if chosen:
            values["city"], step = chosen, "day"
        else:
            data["planner_cities"] = cities
            return "Культурный день · шаг 1/6\n\nВыберите город или напишите его название. /cancel — выйти из планирования.", [
                [(city, f"dp:city:{i}")] for i, city in enumerate(cities)
            ] + [
                [("К афише", "catalog")]
            ]
    elif step == "day":
        chosen = callback[7:] if callback and callback.startswith("dp:day:") else text
        if chosen:
            try:
                if chosen.lower() == "завтра":
                    selected = now.astimezone(LOCAL_TZ).date() + timedelta(days=1)
                else:
                    try:
                        selected = date.fromisoformat(chosen.strip())
                    except ValueError:
                        selected = datetime.strptime(chosen.strip(), "%d.%m.%Y").date()
                if selected < now.astimezone(LOCAL_TZ).date():
                    raise ValueError()
                values["day"], step = selected.isoformat(), "party"
            except ValueError:
                return (
                    "Укажите будущую дату в формате ДД.ММ.ГГГГ или напишите «завтра».",
                    [[("Заново", "planner")]],
                )
    elif step == "party":
        chosen = callback[9:] if callback and callback.startswith("dp:party:") else text
        if chosen:
            try:
                party = parse_party(chosen)
                DayPlanInput.model_validate(values | party)
                values.update(party)
                step = "window"
            except ValueError:
                return (
                    "Укажите состав: «2 взрослых» или «1 взрослый, дети 8 и 12». Всего 1–30 участников, дети — до 17 лет.",
                    [
                        [
                            ("1 взрослый", "dp:party:1 взрослый"),
                            ("2 взрослых", "dp:party:2 взрослых"),
                        ]
                    ],
                )
    elif step == "window":
        chosen = (
            callback[10:] if callback and callback.startswith("dp:window:") else text
        )
        if chosen:
            clocks = re.findall(r"\b\d{1,2}:\d{2}\b", chosen)
            try:
                if len(clocks) != 2:
                    raise ValueError()
                validated = DayPlanInput.model_validate(
                    values | {"start_time": clocks[0], "end_time": clocks[1]}
                )
                values.update(
                    start_time=validated.start_time.isoformat(),
                    end_time=validated.end_time.isoformat(),
                )
                step = "budget"
            except ValueError:
                return "Нужно окно в пределах одного дня, например «10:00–22:00».", [
                    [("10:00–22:00", "dp:window:10:00-22:00")]
                ]
    elif step == "budget":
        chosen = (
            callback[10:] if callback and callback.startswith("dp:budget:") else text
        )
        if chosen:
            try:
                budget = (
                    None
                    if chosen.lower().strip()
                    in ("none", "без бюджета", "без ограничения", "не задан")
                    else int(re.sub(r"\s|₽|рублей|руб", "", chosen.lower()).strip())
                )
                DayPlanInput.model_validate(values | {"budget": budget})
                values["budget"], step = budget, "transfer"
            except ValueError:
                return (
                    "Напишите общий бюджет в рублях на всю группу или «без бюджета».",
                    [[("Пока без бюджета", "dp:budget:none")]],
                )
    elif step == "transfer":
        chosen = callback[8:] if callback and callback.startswith("dp:move:") else text
        if chosen:
            if chosen.lower().strip() in ("same", "одна площадка", "без переезда"):
                values.update(transfer_minutes=None, transfer_cost=0)
            else:
                numbers = re.findall(r"\d+", chosen)
                if len(numbers) != 2:
                    return (
                        "Напишите время переезда и стоимость на всю группу, например «30 200». Или выберите одну площадку.",
                        [[("Только одна площадка", "dp:move:same")]],
                    )
                values.update(
                    transfer_minutes=int(numbers[0]),
                    max_transfer_min=int(numbers[0]),
                    transfer_cost=int(numbers[1]),
                )
            try:
                request = DayPlanInput.model_validate(values)
            except ValueError:
                return (
                    "Проверьте оценку: время до 180 минут, стоимость до 100 000 ₽ на группу за переезд.",
                    [[("Только одна площадка", "dp:move:same")]],
                )
            result = build_day_plan(session, request, now)
            data["day_plan_request"] = request.model_dump(mode="json")
            data.pop("planner_wizard", None)
            return plan_reply(result)
    data["planner_wizard"] = {"step": step, "input": values}
    if step == "day":
        dates = []
        for stamp in session.scalars(
            select(Event.date_start)
            .where(
                Event.status == "published",
                Event.city == values["city"],
                Event.date_start >= now,
            )
            .order_by(Event.date_start)
            .limit(30)
        ):
            local = stamp.astimezone(LOCAL_TZ).date()
            if local not in dates:
                dates.append(local)
        return (
            "Шаг 2/6 · На какой день? Выберите дату из афиши или напишите ДД.ММ.ГГГГ.",
            [[(f"{d:%d.%m.%Y}", "dp:day:" + d.isoformat())] for d in dates[:4]]
            + [[("Заново", "planner")]],
        )
    if step == "party":
        return (
            "Шаг 3/6 · Кто идёт? Например «2 взрослых» или «1 взрослый, дети 8 и 12». Возраст проверю по самому младшему участнику.",
            [
                [
                    ("1 взрослый", "dp:party:1 взрослый"),
                    ("2 взрослых", "dp:party:2 взрослых"),
                ]
            ],
        )
    if step == "window":
        return (
            "Шаг 4/6 · Какое свободное окно? В него должны поместиться все события и запас 15 минут на вход.",
            [
                [
                    ("10:00–22:00", "dp:window:10:00-22:00"),
                    ("12:00–21:00", "dp:window:12:00-21:00"),
                ]
            ],
        )
    if step == "budget":
        return (
            "Шаг 5/6 · Какой общий бюджет на всю группу? Считаю по обычному билету на каждого; льготы не предполагаю. Можно пока без бюджета — тогда неизвестные цены будут явно отмечены.",
            [[("Пока без бюджета", "dp:budget:none")]],
        )
    return (
        "Шаг 6/6 · Перемещения. Можно оставить одну площадку. Для разных площадок напишите свою оценку: минуты и рубли на группу за один переезд, например «30 200». Карты и пробки пока не подключены.",
        [
            [
                ("Только одна площадка", "dp:move:same"),
                ("Пешком: 30 мин, 0 ₽", "dp:move:30 0"),
            ]
        ],
    )
