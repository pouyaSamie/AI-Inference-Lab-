"""Durable outbound worker command queue with leases and idempotency."""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from typing import Any

from lab_core.base import utcnow
from lab_core.errors import ConflictError, LeaseConflictError, NotFoundError
from lab_core.ids import new_id, sha256_hex
from sqlalchemy import select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lab_core import (
    AckDisposition,
    CommandAck,
    CommandCompletion,
    CommandFailure,
    CommandPayload,
    CommandStatus,
    CommandStatusView,
    CommandType,
    EventType,
    FailureKind,
    JobStage,
    JobState,
    WorkerCommand,
    WorkerCommandLease,
    WorkerPollResponse,
)

from ..config import Settings
from ..events import append_event
from ..orm import ExperimentRow, WorkerCommandRow, WorkerRow, as_utc
from .lifecycle import transition_experiment


def _block_failed_preflight(session: Session, row: WorkerCommandRow, code: str) -> None:
    """An unsuccessful transport outcome must not leave preflight looking active."""
    if row.command_type != CommandType.PREFLIGHT.value or not row.experiment_id:
        return
    experiment = session.get(ExperimentRow, row.experiment_id)
    if experiment is None or experiment.state not in {JobState.PREFLIGHTING.value, JobState.READY.value}:
        return
    experiment.preflight_passed = False
    experiment.error_code = code
    # Raw process/transport errors can contain paths and argv. Keep those out of
    # the operator message; the durable failure record retains diagnostic facts.
    experiment.error_message = (
        "The worker could not complete the setup check. Check the selected engine "
        "and worker, then retry preflight. No inference result was produced."
    )
    if "ExecutableTrustError" in (row.last_error or ""):
        experiment.error_message = (
            "The selected engine could not pass its executable identity check. "
            "Rescan engine builds in Settings, then retry preflight."
        )
    elif code == "PREFLIGHT_LEASE_EXPIRED":
        experiment.error_message = (
            "The worker did not finish the setup check before its command lease expired. "
            "Check worker health, then retry preflight."
        )
    transition_experiment(session, experiment, JobState.BLOCKED, stage=JobStage.PREFLIGHT)


def _hash_lease(token: str) -> str:
    return sha256_hex({"lease": token})


def _payload_dict(payload: CommandPayload) -> dict[str, Any]:
    return payload.model_dump(mode="json")


