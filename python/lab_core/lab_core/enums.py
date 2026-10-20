"""Enumerations used at component boundaries.

Values are part of the public contract and must not be renamed without a
schema-version bump.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class EngineId(StrEnum):
    LLAMACPP = "llamacpp"
    STRATA = "strata"
    MOCK_FUTURE = "mock_future"


class Backend(StrEnum):
    CUDA = "cuda"
    CPU = "cpu"
    METAL = "metal"
    VULKAN = "vulkan"
    ROCM = "rocm"
    UNKNOWN = "unknown"


class Objective(StrEnum):
    BALANCED = "balanced"
    DECODE_MAX = "decode_max"
    PREFILL_MAX = "prefill_max"


class ContextLength(IntEnum):
    K4 = 4096
    K8 = 8192
    K16 = 16384
    K32 = 32768
    K64 = 65536
    K128 = 131072


class SearchDepth(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    THOROUGH = "thorough"


class RecipeMode(StrEnum):
    PER_CONTEXT = "per_context"
    CROSS_CONTEXT = "cross_context"


class MeasurementStatus(StrEnum):
    MEASURED = "measured"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    INFEASIBLE = "infeasible"
    SCREENING_ONLY = "screening_only"
    SIMULATED = "simulated"


class EvidenceKind(StrEnum):
    NATIVE_MICROBENCH = "native_microbench"
    SERVER_API = "server_api"
    QUALITY = "quality"
    STABILITY = "stability"
    SIMULATED = "simulated"


class ObservationStatus(StrEnum):
    COMPLETED = "completed"
    RESOURCE_INFEASIBLE = "resource_infeasible"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FailureKind(StrEnum):
    UNSUPPORTED_FLAG = "UNSUPPORTED_FLAG"
    UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"
    INSUFFICIENT_VRAM = "INSUFFICIENT_VRAM"
    INSUFFICIENT_RAM = "INSUFFICIENT_RAM"
    OOM = "OOM"
    SERVER_NOT_READY = "SERVER_NOT_READY"
    MODEL_LOAD_FAILURE = "MODEL_LOAD_FAILURE"
    PROCESS_CRASH = "PROCESS_CRASH"
    TIMEOUT = "TIMEOUT"
    INVALID_METRICS = "INVALID_METRICS"
    CONTEXT_MISMATCH = "CONTEXT_MISMATCH"
    QUALITY_REGRESSION = "QUALITY_REGRESSION"
    THERMAL_CONTAMINATION = "THERMAL_CONTAMINATION"
    EXTERNAL_GPU_CONTENTION = "EXTERNAL_GPU_CONTENTION"
    CANCELLED = "CANCELLED"
    LEASE_CONFLICT = "LEASE_CONFLICT"
    SIMULATION_ERROR = "SIMULATION_ERROR"
    UNKNOWN = "UNKNOWN"


class QualityGateStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    INCONCLUSIVE = "inconclusive"


class JobState(StrEnum):
    QUEUED = "queued"
    PREFLIGHT_REQUIRED = "preflight_required"
    PREFLIGHTING = "preflighting"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


TERMINAL_JOB_STATES = frozenset({JobState.CANCELLED, JobState.COMPLETED, JobState.FAILED, JobState.BLOCKED})


class JobStage(StrEnum):
    QUEUED = "queued"
    PREFLIGHT = "preflight"
    BASELINE = "baseline"
    SCREENING = "screening"
    REFINEMENT = "refinement"
    FINALIST_VALIDATION = "finalist_validation"
    REPORT = "report"
    COMPLETED = "completed"


class PlanStatus(StrEnum):
    READY = "ready"
    PREFLIGHT_REQUIRED = "preflight_required"


class CommandType(StrEnum):
    SCAN = "SCAN"
    PREFLIGHT = "PREFLIGHT"
    CLAIM_TRIAL = "CLAIM_TRIAL"
    PAUSE = "PAUSE"
    CANCEL = "CANCEL"
    VERIFY_RECIPE = "VERIFY_RECIPE"
    PROMOTE = "PROMOTE"


class CommandStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    ACKNOWLEDGED = "acknowledged"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_COMMAND_STATUSES = frozenset(
    {
        CommandStatus.COMPLETED,
        CommandStatus.FAILED,
        CommandStatus.REJECTED,
        CommandStatus.CANCELLED,
        CommandStatus.EXPIRED,
    }
)


class AckDisposition(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CandidateState(StrEnum):
    PROPOSED = "proposed"
    CLAIMED = "claimed"
    OBSERVED = "observed"
    INFEASIBLE = "infeasible"
    FAILED = "failed"
    FINALIZED = "finalized"
    DISCARDED = "discarded"


class StudyState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class OptimizerRequestKind(StrEnum):
    CREATE_STUDY = "CREATE_STUDY"
    ASK = "ASK"
    TELL = "TELL"
    RECONCILE = "RECONCILE"
    PING = "PING"


class OptimizerRequestStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TrialTellState(StrEnum):
    COMPLETE = "complete"
    FAIL = "fail"
    PRUNED = "pruned"


class FeasibilityOutcome(StrEnum):
    FEASIBLE = "feasible"
    RESOURCE_INFEASIBLE = "resource_infeasible"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"
    UNKNOWN = "unknown"


class OOMStage(StrEnum):
    PLANNING = "planning"
    MODEL_LOAD = "model_load"
    KV_ALLOCATION = "kv_allocation"
    PREFILL = "prefill"
    DECODE = "decode"
    UNKNOWN = "unknown"


class RecipeStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    REVOKED = "revoked"


class ImpactClass(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class OperatorRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"
    WORKER = "worker"


class EventType(StrEnum):
    EXPERIMENT_CREATED = "experiment.created"
    EXPERIMENT_STATE_CHANGED = "experiment.state_changed"
    EXPERIMENT_STAGE_CHANGED = "experiment.stage_changed"
    EXPERIMENT_COMPLETED = "experiment.completed"
    EXPERIMENT_FAILED = "experiment.failed"
    COMMAND_QUEUED = "command.queued"
    COMMAND_ACKNOWLEDGED = "command.acknowledged"
    COMMAND_COMPLETED = "command.completed"
    COMMAND_FAILED = "command.failed"
    WORKER_REGISTERED = "worker.registered"
    WORKER_SNAPSHOT = "worker.snapshot"
    WORKER_HEARTBEAT = "worker.heartbeat"
    CANDIDATE_PROPOSED = "candidate.proposed"
    CANDIDATE_CLAIMED = "candidate.claimed"
    OBSERVATION_COMMITTED = "observation.committed"
    OBSERVATION_RECONCILED = "observation.reconciled"
    OPTIMIZER_FINALIZED = "optimizer.finalized"
    OPTIMIZER_OFFLINE = "optimizer.offline"
    RECIPE_CREATED = "recipe.created"
    SYSTEM_RECONCILED = "system.reconciled"
    EVENT_GAP = "event.gap"
    SNAPSHOT = "snapshot"
