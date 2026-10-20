"""Durable controller <-> optimizer protocol.

The controller never executes Optuna in the API process. It writes typed
requests to its own database; a supervised optimizer process claims them over
authenticated internal HTTP, performs Optuna operations against a separate
database, and posts typed results back.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import (
    AwareTimestamp,
    FrozenModel,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    Parameters,
    PositiveInt,
    Sha256,
    utcnow,
)
from .enums import (
    FeasibilityOutcome,
    Objective,
    OptimizerRequestKind,
    TrialTellState,
)
from .search import SearchSpaceSpec
from .version import OPTIMIZER_PROTOCOL_VERSION, SCHEMA_VERSION


class CreateStudyPayload(FrozenModel):
    kind: Literal[OptimizerRequestKind.CREATE_STUDY] = OptimizerRequestKind.CREATE_STUDY
    study_id: Identifier
    study_name: NonEmptyStr
    experiment_id: Identifier
    seed: NonNegativeInt = 20261020
    max_trials: PositiveInt
    search_space: SearchSpaceSpec
    objective: Objective
    direction: Literal["maximize", "minimize"] = "maximize"


class AskPayload(FrozenModel):
    kind: Literal[OptimizerRequestKind.ASK] = OptimizerRequestKind.ASK
    study_id: Identifier
    study_name: NonEmptyStr
    context_tokens: PositiveInt
    workload_digest: Sha256
    attempt_limit: PositiveInt = 32


class TellPayload(FrozenModel):
    kind: Literal[OptimizerRequestKind.TELL] = OptimizerRequestKind.TELL
    study_id: Identifier
    study_name: NonEmptyStr
    candidate_id: Identifier
    trial_number: NonNegativeInt
    state: TrialTellState
    value: float | None = None
    feasibility: FeasibilityOutcome = FeasibilityOutcome.UNKNOWN
    reason: str | None = None

    @model_validator(mode="after")
    def _honest_tell(self) -> TellPayload:
        if self.state is TrialTellState.COMPLETE:
            if self.value is None:
                raise ValueError("a completed Optuna trial requires a finite value")
            if self.feasibility is not FeasibilityOutcome.FEASIBLE:
                raise ValueError("completed trial must be marked feasible")
        elif self.value is not None:
            raise ValueError("failed/infeasible/pruned trial must not carry a value")
        return self


class ReconcilePayload(FrozenModel):
    kind: Literal[OptimizerRequestKind.RECONCILE] = OptimizerRequestKind.RECONCILE
    study_id: Identifier
    study_name: NonEmptyStr


class PingPayload(FrozenModel):
    kind: Literal[OptimizerRequestKind.PING] = OptimizerRequestKind.PING
    note: str | None = None


OptimizerPayload = Annotated[
    CreateStudyPayload | AskPayload | TellPayload | ReconcilePayload | PingPayload,
    Field(discriminator="kind"),
]


class OptimizerRequest(FrozenModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    protocol_version: NonEmptyStr = OPTIMIZER_PROTOCOL_VERSION
    request_id: Identifier
    kind: OptimizerRequestKind
    study_id: Identifier
    payload: OptimizerPayload
    idempotency_key: NonEmptyStr
    attempts: NonNegativeInt = 0
    created_at: AwareTimestamp = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _kind_matches_payload(self) -> OptimizerRequest:
        if self.kind is not self.payload.kind:
            raise ValueError("request kind must match payload kind")
        return self


class OptimizerRequestLease(FrozenModel):
    request: OptimizerRequest
    lease_token: NonEmptyStr
    lease_expires_at: AwareTimestamp


class OptimizerPollResponse(FrozenModel):
    protocol_version: NonEmptyStr = OPTIMIZER_PROTOCOL_VERSION
    leases: tuple[OptimizerRequestLease, ...] = ()
    server_time: AwareTimestamp = Field(default_factory=utcnow)
    poll_after_ms: PositiveInt = 1000


class StudyCreatedResult(FrozenModel):
    kind: Literal["STUDY_CREATED"] = "STUDY_CREATED"
    study_name: NonEmptyStr
    created: bool
    trial_count: NonNegativeInt = 0


class AskResult(FrozenModel):
    kind: Literal["ASK_RESULT"] = "ASK_RESULT"
    study_name: NonEmptyStr
    trial_number: NonNegativeInt
    parameters: Parameters


class TellResult(FrozenModel):
    kind: Literal["TELL_RESULT"] = "TELL_RESULT"
    study_name: NonEmptyStr
    trial_number: NonNegativeInt
    trial_state: str
    finalized: bool
    already_finalized: bool = False
    value: float | None = None


class PendingTrial(FrozenModel):
    trial_number: NonNegativeInt
    state: str


class ReconcileResult(FrozenModel):
    kind: Literal["RECONCILE_RESULT"] = "RECONCILE_RESULT"
    study_name: NonEmptyStr
    total_trials: NonNegativeInt
    completed_trials: NonNegativeInt
    failed_trials: NonNegativeInt
    pending_trials: tuple[PendingTrial, ...] = ()


class PingResult(FrozenModel):
    kind: Literal["PING_RESULT"] = "PING_RESULT"
    optimizer_version: NonEmptyStr
    note: str | None = None


OptimizerResultPayload = Annotated[
    StudyCreatedResult | AskResult | TellResult | ReconcileResult | PingResult,
    Field(discriminator="kind"),
]


class OptimizerCompletion(FrozenModel):
    optimizer_id: Identifier
    lease_token: NonEmptyStr
    result: OptimizerResultPayload | None = None
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _one_outcome(self) -> OptimizerCompletion:
        if self.result is None and not self.error_code:
            raise ValueError("optimizer completion requires a result or an error_code")
        if self.result is not None and self.error_code:
            raise ValueError("optimizer completion cannot carry both result and error")
        return self


class OptimizerHeartbeat(FrozenModel):
    optimizer_id: Identifier
    pid: PositiveInt
    started_at: AwareTimestamp
    last_seen_at: AwareTimestamp = Field(default_factory=utcnow)
    version: NonEmptyStr
    status: Literal["starting", "ready", "degraded", "stopping"] = "ready"
    studies_open: NonNegativeInt = 0


class OptimizerHealth(FrozenModel):
    optimizer_id: Identifier | None = None
    online: bool = False
    status: str = "absent"
    last_seen_at: AwareTimestamp | None = None
    stale_after_seconds: PositiveInt = 30
    studies_open: NonNegativeInt = 0
    version: str | None = None
