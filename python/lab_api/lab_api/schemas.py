"""HTTP request/response contracts for the controller API.

The durable cross-process contracts live in :mod:`lab_core`; these models add
only transport-level envelopes and operator views.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from lab_core import (
    AwareTimestamp,
    BenchmarkObservation,
    CandidateSpec,
    ContextFeasibility,
    ContextLength,
    EngineId,
    ExperimentPlan,
    ExperimentSpec,
    ExperimentStatusView,
    FinalizationResult,
    FrozenModel,
    HardwareSnapshot,
    Identifier,
    JobEvent,
    MeasurementStatus,
    NonEmptyStr,
    NonNegativeInt,
    Objective,
    OptimizerHealth,
    PlanStatus,
    PositiveInt,
    RecipeMode,
    ResourceConstraints,
    SearchDepth,
    SearchPolicy,
    Sha256,
    WorkerHealth,
    WorkerIdentity,
    WorkerSnapshot,
    WorkloadSuite,
)
from lab_updates import (
    ComparisonPlan,
    ComparisonSample,
    ImpactAssessment,
    ReleaseDecision,
    ReleaseMetadata,
)


class PlanRequest(FrozenModel):
    worker_id: Identifier
    engine_id: EngineId
    model_id: NonEmptyStr
    objective: Objective = Objective.BALANCED
    contexts: tuple[ContextLength, ...]
    search_depth: SearchDepth = SearchDepth.STANDARD
    search_policy: SearchPolicy | None = None
    constraints: ResourceConstraints = Field(default_factory=ResourceConstraints)
    workload: WorkloadSuite = Field(default_factory=WorkloadSuite)
    recipe_mode: RecipeMode = RecipeMode.PER_CONTEXT
    gpu_uuids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _canonical_contexts(self) -> PlanRequest:
        if not self.contexts:
            raise ValueError("at least one context is required")
        if len({int(item) for item in self.contexts}) != len(self.contexts):
            raise ValueError("contexts must be unique")
        if self.search_policy is not None and self.search_policy.depth is not self.search_depth:
            raise ValueError("search_policy.depth must match search_depth")
        return self


class PlanResponse(FrozenModel):
    status: PlanStatus
    plan: ExperimentPlan | None = None
    command_id: Identifier | None = None
    reason: str | None = None
    retry_after_ms: NonNegativeInt | None = None

    @model_validator(mode="after")
    def _consistent(self) -> PlanResponse:
        if self.status is PlanStatus.READY and self.plan is None:
            raise ValueError("READY plan response requires a plan")
        if self.status is PlanStatus.PREFLIGHT_REQUIRED and not self.reason:
            raise ValueError("PREFLIGHT_REQUIRED response requires a reason")
        return self


class CreateExperimentRequest(FrozenModel):
    plan: ExperimentPlan
    notes: tuple[str, ...] = ()


class ExperimentView(FrozenModel):
    status: ExperimentStatusView
    plan: ExperimentPlan
    spec: ExperimentSpec
    feasibility: tuple[ContextFeasibility, ...] = ()
    candidates: tuple[CandidateSpec, ...] = ()
    observations: tuple[BenchmarkObservation, ...] = ()
    simulation: bool = False
    warnings: tuple[str, ...] = ()
    created_at: AwareTimestamp
    completed_at: AwareTimestamp | None = None


class ExperimentListResponse(FrozenModel):
    experiments: tuple[ExperimentStatusView, ...]
    total: NonNegativeInt


class ExperimentResultsResponse(FrozenModel):
    experiment_id: Identifier
    status: ExperimentStatusView
    candidates: tuple[CandidateSpec, ...] = ()
    observations: tuple[BenchmarkObservation, ...] = ()
    best_candidate_id: Identifier | None = None
    validated_winner_candidate_id: Identifier | None = None
    finalization: FinalizationResult
    simulated: bool = False
    warnings: tuple[str, ...] = ()
    phase: str = "phase-5-finalization"


class WorkerRegistrationRequest(FrozenModel):
    worker: WorkerIdentity
    hardware: HardwareSnapshot


class WorkerRegistrationResponse(FrozenModel):
    worker: WorkerIdentity
    token: NonEmptyStr
    token_prefix: NonEmptyStr
    snapshot_revision: NonNegativeInt


class WorkerSnapshotRequest(FrozenModel):
    snapshot: WorkerSnapshot


class WorkerSnapshotResponse(FrozenModel):
    accepted: bool
    snapshot_id: Identifier
    revision: NonNegativeInt
    discovery_digest: Sha256
    stale: bool = False


class PollRequest(FrozenModel):
    max_commands: int = Field(default=5, ge=1, le=50)


class OptimizerPollRequest(FrozenModel):
    max_requests: int = Field(default=5, ge=1, le=50)
    optimizer_id: Identifier | None = None


class HeartbeatRequest(FrozenModel):
    health: WorkerHealth
    active_leases: tuple[str, ...] = ()
    owned_pids: tuple[int, ...] = ()
    snapshot_revision: NonNegativeInt | None = None


class LeaseRenewRequest(FrozenModel):
    lease_token: NonEmptyStr
    lease_generation: PositiveInt
    extend_seconds: int = Field(default=120, ge=5, le=3600)


class LeaseRenewResponse(FrozenModel):
    command_id: Identifier
    lease_generation: PositiveInt
    lease_expires_at: AwareTimestamp
    server_time: AwareTimestamp


class HeartbeatResponse(FrozenModel):
    worker_id: Identifier
    status: str
    server_time: AwareTimestamp
    next_heartbeat_after_ms: NonNegativeInt
    warnings: tuple[str, ...] = ()


class WorkerView(FrozenModel):
    worker_id: Identifier
    name: str
    status: str
    protocol_version: str
    last_heartbeat_at: AwareTimestamp | None
    snapshot_revision: int
    snapshot_created_at: AwareTimestamp | None
    gpus: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()


class WorkerListResponse(FrozenModel):
    workers: tuple[WorkerView, ...]
    total: NonNegativeInt


class RecipeCreateRequest(FrozenModel):
    experiment_id: Identifier
    candidate_id: Identifier


class PromotionRequest(FrozenModel):
    target_slot: NonEmptyStr
    dry_run: bool = True


class RecipeView(FrozenModel):
    recipe_id: Identifier
    experiment_id: Identifier
    candidate_id: Identifier
    status: str
    recipe_digest: Sha256
    recipe: dict[str, Any]
    created_at: AwareTimestamp


class RecipeListResponse(FrozenModel):
    recipes: tuple[RecipeView, ...]
    total: NonNegativeInt


class SystemStatusResponse(FrozenModel):
    service: str
    version: str
    environment: str
    api_version: str
    controller_db: str
    optimizer_db: str
    optimizer: OptimizerHealth
    workers_online: NonNegativeInt
    experiments_active: NonNegativeInt
    serving_active: NonNegativeInt = 0
    scheduler_running: bool
    allow_simulation: bool
    warnings: tuple[str, ...] = ()


class HealthResponse(FrozenModel):
    status: str
    service: str
    version: str
    components: dict[str, str] = Field(default_factory=dict)


class EventPage(FrozenModel):
    events: tuple[JobEvent, ...]
    last_event_id: NonNegativeInt
    replay_floor: NonNegativeInt
    has_more: bool = False


class AckResponse(FrozenModel):
    command_id: Identifier
    status: str
    lease_generation: NonNegativeInt


class CompletionResponse(FrozenModel):
    command_id: Identifier
    status: str
    idempotent_replay: bool = False
    experiment_state: str | None = None


class OptimizerRequestAck(FrozenModel):
    request_id: Identifier
    status: str
    idempotent_replay: bool = False


class ReleaseCheckRequest(FrozenModel):
    worker_id: Identifier
    model_id: NonEmptyStr | None = None
    release: ReleaseMetadata


class ReleaseNoticeView(FrozenModel):
    notice_id: Identifier
    release: ReleaseMetadata
    metadata_digest: Sha256
    imported_at: AwareTimestamp
    decision: ReleaseDecision
    decision_note: str | None = None
    decision_at: AwareTimestamp | None = None


class ReleaseCheckResponse(FrozenModel):
    result: Literal["imported", "reused", "already_installed"]
    notice: ReleaseNoticeView
    assessment: ImpactAssessment


class ReleaseListResponse(FrozenModel):
    notices: tuple[ReleaseNoticeView, ...]
    total: NonNegativeInt


class ReleaseDetailResponse(FrozenModel):
    notice: ReleaseNoticeView
    assessments: tuple[ImpactAssessment, ...] = ()
    comparisons: tuple[ComparisonPlan, ...] = ()


class ReleaseDecisionRequest(FrozenModel):
    action: Literal["pin", "defer"]
    note: NonEmptyStr | None = None


class ComparisonCreateRequest(FrozenModel):
    notice_id: Identifier
    assessment_id: Identifier
    contexts: tuple[ContextLength, ...]
    objective: Objective = Objective.BALANCED
    workload: WorkloadSuite = Field(default_factory=WorkloadSuite)
    min_improvement_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _contexts(self) -> ComparisonCreateRequest:
        if not self.contexts:
            raise ValueError("at least one comparison context is required")
        if len({int(item) for item in self.contexts}) != len(self.contexts):
            raise ValueError("comparison contexts must be unique")
        return self


class ComparisonEvidenceRequest(FrozenModel):
    worker_id: Identifier
    model_digest: Sha256
    workload_digest: Sha256
    baseline_engine_sha256: Sha256
    candidate_engine_sha256: Sha256
    simulated: bool = False
    measurement_status: MeasurementStatus = MeasurementStatus.MEASURED
    samples: tuple[ComparisonSample, ...] = Field(default_factory=tuple, max_length=5_000)
    notes: tuple[NonEmptyStr, ...] = ()


class ComparisonListResponse(FrozenModel):
    comparisons: tuple[ComparisonPlan, ...]
    total: NonNegativeInt
