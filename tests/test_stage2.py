import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from sqlalchemy import func, select
from kurai.bot_controller import BotController
from kurai.db import session_factory
from kurai.digests import enqueue_digests, pending_deliveries
from kurai.models import BotDialog, DigestDelivery, Event, Feedback, Subscription
from kurai.query_parser import parse_query
from kurai.schemas import SubscriptionFilter
from kurai.subscriptions import (
    cleanup,
    delete_subscription,
    owner_hash,
    period_bounds,
    save_subscription,
)
from kurai.telegram_worker import dispatch_digests, markup

NOW = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
WEB = {"Authorization": "Bearer " + "a" * 64}
OTHER = {"Authorization": "Bearer " + "b" * 64}


def test_subscription_requires_confirmation_and_has_no_cross_user_access(client):
    values = {"city": "Уфа", "category": "concert", "period": "week"}
    assert (
        client.post("/api/v1/subscriptions", headers=WEB, json=values).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/subscriptions", headers=WEB, json=values | {"confirmed": False}
        ).status_code
        == 422
    )
    created = client.post(
        "/api/v1/subscriptions", headers=WEB, json=values | {"confirmed": True}
    )
    assert created.status_code == 201
    identifier = created.json()["id"]
    assert not client.get("/api/v1/subscriptions", headers=OTHER).json()
    assert (
        client.get(
            f"/api/v1/subscriptions/{identifier}/events", headers=OTHER
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/subscriptions/{identifier}", headers=OTHER).status_code
        == 404
    )
    assert client.get("/api/v1/subscriptions").status_code == 401


def test_subscription_update_keeps_one_record_and_delete_removes_identifier(
    client, app
):
    first = client.post(
        "/api/v1/subscriptions", headers=WEB, json={"city": "Уфа", "confirmed": True}
    ).json()
    second = client.post(
        "/api/v1/subscriptions",
        headers=WEB,
        json={"city": "Салават", "confirmed": True},
    ).json()
    assert first["id"] == second["id"]
    assert (
        client.get("/api/v1/subscriptions", headers=WEB).json()[0]["filters"]["city"]
        == "Салават"
    )
    assert (
        client.delete("/api/v1/subscriptions/" + first["id"], headers=WEB).status_code
        == 204
    )
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Subscription)) == 0


def test_manual_edit_preserves_id_updates_search_and_rejects_stale_version(
    client, rows, admin
):
    item = client.get("/api/v1/events").json()["items"][0]
    changed = deepcopy(rows[0])
    changed["title"] = "Травиата · уточнённый сеанс"
    changed["date_start"] = "2026-11-17T19:00:00+05:00"
    response = client.put(
        "/api/v1/admin/events/" + item["id"],
        headers=admin,
        json={"event": changed, "expected_updated_at": item["updated_at"]},
    )
    assert response.status_code == 200
    assert response.json()["id"] == item["id"]
    assert (
        client.get(
            "/api/v1/events",
            params={"date_from": "2026-11-17", "date_to": "2026-11-17"},
        ).json()["items"][0]["id"]
        == item["id"]
    )
    assert (
        client.put(
            "/api/v1/admin/events/" + item["id"],
            headers=admin,
            json={"event": changed, "expected_updated_at": item["updated_at"]},
        ).status_code
        == 409
    )
    assert any(
        entry["action"] == "manual_edit"
        for entry in client.get("/api/v1/admin/audit", headers=admin).json()
    )


def test_manual_create_is_draft_and_duplicate_is_rejected(client, rows, admin):
    draft = deepcopy(rows[0])
    draft["title"] = "Изолированная тестовая карточка"
    draft["status"] = "draft"
    created = client.post("/api/v1/admin/events", headers=admin, json=draft)
    assert created.status_code == 201
    assert client.get("/api/v1/events/" + created.json()["id"]).status_code == 404
    assert (
        client.post("/api/v1/admin/events", headers=admin, json=draft).status_code
        == 409
    )
    assert client.post("/api/v1/admin/events", json=draft).status_code == 401


