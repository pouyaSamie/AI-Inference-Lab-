"""Experiment creation, operator lifecycle and result projections."""

from __future__ import annotations

from lab_core.base import utcnow
from lab_core.errors import (
    ConflictError,
    IdempotencyConflictError,
    InvalidTransitionError,
    NotFoundError,
    PreflightRequiredError,
    StalePlanError,
)
from lab_core.ids import stable_id
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lab_core import (
    TERMINAL_JOB_STATES,
    BenchmarkObservation,
    CancelPayload,
    CandidateSpec,
    CommandType,
    ContextFeasibility,
    ContextLength,
    EventType,
    ExperimentPlan,
    ExperimentSpec,
    FeasibilityOutcome,
    JobStage,
    JobState,
    PausePayload,
    PlanStatus,
    PreflightPayload,
    WorkerSnapshot,
    finalize_experiment,
)

from ..config import Settings
from ..events import append_event, status_view
from ..orm import (
    CandidateRow,
    ExperimentContextRow,
    ExperimentRow,
    ObservationRow,
    StudyRow,
    as_utc,
)
from ..schemas import (
    CreateExperimentRequest,
    ExperimentListResponse,
    ExperimentResultsResponse,
    ExperimentView,
)
from .commands import enqueue_command
from .inventory import latest_snapshot, snapshot_freshness, snapshot_model
from .lifecycle import transition_experiment
from .observations import _screening_value
from .planning import build_study_search_space


def _validate_plan(
    session: Session,
    settings: Settings,
    plan: ExperimentPlan,
) -> tuple[WorkerSnapshot, int]:
    if plan.status is not PlanStatus.READY:
        raise PreflightRequiredError(
            "plan is not ready; complete the required preflight first",
            details={"command_id": plan.required_preflight_command_id},
        )
    worker_id = plan.spec.worker_id
    snapshot_row = latest_snapshot(session, worker_id)
    if snapshot_row is None:
        raise StalePlanError("no cached snapshot exists for the plan worker")
    worker = snapshot_row.worker_id
    from ..orm import WorkerRow

    worker_row = session.get(WorkerRow, worker)
    if worker_row is None:
        raise NotFoundError("worker is not registered")
    fresh, reasons = snapshot_freshness(settings, worker_row, snapshot_row)
    if not fresh:
        raise StalePlanError(
            "worker inventory changed since the plan was issued", details={"reasons": list(reasons)}
        )
    if plan.worker_snapshot_revision != snapshot_row.revision:
        raise StalePlanError(
            "plan snapshot revision is stale",
            details={
                "plan_revision": plan.worker_snapshot_revision,
                "current_revision": snapshot_row.revision,
            },
        )
    snapshot = snapshot_model(snapshot_row)
    if plan.inventory_snapshot_digest != snapshot_row.discovery_digest:
        raise StalePlanError("plan inventory digest does not match the latest snapshot")
    engine = snapshot.engine(plan.spec.engine.engine_id.value)
    if engine is None or engine.engine.executable_sha256 != plan.spec.engine.executable_sha256:
        raise StalePlanError("engine identity changed since the plan was issued")
    model = snapshot.model(plan.spec.model.model_id)
    if model is None or model.artifact_digest != plan.spec.model.artifact_digest:
        raise StalePlanError("model identity changed since the plan was issued")
    return snapshot, snapshot_row.revision


def _competing_experiment(session: Session, spec: ExperimentSpec) -> ExperimentRow | None:
    terminal = [state.value for state in TERMINAL_JOB_STATES]
    rows = session.scalars(
        select(ExperimentRow).where(
            ExperimentRow.worker_id == spec.worker_id,
            ExperimentRow.engine_id == spec.engine.engine_id.value,
            ExperimentRow.model_id == spec.model.model_id,
            ExperimentRow.objective == spec.objective.value,
            ExperimentRow.state.not_in(terminal),
        )
    ).all()
    requested_contexts = {int(item) for item in spec.contexts}
    requested_gpus = set(spec.gpu_uuids)
    for row in rows:
        row_spec = ExperimentSpec.model_validate(row.spec_json)
        if not requested_contexts.intersection({int(item) for item in row_spec.contexts}):
            continue
        if not requested_gpus or not row_spec.gpu_uuids:
            return row
        if requested_gpus.intersection(row_spec.gpu_uuids):
            return row
    return None


