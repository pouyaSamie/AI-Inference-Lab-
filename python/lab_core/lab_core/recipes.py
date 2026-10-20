"""Reproducible deployment recipe contract."""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import AwareTimestamp, FrozenModel, Identifier, NonEmptyStr, PositiveInt, Sha256, utcnow
from .enums import EngineId, Objective, RecipeStatus
from .ids import sha256_hex
from .version import RECIPE_SCHEMA, SCHEMA_VERSION


class RecipeEngine(FrozenModel):
    id: EngineId
    version: NonEmptyStr
    build: NonEmptyStr
    executable: NonEmptyStr
    sha256: Sha256
    adapter_schema: NonEmptyStr = SCHEMA_VERSION
    source_commit: str | None = None


class RecipeModelFile(FrozenModel):
    path: NonEmptyStr
    sha256: Sha256
    size_bytes: int = 0


class RecipeModel(FrozenModel):
    id: Identifier
    files: tuple[RecipeModelFile, ...]
    artifact_digest: Sha256


class RecipeHardware(FrozenModel):
    gpu_model: NonEmptyStr
    gpu_uuid: NonEmptyStr
    min_vram_bytes: PositiveInt
    driver_version: str | None = None
    compute_capability: str | None = None
    worker_id: Identifier | None = None


class RecipeLaunch(FrozenModel):
    executable: NonEmptyStr
    argv: tuple[str, ...]
    env: dict[str, str] = Field(default_factory=dict)
    bind_host: NonEmptyStr = "127.0.0.1"

    @model_validator(mode="after")
    def _loopback(self) -> RecipeLaunch:
        if self.bind_host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("recipes bind to loopback by default")
        return self


class RecipeValidationRefs(FrozenModel):
    protocol: NonEmptyStr
    experiment_id: Identifier
    metrics_ref: NonEmptyStr
    confidence_ref: NonEmptyStr | None = None
    quality_ref: NonEmptyStr | None = None
    claim_scope: tuple[str, ...] = ()
    validated_at: AwareTimestamp


class RecipeRollback(FrozenModel):
    previous_recipe_id: Identifier | None = None
    required_smoke_tests: tuple[str, ...] = ("ready", "one_token", "profile_identity")
    conditions: tuple[str, ...] = ()


class DeploymentRecipe(FrozenModel):
    schema_id: NonEmptyStr = Field(default=RECIPE_SCHEMA, serialization_alias="schema")
    id: Identifier
    status: RecipeStatus = RecipeStatus.DRAFT
    engine: RecipeEngine
    model: RecipeModel
    hardware: RecipeHardware
    objective: Objective
    context_tokens: PositiveInt
    launch: RecipeLaunch
    validation: RecipeValidationRefs
    rollback: RecipeRollback = Field(default_factory=RecipeRollback)
    created_at: AwareTimestamp = Field(default_factory=utcnow)
    notes: tuple[str, ...] = ()

    def recipe_digest(self) -> str:
        return sha256_hex(self.canonical_payload(exclude=frozenset({"created_at"})))


class RecipeApproval(FrozenModel):
    recipe_id: Identifier
    approved_by: NonEmptyStr
    approved_at: AwareTimestamp = Field(default_factory=utcnow)
    note: str | None = None


class PromotionRecord(FrozenModel):
    recipe_id: Identifier
    target_slot: NonEmptyStr
    promoted: bool
    verified: bool
    previous_recipe_id: Identifier | None = None
    created_at: AwareTimestamp = Field(default_factory=utcnow)
    message: str | None = None