def test_import_cannot_silently_overwrite_manual_review(client, rows, admin):
    item = client.get("/api/v1/events").json()["items"][0]
    revised = deepcopy(rows[0])
    revised["description"] = "Сведения проверены модератором."
    assert (
        client.put(
            "/api/v1/admin/events/" + item["id"],
            headers=admin,
            json={"event": revised, "expected_updated_at": item["updated_at"]},
        ).status_code
        == 200
    )
    newer = deepcopy(rows[0])
    newer["description"] = "Новая внешняя версия, ещё не проверенная."
    report = client.post(
        "/api/v1/admin/import", headers=admin, json={"rows": [newer]}
    ).json()
    assert report["rejected"] == 1
    assert (
        client.get("/api/v1/events/" + item["id"]).json()["description"]
        == revised["description"]
    )


def test_search_matches_cyrillic_tags_case_insensitively(client, rows, admin):
    item = deepcopy(rows[4])
    item["tags"] = ["КУРАЙ", "Джаз"]
    client.post("/api/v1/admin/import", headers=admin, json={"rows": [item]})
    assert client.get("/api/v1/events", params={"q": "джаз"}).json()["total"] == 1


def test_parser_typo_multifilter_and_current_day():
    parsed = parse_query("Концерт в стерлитакмае в субботу до 1000 рублей", {}, NOW)
    assert (
        parsed["city"] == "Стерлитамак"
        and parsed["category"] == "concert"
        and parsed["price_max"] == 1000
    )
    assert parsed["date_from"] == "2026-11-14" and parsed["q"] == ""
    assert parse_query("завтра", {"city": "Уфа"}, NOW)["date_from"] == "2026-11-14"
    sunday = NOW + timedelta(days=2)
    start, end = period_bounds("weekend", sunday)
    assert start == end and start.isoformat() == "2026-11-15"


def controller(app):
    return BotController(app.state.sessions, clock=lambda: NOW)


def test_bot_start_search_card_and_pagination_share_real_catalog(client, app):
    bot = controller(app)
    assert any(
        action == "catalog"
        for row in bot.handle(101, text="/start").buttons
        for _, action in row
    )
    assert "Найдено:" in bot.handle(101, text="/catalog").text
    result = bot.handle(101, text="Травиата")
    assert "Травиата" in result.text and "Цена уточняется" in result.text
    cards = [a for row in result.buttons for _, a in row if a.startswith("e:")]
    assert len(cards) == 2
    detail = bot.handle(101, callback=cards[0])
    assert "Итальянский" in detail.text and "170 мин" in detail.text
    assert any(a.startswith("url:https://") for row in detail.buttons for _, a in row)
    bot.handle(101, callback="reset")
    more = bot.handle(101, callback="catalog")
    assert any(a == "page:2" for row in more.buttons for _, a in row)


def test_bot_subscription_confirm_cancel_and_nonce_replay(client, app):
    bot = controller(app)
    bot.handle(102, text="Концерт в Уфе")
    preview = bot.handle(102, text="/subscribe")
    action = next(
        a for row in preview.buttons for _, a in row if a.startswith("confirm:")
    )
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Subscription)) == 0
    bot.handle(102, callback=action)
    with app.state.sessions() as session:
        saved = session.scalar(select(Subscription))
        assert saved.telegram_id == 102 and saved.filters["city"] == "Уфа"
    assert "устарело" in bot.handle(102, callback=action).text
    edit = bot.handle(102, callback="subscription-edit")
    select_salavat = next(
        a for row in edit.buttons for label, a in row if label == "Салават"
    )
    assert "Подтвердить" in bot.handle(102, callback=select_salavat).text
    bot.handle(102, text="/cancel")
    with app.state.sessions() as session:
        assert session.scalar(select(Subscription)).filters["city"] == "Уфа"
    bot.handle(102, text="Концерт в Салавате")
    bot.handle(102, text="/subscribe")
    bot.handle(102, text="/cancel")
    with app.state.sessions() as session:
        assert session.scalar(select(Subscription)).filters["city"] == "Уфа"
    bot.handle(102, text="/unsubscribe")
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Subscription)) == 0
        assert session.get(BotDialog, owner_hash("telegram", 102)) is None