def create_experiment(
    session: Session,
    settings: Settings,
    request: CreateExperimentRequest,
    *,
    idempotency_key: str,
    request_hash: str,
) -> tuple[ExperimentView, bool]:
    existing = session.scalar(select(ExperimentRow).where(ExperimentRow.idempotency_key == idempotency_key))
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError("idempotency key was used with a different experiment request")
        return experiment_view(session, existing), True

    plan = request.plan
    snapshot, snapshot_revision = _validate_plan(session, settings, plan)
    competing = _competing_experiment(session, plan.spec)
    if competing is not None:
        raise ConflictError(
            "a competing experiment already owns this worker/engine/model/context/GPU combination",
            details={"competing_experiment_id": competing.experiment_id},
            recovery_hint="Wait for the competing experiment to finish or choose a disjoint GPU/context set.",
        )

    spec = plan.spec
    experiment_id = stable_id("exp", spec.spec_digest, plan.plan_digest, idempotency_key)
    now = utcnow()
    experiment = ExperimentRow(
        experiment_id=experiment_id,
        worker_id=spec.worker_id,
        engine_id=spec.engine.engine_id.value,
        model_id=spec.model.model_id,
        objective=spec.objective.value,
        state=JobState.QUEUED.value,
        stage="queued",
        revision=0,
        spec_digest=spec.spec_digest,
        plan_digest=plan.plan_digest,
        spec_json=spec.model_dump(mode="json"),
        plan_json=plan.model_dump(mode="json"),
        inventory_snapshot_digest=spec.inventory_snapshot_digest,
        worker_snapshot_revision=snapshot_revision,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        paused=False,
        preflight_passed=False,
        created_at=now,
        updated_at=now,
    )
    session.add(experiment)
    session.flush()

    for item in plan.feasibility:
        session.add(
            ExperimentContextRow(
                experiment_id=experiment_id,
                context_tokens=int(item.context),
                feasibility_status=item.status.value,
                reason=item.reason,
                estimated_vram_bytes=item.estimated_vram_bytes,
                requires_full_context_proof=item.requires_full_context_proof,
                evidence_json=list(item.evidence),
                created_at=now,
            )
        )

    search_space = build_study_search_space(
        engine_id=spec.engine.engine_id,
        model_architecture=spec.model.architecture,
        model_quantization=spec.model.quantization,
        objective=spec.objective.value,
        contexts=spec.contexts,
    )
    study_id = stable_id("study", spec.spec_digest, plan.plan_digest)
    study = StudyRow(
        study_id=study_id,
        experiment_id=experiment_id,
        engine_id=spec.engine.engine_id.value,
        model_digest=spec.model.artifact_digest,
        worker_profile_digest=snapshot.discovery_digest or snapshot.compute_discovery_digest(),
        search_depth=spec.search_depth.value,
        study_name=f"{experiment_id}:{spec.spec_digest[:16]}",
        state="pending",
        search_space_json=search_space.model_dump(mode="json"),
        # One fixed-default baseline per selected context is required before
        # candidates can be compared. Baselines are not TPE search proposals,
        # so they do not consume the distinct-candidate search budget.
        maximum_trials=(spec.search_policy.max_candidates or 1) + len(spec.contexts),
        proposal_attempts=0,
        seed=spec.search_policy.seed,
        objective=spec.objective.value,
        created_at=now,
    )
    session.add(study)

    append_event(
        session,
        experiment_id,
        EventType.EXPERIMENT_CREATED,
        state=JobState.QUEUED,
        stage="queued",
        payload={
            "spec_digest": spec.spec_digest,
            "plan_digest": plan.plan_digest,
            "worker_snapshot_revision": snapshot_revision,
            "simulated": settings.execution_mode == "simulated",
            "phase": "phase-1-screening",
        },
    )
    transition_experiment(session, experiment, JobState.PREFLIGHTING, stage=JobStage.PREFLIGHT)

    preflight_payload = PreflightPayload(
        experiment_id=experiment_id,
        spec_digest=spec.spec_digest,
        plan_digest=plan.plan_digest,
        engine=spec.engine,
        model=spec.model,
        contexts=spec.contexts,
        gpu_uuids=spec.gpu_uuids,
        expected_snapshot_revision=snapshot_revision,
        full_context_check=spec.constraints.require_full_context_proof,
    )
    enqueue_command(
        session,
        settings,
        worker_id=spec.worker_id,
        command_type=CommandType.PREFLIGHT,
        payload=preflight_payload,
        idempotency_key=f"preflight:{experiment_id}",
        experiment_id=experiment_id,
        expected_snapshot_revision=snapshot_revision,
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(ExperimentRow).where(ExperimentRow.idempotency_key == idempotency_key)
        )
        if existing is not None and existing.request_hash == request_hash:
            return experiment_view(session, existing), True
        raise ConflictError("experiment creation raced with another request") from exc
    return experiment_view(session, experiment), False


