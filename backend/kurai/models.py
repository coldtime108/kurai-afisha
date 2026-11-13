from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, ForeignKey
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Timezone-aware PostgreSQL storage, UTC restoration for SQLite test runs."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timezone required")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(240))
    normalized_title: Mapped[str] = mapped_column(String(240), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    date_start: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    date_end: Mapped[datetime | None] = mapped_column(UTCDateTime())
    duration_min: Mapped[int | None] = mapped_column(Integer)
    city: Mapped[str] = mapped_column(String(120), index=True)
    venue: Mapped[str] = mapped_column(String(240))
    address: Mapped[str] = mapped_column(String(400))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text)
    price_min: Mapped[int | None] = mapped_column(Integer)
    price_max: Mapped[int | None] = mapped_column(Integer)
    is_free: Mapped[bool | None]
    age_limit: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(80))
    org_link: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20))
    source_hash: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSON, default=list)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), index=True)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class RawRecord(Base):
    __tablename__ = "raw_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_hash: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    changes: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