def test_bot_confirmation_is_bound_to_owner_and_expires(client, app):
    bot = controller(app)
    bot.handle(103, text="Уфа")
    reply = bot.handle(103, text="/subscribe")
    action = next(
        a for row in reply.buttons for _, a in row if a.startswith("confirm:")
    )
    assert "устарело" in bot.handle(999, callback=action).text
    later = BotController(app.state.sessions, clock=lambda: NOW + timedelta(minutes=11))
    assert "устарело" in later.handle(103, callback=action).text


def test_bot_feedback_is_only_saved_after_confirmation(client, app):
    bot = controller(app)
    bot.handle(104, text="/feedback")
    reply = bot.handle(104, text="Пожалуйста, уточните время у организатора.")
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Feedback)) == 0
    action = next(
        a for row in reply.buttons for _, a in row if a.startswith("feedback-confirm:")
    )
    bot.handle(104, callback=action)
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Feedback)) == 1


def test_cancelled_bot_card_not_recommended(client, app, admin):
    item = client.get("/api/v1/events").json()["items"][0]
    client.patch(
        f"/api/v1/admin/events/{item['id']}/status",
        headers=admin,
        json={"status": "cancelled"},
    )
    bot = controller(app)
    assert "ОТМЕНЕНО" in bot.handle(105, callback="e:" + item["id"]).text
    reply = bot.handle(105, text="Травиата")
    assert not any(a == "e:" + item["id"] for row in reply.buttons for _, a in row)


def test_expiry_removes_subscription_queue_and_private_dialog(client, app):
    with app.state.sessions() as session:
        sub = save_subscription(
            session,
            owner_hash("telegram", 106),
            "telegram",
            SubscriptionFilter(city="Уфа"),
            confirmed=True,
            telegram_id=106,
            now=NOW - timedelta(days=181),
        )
        session.add(
            DigestDelivery(
                subscription_id=sub.id,
                day="2026-01-01",
                event_ids=[],
                next_attempt_at=NOW,
            )
        )
        session.add(
            BotDialog(
                owner_hash=owner_hash("telegram", 106),
                data={},
                expires_at=NOW - timedelta(seconds=1),
            )
        )
        session.commit()
        cleanup(session, NOW)
        assert not session.scalars(select(Subscription)).all()
        assert not session.scalars(select(DigestDelivery)).all()
        assert not session.scalars(select(BotDialog)).all()


def test_digest_queue_daily_dedup_and_excludes_cancelled(client, app):
    with app.state.sessions() as session:
        sub = save_subscription(
            session,
            owner_hash("telegram", 107),
            "telegram",
            SubscriptionFilter(city="Уфа"),
            confirmed=True,
            telegram_id=107,
            now=NOW - timedelta(days=1),
        )
        sub.next_digest_at = NOW - timedelta(seconds=1)
        for event in session.scalars(select(Event)):
            event.created_at = NOW - timedelta(hours=1)
            event.published_at = NOW - timedelta(hours=1)
        cancelled = session.scalar(select(Event).order_by(Event.date_start))
        cancelled.status = "cancelled"
        session.commit()
        assert enqueue_digests(session, NOW) == 1
        assert enqueue_digests(session, NOW) == 0
        pending = pending_deliveries(session, NOW)
        assert pending and all(
            e.status == "published" for _, _, events in pending for e in events
        )
        delete_subscription(session, sub.owner_hash, "telegram")
        assert not pending_deliveries(session, NOW)


def test_bot_markup_contains_only_callback_or_source_links():
    from kurai.bot_controller import BotReply

    keyboard = markup(
        BotReply(
            "x", [[("Событие", "e:123")], [("Источник", "url:https://example.org")]]
        )
    )
    assert keyboard.inline_keyboard[0][0].callback_data == "e:123"
    assert keyboard.inline_keyboard[1][0].url == "https://example.org"
