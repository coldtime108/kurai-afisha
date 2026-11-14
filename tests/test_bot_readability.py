from datetime import datetime, timezone

from sqlalchemy import select

from kurai.bot_controller import BotController
from kurai.models import Event


def test_short_menu_keeps_privacy_help_and_full_description_accessible(client, app):
    bot = BotController(
        app.state.sessions, lambda: datetime(2026, 11, 13, 6, tzinfo=timezone.utc)
    )
    start = bot.handle(551, text="/start")
    assert len(start.text) < 400 and "NVIDIA" in start.text
    help_reply = bot.handle(551, callback="help")
    assert (
        "24 часа" in help_reply.text
        and "7 дней" in help_reply.text
        and "/unsubscribe" in help_reply.text
    )
    with app.state.sessions() as session:
        event = session.scalar(select(Event).where(Event.status == "published"))
        event.description = "Описание программы. " * 35 + "Проверочный конец описания."
        identifier = event.id
        session.commit()
    card = bot.handle(551, callback="e:" + identifier)
    assert "Проверочный конец описания." not in card.text
    assert any(action == "d:" + identifier for row in card.buttons for _, action in row)
    full = bot.handle(551, callback="d:" + identifier)
    assert "Проверочный конец описания." in full.text
    with app.state.sessions() as session:
        session.get(Event, identifier).status = "draft"
        session.commit()
    assert "ещё проходит проверку" in bot.handle(551, callback="d:" + identifier).text
