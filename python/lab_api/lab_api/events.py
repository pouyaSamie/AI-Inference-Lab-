"""Durable experiment events, status projections and SSE replay metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from lab_core.ids import new_id
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lab_core import (
    CandidateState,
    EventType,
    ExperimentStatusView,
    JobCounters,
    JobEvent,
    JobStage,
    JobState,
    ObservationStatus,
)

from .orm import (
    CandidateRow,
    ExperimentRow,
    JobEventRow,
    ObservationRow,
    ReplayFloorRow,
    as_utc,
    utcnow,
)


def append_event(
    session: Session,
    experiment_id: str,
    event_type: EventType,
    *,
    state: JobState | str | None = None,
    stage: JobStage | str | None = None,
    payload: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> JobEventRow:
    row = JobEventRow(
        event_id=new_id("evt"),
        experiment_id=experiment_id,
        type=event_type.value if isinstance(event_type, EventType) else event_type,
        state=state.value if isinstance(state, JobState) else state,
        stage=stage.value if isinstance(stage, JobStage) else stage,
        payload_json=payload or {},
        created_at=created_at or utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def event_to_model(row: JobEventRow) -> JobEvent:
    return JobEvent(
        event_id=row.event_id,
        experiment_id=row.experiment_id,
        sequence=row.sequence,
        type=EventType(row.type),
        state=JobState(row.state) if row.state else None,
        stage=JobStage(row.stage) if row.stage else None,
        payload=row.payload_json or {},
        created_at=as_utc(row.created_at) or utcnow(),
    )


def replay_floor(session: Session, experiment_id: str) -> int:
    row = session.get(ReplayFloorRow, experiment_id)
    return row.floor_sequence if row else 0


def set_replay_floor(session: Session, experiment_id: str, floor_sequence: int) -> None:
    row = session.get(ReplayFloorRow, experiment_id)
    if row is None:
        session.add(
            ReplayFloorRow(experiment_id=experiment_id, floor_sequence=floor_sequence, updated_at=utcnow())
        )
    else:
        row.floor_sequence = max(row.floor_sequence, floor_sequence)
        row.updated_at = utcnow()
    session.flush()


def latest_sequence(session: Session, experiment_id: str) -> int:
    value = session.scalar(
        select(func.max(JobEventRow.sequence)).where(JobEventRow.experiment_id == experiment_id)
    )
    return int(value or 0)


def events_after(
    session: Session,
    experiment_id: str,
    *,
    after_sequence: int,
    limit: int,
) -> list[JobEventRow]:
    return list(
        session.scalars(
            select(JobEventRow)
            .where(JobEventRow.experiment_id == experiment_id, JobEventRow.sequence > after_sequence)
            .order_by(JobEventRow.sequence)
            .limit(limit)
        )
    )


def recent_events(session: Session, experiment_id: str, *, limit: int = 50) -> list[JobEventRow]:
    rows = list(
        session.scalars(
            select(JobEventRow)
            .where(JobEventRow.experiment_id == experiment_id)
            .order_by(JobEventRow.sequence.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    return rows


def counters_for(session: Session, experiment_id: str, study_id: str | None = None) -> JobCounters:
    proposed = (
        session.scalar(
            select(func.count()).select_from(CandidateRow).where(CandidateRow.experiment_id == experiment_id)
        )
        or 0
    )
    completed = (
        session.scalar(
            select(func.count())
            .select_from(CandidateRow)
            .where(
                CandidateRow.experiment_id == experiment_id,
                CandidateRow.state.in_([CandidateState.OBSERVED.value, CandidateState.FINALIZED.value]),
            )
        )
        or 0
    )
    infeasible = (
        session.scalar(
            select(func.count())
            .select_from(CandidateRow)
            .where(
                CandidateRow.experiment_id == experiment_id,
                CandidateRow.state == CandidateState.INFEASIBLE.value,
            )
        )
        or 0
    )
    failed = (
        session.scalar(
            select(func.count())
            .select_from(CandidateRow)
            .where(
                CandidateRow.experiment_id == experiment_id, CandidateRow.state == CandidateState.FAILED.value
            )
        )
        or 0
    )
    observations = (
        session.scalar(
            select(func.count())
            .select_from(ObservationRow)
            .where(ObservationRow.experiment_id == experiment_id)
        )
        or 0
    )
    return JobCounters(
        candidates_proposed=int(proposed),
        candidates_completed=int(completed),
        candidates_infeasible=int(infeasible),
        candidates_failed=int(failed),
        trials_finalized=int(completed),
        observations_committed=int(observations),
    )


def status_view(session: Session, experiment: ExperimentRow) -> ExperimentStatusView:
    spec = experiment.spec_json or {}
    contexts = tuple(int(item) for item in spec.get("contexts", ()))
    return ExperimentStatusView(
        experiment_id=experiment.experiment_id,
        state=JobState(experiment.state),
        stage=JobStage(experiment.stage),
        revision=experiment.revision,
        spec_digest=experiment.spec_digest,
        plan_digest=experiment.plan_digest,
        worker_id=experiment.worker_id,
        engine_id=experiment.engine_id,
        model_id=experiment.model_id,
        objective=experiment.objective,
        contexts=contexts,
        counters=counters_for(session, experiment.experiment_id),
        last_event_id=latest_sequence(session, experiment.experiment_id),
        created_at=as_utc(experiment.created_at) or utcnow(),
        updated_at=as_utc(experiment.updated_at) or utcnow(),
        paused=experiment.paused,
        error_code=experiment.error_code,
        error_message=experiment.error_message,
    )


def observation_is_success(row: ObservationRow) -> bool:
    return row.status == ObservationStatus.COMPLETED.value
