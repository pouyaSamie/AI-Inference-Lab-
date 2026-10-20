"""HTTP idempotency records for mutating controller endpoints."""

from __future__ import annotations

from typing import Any

from lab_core.errors import IdempotencyConflictError, ValidationFailure
from lab_core.ids import sha256_hex
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .orm import IdempotencyRow, utcnow


def canonical_request_hash(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return sha256_hex(value)


def require_key(key: str | None) -> str:
    if key is None or not key.strip():
        raise ValidationFailure("Idempotency-Key header is required for this operation")
    key = key.strip()
    if len(key) > 200:
        raise ValidationFailure("Idempotency-Key must be at most 200 characters")
    return key


def lookup(
    session: Session,
    *,
    scope: str,
    key: str,
    request_hash: str,
) -> IdempotencyRow | None:
    row = session.scalar(
        select(IdempotencyRow).where(IdempotencyRow.scope == scope, IdempotencyRow.key == key)
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise IdempotencyConflictError(
            "idempotency key was already used with a different request body",
            details={"scope": scope, "key": key},
        )
    return row


def store(
    session: Session,
    *,
    scope: str,
    key: str,
    request_hash: str,
    response: Any,
    status_code: int = 200,
) -> IdempotencyRow:
    payload = response.model_dump(mode="json") if isinstance(response, BaseModel) else response
    row = IdempotencyRow(
        scope=scope,
        key=key,
        request_hash=request_hash,
        response_json=payload,
        status_code=status_code,
        created_at=utcnow(),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(IdempotencyRow).where(IdempotencyRow.scope == scope, IdempotencyRow.key == key)
        )
        if existing is None:
            raise
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError("idempotency key raced with a different request body") from None
        return existing
    return row
