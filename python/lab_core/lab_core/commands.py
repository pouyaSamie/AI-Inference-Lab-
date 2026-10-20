"""Durable worker command protocol (outbound polling, leases, acks)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import AwareTimestamp, FrozenModel, Identifier, JsonScalar, NonEmptyStr, NonNegativeInt, Parameters, PositiveInt, Sha256, utcnow
from .engine import EngineIdentity
from .enums import AckDisposition, CommandStatus, CommandType, ContextLength, FailureKind
from .experiment import ContextFeasibility
from .model import ModelArtifact
from .observation import BenchmarkObservation
from .version import SCHEMA_VERSION, WORKER_PROTOCOL_VERSION
from .worker import WorkerSnapshot


class ScanPayload(FrozenModel):
    command_type: Literal[CommandType.SCAN] = CommandType.SCAN
    roots: tuple[str, ...]
    include_engines: bool = True
    include_models: bool = True
    include_hardware: bool = True
    hash_models: bool = False
    reason: str | None = None


class PreflightPayload(FrozenModel):
    command_type: Literal[CommandType.PREFLIGHT] = CommandType.PREFLIGHT
    experiment_id: Identifier
    spec_digest: Sha256
    plan_digest: Sha256
    engine: EngineIdentity
    model: ModelArtifact
    contexts: tuple[ContextLength, ...]
    gpu_uuids: tuple[str, ...] = ()
    expected_snapshot_revision: NonNegativeInt
    full_context_check: bool = True


class ClaimTrialPayload(FrozenModel):
    command_type: Literal[CommandType.CLAIM_TRIAL] = CommandType.CLAIM_TRIAL
    experiment_id: Identifier
    study_id: Identifier
    candidate_id: Identifier
    trial_number: PositiveInt
    context: ContextLength
    parameters: Parameters
    parameter_digest: Sha256
    workload_digest: Sha256
    engine: EngineIdentity
    model: ModelArtifact
    gpu_uuids: tuple[str, ...] = ()
    timeout_seconds: PositiveInt = 7200
    lease_generation: PositiveInt
    expected_snapshot_revision: NonNegativeInt
    simulation_only: bool = False


class PausePayload(FrozenModel):
    command_type: Literal[CommandType.PAUSE] = CommandType.PAUSE
    experiment_id: Identifier
    reason: str | None = None


class CancelPayload(FrozenModel):
    command_type: Literal[CommandType.CANCEL] = CommandType.CANCEL
    experiment_id: Identifier
    reason: str | None = None
    terminate_owned_processes: bool = True
    grace_seconds: PositiveInt = 10


class VerifyRecipePayload(FrozenModel):
    command_type: Literal[CommandType.VERIFY_RECIPE] = CommandType.VERIFY_RECIPE
    recipe_id: Identifier
    recipe_digest: Sha256
    expected_engine_sha256: Sha256
    expected_model_digest: Sha256


class PromotePayload(FrozenModel):
    command_type: Literal[CommandType.PROMOTE] = CommandType.PROMOTE
    recipe_id: Identifier
    recipe_digest: Sha256
    target_slot: NonEmptyStr
    dry_run: bool = True
    previous_recipe_id: Identifier | None = None


CommandPayload = Annotated[
    ScanPayload
    | PreflightPayload
    | ClaimTrialPayload
    | PausePayload
    | CancelPayload
    | VerifyRecipePayload
    | PromotePayload,
    Field(discriminator="command_type"),
]


class WorkerCommand(FrozenModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    protocol_version: NonEmptyStr = WORKER_PROTOCOL_VERSION
    command_id: Identifier
    command_type: CommandType
    worker_id: Identifier
    payload: CommandPayload
    expected_snapshot_revision: NonNegativeInt = 0
    idempotency_key: NonEmptyStr
    trace_id: str | None = None
    created_at: AwareTimestamp = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _type_matches_payload(self) -> WorkerCommand:
        if self.command_type is not self.payload.command_type:
            raise ValueError("command_type must match payload.command_type")
        return self


class WorkerCommandLease(FrozenModel):
    command: WorkerCommand
    lease_token: str
    lease_generation: PositiveInt
    lease_expires_at: AwareTimestamp


class WorkerPollResponse(FrozenModel):
    protocol_version: NonEmptyStr = WORKER_PROTOCOL_VERSION
    leases: tuple[WorkerCommandLease, ...] = ()
    server_time: AwareTimestamp = Field(default_factory=utcnow)
    poll_after_ms: PositiveInt = 1000


class CommandAck(FrozenModel):
    lease_token: NonEmptyStr
    disposition: AckDisposition
    lease_generation: PositiveInt
    message: str | None = None


class CommandFailure(FrozenModel):
    kind: FailureKind = FailureKind.UNKNOWN
    message: NonEmptyStr
    retryable: bool = False
    details: dict[str, JsonScalar] = Field(default_factory=dict)


class ScanResult(FrozenModel):
    command_type: Literal[CommandType.SCAN] = CommandType.SCAN
    snapshot: WorkerSnapshot
    warnings: tuple[str, ...] = ()


class PreflightResult(FrozenModel):
    command_type: Literal[CommandType.PREFLIGHT] = CommandType.PREFLIGHT
    experiment_id: Identifier
    passed: bool
    feasibility: tuple[ContextFeasibility, ...] = ()
    engine_sha256: Sha256
    model_digest: Sha256
    snapshot_revision: NonNegativeInt
    snapshot: WorkerSnapshot | None = None
    message: str | None = None
    failure_kind: FailureKind | None = None


class TrialResult(FrozenModel):
    command_type: Literal[CommandType.CLAIM_TRIAL] = CommandType.CLAIM_TRIAL
    observation: BenchmarkObservation


class PauseResult(FrozenModel):
    command_type: Literal[CommandType.PAUSE] = CommandType.PAUSE
    experiment_id: Identifier
    accepted: bool
    paused_at_stage: str | None = None
    message: str | None = None


class CancelResult(FrozenModel):
    command_type: Literal[CommandType.CANCEL] = CommandType.CANCEL
    experiment_id: Identifier
    accepted: bool
    terminated_owned_pids: tuple[int, ...] = ()
    message: str | None = None


class VerifyRecipeResult(FrozenModel):
    command_type: Literal[CommandType.VERIFY_RECIPE] = CommandType.VERIFY_RECIPE
    recipe_id: Identifier
    verified: bool
    engine_sha256: Sha256 | None = None
    model_digest: Sha256 | None = None
    mismatches: tuple[str, ...] = ()
    message: str | None = None


class PromoteResult(FrozenModel):
    command_type: Literal[CommandType.PROMOTE] = CommandType.PROMOTE
    recipe_id: Identifier
    promoted: bool
    dry_run: bool
    slot: str | None = None
    message: str | None = None


CommandResult = Annotated[
    ScanResult
    | PreflightResult
    | TrialResult
    | PauseResult
    | CancelResult
    | VerifyRecipeResult
    | PromoteResult,
    Field(discriminator="command_type"),
]


class CommandCompletion(FrozenModel):
    worker_id: Identifier
    lease_token: NonEmptyStr
    lease_generation: PositiveInt
    outcome: CommandStatus
    result: CommandResult | None = None
    failure: CommandFailure | None = None

    @model_validator(mode="after")
    def _terminal_and_consistent(self) -> CommandCompletion:
        allowed = {CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.REJECTED}
        if self.outcome not in allowed:
            raise ValueError("completion outcome must be completed, failed or rejected")
        if self.outcome is CommandStatus.COMPLETED and self.result is None:
            raise ValueError("completed command requires a typed result")
        if self.outcome is not CommandStatus.COMPLETED and self.failure is None:
            raise ValueError("failed/rejected command requires failure details")
        return self


class CommandStatusView(FrozenModel):
    command_id: Identifier
    worker_id: Identifier
    command_type: CommandType
    status: CommandStatus
    attempts: NonNegativeInt
    lease_generation: NonNegativeInt
    created_at: AwareTimestamp
    ack_at: AwareTimestamp | None = None
    completed_at: AwareTimestamp | None = None
    result: CommandResult | None = None
    failure: CommandFailure | None = None
    experiment_id: Identifier | None = None
