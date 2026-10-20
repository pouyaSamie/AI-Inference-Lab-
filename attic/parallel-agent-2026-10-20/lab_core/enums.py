from __future__ import annotations

from enum import StrEnum


class EngineId(StrEnum):
    """Production engine IDs plus an explicitly non-production conformance mock."""

    LLAMACPP = "llamacpp"
    STRATA = "strata"
    MOCK = "mock"

    @property
    def is_production(self) -> bool:
        return self in (EngineId.LLAMACPP, EngineId.STRATA)


class Objective(StrEnum):
    BALANCED = "balanced"
    GENERATION_MAX = "generation_max"
    PREFILL_MAX = "prefill_max"


class SearchDepth(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    THOROUGH = "thorough"


class RecipeMode(StrEnum):
    PER_CONTEXT = "per_context"
    CROSS_CONTEXT = "cross_context"


class ContextTarget(int):
    """Documentation-only helper; contexts are validated by Pydantic literals."""


class ExperimentState(StrEnum):
    QUEUED = "queued"
    PREFLIGHTED = "preflighted"
    BASELINE = "baseline"
    SCREENING = "screening"
    REFINEMENT = "refinement"
    FINALIST_VALIDATION = "finalist_validation"
    REPORT_CREATION = "report_creation"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BLOCKED = "blocked"

    @property
    def terminal(self) -> bool:
        return self in (
            ExperimentState.COMPLETED,
            ExperimentState.CANCELLED,
            ExperimentState.FAILED,
        )


class WorkerStatus(StrEnum):
    ONLINE = "online"
    STALE = "stale"
    OFFLINE = "offline"
    DISABLED = "disabled"


class MeasurementStatus(StrEnum):
    """How a number was obtained. Only measured/simulated carry numeric metrics."""

    MEASURED = "measured"
    SIMULATED = "simulated"
    ESTIMATED = "estimated"
    SCREENING_ONLY = "screening_only"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    INFEASIBLE = "infeasible"


class OutcomeStatus(StrEnum):
    COMPLETED = "completed"
    RESOURCE_INFEASIBLE = "resource_infeasible"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    REJECTED = "rejected"

    @property
    def measurement_bearing(self) -> bool:
        return self is OutcomeStatus.COMPLETED


class ErrorKind(StrEnum):
    UNSUPPORTED_FLAG = "unsupported_flag"
    UNSUPPORTED_MODEL = "unsupported_model"
    INSUFFICIENT_VRAM = "insufficient_vram"
    INSUFFICIENT_RAM = "insufficient_ram"
    OOM = "oom"
    SERVER_NOT_READY = "server_not_ready"
    MODEL_LOAD_FAILURE = "model_load_failure"
    PROCESS_CRASH = "process_crash"
    TIMEOUT = "timeout"
    INVALID_METRICS = "invalid_metrics"
    CONTEXT_MISMATCH = "context_mismatch"
    QUALITY_REGRESSION = "quality_regression"
    THERMAL_CONTAMINATION = "thermal_contamination"
    EXTERNAL_GPU_CONTENTION = "external_gpu_contention"
    CANCELLED = "cancelled"
    PROTOCOL_ERROR = "protocol_error"
    UNKNOWN = "unknown"


class CommandType(StrEnum):
    SCAN = "SCAN"
    PREFLIGHT = "PREFLIGHT"
    CLAIM_TRIAL = "CLAIM_TRIAL"
    PAUSE = "PAUSE"
    CANCEL = "CANCEL"
    VERIFY_RECIPE = "VERIFY_RECIPE"
    PROMOTE = "PROMOTE"


class WorkerCommandState(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    ORPHAN_REVIEW = "ORPHAN_REVIEW"

    @property
    def terminal(self) -> bool:
        return self in (
            WorkerCommandState.COMPLETED,
            WorkerCommandState.FAILED,
            WorkerCommandState.REJECTED,
            WorkerCommandState.CANCELLED,
            WorkerCommandState.EXPIRED,
        )


class OptimizerRequestKind(StrEnum):
    CREATE_STUDY = "CREATE_STUDY"
    ASK = "ASK"
    TELL = "TELL"
    RECONCILE = "RECONCILE"


class OptimizerRequestState(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CapabilityProvenance(StrEnum):
    OBSERVED_CLI = "observed_cli"
    COMPATIBILITY_RULE = "compatibility_rule"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class FeasibilityState(StrEnum):
    FEASIBLE = "feasible"
    PROJECTED = "projected"
    INFEASIBLE = "infeasible"
    INCONCLUSIVE = "inconclusive"
    UNKNOWN = "unknown"


class ModelVerification(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    MISSING = "missing"


class ParameterKind(StrEnum):
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    CATEGORICAL = "categorical"


class ImpactClass(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class JobEventType(StrEnum):
    EXPERIMENT_STATE_CHANGED = "experiment.state_changed"
    COMMAND_QUEUED = "command.queued"
    COMMAND_ACKED = "command.acked"
    COMMAND_COMPLETED = "command.completed"
    COMMAND_FAILED = "command.failed"
    TRIAL_CREATED = "trial.created"
    OBSERVATION_RECORDED = "observation.recorded"
    OPTIMIZER_REQUESTED = "optimizer.requested"
    OPTIMIZER_COMPLETED = "optimizer.completed"
    OPTIMIZER_FAILED = "optimizer.failed"
    EXPERIMENT_COMPLETED = "experiment.completed"
    ERROR = "error"
    EVENT_GAP = "event.gap"
    HEARTBEAT = "heartbeat"


class RecipeStatus(StrEnum):
    VALIDATED = "validated"
    APPROVED = "approved"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


class VerificationDisposition(StrEnum):
    STARTED = "started"
    REJECTED = "rejected"
