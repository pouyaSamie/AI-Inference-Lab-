"""Immutable experiment definitions, plans and context feasibility."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .base import (
    AwareTimestamp,
    FrozenModel,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    PositiveInt,
    Probability,
    Sha256,
    UnitFraction,
    utcnow,
)
from .engine import EngineIdentity
from .enums import ContextLength, FeasibilityOutcome, JobStage, Objective, PlanStatus, RecipeMode, SearchDepth
from .ids import sha256_hex, stable_id
from .model import ModelArtifact
from .version import SCHEMA_VERSION, WORKLOAD_PROTOCOL

SEARCH_DEPTH_POLICY: dict[SearchDepth, tuple[int, int, int, int]] = {
    # depth -> (max distinct candidates, screening replications, finalists, final replications)
    SearchDepth.QUICK: (12, 2, 2, 3),
    SearchDepth.STANDARD: (36, 3, 5, 5),
    SearchDepth.THOROUGH: (96, 4, 8, 7),
}


class SearchPolicy(FrozenModel):
    depth: SearchDepth = SearchDepth.STANDARD
    max_candidates: PositiveInt | None = None
    screening_replications: PositiveInt | None = None
    finalist_count: PositiveInt | None = None
    final_replications: PositiveInt | None = None
    screening_contexts: tuple[ContextLength, ...] = (ContextLength.K4, ContextLength.K32)
    seed: NonNegativeInt = 20261020
    budget_wall_clock_seconds: PositiveInt | None = None
    budget_gpu_hours: float | None = Field(default=None, gt=0)
    min_improvement_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    confidence_level: Probability = 0.95
    max_proposal_attempts: PositiveInt = 4

    @model_validator(mode="after")
    def _apply_depth_defaults(self) -> SearchPolicy:
        defaults = SEARCH_DEPTH_POLICY[self.depth]
        max_candidates = self.max_candidates if self.max_candidates is not None else defaults[0]
        screening_replications = (
            self.screening_replications if self.screening_replications is not None else defaults[1]
        )
        finalist_count = self.finalist_count if self.finalist_count is not None else defaults[2]
        final_replications = self.final_replications if self.final_replications is not None else defaults[3]
        object.__setattr__(self, "max_candidates", max_candidates)
        object.__setattr__(self, "screening_replications", screening_replications)
        object.__setattr__(self, "finalist_count", finalist_count)
        object.__setattr__(self, "final_replications", final_replications)
        if finalist_count > max_candidates:
            raise ValueError("finalist_count cannot exceed max_candidates")
        return self

    def effective(self) -> dict[str, int | float]:
        assert self.max_candidates is not None
        assert self.screening_replications is not None
        assert self.finalist_count is not None
        assert self.final_replications is not None
        return {
            "max_candidates": self.max_candidates,
            "screening_replications": self.screening_replications,
            "finalist_count": self.finalist_count,
            "final_replications": self.final_replications,
        }


class ResourceConstraints(FrozenModel):
    max_vram_bytes: PositiveInt | None = None
    min_free_vram_bytes: NonNegativeInt = 1_500_000_000
    max_system_ram_bytes: PositiveInt | None = None
    min_free_ram_bytes: NonNegativeInt = 2_000_000_000
    max_temperature_c: float | None = Field(default=None, ge=0, le=150)
    max_ttft_p95_ms: float | None = Field(default=None, gt=0)
    min_quality_score: Probability | None = None
    quiet_gpu_required: bool = True
    require_full_context_proof: bool = True
    allow_quality_changing_flags: bool = False


class WorkloadSuite(FrozenModel):
    protocol: NonEmptyStr = WORKLOAD_PROTOCOL
    dataset_id: NonEmptyStr = "lab-synthetic-v1"
    dataset_sha256: Sha256 | None = None
    prompt_levels: tuple[UnitFraction, ...] = (0.25, 0.60, 0.85, 0.98)
    output_tokens: PositiveInt = 256
    extended_output_tokens: PositiveInt = 1024
    repetitions: PositiveInt = 3
    deterministic_sampling: bool = True
    temperature: float = Field(default=0.0, ge=0.0, le=5.0)
    top_p: UnitFraction = 1.0
    seed: NonNegativeInt = 42

    @field_validator("prompt_levels")
    @classmethod
    def _levels_sorted(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if tuple(sorted(set(value))) != value:
            raise ValueError("prompt levels must be sorted and unique")
        if len(value) < 3:
            raise ValueError("at least three prompt-load levels are required")
        return value


class ExperimentSpec(FrozenModel):
    """Immutable definition of one optimization study.

    It binds explicit engine/model identities, the worker, objective, context
    matrix, search policy, workload protocol and constraints. It never contains
    mutable process handles or local-only credentials.
    """

    schema_version: NonEmptyStr = SCHEMA_VERSION
    worker_id: Identifier
    engine: EngineIdentity
    model: ModelArtifact
    objective: Objective
    contexts: tuple[ContextLength, ...]
    search_depth: SearchDepth
    search_policy: SearchPolicy
    constraints: ResourceConstraints = Field(default_factory=ResourceConstraints)
    workload: WorkloadSuite = Field(default_factory=WorkloadSuite)
    recipe_mode: RecipeMode = RecipeMode.PER_CONTEXT
    inventory_snapshot_digest: Sha256
    gpu_uuids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @field_validator("contexts")
    @classmethod
    def _contexts_canonical(cls, value: tuple[ContextLength, ...]) -> tuple[ContextLength, ...]:
        if not value:
            raise ValueError("at least one context is required")
        ordered = tuple(sorted(set(value), key=int))
        return ordered

    @model_validator(mode="after")
    def _depth_matches_policy(self) -> ExperimentSpec:
        if self.search_policy.depth is not self.search_depth:
            raise ValueError("search_depth and search_policy.depth must agree")
        if self.gpu_uuids and len(set(self.gpu_uuids)) != len(self.gpu_uuids):
            raise ValueError("gpu_uuids must be unique")
        return self

    @property
    def spec_digest(self) -> str:
        return sha256_hex(self.canonical_payload())

    def competing_key(self) -> str:
        """Identity that must be unique for a fair study."""
        return sha256_hex(
            {
                "engine_sha256": self.engine.executable_sha256,
                "model_digest": self.model.artifact_digest,
                "worker_id": self.worker_id,
                "gpu_uuids": list(self.gpu_uuids),
                "objective": self.objective,
                "contexts": [int(context) for context in self.contexts],
            }
        )


class ContextFeasibility(FrozenModel):
    context: ContextLength
    status: FeasibilityOutcome = FeasibilityOutcome.UNKNOWN
    estimated_vram_bytes: int | None = None
    reason: str | None = None
    evidence: tuple[str, ...] = ()
    requires_full_context_proof: bool = True

    @model_validator(mode="after")
    def _reason_for_non_feasible(self) -> ContextFeasibility:
        if (
            self.status
            in (
                FeasibilityOutcome.UNSUPPORTED,
                FeasibilityOutcome.RESOURCE_INFEASIBLE,
                FeasibilityOutcome.INCONCLUSIVE,
            )
            and not self.reason
        ):
            raise ValueError("non-feasible context requires an explicit reason")
        return self


class ExperimentPlan(FrozenModel):
    plan_id: Identifier
    status: PlanStatus
    spec: ExperimentSpec
    inventory_snapshot_digest: Sha256
    worker_snapshot_revision: PositiveInt | None = None
    feasibility: tuple[ContextFeasibility, ...] = ()
    warnings: tuple[str, ...] = ()
    required_preflight_command_id: Identifier | None = None
    created_at: AwareTimestamp = Field(default_factory=utcnow)
    stage: JobStage = JobStage.QUEUED

    @model_validator(mode="after")
    def _plan_consistency(self) -> ExperimentPlan:
        if self.status is PlanStatus.PREFLIGHT_REQUIRED and not self.required_preflight_command_id:
            raise ValueError("PREFLIGHT_REQUIRED plan must identify the queued preflight command")
        if self.status is PlanStatus.READY and self.required_preflight_command_id is not None:
            raise ValueError("READY plan must not carry a preflight command id")
        contexts = {item.context for item in self.feasibility}
        if contexts and contexts != set(self.spec.contexts):
            raise ValueError("feasibility must cover exactly the selected contexts")
        return self

    @classmethod
    def build(
        cls,
        *,
        spec: ExperimentSpec,
        status: PlanStatus,
        feasibility: tuple[ContextFeasibility, ...],
        worker_snapshot_revision: int | None,
        warnings: tuple[str, ...] = (),
        required_preflight_command_id: str | None = None,
    ) -> ExperimentPlan:
        plan_id = stable_id(
            "plan",
            spec.spec_digest,
            spec.inventory_snapshot_digest,
            worker_snapshot_revision,
            status.value,
            [item.model_dump(mode="json") for item in feasibility],
        )
        return cls(
            plan_id=plan_id,
            status=status,
            spec=spec,
            inventory_snapshot_digest=spec.inventory_snapshot_digest,
            worker_snapshot_revision=worker_snapshot_revision,
            feasibility=feasibility,
            warnings=warnings,
            required_preflight_command_id=required_preflight_command_id,
        )

    @property
    def plan_digest(self) -> str:
        """Digest of the runnable plan, excluding presentation timestamps."""
        return sha256_hex(
            {
                "plan_id": self.plan_id,
                "status": self.status,
                "spec_digest": self.spec.spec_digest,
                "inventory_snapshot_digest": self.inventory_snapshot_digest,
                "worker_snapshot_revision": self.worker_snapshot_revision,
                "feasibility": [item.model_dump(mode="json") for item in self.feasibility],
                "warnings": list(self.warnings),
            }
        )
