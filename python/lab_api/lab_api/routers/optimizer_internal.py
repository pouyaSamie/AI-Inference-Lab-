"""Internal authenticated endpoints used only by the supervised optimizer."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from lab_core import OptimizerCompletion, OptimizerHealth, OptimizerHeartbeat, OptimizerPollResponse

from ..config import Settings
from ..dependencies import get_session, get_settings
from ..schemas import OptimizerPollRequest, OptimizerRequestAck
from ..security import Principal, require_operator, require_optimizer
from ..services.optimizer_queue import (
    claim_optimizer_requests,
    complete_optimizer_request,
    heartbeat_optimizer,
    optimizer_health,
)

router = APIRouter(tags=["optimizer-internal"])


@router.post("/api/v1/internal/optimizer/heartbeat")
def heartbeat(
    body: OptimizerHeartbeat,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_optimizer),
) -> dict[str, Any]:
    heartbeat_optimizer(session, body)
    return {"accepted": True, "server_time": body.last_seen_at}


@router.post("/api/v1/internal/optimizer/requests/poll", response_model=OptimizerPollResponse)
def poll(
    body: OptimizerPollRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_optimizer),
) -> OptimizerPollResponse:
    return claim_optimizer_requests(
        session,
        settings,
        optimizer_id=body.optimizer_id or principal.subject,
        max_requests=body.max_requests,
    )


@router.post(
    "/api/v1/internal/optimizer/requests/{request_id}/complete",
    response_model=OptimizerRequestAck,
)
def complete(
    request_id: str,
    body: OptimizerCompletion,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_optimizer),
) -> OptimizerRequestAck:
    row, replay = complete_optimizer_request(
        session,
        settings,
        request_id=request_id,
        completion=body,
    )
    return OptimizerRequestAck(
        request_id=row.request_id,
        status=row.status,
        idempotent_replay=replay,
    )


@router.get("/api/v1/internal/optimizer/health")
def health(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> OptimizerHealth:
    return optimizer_health(session, settings)
