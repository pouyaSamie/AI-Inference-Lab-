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
    CandidateRole,
    CandidateSpec,
    ExperimentSpec,
    FinalizationStatus,
    MeasurementStatus,
    ObservationStatus,
    RecipeMode,
    RecipeStatus,
    RegisteredBinary,
    finalize_experiment,
)

from ..config import Settings
from ..orm import CandidateRow, ExperimentRow, ObservationRow, RecipeRow, as_utc
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
    candidate = CandidateSpec.model_validate(candidate_row.payload_json)
    if candidate.role is CandidateRole.BASELINE:
        raise ConflictError(
            "the paired baseline is a reference, not an optimized deployment recipe",
            details={"candidate_id": candidate_id, "reason": "BASELINE_REFERENCE"},
        )
    candidate_rows = session.scalars(
        select(CandidateRow).where(CandidateRow.experiment_id == experiment_id)
    ).all()
    all_observation_rows = session.scalars(
        select(ObservationRow).where(ObservationRow.experiment_id == experiment_id)
    ).all()
    finalization = finalize_experiment(
        experiment_id=experiment_id,
        spec=spec,
        candidates=tuple(CandidateSpec.model_validate(row.payload_json) for row in candidate_rows),
        observations=tuple(
            BenchmarkObservation.model_validate(row.payload_json) for row in all_observation_rows
        ),
    )
    if finalization.simulated:
        raise ConflictError(
            "simulated evidence cannot produce a validated deployment recipe",
            details={"candidate_id": candidate_id, "reason": "SIMULATED_EVIDENCE"},
        )
    evaluation = next(
        (
            item
            for ranking in finalization.per_context
            if int(ranking.context) == int(candidate.context)
            for item in ranking.evaluations
            if item.candidate_id == candidate_id
        ),
        None,
    )
    if spec.recipe_mode is RecipeMode.CROSS_CONTEXT:
        cross = next(
            (item for item in finalization.cross_context if item.candidate_id == candidate_id),
            None,
        )
        if cross is None or not cross.qualified:
            raise ConflictError(
                "candidate has not passed cross-context qualification",
                details={
                    "candidate_id": candidate_id,
                    "reasons": list(cross.reasons) if cross else ["NO_CROSS_CONTEXT_EVALUATION"],
                    "classification": finalization.classification.value,
                },
            )
    elif (
        evaluation is None
        or not evaluation.qualified
        or evaluation.status is not FinalizationStatus.VALIDATED
    ):
        raise ConflictError(
            "candidate has not passed the pre-declared qualification gate",
            details={
                "candidate_id": candidate_id,
                "classification": finalization.classification.value,
                "reasons": list(evaluation.reasons) if evaluation else ["NO_CONTEXT_EVALUATION"],
                "score": evaluation.score if evaluation else None,
                "interval": (
                    evaluation.interval.model_dump(mode="json")
                    if evaluation and evaluation.interval
                    else None
                ),
            },
        )
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
    qualification_ref = f"experiments/{experiment_id}/candidates/{candidate_id}/qualification.json"
    evidence = ValidatedEvidence(
        validated=True,
        experiment_id=experiment_id,
        objective=spec.objective,
        candidate_id=candidate_id,
        observations=observations,
        quality_gates=tuple(gate for item in observations for gate in item.quality_gates),
        confidence_ref=qualification_ref,
        metrics_ref=f"experiments/{experiment_id}/candidates/{candidate_id}/metrics.json",
        notes=(
            "Controller-validated measured evidence.",
            "Paired baseline qualification passed at the declared confidence threshold.",
        ),
    )
    recipe = adapter.build_deployment_recipe(
        candidate,
        evidence,
        binary=binary,
        model=model,
        hardware=snapshot.hardware,
    )
    qualification_note = "Qualification gate passed for this candidate and context."
    if evaluation is not None and evaluation.interval is not None:
        qualification_note = (
            f"Objective ratio {evaluation.score:.4f}; 95% paired interval "
            f"[{evaluation.interval.lower:.4f}, {evaluation.interval.upper:.4f}]."
        )
    recipe = recipe.model_copy(
        update={
            "status": RecipeStatus.VALIDATED,
            "notes": (*recipe.notes, qualification_note),
        }
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
        created_at=as_utc(row.created_at),
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
