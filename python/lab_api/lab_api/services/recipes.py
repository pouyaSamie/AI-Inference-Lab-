"""Deployment recipe creation from validated evidence only."""

from __future__ import annotations

from lab_core.base import utcnow
from lab_core.errors import ConflictError, NotFoundError, UnsupportedCapabilityError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lab_adapters import ValidatedEvidence
from lab_adapters import registry as adapter_registry
from lab_core import (
    BenchmarkObservation,
    BinaryKind,
    CandidateSpec,
    ExperimentSpec,
    MeasurementStatus,
    ObservationStatus,
    RegisteredBinary,
)

from ..config import Settings
from ..orm import CandidateRow, ExperimentRow, ObservationRow, RecipeRow
from ..schemas import RecipeView
from .inventory import latest_snapshot, snapshot_model


def _eligible_observations(session: Session, experiment_id: str, candidate_id: str) -> list[ObservationRow]:
    rows = session.scalars(
        select(ObservationRow).where(
            ObservationRow.experiment_id == experiment_id,
            ObservationRow.candidate_id == candidate_id,
        )
    ).all()
    return list(rows)


def create_recipe(session: Session, settings: Settings, experiment_id: str, candidate_id: str) -> RecipeView:
    experiment = session.get(ExperimentRow, experiment_id)
    if experiment is None:
        raise NotFoundError("experiment not found")
    candidate_row = session.get(CandidateRow, candidate_id)
    if candidate_row is None or candidate_row.experiment_id != experiment_id:
        raise NotFoundError("candidate not found for this experiment")
    observation_rows = _eligible_observations(session, experiment_id, candidate_id)
    if not observation_rows:
        raise ConflictError("no observations exist for this candidate")
    if any(row.simulated for row in observation_rows):
        raise ConflictError(
            "simulated evidence cannot produce a validated deployment recipe",
            details={"candidate_id": candidate_id, "reason": "SIMULATED_EVIDENCE"},
        )
    observations = tuple(BenchmarkObservation.model_validate(row.payload_json) for row in observation_rows)
    if any(item.status is not ObservationStatus.COMPLETED for item in observations):
        raise ConflictError("all recipe observations must be completed")
    if any(item.measurement_status is not MeasurementStatus.MEASURED for item in observations):
        raise ConflictError("all recipe observations must be measured, not estimated or simulated")
    eligibility = [reason for item in observations for reason in item.scoring_eligibility()]
    if eligibility:
        raise ConflictError(
            "observations are not eligible for a validated recipe",
            details={"reasons": sorted(set(eligibility))},
        )
    spec = ExperimentSpec.model_validate(experiment.spec_json)
    snapshot_row = latest_snapshot(session, experiment.worker_id)
    if snapshot_row is None:
        raise ConflictError("no worker snapshot is available for recipe construction")
    snapshot = snapshot_model(snapshot_row)
    engine_manifest = snapshot.engine(spec.engine.engine_id.value)
    if engine_manifest is None:
        raise ConflictError("engine manifest is missing from the worker snapshot")
    model = snapshot.model(spec.model.model_id)
    if model is None:
        raise ConflictError("model artifact is missing from the worker snapshot")
    executable_path = engine_manifest.engine.executable_path
    if not executable_path:
        raise ConflictError("engine executable path is not present in the worker snapshot")
    binary = RegisteredBinary(
        executable_id=engine_manifest.engine.executable_id,
        engine_id=spec.engine.engine_id,
        kind=BinaryKind.SERVER,
        path=executable_path,
        sha256=engine_manifest.engine.executable_sha256,
        version=engine_manifest.engine.version,
        build=engine_manifest.engine.build,
        backend=engine_manifest.engine.backend,
    )
    adapter = adapter_registry().get(spec.engine.engine_id)
    if not hasattr(adapter, "build_deployment_recipe"):
        raise UnsupportedCapabilityError("adapter does not implement deployment recipes")
    candidate = CandidateSpec.model_validate(candidate_row.payload_json)
    evidence = ValidatedEvidence(
        validated=True,
        experiment_id=experiment_id,
        objective=spec.objective,
        candidate_id=candidate_id,
        observations=observations,
        quality_gates=tuple(gate for item in observations for gate in item.quality_gates),
        metrics_ref=f"experiments/{experiment_id}/candidates/{candidate_id}/metrics.json",
        notes=("Controller-validated measured evidence.",),
    )
    recipe = adapter.build_deployment_recipe(
        candidate,
        evidence,
        binary=binary,
        model=model,
        hardware=snapshot.hardware,
    )
    existing = session.get(RecipeRow, recipe.id)
    if existing is not None:
        return _recipe_view(existing)
    row = RecipeRow(
        recipe_id=recipe.id,
        experiment_id=experiment_id,
        candidate_id=candidate_id,
        status=recipe.status.value,
        digest=recipe.recipe_digest(),
        manifest_json=recipe.model_dump(mode="json", by_alias=True),
        created_at=utcnow(),
    )
    session.add(row)
    session.commit()
    return _recipe_view(row)


def _recipe_view(row: RecipeRow) -> RecipeView:
    return RecipeView(
        recipe_id=row.recipe_id,
        experiment_id=row.experiment_id,
        candidate_id=row.candidate_id,
        status=row.status,
        recipe_digest=row.digest,
        recipe=row.manifest_json,
        created_at=row.created_at,
    )


def list_recipes(session: Session, experiment_id: str | None = None) -> tuple[RecipeView, ...]:
    query = select(RecipeRow).order_by(RecipeRow.created_at.desc())
    if experiment_id:
        query = query.where(RecipeRow.experiment_id == experiment_id)
    return tuple(_recipe_view(row) for row in session.scalars(query))


def get_recipe(session: Session, recipe_id: str) -> RecipeView:
    row = session.get(RecipeRow, recipe_id)
    if row is None:
        raise NotFoundError("recipe not found")
    return _recipe_view(row)
