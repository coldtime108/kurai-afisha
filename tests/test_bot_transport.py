import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import Chat, Message, Update
from sqlalchemy import select
from kurai.models import DigestDelivery, Event
from kurai.schemas import SubscriptionFilter
from kurai.subscriptions import owner_hash, save_subscription
from kurai.telegram_worker import build_router, dispatch_digests
from kurai.bot_controller import BotController

NOW = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)


class OfflineTelegram(BaseSession):
    """A Telegram transport that never opens a socket."""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=100,
                date=NOW,
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        if isinstance(method, AnswerCallbackQuery):
            return True
        raise AssertionError("Unexpected Telegram API method")


def test_real_dispatcher_handles_private_search_and_ignores_groups(client, app):
    async def scenario():
        transport = OfflineTelegram()
        bot = Bot("123456:OFFLINE_TEST_ONLY", session=transport)
        dispatcher = Dispatcher()
        dispatcher.include_router(
            build_router(BotController(app.state.sessions, clock=lambda: NOW))
        )
        private = {
            "message_id": 1,
            "date": int(NOW.timestamp()),
            "chat": {"id": 501, "type": "private"},
            "from": {"id": 501, "is_bot": False, "first_name": "Test"},
            "text": "Травиата",
        }
        await dispatcher.feed_update(
            bot, Update.model_validate({"update_id": 1, "message": private})
        )
        sent = [v for v in transport.calls if isinstance(v, SendMessage)]
        assert len(sent) == 1 and "Травиата" in sent[0].text and sent[0].chat_id == 501
        group = private | {"chat": {"id": -100, "type": "group"}}
        await dispatcher.feed_update(
            bot, Update.model_validate({"update_id": 2, "message": group})
        )
        assert len([v for v in transport.calls if isinstance(v, SendMessage)]) == 1
        await bot.session.close()

    asyncio.run(scenario())


def test_callback_acknowledged_but_foreign_chat_not_used(client, app):
    async def scenario():
        transport = OfflineTelegram()
        bot = Bot("123456:OFFLINE_TEST_ONLY", session=transport)
        dispatcher = Dispatcher()
        dispatcher.include_router(
            build_router(BotController(app.state.sessions, clock=lambda: NOW))
        )
        callback = {
            "id": "offline-callback",
            "from": {"id": 502, "is_bot": False, "first_name": "Test"},
            "chat_instance": "offline",
            "data": "catalog",
            "message": {
                "message_id": 1,
                "date": int(NOW.timestamp()),
                "chat": {"id": 501, "type": "private"},
                "text": "Menu",
            },
        }
        await dispatcher.feed_update(
            bot, Update.model_validate({"update_id": 1, "callback_query": callback})
        )
        assert any(isinstance(v, AnswerCallbackQuery) for v in transport.calls)
        assert not any(isinstance(v, SendMessage) for v in transport.calls)

    asyncio.run(scenario())


def setup_delivery(app):
    with app.state.sessions() as session:
        sub = save_subscription(
            session,
            owner_hash("telegram", 503),
            "telegram",
            SubscriptionFilter(city="Уфа"),
            confirmed=True,
            telegram_id=503,
            now=NOW,
        )
        event = session.scalar(
            select(Event)
            .where(Event.date_start > NOW + timedelta(days=1))
            .order_by(Event.date_start)
        )
        job = DigestDelivery(
            subscription_id=sub.id,
            day="2026-11-13",
            event_ids=[event.id],
            next_attempt_at=NOW,
        )
        session.add(job)
        session.commit()
        return job.id, event.id


def test_delivery_failure_is_persisted_and_retried_without_losing_subscription(
    client, app, monkeypatch
):
    job_id, _ = setup_delivery(app)
    import kurai.telegram_worker as worker

    monkeypatch.setattr(worker, "utcnow", lambda: NOW)
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("offline simulated failure")
    asyncio.run(dispatch_digests(bot, app.state.sessions))
    with app.state.sessions() as session:
        job = session.get(DigestDelivery, job_id)
        assert (
            job.status == "pending" and job.attempts == 1 and job.next_attempt_at > NOW
        )


def test_queued_event_moved_to_other_city_is_not_sent(client, app, monkeypatch):
    _, event_id = setup_delivery(app)
    with app.state.sessions() as session:
        session.get(Event, event_id).city = "Другой город"
        session.commit()
    bot = AsyncMock()
    asyncio.run(dispatch_digests(bot, app.state.sessions))
    bot.send_message.assert_not_awaited()
