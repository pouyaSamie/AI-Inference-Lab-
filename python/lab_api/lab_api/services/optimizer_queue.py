"""Durable optimizer outbox/inbox and result side effects.

The FastAPI process writes requests here and never imports Optuna. The
supervised optimizer claims leases over internal HTTP, performs Optuna work in
its own process/database, and returns typed results.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from typing import Any

from lab_core.base import utcnow
from lab_core.errors import ConflictError, NotFoundError, OptimizerUnavailableError
from lab_core.ids import new_id, sha256_hex
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lab_core import (
    AskPayload,
    AskResult,
    CandidateSpec,
    CandidateState,
    ClaimTrialPayload,
    CommandStatus,
    CommandType,
    ContextLength,
    CreateStudyPayload,
    EventType,
    ExperimentSpec,
    FeasibilityOutcome,
    JobStage,
    JobState,
    OptimizerCompletion,
    OptimizerHealth,
    OptimizerHeartbeat,
    OptimizerPollResponse,
    OptimizerRequest,
    OptimizerRequestKind,
    OptimizerRequestLease,
    OptimizerResultPayload,
    PingResult,
    ReconcileResult,
    SearchSpaceSpec,
    StudyCreatedResult,
    TellPayload,
    TellResult,
    TrialTellState,
)

from ..config import Settings
from ..events import append_event
from ..orm import (
    CandidateRow,
    ExperimentRow,
    OptimizerHeartbeatRow,
    OptimizerRequestRow,
    StudyRow,
    WorkerCommandRow,
    as_utc,
)
from .commands import enqueue_command
from .lifecycle import complete_experiment, fail_experiment, set_stage, transition_experiment


def _hash_lease(token: str) -> str:
    return sha256_hex({"optimizer_lease": token})


def enqueue_optimizer_request(
    session: Session,
    *,
    kind: OptimizerRequestKind,
    study_id: str,
    payload: Any,
    idempotency_key: str,
) -> OptimizerRequestRow:
    existing = session.scalar(
        select(OptimizerRequestRow).where(OptimizerRequestRow.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing
    request = OptimizerRequest(
        request_id=new_id("oreq"),
        kind=kind,
        study_id=study_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    row = OptimizerRequestRow(
        request_id=request.request_id,
        kind=kind.value,
        study_id=study_id,
        idempotency_key=idempotency_key,
        payload_json=request.model_dump(mode="json"),
        status="pending",
        attempts=0,
        created_at=utcnow(),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(OptimizerRequestRow).where(OptimizerRequestRow.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        return existing
    return row


def expire_optimizer_leases(session: Session, settings: Settings) -> int:
    now = utcnow()
    rows = session.scalars(
        select(OptimizerRequestRow).where(
            OptimizerRequestRow.status == "leased",
            OptimizerRequestRow.lease_expires_at.is_not(None),
            OptimizerRequestRow.lease_expires_at < now,
        )
    ).all()
    for row in rows:
        if row.attempts >= settings.optimizer_max_attempts:
            row.status = "failed"
            row.error_code = "OPTIMIZER_LEASE_EXPIRED"
            row.error_message = "optimizer lease expired after maximum attempts"
            row.completed_at = now
            _fail_experiment_for_optimizer(session, row)
        else:
            row.status = "pending"
        row.lease_owner = None
        row.lease_token_hash = None
        row.lease_expires_at = None
    if rows:
        session.flush()
    return len(rows)


def claim_optimizer_requests(
    session: Session,
    settings: Settings,
    *,
    optimizer_id: str,
    max_requests: int = 5,
) -> OptimizerPollResponse:
    expire_optimizer_leases(session, settings)
    rows = list(
        session.scalars(
            select(OptimizerRequestRow)
            .where(OptimizerRequestRow.status == "pending")
            .order_by(OptimizerRequestRow.id)
            .limit(max_requests)
        )
    )
    leases: list[OptimizerRequestLease] = []
    now = utcnow()
    for row in rows:
        token = secrets.token_urlsafe(32)
        row.status = "leased"
        row.attempts += 1
        row.lease_owner = optimizer_id
        row.lease_token_hash = _hash_lease(token)
        row.lease_expires_at = now + timedelta(seconds=settings.optimizer_lease_seconds)
        request = OptimizerRequest.model_validate(row.payload_json)
        leases.append(
            OptimizerRequestLease(
                request=request,
                lease_token=token,
                lease_expires_at=row.lease_expires_at,
            )
        )
    session.commit()
    return OptimizerPollResponse(
        leases=tuple(leases),
        server_time=now,
        poll_after_ms=500 if leases else 1000,
    )


def _verify_optimizer_lease(row: OptimizerRequestRow, token: str, optimizer_id: str) -> None:
    if row.lease_owner != optimizer_id:
        raise ConflictError("optimizer lease owner mismatch")
    if row.lease_token_hash is None or not hmac.compare_digest(row.lease_token_hash, _hash_lease(token)):
        raise ConflictError("optimizer lease token is invalid")
    expires = as_utc(row.lease_expires_at)
    if expires is not None and expires < utcnow():
        raise ConflictError("optimizer lease has expired")


def complete_optimizer_request(
    session: Session,
    settings: Settings,
    *,
    request_id: str,
    completion: OptimizerCompletion,
) -> tuple[OptimizerRequestRow, bool]:
    row = session.scalar(select(OptimizerRequestRow).where(OptimizerRequestRow.request_id == request_id))
    if row is None:
        raise NotFoundError("optimizer request not found")
    if row.status in {"completed", "failed"}:
        stored = row.result_json
        submitted = completion.result.model_dump(mode="json") if completion.result else None
        if row.status == "completed" and stored == submitted:
            return row, True
        if row.status == "failed" and completion.error_code == row.error_code:
            return row, True
        raise ConflictError("optimizer request already reached a different outcome")
    _verify_optimizer_lease(row, completion.lease_token, completion.optimizer_id)
    if completion.result is not None:
        row.result_json = completion.result.model_dump(mode="json")
        row.status = "completed"
        row.completed_at = utcnow()
        _apply_optimizer_result(session, settings, row, completion.result)
    else:
        row.status = "failed"
        row.error_code = completion.error_code
        row.error_message = completion.error_message
        row.completed_at = utcnow()
        _fail_experiment_for_optimizer(session, row)
    row.lease_owner = None
    row.lease_token_hash = None
    row.lease_expires_at = None
    session.commit()
    return row, False


def heartbeat_optimizer(session: Session, heartbeat: OptimizerHeartbeat) -> None:
    row = session.get(OptimizerHeartbeatRow, heartbeat.optimizer_id)
    if row is None:
        row = OptimizerHeartbeatRow(
            optimizer_id=heartbeat.optimizer_id,
            pid=heartbeat.pid,
            started_at=heartbeat.started_at,
            last_seen_at=heartbeat.last_seen_at,
            version=heartbeat.version,
            status=heartbeat.status,
            studies_open=heartbeat.studies_open,
        )
        session.add(row)
    else:
        row.pid = heartbeat.pid
        row.started_at = heartbeat.started_at
        row.last_seen_at = heartbeat.last_seen_at
        row.version = heartbeat.version
        row.status = heartbeat.status
        row.studies_open = heartbeat.studies_open
    session.commit()


def optimizer_health(session: Session, settings: Settings) -> OptimizerHealth:
    row = session.scalar(
        select(OptimizerHeartbeatRow).order_by(OptimizerHeartbeatRow.last_seen_at.desc()).limit(1)
    )
    if row is None:
        return OptimizerHealth(
            online=False,
            status="absent",
            stale_after_seconds=settings.optimizer_offline_after_seconds,
        )
    last_seen = as_utc(row.last_seen_at)
    now = utcnow()
    online = (
        last_seen is not None
        and (now - last_seen).total_seconds() <= settings.optimizer_offline_after_seconds
    )
    return OptimizerHealth(
        optimizer_id=row.optimizer_id,
        online=online,
        status="online" if online else "stale",
        last_seen_at=last_seen,
        stale_after_seconds=settings.optimizer_offline_after_seconds,
        studies_open=row.studies_open,
        version=row.version,
    )


def require_optimizer_online(session: Session, settings: Settings) -> None:
    health = optimizer_health(session, settings)
    if not health.online:
        raise OptimizerUnavailableError(
            "the supervised optimizer process is not online",
            details={
                "status": health.status,
                "last_seen_at": health.last_seen_at.isoformat() if health.last_seen_at else None,
            },
        )


def _experiment_for_request(session: Session, row: OptimizerRequestRow) -> tuple[StudyRow, ExperimentRow]:
    study = session.get(StudyRow, row.study_id)
    if study is None:
        raise NotFoundError("study not found")
    experiment = session.get(ExperimentRow, study.experiment_id)
    if experiment is None:
        raise NotFoundError("experiment not found")
    return study, experiment


def _fail_experiment_for_optimizer(session: Session, row: OptimizerRequestRow) -> None:
    try:
        _study, experiment = _experiment_for_request(session, row)
    except NotFoundError:
        return
    fail_experiment(
        session,
        experiment,
        code=row.error_code or "OPTIMIZER_REQUEST_FAILED",
        message=row.error_message or "optimizer request failed",
    )


def _apply_optimizer_result(
    session: Session, settings: Settings, row: OptimizerRequestRow, result: OptimizerResultPayload
) -> None:
    study, experiment = _experiment_for_request(session, row)
    if isinstance(result, StudyCreatedResult):
        if study.state != "active":
            study.state = "active"
            study.started_at = utcnow()
            append_event(
                session,
                experiment.experiment_id,
                EventType.OPTIMIZER_FINALIZED,
                state=JobState(experiment.state),
                stage=JobStage(experiment.stage),
                payload={"study_id": study.study_id, "event": "study_created", "created": result.created},
            )
        if experiment.preflight_passed and JobState(experiment.state) is JobState.READY:
            transition_experiment(
                session,
                experiment,
                JobState.RUNNING,
                stage=JobStage.SCREENING,
                started=True,
                payload={"study_id": study.study_id},
            )
        return

    if isinstance(result, AskResult):
        _apply_ask_result(session, settings, study, experiment, result, row)
        return

    if isinstance(result, TellResult):
        _apply_tell_result(session, settings, study, experiment, result, row)
        return

    if isinstance(result, ReconcileResult):
        if study.state != "active" and result.total_trials >= 0:
            study.state = "active"
        return

    if isinstance(result, PingResult):
        return


def _apply_ask_result(
    session: Session,
    settings: Settings,
    study: StudyRow,
    experiment: ExperimentRow,
    result: AskResult,
    row: OptimizerRequestRow,
) -> None:
    request = OptimizerRequest.model_validate(row.payload_json)
    assert isinstance(request.payload, AskPayload)
    spec = ExperimentSpec.model_validate(experiment.spec_json)
    params = dict(result.parameters)
    context_value = params.pop("context_tokens", request.payload.context_tokens)
    try:
        if not isinstance(context_value, (int, str)):
            raise ValueError("context must be an integer")
        context = ContextLength(int(context_value))
    except (TypeError, ValueError):
        _tell_pruned(session, study, experiment, result.trial_number, "invalid context returned by optimizer")
        return
    if context not in spec.contexts:
        _tell_pruned(
            session, study, experiment, result.trial_number, "optimizer returned a context outside the spec"
        )
        return

    candidate = CandidateSpec(
        study_id=study.study_id,
        experiment_id=experiment.experiment_id,
        trial_number=result.trial_number + 1,
        engine_id=spec.engine.engine_id.value,
        engine_sha256=spec.engine.executable_sha256,
        model_digest=spec.model.artifact_digest,
        worker_id=spec.worker_id,
        context=context,
        parameters=params,
        workload_digest=spec.workload.digest(),
    )
    semantic_digest = candidate.semantic_key()
    duplicate = session.scalar(
        select(CandidateRow).where(
            CandidateRow.study_id == study.study_id,
            CandidateRow.semantic_digest == semantic_digest,
        )
    )
    if duplicate is not None:
        append_event(
            session,
            experiment.experiment_id,
            EventType.CANDIDATE_PROPOSED,
            state=JobState(experiment.state),
            stage=JobStage(experiment.stage),
            payload={
                "study_id": study.study_id,
                "trial_number": result.trial_number,
                "duplicate_of": duplicate.candidate_id,
                "semantic_digest": semantic_digest,
            },
        )
        _tell_pruned(
            session,
            study,
            experiment,
            result.trial_number,
            "duplicate semantic candidate",
        )
        return

    trial_collision = session.scalar(
        select(CandidateRow).where(
            CandidateRow.study_id == study.study_id,
            CandidateRow.trial_number == candidate.trial_number,
        )
    )
    if trial_collision is not None:
        _tell_pruned(
            session,
            study,
            experiment,
            result.trial_number,
            "controller trial number already exists",
        )
        return

    candidate_row = CandidateRow(
        candidate_id=candidate.candidate_id,
        study_id=study.study_id,
        experiment_id=experiment.experiment_id,
        trial_number=candidate.trial_number,
        context_tokens=int(candidate.context),
        parameters_json=candidate.parameters,
        payload_json=candidate.model_dump(mode="json"),
        parameter_digest=candidate.parameter_digest or "",
        semantic_digest=semantic_digest,
        state=CandidateState.PROPOSED.value,
        created_at=utcnow(),
        notes=list(candidate.notes),
    )
    session.add(candidate_row)
    study.proposal_attempts += 1
    session.flush()
    append_event(
        session,
        experiment.experiment_id,
        EventType.CANDIDATE_PROPOSED,
        state=JobState(experiment.state),
        stage=JobStage(experiment.stage),
        payload={
            "candidate_id": candidate.candidate_id,
            "trial_number": candidate.trial_number,
            "context": int(candidate.context),
            "parameter_digest": candidate.parameter_digest,
            "simulated": settings.execution_mode == "simulated",
        },
    )
    if JobState(experiment.state) is JobState.RUNNING and not experiment.paused:
        _enqueue_claim(session, settings, experiment, study, candidate, candidate_row)


def _tell_pruned(
    session: Session,
    study: StudyRow,
    experiment: ExperimentRow,
    optimizer_trial_number: int,
    reason: str,
) -> None:
    candidate_id = f"pruned_{study.study_id}_{optimizer_trial_number}"
    enqueue_optimizer_request(
        session,
        kind=OptimizerRequestKind.TELL,
        study_id=study.study_id,
        payload=TellPayload(
            study_id=study.study_id,
            study_name=study.study_name,
            candidate_id=candidate_id,
            trial_number=optimizer_trial_number,
            state=TrialTellState.PRUNED,
            value=None,
            feasibility=FeasibilityOutcome.UNKNOWN,
            reason=reason,
        ),
        idempotency_key=f"prune:{study.study_id}:{optimizer_trial_number}:{new_id('req')}",
    )


def _enqueue_claim(
    session: Session,
    settings: Settings,
    experiment: ExperimentRow,
    study: StudyRow,
    candidate: CandidateSpec,
    candidate_row: CandidateRow,
) -> WorkerCommandRow:
    spec = ExperimentSpec.model_validate(experiment.spec_json)
    payload = ClaimTrialPayload(
        experiment_id=experiment.experiment_id,
        study_id=study.study_id,
        candidate_id=candidate.candidate_id,
        trial_number=candidate.trial_number,
        context=candidate.context,
        parameters=candidate.parameters,
        parameter_digest=candidate.parameter_digest or "",
        workload_digest=candidate.workload_digest,
        workload=spec.workload,
        engine=spec.engine,
        model=spec.model,
        gpu_uuids=spec.gpu_uuids,
        timeout_seconds=settings.trial_timeout_seconds,
        lease_generation=1,
        expected_snapshot_revision=experiment.worker_snapshot_revision,
        simulation_only=settings.execution_mode == "simulated",
    )
    command = enqueue_command(
        session,
        settings,
        worker_id=experiment.worker_id,
        command_type=CommandType.CLAIM_TRIAL,
        payload=payload,
        idempotency_key=f"claim:{candidate.candidate_id}",
        experiment_id=experiment.experiment_id,
        candidate_id=candidate.candidate_id,
        expected_snapshot_revision=experiment.worker_snapshot_revision,
    )
    if candidate_row.state == CandidateState.PROPOSED.value:
        candidate_row.state = CandidateState.CLAIMED.value
        candidate_row.claimed_at = utcnow()
    return command


def _apply_tell_result(
    session: Session,
    settings: Settings,
    study: StudyRow,
    experiment: ExperimentRow,
    result: TellResult,
    row: OptimizerRequestRow,
) -> None:
    request = OptimizerRequest.model_validate(row.payload_json)
    assert isinstance(request.payload, TellPayload)
    candidate = session.get(CandidateRow, request.payload.candidate_id)
    if candidate is not None:
        candidate.optimizer_finalized = True
        candidate.completed_at = utcnow()
        if result.trial_state == "complete":
            candidate.state = CandidateState.FINALIZED.value
        append_event(
            session,
            experiment.experiment_id,
            EventType.OPTIMIZER_FINALIZED,
            state=JobState(experiment.state),
            stage=JobStage(experiment.stage),
            payload={
                "candidate_id": candidate.candidate_id,
                "trial_number": candidate.trial_number,
                "trial_state": result.trial_state,
                "value": result.value,
            },
        )
    _maybe_complete(session, study, experiment)


def _maybe_complete(session: Session, study: StudyRow, experiment: ExperimentRow) -> None:
    total = (
        session.scalar(
            select(func.count()).select_from(CandidateRow).where(CandidateRow.study_id == study.study_id)
        )
        or 0
    )
    pending = (
        session.scalar(
            select(func.count())
            .select_from(CandidateRow)
            .where(
                CandidateRow.study_id == study.study_id,
                CandidateRow.optimizer_finalized.is_(False),
            )
        )
        or 0
    )
    if total >= study.maximum_trials and pending == 0:
        study.state = "completed"
        study.completed_at = utcnow()
        set_stage(session, experiment, JobStage.REPORT)
        complete_experiment(
            session,
            experiment,
            payload={
                "study_id": study.study_id,
                "candidates": int(total),
                "phase_1_note": "Phase 1 screening only; no validated deployment recipe is claimed.",
            },
        )
    elif study.proposal_attempts >= study.maximum_trials * 8:
        fail_experiment(
            session,
            experiment,
            code="OPTIMIZER_SEARCH_EXHAUSTED",
            message="optimizer exceeded the bounded proposal-attempt budget",
        )


def reconcile_study(session: Session, settings: Settings, study: StudyRow) -> None:
    """Drive one study toward its next deterministic action."""
    experiment = session.get(ExperimentRow, study.experiment_id)
    if experiment is None:
        return
    state = JobState(experiment.state)
    if state in (
        JobState.CANCELLED,
        JobState.FAILED,
        JobState.BLOCKED,
        JobState.COMPLETED,
        JobState.CANCELLING,
    ):
        return
    if not experiment.preflight_passed or experiment.paused:
        return

    if study.state == "pending":
        pending_create = session.scalar(
            select(OptimizerRequestRow).where(
                OptimizerRequestRow.study_id == study.study_id,
                OptimizerRequestRow.kind == OptimizerRequestKind.CREATE_STUDY.value,
                OptimizerRequestRow.status.in_(["pending", "leased"]),
            )
        )
        if pending_create is None:
            spec = ExperimentSpec.model_validate(experiment.spec_json)
            search_space = SearchSpaceSpec.model_validate(study.search_space_json)
            enqueue_optimizer_request(
                session,
                kind=OptimizerRequestKind.CREATE_STUDY,
                study_id=study.study_id,
                payload=CreateStudyPayload(
                    study_id=study.study_id,
                    study_name=study.study_name,
                    experiment_id=experiment.experiment_id,
                    seed=study.seed,
                    max_trials=study.maximum_trials,
                    search_space=search_space,
                    objective=spec.objective,
                ),
                idempotency_key=f"create:{study.study_id}",
            )
        return

    if state is JobState.READY:
        transition_experiment(
            session,
            experiment,
            JobState.RUNNING,
            stage=JobStage.SCREENING,
            started=True,
        )

    # A proposed candidate without a live claim command must be claimed again.
    proposed = session.scalars(
        select(CandidateRow).where(
            CandidateRow.study_id == study.study_id,
            CandidateRow.state.in_([CandidateState.PROPOSED.value, CandidateState.CLAIMED.value]),
            CandidateRow.optimizer_finalized.is_(False),
        )
    ).all()
    for candidate_row in proposed:
        live = session.scalar(
            select(WorkerCommandRow).where(
                WorkerCommandRow.candidate_id == candidate_row.candidate_id,
                WorkerCommandRow.command_type == CommandType.CLAIM_TRIAL.value,
                WorkerCommandRow.status.in_(
                    [
                        CommandStatus.PENDING.value,
                        CommandStatus.LEASED.value,
                        CommandStatus.ACKNOWLEDGED.value,
                        CommandStatus.RUNNING.value,
                    ]
                ),
            )
        )
        if live is None:
            terminal = session.scalar(
                select(WorkerCommandRow).where(
                    WorkerCommandRow.candidate_id == candidate_row.candidate_id,
                    WorkerCommandRow.command_type == CommandType.CLAIM_TRIAL.value,
                    WorkerCommandRow.status.in_([CommandStatus.COMPLETED.value, CommandStatus.EXPIRED.value]),
                )
            )
            if terminal is None:
                candidate = CandidateSpec.model_validate(candidate_row.payload_json)
                _enqueue_claim(session, settings, experiment, study, candidate, candidate_row)

    pending_action = session.scalar(
        select(OptimizerRequestRow).where(
            OptimizerRequestRow.study_id == study.study_id,
            OptimizerRequestRow.kind.in_([OptimizerRequestKind.ASK.value, OptimizerRequestKind.TELL.value]),
            OptimizerRequestRow.status.in_(["pending", "leased"]),
        )
    )
    in_flight = session.scalar(
        select(CandidateRow).where(
            CandidateRow.study_id == study.study_id,
            CandidateRow.optimizer_finalized.is_(False),
        )
    )
    total = (
        session.scalar(
            select(func.count()).select_from(CandidateRow).where(CandidateRow.study_id == study.study_id)
        )
        or 0
    )
    if pending_action is None and in_flight is None and total < study.maximum_trials:
        spec = ExperimentSpec.model_validate(experiment.spec_json)
        context = spec.contexts[total % len(spec.contexts)]
        enqueue_optimizer_request(
            session,
            kind=OptimizerRequestKind.ASK,
            study_id=study.study_id,
            payload=AskPayload(
                study_id=study.study_id,
                study_name=study.study_name,
                context_tokens=int(context),
                workload_digest=spec.workload.digest(),
            ),
            idempotency_key=f"ask:{study.study_id}:{new_id('req')}",
        )
    elif pending_action is None and in_flight is None and total >= study.maximum_trials:
        _maybe_complete(session, study, experiment)
