"""Optional Telegram worker. No token => no network connection or fake live status."""

import asyncio
import json
import logging
import os
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from .bot_controller import BotController, BotReply, event_text
from .assistant import AssistantService
from .telegram_session import SystemNetworkSession
from .catalog import query_for
from .db import make_engine, session_factory
from .digests import enqueue_digests, pending_deliveries
from .models import DigestDelivery, Event, Subscription, utcnow
from .subscriptions import cleanup, delete_subscription, subscription_filters

logger = logging.getLogger("kurai.bot")


def log_status(event):
    logger.info(json.dumps({"event": event, "request_id": str(uuid4())}))


def log_failure(event):
    logger.warning(json.dumps({"event": event, "request_id": str(uuid4())}))


def markup(reply: BotReply):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                (
                    InlineKeyboardButton(text=label, url=action[4:])
                    if action.startswith("url:")
                    else InlineKeyboardButton(text=label, callback_data=action)
                )
                for label, action in row
            ]
            for row in reply.buttons
        ]
    )


def build_router(controller: BotController):
    router = Router(name="kurai_catalog")

    @router.message(F.chat.type == "private")
    async def message(message: Message):
        if not message.from_user:
            return
        text = message.text or ""
        if not text:
            await message.answer("Напишите название события или откройте /start.")
            return
        try:
            reply = await asyncio.to_thread(
                controller.handle, message.from_user.id, text=text
            )
            await message.answer(reply.text, reply_markup=markup(reply))
            log_status("bot_message_delivered")
        except Exception:
            log_failure("bot_request_failed")
            await message.answer(
                "Не удалось открыть афишу. Попробуйте ещё раз через минуту."
            )

    @router.callback_query(F.message.chat.type == "private")
    async def callback(callback: CallbackQuery):
        await callback.answer()
        if (
            not isinstance(callback.message, Message)
            or callback.message.chat.id != callback.from_user.id
        ):
            return
        try:
            reply = await asyncio.to_thread(
                controller.handle, callback.from_user.id, callback=callback.data or ""
            )
            await callback.message.answer(reply.text, reply_markup=markup(reply))
            log_status("bot_callback_delivered")
        except Exception:
            log_failure("bot_callback_failed")
            await callback.message.answer(
                "Не удалось выполнить действие. Откройте /start."
            )

    return router


async def dispatch_digests(bot, sessions):
    now = utcnow()
    with sessions() as session:
        cleanup(session, now)
        enqueue_digests(session, now)
        deliveries = pending_deliveries(session, now)
    for identifier, chat_id, events in deliveries:
        try:
            # Recheck deletion/status immediately before delivery.
            with sessions() as session:
                job = session.get(DigestDelivery, identifier)
                sub = session.get(Subscription, job.subscription_id) if job else None
                if not job or not sub:
                    continue
                events = session.scalars(
                    query_for(subscription_filters(sub))
                    .where(Event.id.in_(job.event_ids), Event.date_start > utcnow())
                    .order_by(Event.date_start)
                ).all()
                if not events:
                    job.status = "skipped"
                    session.commit()
                    continue
            text = (
                "Новые события вашей афиши · время РБ (UTC+5)\n\n"
                + "\n\n".join(event_text(item, compact=True) for item in events)
                + "\n\n/unsubscribe — удалить подписку"
            )
            await bot.send_message(
                chat_id,
                text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=item.title[:50], callback_data="e:" + item.id
                            )
                        ]
                        for item in events
                    ]
                ),
            )
            log_status("digest_delivered")
            with sessions() as session:
                job = session.get(DigestDelivery, identifier)
                if job:
                    job.status = "sent"
                    job.attempts += 1
                    session.commit()
        except TelegramForbiddenError:
            with sessions() as session:
                job = session.get(DigestDelivery, identifier)
                sub = session.get(Subscription, job.subscription_id) if job else None
                if sub:
                    delete_subscription(session, sub.owner_hash, "telegram")
        except Exception as error:
            with sessions() as session:
                job = session.get(DigestDelivery, identifier)
                if job:
                    job.attempts += 1
                    job.status = "failed" if job.attempts >= 3 else "pending"
                    delay = (
                        max(60, error.retry_after)
                        if isinstance(error, TelegramRetryAfter)
                        else 60 * (2**job.attempts)
                    )
                    job.next_attempt_at = utcnow() + timedelta(seconds=delay)
                    session.commit()
            log_failure("digest_delivery_failed")
        await asyncio.sleep(0.1)


async def digest_loop(bot, sessions):
    while True:
        try:
            await dispatch_digests(bot, sessions)
        except Exception:
            log_failure("digest_cycle_failed")
        await asyncio.sleep(60)


async def run():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit("Задайте TELEGRAM_BOT_TOKEN в локальных настройках запуска.")
    engine = make_engine()
    sessions = session_factory(engine)
    # Framework logs can contain Telegram IDs; only our content-free status logs are enabled.
    logging.getLogger("aiogram").setLevel(logging.CRITICAL)
    bot = Bot(token=token, session=SystemNetworkSession())
    dispatcher = Dispatcher(events_isolation=SimpleEventIsolation(), disable_fsm=False)
    dispatcher.include_router(
        build_router(BotController(sessions, assistant=AssistantService(sessions)))
    )
    async with bot.context(auto_close=True):
        info = await bot.get_webhook_info()
        if info.url:
            raise SystemExit(
                "У бота настроен webhook. Используйте отдельного бота для polling или переключите режим вручную."
            )
        # Fail before announcing readiness if credentials or the shared DB are unavailable.
        await bot.get_me()
        with sessions() as session:
            session.execute(select(Event.id).limit(1))
        log_status("bot_polling_starting")
        digest_task = asyncio.create_task(digest_loop(bot, sessions))
        try:
            await dispatcher.start_polling(
                bot,
                handle_signals=True,
                close_bot_session=False,
                tasks_concurrency_limit=20,
            )
        finally:
            digest_task.cancel()
            try:
                await digest_task
            except asyncio.CancelledError:
                pass
            engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception:
        # Third-party exception messages can include API URLs containing the token.
        log_failure("bot_worker_stopped")
        raise SystemExit(1) from None
