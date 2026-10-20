"""Canonical serialization and content hashing.

Canonical JSON is UTF-8, key-sorted, whitespace-free and rejects NaN/Infinity.
Every durable identity (plan digest, candidate fingerprint, artifact manifest,
optimizer message checksum) is derived through these helpers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize(item) for item in value), key=repr)
    return value


def canonical_json(value: Any) -> str:
    """Serialize a Pydantic model or plain value to canonical JSON text."""
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    """Return the lowercase hex SHA-256 of canonical JSON for ``value``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_sequence(values: Sequence[str]) -> str:
    return canonical_sha256(list(values))
