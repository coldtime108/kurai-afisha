"""Ownership checks and explicit moderator edits."""

import re
from uuid import UUID
from typing import Annotated
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .catalog import search
from .ingestion import normalize, sha
from .models import AuditEntry, Event, RawRecord, Subscription, utcnow
from .schemas import (
    EditEventInput,
    EventInput,
    EventOut,
    EventPageOut,
    SubscriptionFilter,
    SubscriptionInput,
    SubscriptionOut,
)
from .subscriptions import (
    cleanup,
    delete_subscription,
    owner_hash,
    save_subscription,
    subscription_filters,
)


def event_values(data: EventInput):
    values = data.model_dump(mode="json")
    key = sha(
        [
            normalize(data.title),
            values["date_start"],
            normalize(data.city),
            normalize(data.venue),
        ]
    )
    fingerprint = sha(values)
    source = {
        "url": values["source_url"],
        "verified_at": values["verified_at"],
        "type": values["source_type"],
    }
    values.update(
        {
            field: getattr(data, field)
            for field in ("date_start", "date_end", "verified_at")
        }
    )
    return values, key, fingerprint, source


def install_features(app, db, admin, limit):
    def owner(authorization: Annotated[str | None, Header()] = None):
        match = re.fullmatch(r"Bearer ([a-f0-9]{64})", authorization or "")
        if not match:
            raise HTTPException(401, "Для подписки нужен ключ этого устройства")
        return owner_hash("web", match.group(1))

    @app.get("/api/v1/subscriptions", response_model=list[SubscriptionOut])
    def list_subscriptions(
        request: Request, identity=Depends(owner), session=Depends(db)
    ):
        limit(request)
        cleanup(session)
        result = session.scalars(
            select(Subscription).where(
                Subscription.owner_hash == identity, Subscription.channel == "web"
            )
        ).all()
        return [
            {"id": item.id, "filters": item.filters, "expires_at": item.expires_at}
            for item in result
        ]

    @app.post("/api/v1/subscriptions", status_code=201, response_model=SubscriptionOut)
    def subscribe(
        data: SubscriptionInput,
        request: Request,
        identity=Depends(owner),
        session=Depends(db),
    ):
        limit(request, "subscriptions", 10)
        try:
            item = save_subscription(
                session,
                identity,
                "web",
                SubscriptionFilter.model_validate(
                    data.model_dump(exclude={"confirmed"})
                ),
                confirmed=data.confirmed,
            )
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "Подписка уже изменилась. Обновите страницу")
        return {"id": item.id, "filters": item.filters, "expires_at": item.expires_at}

    @app.delete("/api/v1/subscriptions/{subscription_id}", status_code=204)
    def unsubscribe(
        subscription_id: UUID,
        request: Request,
        identity=Depends(owner),
        session=Depends(db),
    ):
        limit(request, "subscriptions", 10)
        item = session.get(Subscription, str(subscription_id))
        if not item or item.owner_hash != identity or item.channel != "web":
            raise HTTPException(404, "Подписка не найдена")
        delete_subscription(session, identity, "web")

    @app.get(
        "/api/v1/subscriptions/{subscription_id}/events", response_model=EventPageOut
    )
    def subscribed_events(
        subscription_id: UUID,
        request: Request,
        identity=Depends(owner),
        session=Depends(db),
    ):
        limit(request)
        item = session.get(Subscription, str(subscription_id))
        if (
            not item
            or item.owner_hash != identity
            or item.channel != "web"
            or item.expires_at <= utcnow()
        ):
            raise HTTPException(404, "Подписка не найдена")
        rows, total, suggestions = search(session, subscription_filters(item), size=50)
        return {
            "items": [
                EventOut.model_validate(row).model_dump(mode="json") for row in rows
            ],
            "total": total,
            "page": 1,
            "size": 50,
            "suggestions": suggestions,
        }

    @app.post(
        "/api/v1/admin/events",
        dependencies=[Depends(admin)],
        status_code=201,
        response_model=EventOut,
    )
    def create_event(data: EventInput, session=Depends(db)):
        values, key, fingerprint, source = event_values(data)
        if session.scalar(select(Event.id).where(Event.dedup_key == key)):
            raise HTTPException(
                409, "Такой сеанс уже есть. Откройте его для редактирования"
            )
        item = Event(
            **values,
            normalized_title=normalize(data.title),
            dedup_key=key,
            source_hash=fingerprint,
            sources=[source],
            moderated_at=utcnow(),
        )
        session.add(item)
        session.flush()
        if not session.scalar(
            select(RawRecord.id).where(RawRecord.source_hash == fingerprint)
        ):
            session.add(
                RawRecord(
                    source_hash=fingerprint,
                    payload=data.model_dump(mode="json"),
                    event_id=item.id,
                )
            )
        session.add(
            AuditEntry(
                actor="moderator",
                action="manual_create",
                entity_id=item.id,
                changes={"after": data.model_dump(mode="json")},
            )
        )
        session.commit()
        return EventOut.model_validate(item)

    @app.put(
        "/api/v1/admin/events/{event_id}",
        dependencies=[Depends(admin)],
        response_model=EventOut,
    )
    def edit_event(event_id: UUID, data: EditEventInput, session=Depends(db)):
        item = session.scalar(
            select(Event).where(Event.id == str(event_id)).with_for_update()
        )
        if not item:
            raise HTTPException(404, "Событие не найдено")
        if item.updated_at != data.expected_updated_at:
            raise HTTPException(
                409, "Карточка уже изменилась. Обновите данные перед сохранением"
            )
        values, key, fingerprint, source = event_values(data.event)
        other = session.scalar(
            select(Event.id).where(Event.dedup_key == key, Event.id != item.id)
        )
        if other:
            raise HTTPException(409, "Такой сеанс уже есть в другой карточке")
        before = EventOut.model_validate(item).model_dump(mode="json")
        for field, value in values.items():
            setattr(item, field, value)
        item.normalized_title, item.dedup_key, item.source_hash = (
            normalize(data.event.title),
            key,
            fingerprint,
        )
        item.sources = [s for s in item.sources if s["url"] != source["url"]] + [source]
        item.moderated_at = utcnow()
        if not session.scalar(
            select(RawRecord.id).where(RawRecord.source_hash == fingerprint)
        ):
            session.add(
                RawRecord(
                    source_hash=fingerprint,
                    payload=data.event.model_dump(mode="json"),
                    event_id=item.id,
                )
            )
        session.add(
            AuditEntry(
                actor="moderator",
                action="manual_edit",
                entity_id=item.id,
                changes={"before": before, "after": data.event.model_dump(mode="json")},
            )
        )
        session.commit()
        return EventOut.model_validate(item)
