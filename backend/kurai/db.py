import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def make_engine(url: str | None = None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///./kurai.db")
    engine = create_engine(url, pool_pre_ping=True, **({"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}))
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_options(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
    return engine


def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
