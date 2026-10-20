"""FastAPI dependency helpers shared by routers and services."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any, cast

from fastapi import Request
from sqlalchemy.orm import Session

from .config import Settings


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else "req_unknown"


def get_runtime(request: Request) -> Any:
    return request.app.state.runtime


class RequestContext:
    def __init__(self, request: Request) -> None:
        self.request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))
        self.client: str = request.client.host if request.client else "unknown"
