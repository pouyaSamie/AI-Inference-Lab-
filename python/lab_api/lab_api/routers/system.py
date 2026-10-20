"""Health, readiness and operator-facing system status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from lab_core.version import API_VERSION, SCHEMA_VERSION
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from lab_core import TERMINAL_JOB_STATES

from ..config import Settings
from ..dependencies import get_session, get_settings
from ..orm import ExperimentRow
from ..schemas import HealthResponse, SystemStatusResponse
from ..security import Principal, require_operator
from ..services.inventory import active_worker_count
from ..services.optimizer_queue import optimizer_health

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="lab-controller",
        version=SCHEMA_VERSION,
        components={"process": "alive"},
    )


@router.get("/ready", response_model=HealthResponse)
def ready(session: Session = Depends(get_session)) -> JSONResponse:
    try:
        session.execute(text("SELECT 1"))
        components = {"database": "ok"}
        status = "ready"
        code = 200
    except Exception as exc:  # pragma: no cover - only on broken DB
        components = {"database": f"error: {type(exc).__name__}"}
        status = "not_ready"
        code = 503
    payload = HealthResponse(
        status=status,
        service="lab-controller",
        version=SCHEMA_VERSION,
        components=components,
    )
    return JSONResponse(payload.model_dump(mode="json"), status_code=code)


@router.get("/api/v1/status", response_model=SystemStatusResponse)
def status(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> SystemStatusResponse:
    terminal = [state.value for state in TERMINAL_JOB_STATES]
    active = (
        session.scalar(
            select(func.count()).select_from(ExperimentRow).where(ExperimentRow.state.not_in(terminal))
        )
        or 0
    )
    runtime = request.app.state.runtime
    warnings: list[str] = []
    health = optimizer_health(session, settings)
    if not health.online:
        warnings.append("OPTIMIZER_OFFLINE")
    if settings.execution_mode == "simulated":
        warnings.append("PHASE_1_SIMULATED_EXECUTION")
    return SystemStatusResponse(
        service=settings.service_name,
        version=SCHEMA_VERSION,
        environment=settings.environment,
        api_version=API_VERSION,
        controller_db=settings.controller_db_url.rsplit("/", 1)[-1],
        optimizer_db=settings.optimizer_db_url.rsplit("/", 1)[-1],
        optimizer=health,
        workers_online=active_worker_count(session),
        experiments_active=int(active),
        scheduler_running=bool(runtime.running),
        allow_simulation=settings.allow_simulation,
        warnings=tuple(warnings),
    )
