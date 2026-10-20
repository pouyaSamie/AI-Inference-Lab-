"""Apply typed worker command results to the controller state."""

from __future__ import annotations

from lab_core.base import utcnow
from lab_core.errors import NotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lab_core import (
    CancelResult,
    CommandCompletion,
    EventType,
    JobStage,
    JobState,
    PauseResult,
    PreflightResult,
    PromoteResult,
    ScanResult,
    TrialResult,
    VerifyRecipeResult,
)

from ..config import Settings
from ..events import append_event
from ..orm import (
    ExperimentContextRow,
    ExperimentRow,
    PromotionRow,
    RecipeRow,
    StudyRow,
    WorkerCommandRow,
)
from .inventory import store_snapshot
from .lifecycle import transition_experiment
from .observations import commit_observation
from .optimizer_queue import reconcile_study


def apply_command_completion(
    session: Session,
    settings: Settings,
    row: WorkerCommandRow,
    completion: CommandCompletion,
) -> None:
    if row.experiment_id:
        append_event(
            session,
            row.experiment_id,
            EventType.COMMAND_COMPLETED,
            payload={
                "command_id": row.command_id,
                "command_type": row.command_type,
                "outcome": completion.outcome.value,
            },
        )
        if completion.failure is not None:
            append_event(
                session,
                row.experiment_id,
                EventType.COMMAND_FAILED,
                payload={
                    "command_id": row.command_id,
                    "command_type": row.command_type,
                    "failure": completion.failure.model_dump(mode="json"),
                },
            )
    result = completion.result
    if result is None:
        return
    if isinstance(result, ScanResult):
        store_snapshot(session, settings, row.worker_id, result.snapshot)
        return
    if isinstance(result, PreflightResult):
        _apply_preflight(session, settings, row, result)
        return
    if isinstance(result, TrialResult):
        commit_observation(session, settings, result.observation)
        return
    if isinstance(result, PauseResult):
        _apply_pause(session, row, result)
        return
    if isinstance(result, CancelResult):
        _apply_cancel(session, row, result)
        return
    if isinstance(result, VerifyRecipeResult):
        _apply_verify_recipe(session, result)
        return
    if isinstance(result, PromoteResult):
        _apply_promote(session, result)
        return


def _apply_preflight(
    session: Session,
    settings: Settings,
    row: WorkerCommandRow,
    result: PreflightResult,
) -> None:
    experiment = session.get(ExperimentRow, result.experiment_id)
    if experiment is None:
        raise NotFoundError("experiment not found for preflight result")
    contexts = {
        item.context_tokens: item
        for item in session.scalars(
            select(ExperimentContextRow).where(ExperimentContextRow.experiment_id == experiment.experiment_id)
        )
    }
    for feasibility in result.feasibility:
        context_row = contexts.get(int(feasibility.context))
        if context_row is None:
            context_row = ExperimentContextRow(
                experiment_id=experiment.experiment_id,
                context_tokens=int(feasibility.context),
                feasibility_status=feasibility.status.value,
                reason=feasibility.reason,
                estimated_vram_bytes=feasibility.estimated_vram_bytes,
                requires_full_context_proof=feasibility.requires_full_context_proof,
                evidence_json=list(feasibility.evidence),
                created_at=utcnow(),
            )
            session.add(context_row)
        else:
            context_row.feasibility_status = feasibility.status.value
            context_row.reason = feasibility.reason
            context_row.estimated_vram_bytes = feasibility.estimated_vram_bytes
            context_row.requires_full_context_proof = feasibility.requires_full_context_proof
            context_row.evidence_json = list(feasibility.evidence)

    experiment.preflight_json = result.model_dump(mode="json")
    if result.snapshot is not None:
        store_snapshot(session, settings, row.worker_id, result.snapshot)
        experiment.worker_snapshot_revision = result.snapshot_revision

    if result.passed:
        experiment.preflight_passed = True
        experiment.error_code = None
        experiment.error_message = None
        if JobState(experiment.state) in (JobState.PREFLIGHTING, JobState.READY):
            if JobState(experiment.state) is JobState.PREFLIGHTING:
                transition_experiment(
                    session,
                    experiment,
                    JobState.READY,
                    stage=JobStage.BASELINE,
                    payload={"preflight_passed": True},
                )
            else:
                append_event(
                    session,
                    experiment.experiment_id,
                    EventType.SYSTEM_RECONCILED,
                    state=JobState(experiment.state),
                    stage=JobStage(experiment.stage),
                    payload={"event": "preflight_passed", "snapshot_revision": result.snapshot_revision},
                )
        study = session.scalar(select(StudyRow).where(StudyRow.experiment_id == experiment.experiment_id))
        if study is not None:
            reconcile_study(session, settings, study)
    else:
        if JobState(experiment.state) in (JobState.PREFLIGHTING, JobState.READY):
            transition_experiment(
                session,
                experiment,
                JobState.BLOCKED,
                stage=JobStage.PREFLIGHT,
                payload={"preflight_passed": False, "message": result.message},
            )
        experiment.error_code = result.failure_kind.value if result.failure_kind else "PREFLIGHT_FAILED"
        experiment.error_message = result.message or "worker preflight failed"


