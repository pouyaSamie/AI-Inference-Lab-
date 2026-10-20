"""Deterministic state machines shared by the controller and worker protocol."""

from __future__ import annotations

from lab_core.enums import ExperimentState, WorkerCommandState
from lab_core.errors import InvalidStateTransitionError

# Phase 1 supports queued -> screening directly after optimizer study creation.
# Later phases add baseline/refinement/finalist validation transitions without
# changing the meaning of existing edges.
EXPERIMENT_TRANSITIONS: dict[ExperimentState, frozenset[ExperimentState]] = {
    ExperimentState.QUEUED: frozenset(
        {
            ExperimentState.PREFLIGHTED,
            ExperimentState.SCREENING,
            ExperimentState.BLOCKED,
            ExperimentState.CANCELLING,
            ExperimentState.PAUSED,
            ExperimentState.FAILED,
        }
    ),
    ExperimentState.PREFLIGHTED: frozenset(
        {
            ExperimentState.BASELINE,
            ExperimentState.SCREENING,
            ExperimentState.BLOCKED,
            ExperimentState.CANCELLING,
            ExperimentState.PAUSED,
            ExperimentState.FAILED,
        }
    ),
    ExperimentState.BASELINE: frozenset(
        {
            ExperimentState.SCREENING,
            ExperimentState.PAUSED,
            ExperimentState.CANCELLING,
            ExperimentState.FAILED,
        }
    ),
    ExperimentState.SCREENING: frozenset(
        {
            ExperimentState.REFINEMENT,
            ExperimentState.FINALIST_VALIDATION,
            ExperimentState.REPORT_CREATION,
            ExperimentState.PAUSED,
            ExperimentState.CANCELLING,
            ExperimentState.FAILED,
            ExperimentState.BLOCKED,
        }
    ),
    ExperimentState.REFINEMENT: frozenset(
        {
            ExperimentState.FINALIST_VALIDATION,
            ExperimentState.REPORT_CREATION,
            ExperimentState.PAUSED,
            ExperimentState.CANCELLING,
            ExperimentState.FAILED,
        }
    ),
    ExperimentState.FINALIST_VALIDATION: frozenset(
        {
            ExperimentState.REPORT_CREATION,
            ExperimentState.PAUSED,
            ExperimentState.CANCELLING,
            ExperimentState.FAILED,
        }
    ),
    ExperimentState.REPORT_CREATION: frozenset(
        {
            ExperimentState.COMPLETED,
            ExperimentState.FAILED,
            ExperimentState.CANCELLING,
        }
    ),
    ExperimentState.PAUSED: frozenset(
        {
            ExperimentState.SCREENING,
            ExperimentState.BASELINE,
            ExperimentState.CANCELLING,
            ExperimentState.FAILED,
            ExperimentState.COMPLETED,
        }
    ),
    ExperimentState.CANCELLING: frozenset(
        {ExperimentState.CANCELLED, ExperimentState.FAILED}
    ),
    ExperimentState.BLOCKED: frozenset(
        {
            ExperimentState.PREFLIGHTED,
            ExperimentState.SCREENING,
            ExperimentState.CANCELLING,
            ExperimentState.FAILED,
        }
    ),
    ExperimentState.COMPLETED: frozenset(),
    ExperimentState.CANCELLED: frozenset(),
    ExperimentState.FAILED: frozenset(),
}

COMMAND_TRANSITIONS: dict[WorkerCommandState, frozenset[WorkerCommandState]] = {
    WorkerCommandState.PENDING: frozenset(
        {
            WorkerCommandState.CLAIMED,
            WorkerCommandState.CANCELLED,
            WorkerCommandState.EXPIRED,
        }
    ),
    WorkerCommandState.CLAIMED: frozenset(
        {
            WorkerCommandState.RUNNING,
            WorkerCommandState.COMPLETED,
            WorkerCommandState.FAILED,
            WorkerCommandState.REJECTED,
            WorkerCommandState.PENDING,  # lease expired and returned to queue
            WorkerCommandState.EXPIRED,
            WorkerCommandState.ORPHAN_REVIEW,
        }
    ),
    WorkerCommandState.RUNNING: frozenset(
        {
            WorkerCommandState.COMPLETED,
            WorkerCommandState.FAILED,
            WorkerCommandState.CANCELLED,
            WorkerCommandState.ORPHAN_REVIEW,
            WorkerCommandState.PENDING,
        }
    ),
    WorkerCommandState.EXPIRED: frozenset({WorkerCommandState.PENDING}),
    WorkerCommandState.ORPHAN_REVIEW: frozenset(
        {WorkerCommandState.PENDING, WorkerCommandState.FAILED, WorkerCommandState.CANCELLED}
    ),
    WorkerCommandState.COMPLETED: frozenset(),
    WorkerCommandState.FAILED: frozenset(),
    WorkerCommandState.REJECTED: frozenset(),
    WorkerCommandState.CANCELLED: frozenset(),
}


def assert_experiment_transition(current: ExperimentState, target: ExperimentState) -> None:
    if target not in EXPERIMENT_TRANSITIONS[current]:
        raise InvalidStateTransitionError(
            f"experiment cannot transition from {current.value} to {target.value}",
            details={"current": current.value, "target": target.value},
        )


def assert_command_transition(current: WorkerCommandState, target: WorkerCommandState) -> None:
    if target not in COMMAND_TRANSITIONS[current]:
        raise InvalidStateTransitionError(
            f"command cannot transition from {current.value} to {target.value}",
            details={"current": current.value, "target": target.value},
        )
