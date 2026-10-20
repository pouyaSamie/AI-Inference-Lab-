"""Stable identifiers, canonical serialization and deterministic hashing.

The platform uses SHA-256 over canonical JSON (sorted keys, no whitespace) for
every digest that appears in an API contract, a command, or a recipe. This
module is the single implementation of that rule.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic import BaseModel

ID_NAMESPACE: Final = uuid.UUID("6f1f7db0-9f4a-5d6e-9b2a-1c7f0f1a2b3c")
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"


def _normalize(value: Any) -> Any:
    """Convert supported values into a JSON-safe, canonical structure."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"value of type {type(value)!r} is not canonically serializable")


def canonical_json(value: Any) -> str:
    """Serialize a value deterministically.

    Floats are serialized by the standard library with ``repr`` semantics.
    NaN and infinity are rejected because they cannot be hashed reproducibly
    or represented in JSON.
    """
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(value: Any) -> str:
    """SHA-256 of the canonical JSON representation of ``value``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 of UTF-8 text (used for fixture and file hashing)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_uuid(*parts: Any) -> str:
    """Deterministic UUIDv5 from arbitrary canonicalizable parts."""
    return str(uuid.uuid5(ID_NAMESPACE, canonical_json(list(parts))))


def stable_id(prefix: str, *parts: Any) -> str:
    """Readable deterministic identifier, e.g. ``cand_<uuid>``."""
    _validate_id_prefix(prefix)
    return f"{prefix}_{stable_uuid(*parts)}"


def new_id(prefix: str) -> str:
    """Non-deterministic identifier for durable command/event rows."""
    _validate_id_prefix(prefix)
    return f"{prefix}_{uuid.uuid4().hex}"


def _validate_id_prefix(prefix: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9]{0,15}", prefix):
        raise ValueError(f"invalid id prefix: {prefix!r}")


def is_sha256(value: str) -> bool:
    return bool(SHA256_RE.fullmatch(value))


def assert_sha256(value: str, *, field: str = "digest") -> None:
    if not is_sha256(value):
        raise ValueError(f"{field} must be a lowercase 64-character SHA-256 hex digest")


def sorted_unique(values: Sequence[str]) -> list[str]:
    """Canonical ordering for context lists, tags and identifiers."""
    return sorted(dict.fromkeys(values))
