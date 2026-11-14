"""Moderator controls for collection and review of source proposals."""

import os
from uuid import UUID
from fastapi import BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .collection import CollectionService
from .models import CollectedItem, CollectionRun


class ReviewReceipt(BaseModel):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


def run_out(run):
    return (
        {
            "id": run.id,
            "status": run.status,
            "summary": run.summary,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
        if run
        else None
    )


def install_collection(app, db, admin, limit):
    service = CollectionService(app.state.sessions)
    app.state.collection = service

    @app.get("/api/v1/admin/collection", dependencies=[Depends(admin)])
    def status(session=Depends(db)):
        latest = session.scalar(
            select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(1)
        )
        return {
            "scheduled": os.getenv("COLLECTION_ENABLED", "false").lower() == "true",
            "interval_hours": 6,
            "sources": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "url": s["url"],
                    "cities": s.get("cities", [s.get("city")]),
                }
                for s in service.definitions
            ],
            "latest": run_out(latest),
        }

    @app.post(
        "/api/v1/admin/collection", dependencies=[Depends(admin)], status_code=202
    )
    def collect(request: Request, background: BackgroundTasks, session=Depends(db)):
        limit(request, "collection", 3)
        if not service.lock.acquire(blocking=False):
            raise HTTPException(409, "Сбор уже выполняется")
        try:
            job = CollectionRun(
                status="pending", summary=[], started_at=service.clock()
            )
            session.add(job)
            session.commit()
        except Exception:
            service.lock.release()
            raise
        background.add_task(service.run, job.id, True)
        return {"id": job.id, "status": "pending"}

    @app.get(
        "/api/v1/admin/collection/runs/{identifier}", dependencies=[Depends(admin)]
    )
    def get_run(identifier: UUID, session=Depends(db)):
        job = session.get(CollectionRun, str(identifier))
        if not job:
            raise HTTPException(404, "Запуск не найден")
        return run_out(job)

    @app.get("/api/v1/admin/collection/items", dependencies=[Depends(admin)])
    def proposals(session=Depends(db)):
        items = session.scalars(
            select(CollectedItem)
            .where(
                (CollectedItem.reviewed_hash.is_(None))
                | (CollectedItem.reviewed_hash != CollectedItem.fingerprint)
            )
            .order_by(CollectedItem.last_seen_at.desc())
            .limit(200)
        ).all()
        return [
            {
                "id": r.id,
                "source_id": r.source_id,
                "event_id": r.event_id,
                "payload": r.payload,
                "issues": r.issues,
                "fingerprint": r.fingerprint,
                "last_seen_at": r.last_seen_at,
            }
            for r in items
        ]

    @app.post(
        "/api/v1/admin/collection/items/{identifier}/reviewed",
        dependencies=[Depends(admin)],
    )
    def reviewed(identifier: UUID, data: ReviewReceipt, session=Depends(db)):
        item = session.get(CollectedItem, str(identifier))
        if not item:
            raise HTTPException(404, "Запись источника не найдена")
        if item.fingerprint != data.fingerprint:
            raise HTTPException(409, "Источник уже обновился. Откройте сверку заново")
        item.reviewed_hash = data.fingerprint
        session.commit()
        return {"message": "Запись источника рассмотрена"}
