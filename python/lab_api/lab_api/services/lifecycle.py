"""Experiment lifecycle transitions shared by API services and the scheduler."""

from __future__ import annotations

from typing import Any

from lab_core.base import utcnow
from sqlalchemy.orm import Session

from lab_core import EventType, JobStage, JobState, ensure_transition, is_terminal

from ..events import append_event
from ..orm import ExperimentRow


def transition_experiment(
    session: Session,
    experiment: ExperimentRow,
    target: JobState,
    *,
    stage: JobStage | None = None,
    payload: dict[str, Any] | None = None,
    started: bool = False,
) -> ExperimentRow:
    current = JobState(experiment.state)
    ensure_transition(current, target)
    experiment.state = target.value
    if stage is not None:
        experiment.stage = stage.value
    experiment.revision += 1
    experiment.updated_at = utcnow()
    if started and experiment.started_at is None:
        experiment.started_at = utcnow()
    if target in (JobState.COMPLETED, JobState.CANCELLED, JobState.FAILED, JobState.BLOCKED):
        experiment.completed_at = utcnow()
    else:
        experiment.completed_at = None
    append_event(
        session,
        experiment.experiment_id,
        EventType.EXPERIMENT_STATE_CHANGED,
        state=target,
        stage=JobStage(experiment.stage),
        payload={
            "from": current.value,
            "to": target.value,
            "stage": experiment.stage,
            **(payload or {}),
        },
    )
    return experiment


def set_stage(session: Session, experiment: ExperimentRow, stage: JobStage) -> ExperimentRow:
    if experiment.stage == stage.value:
        return experiment
    old = experiment.stage
    experiment.stage = stage.value
    experiment.revision += 1
    experiment.updated_at = utcnow()
    append_event(
        session,
        experiment.experiment_id,
        EventType.EXPERIMENT_STAGE_CHANGED,
        state=JobState(experiment.state),
        stage=stage,
        payload={"from": old, "to": stage.value},
    )
    return experiment


def fail_experiment(
    session: Session,
    experiment: ExperimentRow,
    *,
    code: str,
    message: str,
    stage: JobStage | None = None,
) -> ExperimentRow:
    experiment.error_code = code
    experiment.error_message = message
    if not is_terminal(JobState(experiment.state)):
        transition_experiment(
            session,
            experiment,
            JobState.FAILED,
            stage=stage,
            payload={"error_code": code, "error_message": message},
        )
    append_event(
        session,
        experiment.experiment_id,
        EventType.EXPERIMENT_FAILED,
        state=JobState(experiment.state),
        stage=JobStage(experiment.stage),
        payload={"code": code, "message": message},
    )
    return experiment


def complete_experiment(
    session: Session,
    experiment: ExperimentRow,
    *,
    payload: dict[str, Any] | None = None,
) -> ExperimentRow:
    if JobState(experiment.state) is not JobState.COMPLETED:
        transition_experiment(
            session,
            experiment,
            JobState.COMPLETED,
            stage=JobStage.COMPLETED,
            payload={"phase": "phase-1-screening", **(payload or {})},
        )
    append_event(
        session,
        experiment.experiment_id,
        EventType.EXPERIMENT_COMPLETED,
        state=JobState.COMPLETED,
        stage=JobStage.COMPLETED,
        payload=payload or {},
    )
    return experiment
