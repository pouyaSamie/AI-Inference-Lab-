"""Authentication and authorization primitives.

Three narrowly scoped credentials exist:

* operator credential: interactive/UI control plane (admin role in Phase 1)
* enrollment credential: one-time worker registration
* optimizer credential: internal durable optimizer polling
* worker credential: issued at enrollment, stored only as a salted hash
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from lab_core.errors import AuthenticationError, AuthorizationError

from .config import Settings
from .dependencies import get_session, get_settings
from .orm import WorkerRow

TokenKind = Literal["operator", "worker", "optimizer"]


@dataclass(frozen=True, slots=True)
class Principal:
    kind: TokenKind
    role: str
    subject: str
    worker_id: str | None = None


def hash_worker_token(pepper: str, token: str) -> str:
    return hashlib.sha256(f"{pepper}:{token}".encode("utf-8")).hexdigest()


def new_worker_token() -> str:
    return secrets.token_urlsafe(32)


def token_prefix(token: str) -> str:
    return token[:12]


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthenticationError("missing bearer credential")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise AuthenticationError("authorization header must use the Bearer scheme")
    return value.strip()


def _match(secret: str, candidate: str) -> bool:
    if not secret:
        return False
    return hmac.compare_digest(secret.encode("utf-8"), candidate.encode("utf-8"))


def authenticate(
    request: Request,
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Principal:
    token = _extract_bearer(authorization)

    if _match(settings.operator_token.get_secret_value(), token):
        principal = Principal(kind="operator", role="admin", subject="operator")
        request.state.principal = principal
        return principal
    if _match(settings.optimizer_token.get_secret_value(), token):
        principal = Principal(kind="optimizer", role="optimizer", subject="optimizer")
        request.state.principal = principal
        return principal

    prefix = token_prefix(token)
    rows = session.scalars(
        select(WorkerRow).where(WorkerRow.token_prefix == prefix, WorkerRow.disabled.is_(False))
    ).all()
    expected = hash_worker_token(settings.worker_token_pepper.get_secret_value(), token)
    for row in rows:
        if hmac.compare_digest(row.token_sha256, expected):
            principal = Principal(kind="worker", role="worker", subject=row.worker_id, worker_id=row.worker_id)
            request.state.principal = principal
            return principal
    raise AuthenticationError("credential is not valid for this controller")


def require_operator(principal: Principal = Depends(authenticate)) -> Principal:
    if principal.kind != "operator":
        raise AuthorizationError("operator credential required")
    return principal


def require_worker(principal: Principal = Depends(authenticate)) -> Principal:
    if principal.kind != "worker" or not principal.worker_id:
        raise AuthorizationError("worker credential required")
    return principal


def require_optimizer(principal: Principal = Depends(authenticate)) -> Principal:
    if principal.kind != "optimizer":
        raise AuthorizationError("optimizer credential required")
    return principal


def require_enrollment(
    settings: Settings = Depends(get_settings),
    enrollment_token: str | None = Header(default=None, alias="X-Enrollment-Token"),
) -> None:
    if not enrollment_token or not _match(settings.enrollment_token.get_secret_value(), enrollment_token):
        raise AuthenticationError("invalid or missing enrollment token")
