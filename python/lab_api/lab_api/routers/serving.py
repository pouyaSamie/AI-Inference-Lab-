"""Explicit local recipe sessions, executed only by outbound worker commands."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Header
from lab_core.errors import ConflictError, NotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lab_core import (
    TERMINAL_JOB_STATES,
    CandidateSpec,
    CommandStatusView,
    CommandType,
    ExperimentSpec,
    RecipeChatPayload,
    RecipeChatRequest,
    RunRecipePayload,
    ServingSession,
    StopRecipePayload,
    stable_id,
    utcnow,
)

from ..config import Settings
from ..dependencies import get_session, get_settings
from ..idempotency import require_key
from ..orm import CandidateRow, ExperimentRow, RecipeRow, WorkerCommandRow, WorkerRow, as_utc
from ..security import Principal, require_operator
from ..services.commands import command_status_view, enqueue_command
from ..services.inventory import latest_snapshot, snapshot_model

router = APIRouter(tags=["serving"])


def _worker(session: Session, settings: Settings, worker_id: str) -> WorkerRow:
    worker = session.get(WorkerRow, worker_id)
    seen = as_utc(worker.last_heartbeat_at) if worker else None
    if (
        worker is None
        or worker.disabled
        or seen is None
        or seen < utcnow() - timedelta(seconds=settings.worker_offline_after_seconds)
    ):
        raise ConflictError("The worker is offline. Start the local lab and retry.")
    return worker


@router.get("/api/v1/serving/{worker_id}", response_model=ServingSession | None)
def status(
    worker_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> ServingSession | None:
    worker = _worker(session, settings, worker_id)
    return ServingSession.model_validate(worker.serving_json) if worker.serving_json else None


@router.post("/api/v1/recipes/{recipe_id}/run", response_model=CommandStatusView)
def run(
    recipe_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> CommandStatusView:
    key = require_key(idempotency_key)
    if settings.execution_mode != "real":
        raise ConflictError("The simulated lab cannot launch an engine from a recipe.")
    row = session.get(RecipeRow, recipe_id)
    if row is None:
        raise NotFoundError("recipe not found")
    if row.status != "validated":
        raise ConflictError("Only a validated recipe can start an engine.")
    previous = session.scalar(
        select(WorkerCommandRow).where(WorkerCommandRow.idempotency_key == f"run-recipe:{recipe_id}:{key}")
    )
    if previous is not None:
        return command_status_view(previous)
    candidate_row = session.get(CandidateRow, row.candidate_id)
    if candidate_row is None:
        raise ConflictError("The recipe's original candidate is missing.")
    candidate = CandidateSpec.model_validate(candidate_row.payload_json)
    experiment = session.get(ExperimentRow, row.experiment_id)
    if experiment is None:
        raise ConflictError("The recipe's original experiment is missing.")
    original_model = ExperimentSpec.model_validate(experiment.spec_json).model
    worker = _worker(session, settings, candidate.worker_id)
    if "recipe-serving" not in worker.roles:
        raise ConflictError("This worker does not support recipe serving. Upgrade the worker first.")
    if worker.serving_json and worker.serving_json.get("state") in {"starting", "ready"}:
        raise ConflictError("Stop the current recipe session before starting another.")
    active = session.scalar(
        select(ExperimentRow.experiment_id)
        .where(
            ExperimentRow.worker_id == candidate.worker_id,
            ExperimentRow.state.not_in([item.value for item in TERMINAL_JOB_STATES]),
        )
        .limit(1)
    )
    if active:
        raise ConflictError("Finish or cancel the current benchmark before running a recipe.")
    snapshot_row = latest_snapshot(session, candidate.worker_id)
    model = snapshot_model(snapshot_row).model(row.manifest_json["model"]["id"]) if snapshot_row else None
    if model is None or not model.hashes_complete() or model.artifact_digest != candidate.model_digest:
        raise ConflictError("The model identity changed or is unverified. Rescan and verify it first.")
    notes = row.manifest_json.get("notes", [])
    profile_hash = next((s.split("=", 1)[1] for s in notes if s.startswith("profile_sha256=")), None)
    command = enqueue_command(
        session,
        settings,
        worker_id=candidate.worker_id,
        command_type=CommandType.RUN_RECIPE,
        payload=RunRecipePayload(
            session_id=stable_id("serve", recipe_id, key),
            recipe_id=recipe_id,
            recipe_digest=row.digest,
            candidate=candidate,
            model=original_model,
            gpu_uuid=row.manifest_json["hardware"]["gpu_uuid"],
            profile_sha256=profile_hash,
        ),
        idempotency_key=f"run-recipe:{recipe_id}:{key}",
    )
    session.commit()
    return command_status_view(command)


@router.post("/api/v1/serving/{worker_id}/{session_id}/stop", response_model=CommandStatusView)
def stop(
    worker_id: str,
    session_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> CommandStatusView:
    _worker(session, settings, worker_id)
    command = enqueue_command(
        session,
        settings,
        worker_id=worker_id,
        command_type=CommandType.STOP_RECIPE,
        payload=StopRecipePayload(session_id=session_id),
        idempotency_key=f"stop-recipe:{session_id}",
    )
    session.commit()
    return command_status_view(command)


@router.post("/api/v1/serving/{worker_id}/chat", response_model=CommandStatusView)
def chat(
    worker_id: str,
    body: RecipeChatRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> CommandStatusView:
    key = require_key(idempotency_key)
    worker = _worker(session, settings, worker_id)
    current = worker.serving_json
    if current.get("state") != "ready" or current.get("session_id") != body.session_id:
        raise ConflictError("The selected engine session is not ready. Start the recipe first.")
    command = enqueue_command(
        session,
        settings,
        worker_id=worker_id,
        command_type=CommandType.RECIPE_CHAT,
        payload=RecipeChatPayload(**body.model_dump()),
        idempotency_key=f"recipe-chat:{key}",
    )
    session.commit()
    return command_status_view(command)
