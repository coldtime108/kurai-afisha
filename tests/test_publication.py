from copy import deepcopy
from datetime import datetime, timedelta, timezone

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import select

from kurai.digests import enqueue_digests
from kurai.ingestion import import_rows
from kurai.models import DigestDelivery, Event
from kurai.schemas import SubscriptionFilter
from kurai.subscriptions import owner_hash, save_subscription

NOW = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize("route", ["status", "editor", "import"])
def test_old_draft_published_after_subscription_is_queued(
    client, app, rows, admin, monkeypatch, route
):
    draft = deepcopy(rows[4])
    draft["title"] = "Изолированная проверка старого черновика"
    draft["status"] = "draft"
    client.post("/api/v1/admin/import", headers=admin, json={"rows": [draft]})
    published = NOW + timedelta(hours=1)
    with app.state.sessions() as session:
        for item in session.scalars(select(Event)):
            item.published_at = NOW - timedelta(days=1) if item.status == "published" else None
        item = session.scalar(select(Event).where(Event.title == draft["title"]))
        item.created_at = NOW - timedelta(days=3)
        identifier = item.id
        sub = save_subscription(
            session, owner_hash("telegram", 801), "telegram", SubscriptionFilter(city="Уфа"),
            confirmed=True, telegram_id=801, now=NOW,
        )
        sub.next_digest_at = NOW + timedelta(hours=2)
        session.commit()
    monkeypatch.setattr("kurai.models.utcnow", lambda: published)
    if route == "status":
        response = client.patch(
            f"/api/v1/admin/events/{identifier}/status", headers=admin,
            json={"status": "published"},
        )
    elif route == "editor":
        item = next(row for row in client.get("/api/v1/admin/events", headers=admin).json() if row["id"] == identifier)
        response = client.put(
            f"/api/v1/admin/events/{identifier}", headers=admin,
            json={"event": draft | {"status": "published"}, "expected_updated_at": item["updated_at"]},
        )
    else:
        response = client.post(
            "/api/v1/admin/import", headers=admin,
            json={"rows": [draft | {"status": "published"}]},
        )
        assert response.json()["updated"] == 1
    assert response.status_code == 200
    with app.state.sessions() as session:
        item = session.get(Event, identifier)
        assert item.published_at == published and item.created_at < NOW
        assert enqueue_digests(session, NOW + timedelta(hours=2)) == 1
        assert session.scalar(select(DigestDelivery)).event_ids == [identifier]


def test_editing_public_event_does_not_make_it_new_again(client, app, rows, admin):
    with app.state.sessions() as session:
        for item in session.scalars(select(Event)):
            item.published_at = NOW - timedelta(days=1)
        session.commit()
        sub = save_subscription(
            session, owner_hash("telegram", 802), "telegram", SubscriptionFilter(city="Уфа"),
            confirmed=True, telegram_id=802, now=NOW,
        )
        sub.next_digest_at = NOW + timedelta(hours=1)
        session.commit()
    item = next(row for row in client.get("/api/v1/events").json()["items"] if row["title"] == rows[4]["title"])
    changed = rows[4] | {"description": "Описание уточнено в изолированной проверке."}
    result = client.put(
        "/api/v1/admin/events/" + item["id"], headers=admin,
        json={"event": changed, "expected_updated_at": item["updated_at"]},
    )
    assert result.status_code == 200
    assert result.json()["published_at"] == item["published_at"]
    with app.state.sessions() as session:
        assert enqueue_digests(session, NOW + timedelta(hours=1)) == 0


def test_migration_preserves_old_publication_dates_without_announcing_old_events(app, rows):
    with app.state.sessions() as session:
        import_rows(session, rows)
        for item in session.scalars(select(Event)):
            item.created_at = NOW - timedelta(days=2)
        first = session.scalar(select(Event))
        first.status = "draft"
        session.commit()
    app.state.engine.dispose()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", str(app.state.engine.url))
    config.attributes["ignore_database_env"] = True
    command.downgrade(config, "0002")
    command.upgrade(config, "head")
    with app.state.sessions() as session:
        for item in session.scalars(select(Event)):
            assert item.published_at == (item.created_at if item.status == "published" else None)
