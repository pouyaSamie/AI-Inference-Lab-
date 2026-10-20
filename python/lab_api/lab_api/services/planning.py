"""Snapshot-only planning.

Planning never probes a binary or model. It consumes the latest cached worker
snapshot and either returns a ready immutable plan or a typed preflight
requirement with a queued SCAN command.
"""

from __future__ import annotations

from lab_core.errors import NotFoundError
from lab_core.ids import new_id
from sqlalchemy.orm import Session

from lab_adapters import registry as adapter_registry
from lab_core import (
    CommandType,
    ContextFeasibility,
    ContextLength,
    DimensionKind,
    EngineId,
    ExperimentPlan,
    ExperimentSpec,
    FeasibilityOutcome,
    ParameterDimension,
    PlanStatus,
    ScanPayload,
    SearchPolicy,
    SearchSpaceRequest,
    SearchSpaceSpec,
)

from ..config import Settings
from ..orm import WorkerCommandRow, WorkerRow
from ..schemas import PlanRequest, PlanResponse
from .commands import enqueue_command
from .inventory import latest_snapshot, snapshot_freshness, snapshot_model


def _queue_scan(session: Session, settings: Settings, worker_id: str, reason: str) -> WorkerCommandRow:
    return enqueue_command(
        session,
        settings,
        worker_id=worker_id,
        command_type=CommandType.SCAN,
        payload=ScanPayload(
            roots=tuple(settings.allowed_model_roots),
            include_engines=True,
            include_models=True,
            include_hardware=True,
            hash_models=settings.scan_hash_models,
            reason=reason,
        ),
        idempotency_key=f"scan:{worker_id}:{new_id('req')}",
    )


def build_study_search_space(
    *,
    engine_id: EngineId,
    model_architecture: str,
    model_quantization: str | None,
    objective: str,
    contexts: tuple[ContextLength, ...],
) -> SearchSpaceSpec:
    adapter = adapter_registry().get(engine_id)
    base = adapter.search_space(
        SearchSpaceRequest(
            engine_id=engine_id,
            model_architecture=model_architecture,
            model_quantization=model_quantization,
            context_tokens=int(min(contexts)),
            objective=objective,
        )
    )
    fixed = {key: value for key, value in base.fixed_parameters.items() if key != "ctx_size"}
    dimensions = tuple(
        dimension for dimension in base.dimensions if dimension.name not in {"ctx_size", "context_tokens"}
    )
    context_dimension = ParameterDimension(
        name="context_tokens",
        kind=DimensionKind.CATEGORICAL,
        choices=tuple(int(context) for context in contexts),
        default=int(contexts[0]),
        description="Selected context length; the controller removes it before execution.",
    )
    return SearchSpaceSpec(
        engine_id=base.engine_id,
        dimensions=(context_dimension, *dimensions),
        fixed_parameters=fixed,
        constraints=base.constraints,
        max_proposals=base.max_proposals,
        notes=(*base.notes, "Phase 1 controller adds context_tokens as a categorical dimension."),
    )


def build_plan(session: Session, settings: Settings, request: PlanRequest) -> PlanResponse:
    worker = session.get(WorkerRow, request.worker_id)
    if worker is None:
        raise NotFoundError("worker is not registered", details={"worker_id": request.worker_id})

    snapshot_row = latest_snapshot(session, worker.worker_id)
    fresh, stale_reasons = snapshot_freshness(settings, worker, snapshot_row)
    if not fresh:
        command = _queue_scan(
            session,
            settings,
            worker.worker_id,
            reason="plan requested with stale or absent inventory: " + ", ".join(stale_reasons),
        )
        return PlanResponse(
            status=PlanStatus.PREFLIGHT_REQUIRED,
            command_id=command.command_id,
            reason="Inventory is not fresh: " + ", ".join(stale_reasons),
            retry_after_ms=2000,
        )

    assert snapshot_row is not None
    snapshot = snapshot_model(snapshot_row)
    engine = snapshot.engine(request.engine_id.value)
    if engine is None:
        command = _queue_scan(
            session,
            settings,
            worker.worker_id,
            reason=f"engine {request.engine_id.value} was not present in the cached snapshot",
        )
        return PlanResponse(
            status=PlanStatus.PREFLIGHT_REQUIRED,
            command_id=command.command_id,
            reason=f"Engine {request.engine_id.value!r} is not present in the worker inventory.",
            retry_after_ms=2000,
        )
    model = snapshot.model(request.model_id)
    if model is None:
        command = _queue_scan(
            session,
            settings,
            worker.worker_id,
            reason=f"model {request.model_id!r} was not present in the cached snapshot",
        )
        return PlanResponse(
            status=PlanStatus.PREFLIGHT_REQUIRED,
            command_id=command.command_id,
            reason=f"Model {request.model_id!r} is not present in the worker inventory.",
            retry_after_ms=2000,
        )

    policy = request.search_policy or SearchPolicy(depth=request.search_depth)
    if policy.depth is not request.search_depth:
        policy = policy.model_copy(update={"depth": request.search_depth})

    gpu_uuids = request.gpu_uuids or tuple(gpu.uuid for gpu in snapshot.hardware.gpus)
    spec = ExperimentSpec(
        worker_id=worker.worker_id,
        engine=engine.engine,
        model=model,
        objective=request.objective,
        contexts=request.contexts,
        search_depth=request.search_depth,
        search_policy=policy,
        constraints=request.constraints,
        workload=request.workload,
        recipe_mode=request.recipe_mode,
        inventory_snapshot_digest=snapshot.discovery_digest or snapshot.compute_discovery_digest(),
        gpu_uuids=gpu_uuids,
        notes=request.notes,
    )

    warnings: list[str] = []
    if settings.execution_mode == "simulated":
        warnings.append("PHASE_1_SIMULATED_EXECUTION")
    if not model.hashes_complete():
        warnings.append("MODEL_HASHES_INCOMPLETE")
    if not snapshot.hardware.gpus:
        warnings.append("NO_GPU_INVENTORY")
    if engine.engine.executable_path is None:
        warnings.append("ENGINE_PATH_NOT_IN_SNAPSHOT")
    warnings.extend(snapshot.hardware.contamination_warnings)

    feasibility = tuple(
        ContextFeasibility(
            context=context,
            status=FeasibilityOutcome.UNKNOWN,
            reason="Context fit is proven by the worker's full-context preflight, not by cached inventory.",
            requires_full_context_proof=True,
        )
        for context in request.contexts
    )
    warnings.append("CONTEXT_FEASIBILITY_UNPROVEN")

    plan = ExperimentPlan.build(
        spec=spec,
        status=PlanStatus.READY,
        feasibility=feasibility,
        worker_snapshot_revision=snapshot.revision,
        warnings=tuple(dict.fromkeys(warnings)),
    )
    return PlanResponse(status=PlanStatus.READY, plan=plan)
