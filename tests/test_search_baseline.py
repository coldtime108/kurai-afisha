from datetime import datetime, timezone
from sqlalchemy import select

from kurai.bot_controller import BotController
from kurai.evaluate import evaluate
from kurai.models import Event

NOW = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)


def test_reviewed_baseline_uses_isolated_database_even_with_database_env(monkeypatch, tmp_path):
    untouched = tmp_path / "not-the-evaluation-database.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + untouched.as_posix())
    result = evaluate()
    assert result["passed"], [item for item in result["results"] if not item["passed"]]
    assert result["api"]["cases"] >= 20 and result["bot"]["cases"] >= 10
    assert not untouched.exists()


def test_bot_understands_city_added_to_catalog(client, app):
    with app.state.sessions() as session:
        event = session.scalar(select(Event).where(Event.title == "Травиата"))
        event.city = "Ишимбай"
        session.commit()
    reply = BotController(app.state.sessions, clock=lambda: NOW).handle(803, text="Травиата в Ишимбае")
    assert "Ишимбай" in reply.text and "Найдено: 1" in reply.text


def test_empty_results_explain_venue_and_free_entry_filters(client):
    missing_venue = client.get("/api/v1/events", params={"venue": "Неизвестная площадка"}).json()
    assert any("площадках" in message for message in missing_venue["suggestions"])
    free = client.get("/api/v1/events", params={"is_free": True}).json()
    assert any("бесплатного" in message for message in free["suggestions"])
