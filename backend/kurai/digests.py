"""Durable daily Telegram digests. One scheduler process per deployment."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .catalog import query_for, LOCAL_TZ
from .models import DigestDelivery, Event, Subscription, utcnow
from .subscriptions import next_digest, subscription_filters


def enqueue_digests(session, now=None):
    now = now or utcnow()
    count = 0
    due = session.scalars(
        select(Subscription).where(
            Subscription.channel == "telegram",
            Subscription.expires_at > now,
            Subscription.next_digest_at <= now,
        )
    ).all()
    for sub in due:
        day = now.astimezone(LOCAL_TZ).date().isoformat()
        if session.scalar(
            select(DigestDelivery.id).where(
                DigestDelivery.subscription_id == sub.id, DigestDelivery.day == day
            )
        ):
            sub.next_digest_at = next_digest(now)
            continue
        ids = list(
            session.scalars(
                query_for(subscription_filters(sub, now))
                .where(
                    Event.published_at > sub.last_digest_at,
                    Event.published_at <= now,
                    Event.date_start > now,
                )
                .order_by(Event.date_start, Event.id)
                .limit(3)
            )
        )
        sub.last_digest_at = now
        sub.next_digest_at = next_digest(now)
        if ids:
            session.add(
                DigestDelivery(
                    subscription_id=sub.id,
                    day=day,
                    event_ids=[item.id for item in ids],
                    next_attempt_at=now,
                )
            )
            count += 1
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return 0
    return count


def pending_deliveries(session, now=None):
    now = now or utcnow()
    jobs = session.scalars(
        select(DigestDelivery)
        .where(
            DigestDelivery.status == "pending", DigestDelivery.next_attempt_at <= now
        )
        .limit(100)
    ).all()
    results = []
    for job in jobs:
        sub = session.get(Subscription, job.subscription_id)
        if not sub or sub.expires_at <= now or not sub.telegram_id:
            job.status = "skipped"
            continue
        events = session.scalars(
            query_for(subscription_filters(sub, now))
            .where(Event.id.in_(job.event_ids), Event.date_start > now)
            .order_by(Event.date_start)
        ).all()
        if not events:
            job.status = "skipped"
            continue
        results.append((job.id, sub.telegram_id, events))
    session.commit()
    return results