def enqueue_command(
    session: Session,
    settings: Settings,
    *,
    worker_id: str,
    command_type: CommandType,
    payload: CommandPayload,
    idempotency_key: str,
    experiment_id: str | None = None,
    candidate_id: str | None = None,
    expected_snapshot_revision: int = 0,
) -> WorkerCommandRow:
    if payload.command_type is not command_type:
        raise ValueError("command_type must match payload.command_type")
    existing = session.scalar(
        select(WorkerCommandRow).where(WorkerCommandRow.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.command_type != command_type.value or existing.payload_json != _payload_dict(payload):
            raise ConflictError(
                "command idempotency key was reused with a different command",
                details={"command_id": existing.command_id},
            )
        return existing
    worker = session.get(WorkerRow, worker_id)
    if worker is None:
        raise NotFoundError("worker is not registered")
    row = WorkerCommandRow(
        command_id=new_id("cmd"),
        worker_id=worker_id,
        command_type=command_type.value,
        payload_json=_payload_dict(payload),
        idempotency_key=idempotency_key,
        status=CommandStatus.PENDING.value,
        attempts=0,
        lease_generation=0,
        experiment_id=experiment_id,
        candidate_id=candidate_id,
        expected_snapshot_revision=expected_snapshot_revision,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(WorkerCommandRow).where(WorkerCommandRow.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        if existing.payload_json != _payload_dict(payload):
            raise ConflictError("command idempotency key raced with a different command") from exc
        return existing
    if experiment_id:
        append_event(
            session,
            experiment_id,
            EventType.COMMAND_QUEUED,
            payload={
                "command_id": row.command_id,
                "command_type": command_type.value,
                "idempotency_key": idempotency_key,
            },
        )
    return row


def expire_stale_leases(session: Session, settings: Settings) -> int:
    now = utcnow()
    rows = session.scalars(
        select(WorkerCommandRow).where(
            WorkerCommandRow.status.in_(
                [
                    CommandStatus.LEASED.value,
                    CommandStatus.ACKNOWLEDGED.value,
                    CommandStatus.RUNNING.value,
                ]
            ),
            WorkerCommandRow.lease_expires_at.is_not(None),
            WorkerCommandRow.lease_expires_at < now,
        )
    ).all()
    for row in rows:
        interactive = row.command_type in {CommandType.RUN_RECIPE.value, CommandType.RECIPE_CHAT.value}
        if interactive or row.attempts >= settings.command_max_attempts:
            row.status = CommandStatus.EXPIRED.value
            row.lease_token_hash = None
            row.lease_expires_at = None
            row.last_error = (
                "interactive request expired; retry explicitly"
                if interactive
                else "lease expired after maximum attempts"
            )
            row.completed_at = now
            if interactive:
                row.failure_json = CommandFailure(
                    kind=FailureKind.TIMEOUT,
                    message="The engine request expired. Review its status and retry explicitly.",
                    retryable=False,
                ).model_dump(mode="json")
            if row.experiment_id:
                append_event(
                    session,
                    row.experiment_id,
                    EventType.COMMAND_FAILED,
                    payload={
                        "command_id": row.command_id,
                        "command_type": row.command_type,
                        "reason": "LEASE_EXPIRED",
                    },
                )
            _block_failed_preflight(session, row, "PREFLIGHT_LEASE_EXPIRED")
        else:
            row.status = CommandStatus.PENDING.value
            row.lease_token_hash = None
            row.lease_expires_at = None
            row.last_error = "lease expired; requeued"
        row.updated_at = now
    if rows:
        session.flush()
    return len(rows)


def poll_commands(
    session: Session,
    settings: Settings,
    *,
    worker_id: str,
    max_commands: int | None = None,
) -> WorkerPollResponse:
    worker = session.get(WorkerRow, worker_id)
    if worker is None:
        raise NotFoundError("worker is not registered")
    if worker.disabled:
        raise ConflictError("worker is disabled")
    expire_stale_leases(session, settings)
    limit = min(max_commands or settings.max_command_batch, settings.max_command_batch)
    lifecycle = (CommandType.CANCEL.value, CommandType.PAUSE.value, CommandType.STOP_RECIPE.value)
    active_execution = session.scalar(
        select(WorkerCommandRow.command_id)
        .where(
            WorkerCommandRow.worker_id == worker_id,
            WorkerCommandRow.status.in_(
                [
                    CommandStatus.LEASED.value,
                    CommandStatus.ACKNOWLEDGED.value,
                    CommandStatus.RUNNING.value,
                ]
            ),
            WorkerCommandRow.command_type.not_in(lifecycle),
        )
        .limit(1)
    )
    rows = list(
        session.scalars(
            select(WorkerCommandRow)
            .where(
                WorkerCommandRow.worker_id == worker_id,
                WorkerCommandRow.status == CommandStatus.PENDING.value,
                (WorkerCommandRow.command_type.in_(lifecycle) if active_execution else true()),
            )
            .order_by(
                WorkerCommandRow.command_type.in_(lifecycle).desc(),
                WorkerCommandRow.created_at,
                WorkerCommandRow.command_id,
            )
            .limit(limit)
        )
    )
    leases: list[WorkerCommandLease] = []
    now = utcnow()
    execution_leased = bool(active_execution)
    for row in rows:
        if row.command_type not in lifecycle:
            if execution_leased:
                continue
            execution_leased = True
        token = secrets.token_urlsafe(32)
        row.status = CommandStatus.LEASED.value
        row.attempts += 1
        row.lease_generation += 1
        row.lease_token_hash = _hash_lease(token)
        row.lease_expires_at = now + timedelta(seconds=settings.worker_lease_seconds)
        row.updated_at = now
        command = WorkerCommand(
            command_id=row.command_id,
            command_type=CommandType(row.command_type),
            worker_id=row.worker_id,
            payload=row.payload_json,
            expected_snapshot_revision=row.expected_snapshot_revision,
            idempotency_key=row.idempotency_key,
            created_at=as_utc(row.created_at) or now,
        )
        leases.append(
            WorkerCommandLease(
                command=command,
                lease_token=token,
                lease_generation=row.lease_generation,
                lease_expires_at=row.lease_expires_at,
            )
        )
    worker.last_heartbeat_at = now
    worker.status = "online"
    session.commit()
    return WorkerPollResponse(
        leases=tuple(leases),
        server_time=now,
        poll_after_ms=1000 if leases else 2000,
    )


def _verify_lease(row: WorkerCommandRow, token: str, generation: int) -> None:
    if row.lease_token_hash is None or not hmac.compare_digest(row.lease_token_hash, _hash_lease(token)):
        raise LeaseConflictError("lease token is not valid for this command")
    if row.lease_generation != generation:
        raise LeaseConflictError(
            "lease generation is stale",
            details={"expected": row.lease_generation, "received": generation},
        )
    expires = as_utc(row.lease_expires_at)
    if expires is not None and expires < utcnow():
        raise LeaseConflictError("lease has expired")


def ack_command(
    session: Session,
    settings: Settings,
    *,
    worker_id: str,
    command_id: str,
    ack: CommandAck,
) -> WorkerCommandRow:
    row = session.get(WorkerCommandRow, command_id)
    if row is None or row.worker_id != worker_id:
        raise NotFoundError("command not found for this worker")
    if row.status in {
        CommandStatus.COMPLETED.value,
        CommandStatus.FAILED.value,
        CommandStatus.REJECTED.value,
        CommandStatus.EXPIRED.value,
        CommandStatus.CANCELLED.value,
    }:
        raise ConflictError("command is already terminal", details={"status": row.status})
    _verify_lease(row, ack.lease_token, ack.lease_generation)
    if ack.disposition is AckDisposition.ACCEPTED:
        row.status = CommandStatus.ACKNOWLEDGED.value
        row.ack_at = utcnow()
    else:
        row.status = CommandStatus.REJECTED.value
        row.lease_token_hash = None
        row.lease_expires_at = None
        row.completed_at = utcnow()
        row.last_error = ack.message or "worker rejected command"
        _block_failed_preflight(session, row, "PREFLIGHT_REJECTED")
        if row.experiment_id:
            append_event(
                session,
                row.experiment_id,
                EventType.COMMAND_FAILED,
                payload={"command_id": row.command_id, "reason": "WORKER_REJECTED", "message": ack.message},
            )
    row.updated_at = utcnow()
    session.commit()
    return row


def renew_command_lease(
    session: Session,
    settings: Settings,
    *,
    worker_id: str,
    command_id: str,
    lease_token: str,
    lease_generation: int,
    extend_seconds: int,
) -> WorkerCommandRow:
    row = session.get(WorkerCommandRow, command_id)
    if row is None or row.worker_id != worker_id:
        raise NotFoundError("command not found for this worker")
    if row.status in {
        CommandStatus.COMPLETED.value,
        CommandStatus.FAILED.value,
        CommandStatus.REJECTED.value,
        CommandStatus.EXPIRED.value,
        CommandStatus.CANCELLED.value,
    }:
        raise ConflictError("command is already terminal", details={"status": row.status})
    _verify_lease(row, lease_token, lease_generation)
    now = utcnow()
    extension = max(settings.worker_lease_seconds, min(extend_seconds, settings.worker_lease_max_seconds))
    row.lease_expires_at = now + timedelta(seconds=extension)
    row.updated_at = now
    session.commit()
    return row


def complete_command(
    session: Session,
    settings: Settings,
    *,
    worker_id: str,
    command_id: str,
    completion: CommandCompletion,
) -> tuple[WorkerCommandRow, bool]:
    from .execution import apply_command_completion

    row = session.get(WorkerCommandRow, command_id)
    if row is None or row.worker_id != worker_id:
        raise NotFoundError("command not found for this worker")
    if completion.worker_id != worker_id:
        raise ConflictError("completion worker_id does not match command worker")

    if row.status in {
        CommandStatus.COMPLETED.value,
        CommandStatus.FAILED.value,
        CommandStatus.REJECTED.value,
        CommandStatus.EXPIRED.value,
        CommandStatus.CANCELLED.value,
    }:
        stored = row.result_json
        submitted = completion.result.model_dump(mode="json") if completion.result else None
        submitted_failure = completion.failure.model_dump(mode="json") if completion.failure else None
        if (
            row.status == completion.outcome.value
            and stored == submitted
            and row.failure_json == submitted_failure
        ):
            return row, True
        raise ConflictError(
            "command already reached a different terminal outcome",
            details={"status": row.status, "requested_outcome": completion.outcome.value},
        )

    _verify_lease(row, completion.lease_token, completion.lease_generation)
    if completion.outcome is CommandStatus.COMPLETED:
        assert completion.result is not None
        row.result_json = completion.result.model_dump(mode="json")
        row.failure_json = None
        row.status = CommandStatus.COMPLETED.value
    else:
        assert completion.failure is not None
        row.failure_json = completion.failure.model_dump(mode="json")
        row.status = completion.outcome.value
        row.last_error = completion.failure.message
    row.lease_token_hash = None
    row.lease_expires_at = None
    row.completed_at = utcnow()
    row.updated_at = utcnow()
    session.flush()

    if row.status == CommandStatus.COMPLETED.value:
        apply_command_completion(session, settings, row, completion)
    elif row.experiment_id:
        append_event(
            session,
            row.experiment_id,
            EventType.COMMAND_FAILED,
            payload={
                "command_id": row.command_id,
                "command_type": row.command_type,
                "failure": completion.failure.model_dump(mode="json") if completion.failure else None,
            },
        )
        _block_failed_preflight(session, row, "PREFLIGHT_EXECUTION_FAILED")
    session.commit()
    return row, False


def command_status_view(row: WorkerCommandRow) -> CommandStatusView:
    result: Any = None
    failure = None
    if row.result_json:
        from lab_core.commands import CommandResult
        from pydantic import TypeAdapter

        adapter: TypeAdapter[CommandResult] = TypeAdapter(CommandResult)
        result = adapter.validate_python(row.result_json)
    if row.failure_json:
        from lab_core.commands import CommandFailure

        failure = CommandFailure.model_validate(row.failure_json)
    return CommandStatusView(
        command_id=row.command_id,
        worker_id=row.worker_id,
        command_type=CommandType(row.command_type),
        status=CommandStatus(row.status),
        attempts=row.attempts,
        lease_generation=row.lease_generation,
        created_at=as_utc(row.created_at) or utcnow(),
        ack_at=as_utc(row.ack_at),
        completed_at=as_utc(row.completed_at),
        result=result,
        failure=failure,
        experiment_id=row.experiment_id,
    )


def list_commands_for_experiment(session: Session, experiment_id: str) -> list[WorkerCommandRow]:
    return list(
        session.scalars(
            select(WorkerCommandRow)
            .where(WorkerCommandRow.experiment_id == experiment_id)
            .order_by(WorkerCommandRow.created_at)
        )
    )
