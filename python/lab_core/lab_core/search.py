"""Conditional search-space contracts.

Phase 1 persists and transmits these definitions between adapters, the
controller and the optimizer. Conditional dimensions are expressed explicitly
so Phase 5 can map them onto Optuna without changing the protocol.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .base import FrozenModel, JsonScalar, NonEmptyStr, PositiveInt
from .enums import EngineId
from .version import SCHEMA_VERSION


class DimensionKind(StrEnum):
    INT = "int"
    FLOAT = "float"
    CATEGORICAL = "categorical"
    BOOL = "bool"


class ConditionOperator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    NOT_IN = "not_in"
    GTE = "gte"
    LTE = "lte"


class SearchCondition(FrozenModel):
    parameter: NonEmptyStr
    operator: ConditionOperator
    values: tuple[JsonScalar, ...]

    @model_validator(mode="after")
    def _values_required(self) -> SearchCondition:
        if not self.values and self.operator is not ConditionOperator.EQ:
            raise ValueError("condition requires at least one value")
        return self


class ParameterDimension(FrozenModel):
    name: NonEmptyStr
    kind: DimensionKind
    choices: tuple[JsonScalar, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    log: bool = False
    default: JsonScalar = None
    conditions: tuple[SearchCondition, ...] = ()
    engine_constraints: tuple[str, ...] = ()
    quality_risk: bool = False
    description: str | None = None

    @model_validator(mode="after")
    def _validate_dimension(self) -> ParameterDimension:
        if self.kind in (DimensionKind.CATEGORICAL, DimensionKind.BOOL) and not self.choices:
            raise ValueError(f"dimension {self.name!r} requires choices")
        if self.kind in (DimensionKind.INT, DimensionKind.FLOAT):
            if self.minimum is None or self.maximum is None:
                raise ValueError(f"numeric dimension {self.name!r} requires minimum and maximum")
            if self.minimum > self.maximum:
                raise ValueError(f"dimension {self.name!r} has minimum > maximum")
            if self.log and self.kind is DimensionKind.INT and (self.minimum <= 0 or self.maximum <= 0):
                raise ValueError("log-scaled integer dimension requires positive bounds")
        return self


class SearchSpaceSpec(FrozenModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    engine_id: EngineId
    dimensions: tuple[ParameterDimension, ...]
    fixed_parameters: dict[str, JsonScalar] = Field(default_factory=dict)
    constraints: tuple[str, ...] = ()
    max_proposals: PositiveInt = 256
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _unique_names(self) -> SearchSpaceSpec:
        names = [dimension.name for dimension in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("search dimension names must be unique")
        overlap = set(names) & set(self.fixed_parameters)
        if overlap:
            raise ValueError(f"parameters both fixed and searched: {sorted(overlap)}")
        return self

    def dimension(self, name: str) -> ParameterDimension | None:
        return next((item for item in self.dimensions if item.name == name), None)

    def is_active(self, dimension: ParameterDimension, parameters: dict[str, JsonScalar]) -> bool:
        for condition in dimension.conditions:
            value = parameters.get(condition.parameter)
            if not _condition_matches(condition, value):
                return False
        return True


def _condition_matches(condition: SearchCondition, value: JsonScalar) -> bool:
    if condition.operator is ConditionOperator.EQ:
        return value == condition.values[0]
    if condition.operator is ConditionOperator.NEQ:
        return value != condition.values[0]
    if condition.operator is ConditionOperator.IN:
        return value in condition.values
    if condition.operator is ConditionOperator.NOT_IN:
        return value not in condition.values
    if condition.operator is ConditionOperator.GTE:
        return (
            isinstance(value, (int, float))
            and isinstance(condition.values[0], (int, float))
            and value >= condition.values[0]
        )
    if condition.operator is ConditionOperator.LTE:
        return (
            isinstance(value, (int, float))
            and isinstance(condition.values[0], (int, float))
            and value <= condition.values[0]
        )
    return False  # type: ignore[unreachable]


class SearchSpaceRequest(FrozenModel):
    engine_id: EngineId
    model_architecture: NonEmptyStr
    model_quantization: str | None = None
    context_tokens: int
    objective: str
    observations: tuple[dict[str, JsonScalar], ...] = ()
