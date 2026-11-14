"""Private device-owned conversations, with moderator-only diagnostic traces."""

import re
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Response
from sqlalchemy import select

from .assistant import AssistantBusy, AssistantService
from .assistant_schemas import AssistantInput, AssistantReply, ConfirmationInput
from .models import AssistantTrace
from .subscriptions import owner_hash


def install_assistant(app, db, admin, limit, provider=None):
    service = AssistantService(app.state.sessions, provider)
    app.state.assistant = service

    def owner(authorization: Annotated[str | None, Header()] = None):
        match = re.fullmatch(r"Bearer ([a-f0-9]{64})", authorization or "")
        if not match:
            raise HTTPException(401, "Для диалога нужен ключ этого устройства")
        return owner_hash("web", match.group(1))

    def private(response: Response):
        response.headers["Cache-Control"] = "no-store"

    @app.get("/api/v1/assistant/status")
    def status(request: Request, response: Response):
        limit(request)
        private(response)
        return {
            "enabled": service.provider.ready,
            "fallback": True,
            "privacy": "Текст диалога передаётся NVIDIA для разбора запроса. Память — до 24 часов, диагностические записи — до 7 дней. Не указывайте личные данные и ключи доступа.",
        }

    @app.post("/api/v1/assistant/messages", response_model=AssistantReply)
    def message(
        data: AssistantInput,
        request: Request,
        response: Response,
        identity=Depends(owner),
    ):
        private(response)
        try:
            return service.respond(identity, "web", data.message)
        except AssistantBusy:
            raise HTTPException(409, "Предыдущий запрос ещё обрабатывается")

    @app.post("/api/v1/assistant/confirm", response_model=AssistantReply)
    def confirm(
        data: ConfirmationInput,
        request: Request,
        response: Response,
        identity=Depends(owner),
    ):
        private(response)
        try:
            return service.confirm(identity, "web", data.token, data.accept)
        except AssistantBusy:
            raise HTTPException(409, "Предыдущий запрос ещё обрабатывается")

    @app.delete("/api/v1/assistant/dialog", status_code=204)
    def reset(request: Request, response: Response, identity=Depends(owner)):
        private(response)
        try:
            service.reset(identity)
        except AssistantBusy:
            raise HTTPException(409, "Предыдущий запрос ещё обрабатывается")

    @app.get("/api/v1/admin/assistant/traces", dependencies=[Depends(admin)])
    def traces(response: Response, session=Depends(db)):
        private(response)
        return [
            {
                "id": row.id,
                "channel": row.channel,
                "created_at": row.created_at,
                **row.details,
            }
            for row in session.scalars(
                select(AssistantTrace)
                .order_by(AssistantTrace.created_at.desc())
                .limit(100)
            )
        ]
