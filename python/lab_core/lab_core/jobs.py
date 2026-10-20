"""Job state machine, durable events and operator-facing status contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .base import AwareTimestamp, FrozenModel, Identifier, NonEmptyStr, NonNegativeInt, PositiveInt, Sha256
from .enums import TERMINAL_JOB_STATES, EventType, JobStage, JobState
from .errors import InvalidTransitionError


class TransitionCause(StrEnum):
    CREATE = "create"
    SCHEDULER = "scheduler"
    WORKER = "worker"
    OPERATOR = "operator"
    OPTIMIZER = "optimizer"
    RECOVERY = "recovery"


ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset(
        {JobState.PREFLIGHTING, JobState.READY, JobState.BLOCKED, JobState.CANCELLED, JobState.FAILED}
    ),
    JobState.PREFLIGHT_REQUIRED: frozenset(
        {JobState.PREFLIGHTING, JobState.BLOCKED, JobState.CANCELLED, JobState.FAILED}
    ),
    JobState.PREFLIGHTING: frozenset(
        {JobState.READY, JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED, JobState.PREFLIGHT_REQUIRED}
    ),
    JobState.READY: frozenset(
        {JobState.RUNNING, JobState.PAUSED, JobState.CANCELLED, JobState.FAILED, JobState.BLOCKED}
    ),
    JobState.RUNNING: frozenset(
        {
            JobState.PAUSED,
            JobState.CANCELLING,
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.BLOCKED,
        }
    ),
    JobState.PAUSED: frozenset(
        {JobState.RUNNING, JobState.CANCELLING, JobState.FAILED, JobState.BLOCKED, JobState.COMPLETED}
    ),
    JobState.CANCELLING: frozenset({JobState.CANCELLED, JobState.FAILED}),
    JobState.COMPLETED: frozenset(),
    JobState.CANCELLED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.BLOCKED: frozenset({JobState.READY, JobState.CANCELLED, JobState.FAILED}),
}


def ensure_transition(current: JobState, target: JobState) -> None:
    if target is current:
        return
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(
            f"cannot transition experiment from {current.value} to {target.value}",
            details={"current": current.value, "target": target.value},
        )


def is_terminal(state: JobState) -> bool:
    return state in TERMINAL_JOB_STATES


class JobEvent(FrozenModel):
    event_id: Identifier
    experiment_id: Identifier
    sequence: PositiveInt
    type: EventType
    state: JobState | None = None
    stage: JobStage | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareTimestamp

    @model_validator(mode="after")
    def _event_type_matches_gap(self) -> JobEvent:
        if self.type is EventType.EVENT_GAP and "replay_floor" not in self.payload:
            raise ValueError("EVENT_GAP event must include replay_floor")
        return self


class JobCounters(FrozenModel):
    candidates_proposed: NonNegativeInt = 0
    candidates_completed: NonNegativeInt = 0
    candidates_infeasible: NonNegativeInt = 0
    candidates_failed: NonNegativeInt = 0
    trials_finalized: NonNegativeInt = 0
    observations_committed: NonNegativeInt = 0
    work_units_total: NonNegativeInt | None = None
    work_units_done: NonNegativeInt = 0


class ExperimentStatusView(FrozenModel):
    experiment_id: Identifier
    state: JobState
    stage: JobStage
    revision: NonNegativeInt
    spec_digest: Sha256
    plan_digest: Sha256
    worker_id: Identifier
    engine_id: NonEmptyStr
    model_id: NonEmptyStr
    objective: NonEmptyStr
    contexts: tuple[int, ...]
    counters: JobCounters = Field(default_factory=JobCounters)
    last_event_id: int = 0
    created_at: AwareTimestamp
    updated_at: AwareTimestamp
    paused: bool = False
    error_code: str | None = None
    error_message: str | None = None


class ExperimentSnapshot(FrozenModel):
    """Immutable snapshot delivered when an SSE replay gap is detected."""

    snapshot_sequence: NonNegativeInt
    status: ExperimentStatusView
    recent_events: tuple[JobEvent, ...] = ()
