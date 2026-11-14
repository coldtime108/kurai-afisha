from datetime import datetime, timezone
from sqlalchemy import select

from kurai.bot_controller import BotController
from kurai.ingestion import import_rows
from kurai.models import Event
from kurai.seed import reviewed_rows
from kurai.query_parser import parse_query


def test_expanded_reviewed_data_is_repeatable_and_merges_theatre_and_ticket_sources(
    app,
):
    rows = reviewed_rows()
    with app.state.sessions() as session:
        first = import_rows(session, rows)
        assert (
            first["added"] == len(rows) - 1
            and first["updated"] == 1
            and first["rejected"] == 0
        )
        second = import_rows(session, rows)
        assert second["skipped"] == len(rows) and not second["added"]
        event = session.scalar(select(Event).where(Event.title == "Макбет"))
        assert event.city == "Стерлитамак" and event.age_limit == 16
        assert len(event.sources) == 2 and event.duration_min == 170
        assert (event.price_min, event.price_max) == (500, 800)
    controller = BotController(
        app.state.sessions, clock=lambda: datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
    )
    reply = controller.handle(
        804, text="Спектакль в Стерлитамаке в субботу до 800 рублей"
    )
    assert "Найдено: 1" in reply.text and "Макбет" in reply.text
    child_reply = controller.handle(
        805, text="Спектакль в Стерлитамаке с ребенком 8 лет"
    ).text
    assert "Найдено: 1" in child_reply and "Царевна" in child_reply


def test_regional_cities_have_real_sessions_and_work_in_search_and_bot(client, app):
    now = datetime(2026, 11, 14, 6, tzinfo=timezone.utc)
    with app.state.sessions() as session:
        import_rows(session, reviewed_rows())
    cities = client.get("/api/v1/meta").json()["cities"]
    assert len(cities) == 13
    bot = BotController(app.state.sessions, lambda: now)
    city_menu = bot.handle(9001, callback="cities")
    assert {
        label
        for row in city_menu.buttons
        for label, action in row
        if action.startswith("city:")
    } == set(cities)
    forms = [
        "в Белебее",
        "в Бирске",
        "в Ишимбае",
        "в Кумертау",
        "в Мелеузе",
        "в Нефтекамске",
        "в Октябрьском",
        "в Салавате",
        "в Сибае",
        "в Туймазах",
        "в Янауле",
    ]
    for form in forms:
        city = parse_query("Концерт " + form, {}, now)["city"]
        result = client.get(
            "/api/v1/events",
            params={"city": city, "date_from": "2026-11-14", "date_to": "2027-03-31"},
        ).json()
        assert result["total"] > 0 and all(
            item["city"] == city for item in result["items"]
        )
    reply = bot.handle(9002, text="Концерт в Октябрьском 15 ноября до 1300 рублей")
    assert "Данир Сабиров" in reply.text
    assert "Мунча Ташы" not in reply.text