def experiment_view(session: Session, experiment: ExperimentRow) -> ExperimentView:
    plan = ExperimentPlan.model_validate(experiment.plan_json)
    spec = ExperimentSpec.model_validate(experiment.spec_json)
    contexts = session.scalars(
        select(ExperimentContextRow)
        .where(ExperimentContextRow.experiment_id == experiment.experiment_id)
        .order_by(ExperimentContextRow.context_tokens)
    ).all()
    feasibility = tuple(
        ContextFeasibility(
            context=ContextLength(row.context_tokens),
            status=FeasibilityOutcome(row.feasibility_status),
            estimated_vram_bytes=row.estimated_vram_bytes,
            reason=row.reason,
            evidence=tuple(row.evidence_json or ()),
            requires_full_context_proof=row.requires_full_context_proof,
        )
        for row in contexts
    )
    candidate_rows = session.scalars(
        select(CandidateRow)
        .where(CandidateRow.experiment_id == experiment.experiment_id)
        .order_by(CandidateRow.trial_number)
    ).all()
    candidates = tuple(CandidateSpec.model_validate(row.payload_json) for row in candidate_rows)
    observation_rows = session.scalars(
        select(ObservationRow)
        .where(ObservationRow.experiment_id == experiment.experiment_id)
        .order_by(ObservationRow.committed_at)
    ).all()
    observations = tuple(BenchmarkObservation.model_validate(row.payload_json) for row in observation_rows)
    return ExperimentView(
        status=status_view(session, experiment),
        plan=plan,
        spec=spec,
        feasibility=feasibility or plan.feasibility,
        candidates=candidates,
        observations=observations,
        simulation=any(item.simulated for item in observations) or settings_mode(session, experiment),
        warnings=plan.warnings,
        created_at=as_utc(experiment.created_at) or utcnow(),
        completed_at=as_utc(experiment.completed_at),
    )


def settings_mode(session: Session, experiment: ExperimentRow) -> bool:
    # Kept deliberately simple: a Phase 1 experiment is simulated if any
    # observation says so or the plan warned about simulated execution.
    plan = ExperimentPlan.model_validate(experiment.plan_json)
    return "PHASE_1_SIMULATED_EXECUTION" in plan.warnings


def list_experiments(session: Session, *, limit: int = 50, offset: int = 0) -> ExperimentListResponse:
    rows = session.scalars(
        select(ExperimentRow).order_by(ExperimentRow.created_at.desc()).offset(offset).limit(limit)
    ).all()
    total = session.query(ExperimentRow).count()
    return ExperimentListResponse(
        experiments=tuple(status_view(session, row) for row in rows),
        total=total,
    )


def get_experiment(session: Session, experiment_id: str) -> ExperimentRow:
    row = session.get(ExperimentRow, experiment_id)
    if row is None:
        raise NotFoundError("experiment not found")
    return row


def pause_experiment(session: Session, settings: Settings, experiment_id: str) -> ExperimentView:
    experiment = get_experiment(session, experiment_id)
    if JobState(experiment.state) in TERMINAL_JOB_STATES:
        raise InvalidTransitionError("cannot pause a terminal experiment")
    if experiment.paused:
        return experiment_view(session, experiment)
    if JobState(experiment.state) is JobState.RUNNING or JobState(experiment.state) is JobState.READY:
        transition_experiment(session, experiment, JobState.PAUSED)
    else:
        raise InvalidTransitionError("experiment can only be paused while ready or running")
    experiment.paused = True
    enqueue_command(
        session,
        settings,
        worker_id=experiment.worker_id,
        command_type=CommandType.PAUSE,
        payload=PausePayload(experiment_id=experiment_id, reason="operator pause"),
        idempotency_key=f"pause:{experiment_id}:{experiment.revision}",
        experiment_id=experiment_id,
    )
    session.commit()
    return experiment_view(session, experiment)


