"""Experiment planning, lifecycle, results and event-stream endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from lab_core import PlanStatus

from ..config import Settings
from ..dependencies import get_session, get_settings
from ..events import event_to_model, events_after, replay_floor
from ..idempotency import canonical_request_hash, require_key
from ..schemas import (
    CreateExperimentRequest,
    EventPage,
    ExperimentListResponse,
    ExperimentResultsResponse,
    ExperimentView,
    PlanRequest,
    PlanResponse,
)
from ..security import Principal, require_operator, require_operator_stateless
from ..services.commands import command_status_view, list_commands_for_experiment
from ..services.experiments import (
    cancel_experiment,
    create_experiment,
    experiment_results,
    experiment_view,
    get_experiment,
    list_experiments,
    pause_experiment,
    resume_experiment,
    retry_preflight,
)
from ..services.planning import build_plan
from ..services.sse import event_stream

router = APIRouter(tags=["experiments"])


@router.post("/api/v1/experiments/plan", response_model=PlanResponse)
def plan_experiment(
    body: PlanRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> PlanResponse | JSONResponse:
    response = build_plan(session, settings, body)
    session.commit()
    if response.status is PlanStatus.READY:
        return response
    return JSONResponse(response.model_dump(mode="json"), status_code=202)


@router.post(
    "/api/v1/experiments",
    response_model=ExperimentView,
    status_code=201,
)
def create(
    body: CreateExperimentRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> ExperimentView:
    key = require_key(idempotency_key)
    view, replay = create_experiment(
        session,
        settings,
        body,
        idempotency_key=key,
        request_hash=canonical_request_hash(body),
    )
    response.status_code = 200 if replay else 201
    if replay:
        response.headers["Idempotent-Replayed"] = "true"
    return view


@router.get("/api/v1/experiments", response_model=ExperimentListResponse)
def list_all(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ExperimentListResponse:
    return list_experiments(session, limit=limit, offset=offset)


@router.get("/api/v1/experiments/{experiment_id}", response_model=ExperimentView)
def get_one(
    experiment_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ExperimentView:
    return experiment_view(session, get_experiment(session, experiment_id))


@router.post("/api/v1/experiments/{experiment_id}/pause", response_model=ExperimentView)
def pause(
    experiment_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> ExperimentView:
    return pause_experiment(session, settings, experiment_id)


@router.post("/api/v1/experiments/{experiment_id}/resume", response_model=ExperimentView)
def resume(
    experiment_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ExperimentView:
    return resume_experiment(session, experiment_id)


@router.post("/api/v1/experiments/{experiment_id}/cancel", response_model=ExperimentView)
def cancel(
    experiment_id: str,
    reason: str | None = Query(default=None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> ExperimentView:
    return cancel_experiment(session, settings, experiment_id, reason)


@router.post("/api/v1/experiments/{experiment_id}/preflight/retry", response_model=ExperimentView)
def retry(
    experiment_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> ExperimentView:
    return retry_preflight(session, settings, experiment_id)


@router.get("/api/v1/experiments/{experiment_id}/results", response_model=ExperimentResultsResponse)
def results(
    experiment_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ExperimentResultsResponse:
    return experiment_results(session, experiment_id)


@router.get("/api/v1/experiments/{experiment_id}/commands")
def commands(
    experiment_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> list[dict[str, Any]]:
    get_experiment(session, experiment_id)
    return [
        command_status_view(row).model_dump(mode="json")
        for row in list_commands_for_experiment(session, experiment_id)
    ]


@router.get("/api/v1/experiments/{experiment_id}/events/page", response_model=EventPage)
def events_page(
    experiment_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=2000),
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> EventPage:
    get_experiment(session, experiment_id)
    floor = replay_floor(session, experiment_id)
    effective_after = max(after, floor)
    rows = events_after(session, experiment_id, after_sequence=effective_after, limit=limit + 1)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return EventPage(
        events=tuple(event_to_model(row) for row in rows),
        last_event_id=rows[-1].sequence if rows else effective_after,
        replay_floor=floor,
        has_more=has_more,
    )


@router.get("/api/v1/experiments/{experiment_id}/events")
async def events(
    experiment_id: str,
    request: Request,
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    last_event_id: int = Query(default=0, ge=0),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator_stateless),
) -> StreamingResponse:
    with request.app.state.session_factory() as session:
        get_experiment(session, experiment_id)
    last = last_event_id
    if last_event_id_header:
        try:
            last = max(last, int(last_event_id_header))
        except ValueError:
            last = last_event_id
    factory = request.app.state.session_factory
    stream = event_stream(request, settings, factory, experiment_id, last_event_id=last)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
