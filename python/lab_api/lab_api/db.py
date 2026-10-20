"""SQLAlchemy engine/session setup with explicit SQLite safety pragmas."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import Settings


def _is_memory_sqlite(url: str) -> bool:
    parsed = make_url(url)
    return parsed.get_backend_name() == "sqlite" and (
        parsed.database in (None, "", ":memory:")
        or "mode=memory" in (parsed.query.get("uri", [""])[0] if parsed.query else "")
    )


def create_controller_engine(settings: Settings) -> Engine:
    parsed = make_url(settings.controller_db_url)
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}
    if parsed.get_backend_name() == "sqlite":
        memory = _is_memory_sqlite(settings.controller_db_url)
        kwargs["connect_args"] = {
            "timeout": settings.sqlite_busy_timeout_ms / 1000.0,
            "check_same_thread": False,
        }
        if memory:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(settings.controller_db_url, **kwargs)

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
                if not memory:
                    cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute(f"PRAGMA synchronous={settings.sqlite_synchronous}")
            finally:
                cursor.close()

        return engine
    return create_engine(settings.controller_db_url, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
