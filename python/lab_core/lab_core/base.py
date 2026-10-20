"""Frozen Pydantic base classes and shared field aliases."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, TypeAlias

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from .ids import canonical_json, sha256_hex


class FrozenModel(BaseModel):
    """Immutable, strict, canonicalizable model for component boundaries."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        validate_assignment=False,
        ser_json_timedelta="iso8601",
    )

    def canonical_payload(self, *, exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude=set(exclude))

    def canonical_json(self, *, exclude: frozenset[str] = frozenset()) -> str:
        return canonical_json(self.canonical_payload(exclude=exclude))

    def digest(self, *, exclude: frozenset[str] = frozenset()) -> str:
        return sha256_hex(self.canonical_payload(exclude=exclude))


NonEmptyStr: TypeAlias = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]
Identifier: TypeAlias = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
]
Sha256: TypeAlias = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
]
JsonScalar: TypeAlias = str | int | float | bool | None
Parameters: TypeAlias = dict[str, JsonScalar]
AwareTimestamp: TypeAlias = AwareDatetime
PositiveInt: TypeAlias = Annotated[int, Field(gt=0)]
NonNegativeInt: TypeAlias = Annotated[int, Field(ge=0)]
Probability: TypeAlias = Annotated[float, Field(ge=0.0, le=1.0)]
UnitFraction: TypeAlias = Annotated[float, Field(gt=0.0, le=1.0)]


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_parameters(parameters: Parameters) -> dict[str, JsonScalar]:
    """Return a copy with canonical key ordering for hashing and persistence."""
    return {key: parameters[key] for key in sorted(parameters)}


def parameters_digest(parameters: Parameters) -> str:
    return sha256_hex(canonical_parameters(parameters))
