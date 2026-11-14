"""Subscription ownership and deterministic periods shared by web and Telegram."""

import hashlib
from datetime import datetime, time, timedelta, timezone
from sqlalchemy import delete, select
from .catalog import Filters, LOCAL_TZ
from .models import (
    AssistantDialog,
    AssistantQuota,
    AssistantTrace,
    BotDialog,
    DigestDelivery,
    Feedback,
    Subscription,
    utcnow,
)
from .schemas import SubscriptionFilter


def owner_hash(channel: str, identifier: str | int) -> str:
    return hashlib.sha256(f"{channel}:{identifier}".encode()).hexdigest()


def period_bounds(period: str, now: datetime | None = None):
    today = (now or utcnow()).astimezone(LOCAL_TZ).date()
    if period == "today":
        return today, today
    if period == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=1)
    if period == "weekend":
        if today.weekday() == 6:
            return today, today
        start = today + timedelta(days=(5 - today.weekday()) % 7)
        return start, start + timedelta(days=1)
    return today, today + timedelta(days=6)


def next_digest(now: datetime):
    local = now.astimezone(LOCAL_TZ)
    candidate = datetime.combine(local.date(), time(18), LOCAL_TZ)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def save_subscription(
    session,
    owner: str,
    channel: str,
    filters: SubscriptionFilter,
    *,
    confirmed: bool,
    telegram_id: int | None = None,
    now: datetime | None = None,
):
    if confirmed is not True:
        raise ValueError("Подтвердите подписку")
    if channel not in ("web", "telegram") or (
        channel == "telegram" and not telegram_id
    ):
        raise ValueError("Некорректный канал подписки")
    now = now or utcnow()
    existing = session.scalar(
        select(Subscription)
        .where(Subscription.owner_hash == owner, Subscription.channel == channel)
        .with_for_update()
    )
    if existing is None:
        existing = Subscription(
            owner_hash=owner,
            channel=channel,
            telegram_id=telegram_id,
            filters={},
            expires_at=now + timedelta(days=180),
            last_digest_at=now,
            next_digest_at=next_digest(now),
        )
        session.add(existing)
    else:
        session.execute(
            delete(DigestDelivery).where(
                DigestDelivery.subscription_id == existing.id,
                DigestDelivery.status == "pending",
            )
        )
    existing.filters = filters.model_dump(mode="json")
    existing.expires_at = now + timedelta(days=180)
    existing.last_digest_at = now
    existing.next_digest_at = next_digest(now)
    session.commit()
    return existing


def delete_subscription(session, owner: str, channel: str):
    subscriptions = session.scalars(
        select(Subscription).where(
            Subscription.owner_hash == owner, Subscription.channel == channel
        )
    ).all()
    for item in subscriptions:
        session.execute(
            delete(DigestDelivery).where(DigestDelivery.subscription_id == item.id)
        )
        session.delete(item)
    if channel == "telegram":
        session.execute(delete(BotDialog).where(BotDialog.owner_hash == owner))
        session.execute(
            delete(AssistantDialog).where(AssistantDialog.owner_hash == owner)
        )
        session.execute(
            delete(AssistantTrace).where(AssistantTrace.owner_hash == owner)
        )
    session.commit()


def cleanup(session, now: datetime | None = None):
    now = now or utcnow()
    expired = select(Subscription.id).where(Subscription.expires_at <= now)
    session.execute(
        delete(DigestDelivery).where(DigestDelivery.subscription_id.in_(expired))
    )
    session.execute(delete(Subscription).where(Subscription.expires_at <= now))
    session.execute(delete(BotDialog).where(BotDialog.expires_at <= now))
    session.execute(delete(AssistantDialog).where(AssistantDialog.expires_at <= now))
    session.execute(
        delete(AssistantTrace).where(
            AssistantTrace.created_at < now - timedelta(days=7)
        )
    )
    session.execute(
        delete(AssistantQuota).where(
            AssistantQuota.day < (now - timedelta(days=7)).date().isoformat()
        )
    )
    session.execute(
        delete(Feedback).where(Feedback.created_at < now - timedelta(days=30))
    )
    session.execute(
        delete(DigestDelivery).where(
            DigestDelivery.status != "pending",
            DigestDelivery.created_at < now - timedelta(days=30),
        )
    )
    session.commit()


def subscription_filters(item: Subscription, now: datetime | None = None):
    values = SubscriptionFilter.model_validate(item.filters)
    start, end = period_bounds(values.period, now)
    return Filters(
        city=values.city,
        category=values.category.value if values.category else None,
        date_from=start,
        date_to=end,
    )
