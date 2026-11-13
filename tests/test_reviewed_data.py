from datetime import datetime, timezone
from sqlalchemy import select

from kurai.bot_controller import BotController
from kurai.ingestion import import_rows
from kurai.models import Event
from kurai.seed import reviewed_rows


def test_expanded_reviewed_data_is_repeatable_and_merges_theatre_and_ticket_sources(app):
    rows = reviewed_rows()
    with app.state.sessions() as session:
        first = import_rows(session, rows)
        assert first["added"] == 12 and first["updated"] == 1 and first["rejected"] == 0
        second = import_rows(session, rows)
        assert second["skipped"] == len(rows) and not second["added"]
        event = session.scalar(select(Event).where(Event.title == "Макбет"))
        assert event.city == "Стерлитамак" and event.age_limit == 16
        assert len(event.sources) == 2 and event.duration_min == 170
        assert (event.price_min, event.price_max) == (500, 800)
    controller = BotController(
        app.state.sessions, clock=lambda: datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
    )
    reply = controller.handle(804, text="Спектакль в Стерлитамаке в субботу до 800 рублей")
    assert "Найдено: 1" in reply.text and "Макбет" in reply.text
    assert "Найдено: 0" in controller.handle(805, text="Спектакль в Стерлитамаке с ребенком 8 лет").text
