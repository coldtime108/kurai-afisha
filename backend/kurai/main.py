import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import delete, select, text

from .catalog import Filters, LOCAL_TZ, search
from .db import make_engine, session_factory
from .ingestion import import_rows
from .features import install_features
from .subscriptions import cleanup
from .models import AuditEntry, Event, Feedback, record_publication
from .schemas import (
    CATEGORIES,
    Category,
    EventOut,
    EventPageOut,
    FeedbackInput,
    ImportBatch,
    StatusChange,
)

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("kurai.access")


def create_app(database_url=None, admin_token=None, web_dir=None):
    engine = make_engine(database_url)
    sessions = session_factory(engine)
    secret = admin_token if admin_token is not None else os.getenv("ADMIN_TOKEN", "")
    web = Path(web_dir or ROOT / "frontend" / "dist")
    hits = defaultdict(deque)
    hit_lock = Lock()
    salt = secrets.token_bytes(32)
    metrics = {"requests": 0, "errors": 0, "latency_ms": deque(maxlen=1000)}

    @asynccontextmanager
    async def lifespan(_):
        def purge():
            with sessions() as session:
                cleanup(session)

        async def maintenance():
            while True:
                try:
                    await asyncio.to_thread(purge)
                except Exception:
                    logger.warning('{"event":"retention_cleanup_failed"}')
                await asyncio.sleep(3600)

        task = asyncio.create_task(maintenance())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            engine.dispose()

    app = FastAPI(
        title="Курай · Афиша Башкортостана",
        version="0.2.0",
        description="Независимый проект. Неизвестные значения не подменяются догадками.",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.engine, app.state.sessions = engine, sessions

    def db():
        with sessions() as session:
            yield session

    def admin(authorization: Annotated[str | None, Header()] = None):
        if not secret:
            raise HTTPException(503, "Модерация пока не настроена")
        if not hmac.compare_digest(authorization or "", "Bearer " + secret):
            raise HTTPException(401, "Для этого действия нужен доступ модератора")

    def limit(request: Request, group="public", count=120):
        identity = hmac.new(
            salt,
            (request.client.host if request.client else "local").encode(),
            hashlib.sha256,
        ).hexdigest()
        now = time.monotonic()
        with hit_lock:
            if len(hits) > 10000:
                for key in list(hits):
                    if not hits[key] or hits[key][-1] <= now - 60:
                        del hits[key]
                if len(hits) > 10000:
                    raise HTTPException(429, "Сервис занят. Попробуйте через минуту")
            bucket = hits[(group, identity)]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= count:
                raise HTTPException(
                    429,
                    "Слишком много запросов. Попробуйте через минуту",
                    headers={"Retry-After": "60"},
                )
            bucket.append(now)

    def public_limit(request: Request):
        limit(request)

    def error_response(request, status, code, message, details=None, headers=None):
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or [],
                    "request_id": getattr(request.state, "request_id", ""),
                }
            },
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        codes = {
            401: "unauthorized",
            404: "not_found",
            413: "payload_too_large",
            422: "validation_error",
            429: "rate_limited",
            503: "unavailable",
        }
        return error_response(
            request,
            error.status_code,
            codes.get(error.status_code, "request_error"),
            str(error.detail),
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        details = [
            {"field": ".".join(str(v) for v in e["loc"]), "message": e["msg"]}
            for e in error.errors()
        ]
        return error_response(
            request, 422, "validation_error", "Проверьте заполненные поля", details
        )

    @app.middleware("http")
    async def observe(request: Request, call_next):
        request.state.request_id = str(uuid4())
        started = time.perf_counter()
        try:
            length = request.headers.get("content-length", "0")
            if not length.isdecimal() or int(length) > 2_000_000:
                response = error_response(
                    request,
                    413,
                    "payload_too_large",
                    "Файл слишком большой. Максимум — 2 МБ",
                )
            else:
                response = await call_next(request)
        except Exception:
            response = error_response(
                request,
                500,
                "internal_error",
                "Не удалось выполнить запрос. Попробуйте позже",
            )
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        metrics["requests"] += 1
        metrics["errors"] += int(response.status_code >= 500)
        metrics["latency_ms"].append(elapsed)
        route = request.scope.get("route")
        logger.info(
            json.dumps(
                {
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "route": getattr(route, "path", "unmatched"),
                    "status": response.status_code,
                    "duration_ms": elapsed,
                }
            )
        )
        response.headers.update(
            {
                "X-Request-ID": request.state.request_id,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors "
                + ("*" if request.url.path == "/widget" else "'none'"),
            }
        )
        return response

    def cached(request: Request, payload, age=60):
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, default=str
        ).encode()
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        headers = {
            "ETag": etag,
            "Cache-Control": f"public, max-age={age}, must-revalidate",
        }
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(content=body, media_type="application/json", headers=headers)

    @app.get("/health")
    def health():
        try:
            with engine.connect() as connection:
                connection.execute(select(Event.id).limit(1))
            return {"status": "ok", "version": "0.2.0", "assistant": "not_connected"}
        except Exception:
            raise HTTPException(503, "База событий временно недоступна")

    @app.get("/metrics", dependencies=[Depends(admin)])
    def read_metrics():
        values = sorted(metrics["latency_ms"])
        return {
            "requests": metrics["requests"],
            "errors": metrics["errors"],
            "p95_ms": (
                values[min(int(len(values) * 0.95), len(values) - 1)] if values else 0
            ),
        }

    @app.get("/api/v1/meta", dependencies=[Depends(public_limit)])
    def meta(request: Request, session=Depends(db)):
        published = Event.status == "published"
        return cached(
            request,
            {
                "cities": list(
                    session.scalars(
                        select(Event.city)
                        .where(published)
                        .distinct()
                        .order_by(Event.city)
                    )
                ),
                "categories": [
                    {"id": key, "label": value} for key, value in CATEGORIES.items()
                ],
                "venues": list(
                    session.scalars(
                        select(Event.venue)
                        .where(published)
                        .distinct()
                        .order_by(Event.venue)
                    )
                ),
                "timezone": "Asia/Yekaterinburg",
                "today": datetime.now(LOCAL_TZ).date().isoformat(),
                "service_notice": "Независимый проект. Не является официальным сервисом Министерства культуры Республики Башкортостан.",
            },
        )

    @app.get(
        "/api/v1/events",
        dependencies=[Depends(public_limit)],
        response_model=EventPageOut,
    )
    def events(
        q: str = Query("", max_length=200),
        city: str | None = Query(None, max_length=120),
        category: Category | None = None,
        venue: str | None = Query(None, max_length=240),
        date_from: date | None = None,
        date_to: date | None = None,
        price_max: int | None = Query(None, ge=0, le=10000000),
        age: int | None = Query(None, ge=0, le=120),
        is_free: bool = False,
        page: int = Query(1, ge=1),
        size: int = Query(12, ge=1, le=50),
        sort: str = Query("date", pattern="^(date|price)$"),
        session=Depends(db),
    ):
        if date_from and date_to and date_to < date_from:
            raise HTTPException(
                422, "Дата окончания должна быть не раньше начала периода"
            )
        filters = Filters(
            q=q,
            city=city,
            category=category.value if category else None,
            venue=venue,
            date_from=date_from,
            date_to=date_to,
            price_max=price_max,
            age=age,
            is_free=is_free,
        )
        rows, total, suggestions = search(session, filters, page, size, sort)
        return {
            "items": [
                EventOut.model_validate(row).model_dump(mode="json") for row in rows
            ],
            "total": total,
            "page": page,
            "size": size,
            "suggestions": suggestions,
        }

    @app.get(
        "/api/v1/events/{event_id}",
        dependencies=[Depends(public_limit)],
        response_model=EventOut,
    )
    def get_event(event_id: UUID, request: Request, session=Depends(db)):
        item = session.get(Event, str(event_id))
        if not item or item.status == "draft":
            raise HTTPException(404, "Событие не найдено")
        return cached(
            request, EventOut.model_validate(item).model_dump(mode="json"), age=0
        )

    @app.post("/api/v1/feedback", status_code=201)
    def feedback(data: FeedbackInput, request: Request, session=Depends(db)):
        limit(request, "feedback", 3)
        if data.website:
            raise HTTPException(422, "Не удалось принять обращение")
        if data.event_id:
            event = session.get(Event, data.event_id)
            if not event or event.status == "draft":
                raise HTTPException(404, "Событие не найдено")
        session.execute(
            delete(Feedback).where(
                Feedback.created_at < datetime.now(timezone.utc) - timedelta(days=30)
            )
        )
        item = Feedback(event_id=data.event_id, message=data.message)
        session.add(item)
        session.commit()
        return {"id": item.id, "message": "Обращение сохранено в очереди модерации"}

    @app.get("/api/v1/admin/feedback", dependencies=[Depends(admin)])
    def feedback_queue(session=Depends(db)):
        session.execute(
            delete(Feedback).where(
                Feedback.created_at < datetime.now(timezone.utc) - timedelta(days=30)
            )
        )
        session.commit()
        return [
            {
                "id": row.id,
                "event_id": row.event_id,
                "message": row.message,
                "created_at": row.created_at,
            }
            for row in session.scalars(
                select(Feedback).order_by(Feedback.created_at.desc()).limit(200)
            )
        ]

    @app.post("/api/v1/admin/import", dependencies=[Depends(admin)])
    def import_events(data: ImportBatch, session=Depends(db)):
        return import_rows(session, data.rows)

    @app.post("/api/v1/admin/import-file", dependencies=[Depends(admin)])
    async def import_file(file: UploadFile = File(...), session=Depends(db)):
        content = await file.read(2_000_001)
        if len(content) > 2_000_000:
            raise HTTPException(413, "Максимальный размер файла — 2 МБ")
        try:
            decoded = content.decode("utf-8-sig")
            if (file.filename or "").lower().endswith(".csv"):
                rows = list(csv.DictReader(io.StringIO(decoded)))
                for row in rows:
                    for key in list(row):
                        if row[key] == "":
                            row[key] = None
                    if isinstance(row.get("tags"), str):
                        row["tags"] = [
                            v.strip() for v in row["tags"].split("|") if v.strip()
                        ]
                    elif "tags" in row and row["tags"] is None:
                        row["tags"] = []
            else:
                rows = json.loads(decoded)
            if (
                not isinstance(rows, list)
                or len(rows) > 1000
                or any(not isinstance(row, dict) for row in rows)
            ):
                raise ValueError()
        except (ValueError, UnicodeError, csv.Error, TypeError):
            raise HTTPException(
                422, "Нужен UTF-8 CSV с заголовками или JSON-массив, до 1000 записей"
            )
        return import_rows(session, rows)

    @app.get(
        "/api/v1/admin/events",
        dependencies=[Depends(admin)],
        response_model=list[EventOut],
    )
    def admin_events(session=Depends(db)):
        return [
            EventOut.model_validate(row)
            for row in session.scalars(
                select(Event).order_by(Event.date_start).limit(1000)
            )
        ]

    @app.patch("/api/v1/admin/events/{event_id}/status", dependencies=[Depends(admin)])
    def status(event_id: UUID, data: StatusChange, session=Depends(db)):
        item = session.get(Event, str(event_id))
        if not item:
            raise HTTPException(404, "Событие не найдено")
        if data.status == "published" and not item.verified_at:
            raise HTTPException(422, "Сначала проверьте источник")
        before = item.status
        item.status = data.status
        record_publication(item, before)
        item.moderated_at = datetime.now(timezone.utc)
        session.add(
            AuditEntry(
                actor="moderator",
                action="status_change",
                entity_id=item.id,
                changes={"before": before, "after": item.status},
            )
        )
        session.commit()
        return {"id": item.id, "status": item.status}

    @app.get("/api/v1/admin/audit", dependencies=[Depends(admin)])
    def audit(session=Depends(db)):
        return [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "entity_id": row.entity_id,
                "changes": row.changes,
                "created_at": row.created_at,
            }
            for row in session.scalars(
                select(AuditEntry).order_by(AuditEntry.id.desc()).limit(200)
            )
        ]

    install_features(app, db, admin, limit)

    if (web / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

    @app.get("/api/docs", include_in_schema=False)
    def api_docs():
        return FileResponse(Path(__file__).parent / "static" / "api-docs.html")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith(("api/", "assets/")):
            raise HTTPException(404, "Страница не найдена")
        if (web / "index.html").is_file():
            return FileResponse(
                web / "index.html", headers={"Cache-Control": "no-cache"}
            )
        raise HTTPException(503, "Веб-интерфейс ещё не собран")

    return app


app = create_app()