def resume_experiment(session: Session, experiment_id: str) -> ExperimentView:
    experiment = get_experiment(session, experiment_id)
    if not experiment.paused:
        return experiment_view(session, experiment)
    if JobState(experiment.state) is not JobState.PAUSED:
        raise InvalidTransitionError("only a paused experiment can be resumed")
    transition_experiment(
        session,
        experiment,
        JobState.RUNNING if experiment.preflight_passed else JobState.READY,
    )
    experiment.paused = False
    append_event(
        session,
        experiment_id,
        EventType.EXPERIMENT_STATE_CHANGED,
        state=JobState(experiment.state),
        stage=JobStage(experiment.stage),
        payload={"event": "resumed"},
    )
    session.commit()
    return experiment_view(session, experiment)


def cancel_experiment(
    session: Session, settings: Settings, experiment_id: str, reason: str | None = None
) -> ExperimentView:
    experiment = get_experiment(session, experiment_id)
    state = JobState(experiment.state)
    if state in TERMINAL_JOB_STATES:
        raise InvalidTransitionError("experiment is already terminal")
    if state in (JobState.RUNNING, JobState.PAUSED):
        transition_experiment(session, experiment, JobState.CANCELLING)
    else:
        transition_experiment(session, experiment, JobState.CANCELLED)
    enqueue_command(
        session,
        settings,
        worker_id=experiment.worker_id,
        command_type=CommandType.CANCEL,
        payload=CancelPayload(
            experiment_id=experiment_id,
            reason=reason or "operator cancel",
            terminate_owned_processes=True,
            grace_seconds=10,
        ),
        idempotency_key=f"cancel:{experiment_id}:{experiment.revision}",
        experiment_id=experiment_id,
    )
    session.commit()
    return experiment_view(session, experiment)


def retry_preflight(session: Session, settings: Settings, experiment_id: str) -> ExperimentView:
    experiment = get_experiment(session, experiment_id)
    if JobState(experiment.state) is not JobState.BLOCKED:
        raise InvalidTransitionError("preflight can only be retried from a blocked experiment")
    transition_experiment(
        session,
        experiment,
        JobState.READY,
        payload={"event": "preflight_retry"},
    )
    experiment.preflight_passed = False
    experiment.error_code = None
    experiment.error_message = None
    spec = ExperimentSpec.model_validate(experiment.spec_json)
    enqueue_command(
        session,
        settings,
        worker_id=experiment.worker_id,
        command_type=CommandType.PREFLIGHT,
        payload=PreflightPayload(
            experiment_id=experiment_id,
            spec_digest=experiment.spec_digest,
            plan_digest=experiment.plan_digest,
            engine=spec.engine,
            model=spec.model,
            contexts=spec.contexts,
            gpu_uuids=spec.gpu_uuids,
            expected_snapshot_revision=experiment.worker_snapshot_revision,
            full_context_check=spec.constraints.require_full_context_proof,
        ),
        idempotency_key=f"preflight:{experiment_id}:retry:{experiment.revision}",
        experiment_id=experiment_id,
        expected_snapshot_revision=experiment.worker_snapshot_revision,
    )
    session.commit()
    return experiment_view(session, experiment)


def experiment_results(session: Session, experiment_id: str) -> ExperimentResultsResponse:
    view = experiment_view(session, get_experiment(session, experiment_id))
    best_id = None
    best_value = float("-inf")
    by_candidate: dict[str, BenchmarkObservation] = {item.candidate_id: item for item in view.observations}
    for candidate in view.candidates:
        observation = by_candidate.get(candidate.candidate_id)
        value = _screening_value(view.spec.objective, observation) if observation is not None else None
        if value is not None and value > best_value:
            best_value = value
            best_id = candidate.candidate_id
    finalization = finalize_experiment(
        experiment_id=experiment_id,
        spec=view.spec,
        candidates=view.candidates,
        observations=view.observations,
    )
    warnings = [*view.warnings, *finalization.warnings]
    if view.simulation:
        warnings.append("SIMULATED_RESULTS_NOT_VALIDATED_FOR_DEPLOYMENT")
    return ExperimentResultsResponse(
        experiment_id=experiment_id,
        status=view.status,
        candidates=view.candidates,
        observations=view.observations,
        best_candidate_id=best_id,
        validated_winner_candidate_id=finalization.validated_winner_candidate_id,
        finalization=finalization,
        simulated=view.simulation,
        warnings=tuple(dict.fromkeys(warnings)),
        phase="phase-5-finalization",
    )
