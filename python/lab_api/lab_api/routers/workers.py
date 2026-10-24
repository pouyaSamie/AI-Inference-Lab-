"""Worker enrollment, inventory, heartbeat and command transport endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from lab_core.base import Identifier, utcnow
from lab_core.errors import AuthorizationError, NotFoundError
from sqlalchemy.orm import Session

from lab_core import CommandAck, CommandCompletion, CommandStatusView, WorkerPollResponse, WorkerSnapshot

from ..config import Settings
from ..dependencies import get_session, get_settings
from ..orm import ExperimentRow, WorkerCommandRow, WorkerRow
from ..schemas import (
    AckResponse,
    CompletionResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    LeaseRenewRequest,
    LeaseRenewResponse,
    PollRequest,
    WorkerListResponse,
    WorkerRegistrationRequest,
    WorkerRegistrationResponse,
    WorkerSnapshotRequest,
    WorkerSnapshotResponse,
    WorkerView,
)
from ..security import Principal, require_enrollment, require_operator, require_worker
from ..services.commands import (
    ack_command,
    command_status_view,
    complete_command,
    poll_commands,
    renew_command_lease,
)
from ..services.inventory import (
    heartbeat,
    latest_snapshot,
    list_worker_summaries,
    register_worker,
    snapshot_model,
    store_snapshot,
    worker_summary,
)

router = APIRouter(tags=["workers"])


def _assert_worker(principal: Principal, worker_id: str) -> None:
    if principal.worker_id != worker_id:
        raise AuthorizationError("worker credential does not match the requested worker")


@router.post(
    "/api/v1/workers/register",
    response_model=WorkerRegistrationResponse,
    status_code=201,
    dependencies=[Depends(require_enrollment)],
)
def register(
    body: WorkerRegistrationRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> WorkerRegistrationResponse:
    row, token = register_worker(session, settings, body.worker, body.hardware)
    session.commit()
    return WorkerRegistrationResponse(
        worker=body.worker,
        token=token,
        token_prefix=row.token_prefix,
        snapshot_revision=row.snapshot_revision,
    )


@router.get("/api/v1/workers", response_model=WorkerListResponse)
def list_workers(
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> WorkerListResponse:
    summaries = list_worker_summaries(session)
    views = tuple(
        WorkerView(
            worker_id=item.worker_id,
            name=item.name,
            status=item.status,
            protocol_version=item.protocol_version,
            last_heartbeat_at=item.last_heartbeat_at,
            snapshot_revision=item.snapshot_revision or 0,
            snapshot_created_at=item.snapshot_created_at,
            gpus=tuple(gpu.model_dump(mode="json") for gpu in item.gpus),
            warnings=item.warnings,
        )
        for item in summaries
    )
    return WorkerListResponse(workers=views, total=len(views))


@router.get("/api/v1/workers/{worker_id}", response_model=WorkerView)
def get_worker(
    worker_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> WorkerView:
    row = session.get(WorkerRow, worker_id)
    if row is None:
        raise NotFoundError("worker not found")
    item = worker_summary(session, row)
    return WorkerView(
        worker_id=item.worker_id,
        name=item.name,
        status=item.status,
        protocol_version=item.protocol_version,
        last_heartbeat_at=item.last_heartbeat_at,
        snapshot_revision=item.snapshot_revision or 0,
        snapshot_created_at=item.snapshot_created_at,
        gpus=tuple(gpu.model_dump(mode="json") for gpu in item.gpus),
        warnings=item.warnings,
    )


@router.get("/api/v1/workers/{worker_id}/snapshot", response_model=WorkerSnapshot)
def get_worker_snapshot(
    worker_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> WorkerSnapshot:
    """Return the latest cached worker snapshot without contacting the worker."""
    if session.get(WorkerRow, worker_id) is None:
        raise NotFoundError("worker not found")
    row = latest_snapshot(session, worker_id)
    if row is None:
        raise NotFoundError("worker has no cached snapshot")
    return snapshot_model(row)


@router.post("/api/v1/workers/{worker_id}/snapshot", response_model=WorkerSnapshotResponse)
def upload_snapshot(
    worker_id: str,
    body: WorkerSnapshotRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_worker),
) -> WorkerSnapshotResponse:
    _assert_worker(principal, worker_id)
    row = store_snapshot(session, settings, worker_id, body.snapshot)
    session.commit()
    return WorkerSnapshotResponse(
        accepted=True,
        snapshot_id=row.snapshot_id,
        revision=row.revision,
        discovery_digest=row.discovery_digest,
    )


@router.post("/api/v1/workers/{worker_id}/heartbeat", response_model=HeartbeatResponse)
def worker_heartbeat(
    worker_id: str,
    body: HeartbeatRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_worker),
) -> HeartbeatResponse:
    _assert_worker(principal, worker_id)
    row = heartbeat(session, settings, worker_id, body.health, snapshot_revision=body.snapshot_revision)
    session.commit()
    return HeartbeatResponse(
        worker_id=worker_id,
        status=row.status,
        server_time=utcnow(),
        next_heartbeat_after_ms=max(1000, settings.worker_offline_after_seconds * 500),
    )


@router.post("/api/v1/workers/{worker_id}/commands/poll", response_model=WorkerPollResponse)
def poll(
    worker_id: str,
    body: PollRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_worker),
) -> WorkerPollResponse:
    _assert_worker(principal, worker_id)
    return poll_commands(session, settings, worker_id=worker_id, max_commands=body.max_commands)


@router.post(
    "/api/v1/workers/{worker_id}/commands/{command_id}/ack",
    response_model=AckResponse,
)
def ack(
    worker_id: str,
    command_id: str,
    body: CommandAck,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_worker),
) -> AckResponse:
    _assert_worker(principal, worker_id)
    row = ack_command(session, settings, worker_id=worker_id, command_id=command_id, ack=body)
    return AckResponse(command_id=row.command_id, status=row.status, lease_generation=row.lease_generation)


@router.post(
    "/api/v1/workers/{worker_id}/commands/{command_id}/renew",
    response_model=LeaseRenewResponse,
)
def renew(
    worker_id: str,
    command_id: str,
    body: LeaseRenewRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_worker),
) -> LeaseRenewResponse:
    _assert_worker(principal, worker_id)
    row = renew_command_lease(
        session,
        settings,
        worker_id=worker_id,
        command_id=command_id,
        lease_token=body.lease_token,
        lease_generation=body.lease_generation,
        extend_seconds=body.extend_seconds,
    )
    assert row.lease_expires_at is not None
    return LeaseRenewResponse(
        command_id=row.command_id,
        lease_generation=row.lease_generation,
        lease_expires_at=row.lease_expires_at,
        server_time=utcnow(),
    )


@router.post(
    "/api/v1/workers/{worker_id}/commands/{command_id}/complete",
    response_model=CompletionResponse,
)
def complete(
    worker_id: str,
    command_id: str,
    body: CommandCompletion,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_worker),
) -> CompletionResponse:
    _assert_worker(principal, worker_id)
    row, replay = complete_command(
        session,
        settings,
        worker_id=worker_id,
        command_id=command_id,
        completion=body,
    )
    state = None
    if row.experiment_id:
        experiment = session.get(ExperimentRow, row.experiment_id)
        state = experiment.state if experiment else None
    return CompletionResponse(
        command_id=row.command_id,
        status=row.status,
        idempotent_replay=replay,
        experiment_state=state,
    )


@router.get("/api/v1/workers/{worker_id}/commands", response_model=list[CommandStatusView])
def list_worker_commands(
    worker_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> list[dict[str, Any]]:
    rows = (
        session.query(WorkerCommandRow)
        .filter(WorkerCommandRow.worker_id == worker_id)
        .order_by(WorkerCommandRow.created_at)
        .all()
    )
    return [command_status_view(row).model_dump(mode="json") for row in rows]


@router.post("/api/v1/workers/{worker_id}/verify-models", response_model=CommandStatusView)
def verify_models(
    worker_id: str,
    model_id: Identifier | None = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> CommandStatusView:
    from ..services.planning import _queue_scan

    if session.get(WorkerRow, worker_id) is None:
        raise NotFoundError("worker not found")
    command = _queue_scan(
        session, settings, worker_id, "Verify imported model files", model_id=model_id, verify=True
    )
    session.commit()
    return command_status_view(command)