def _apply_pause(session: Session, row: WorkerCommandRow, result: PauseResult) -> None:
    if not result.accepted:
        if row.experiment_id:
            append_event(
                session,
                row.experiment_id,
                EventType.COMMAND_FAILED,
                payload={
                    "command_id": row.command_id,
                    "reason": "PAUSE_NOT_ACCEPTED",
                    "message": result.message,
                },
            )
        return
    experiment = session.get(ExperimentRow, result.experiment_id)
    if experiment is None:
        raise NotFoundError("experiment not found for pause result")
    experiment.paused = True
    if JobState(experiment.state) is not JobState.PAUSED:
        transition_experiment(session, experiment, JobState.PAUSED)


def _apply_cancel(session: Session, row: WorkerCommandRow, result: CancelResult) -> None:
    if not result.accepted:
        if row.experiment_id:
            append_event(
                session,
                row.experiment_id,
                EventType.COMMAND_FAILED,
                payload={
                    "command_id": row.command_id,
                    "reason": "CANCEL_NOT_ACCEPTED",
                    "message": result.message,
                },
            )
        return
    experiment = session.get(ExperimentRow, result.experiment_id)
    if experiment is None:
        raise NotFoundError("experiment not found for cancel result")
    if JobState(experiment.state) is not JobState.CANCELLED:
        if JobState(experiment.state) is JobState.CANCELLING:
            transition_experiment(session, experiment, JobState.CANCELLED)
        else:
            # Direct cancellation from a pre-run state.
            transition_experiment(session, experiment, JobState.CANCELLED)
    study = session.scalar(select(StudyRow).where(StudyRow.experiment_id == experiment.experiment_id))
    if study is not None:
        study.state = "failed"


def _apply_verify_recipe(session: Session, result: VerifyRecipeResult) -> None:
    recipe = session.get(RecipeRow, result.recipe_id)
    if recipe is None:
        raise NotFoundError("recipe not found for verification result")
    recipe.status = "validated" if result.verified else "revoked"


def _apply_promote(session: Session, result: PromoteResult) -> None:
    recipe = session.get(RecipeRow, result.recipe_id)
    if recipe is None:
        raise NotFoundError("recipe not found for promotion result")
    if result.promoted:
        recipe.status = "promoted"
    session.add(
        PromotionRow(
            promotion_id=f"promo_{result.recipe_id}_{utcnow().timestamp()}",
            recipe_id=result.recipe_id,
            target_slot=result.slot or "default",
            dry_run=result.dry_run,
            promoted=result.promoted,
            verified=result.promoted,
            message=result.message,
            created_at=utcnow(),
        )
    )
