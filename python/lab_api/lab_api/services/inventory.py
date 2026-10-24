"""Worker enrollment, inventory snapshots and freshness rules."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from lab_core.errors import ConflictError, NotFoundError, ValidationFailure
from lab_core.ids import new_id
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lab_core import (
    EngineCapabilityManifest,
    EngineId,
    HardwareSnapshot,
    ModelArtifact,
    WorkerHealth,
    WorkerIdentity,
    WorkerSnapshot,
    WorkerSummary,
)

from ..config import Settings
from ..orm import SystemEventRow, WorkerRow, WorkerSnapshotRow, as_utc, utcnow
from ..security import hash_worker_token, new_worker_token, token_prefix


def _system_event(session: Session, event_type: str, payload: dict[str, Any]) -> None:
    session.add(
        SystemEventRow(
            event_id=new_id("sysev"),
            type=event_type,
            payload_json=payload,
            created_at=utcnow(),
        )
    )


def register_worker(
    session: Session,
    settings: Settings,
    identity: WorkerIdentity,
    hardware: HardwareSnapshot,
) -> tuple[WorkerRow, str]:
    existing = session.get(WorkerRow, identity.worker_id)
    if existing is not None:
        raise ConflictError(
            "worker_id is already registered",
            details={"worker_id": identity.worker_id},
            recovery_hint="Reuse the existing worker credential or enroll with a new worker_id.",
        )

    token = new_worker_token()
    now = utcnow()
    row = WorkerRow(
        worker_id=identity.worker_id,
        name=identity.name,
        version=identity.version,
        protocol_version=identity.protocol_version,
        platform=identity.platform,
        roles=list(identity.roles),
        enrolled_at=as_utc(identity.enrolled_at) or now,
        last_heartbeat_at=now,
        status="online",
        snapshot_revision=0,
        token_prefix=token_prefix(token),
        token_sha256=hash_worker_token(settings.worker_token_pepper.get_secret_value(), token),
        disabled=False,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    _system_event(
        session,
        "worker.registered",
        {
            "worker_id": identity.worker_id,
            "name": identity.name,
            "hardware_digest": hardware.digest(),
        },
    )
    try:
        session.flush()
    except IntegrityError as exc:
        raise ConflictError("worker_id is already registered") from exc
    return row, token


def latest_snapshot(session: Session, worker_id: str) -> WorkerSnapshotRow | None:
    return session.scalar(
        select(WorkerSnapshotRow)
        .where(WorkerSnapshotRow.worker_id == worker_id)
        .order_by(WorkerSnapshotRow.revision.desc())
        .limit(1)
    )


def snapshot_model(row: WorkerSnapshotRow) -> WorkerSnapshot:
    return WorkerSnapshot.model_validate(row.payload_json)


def store_snapshot(
    session: Session, settings: Settings, worker_id: str, snapshot: WorkerSnapshot
) -> WorkerSnapshotRow:
    if snapshot.worker_id != worker_id:
        raise ValidationFailure("snapshot worker_id does not match the authenticated worker")

    existing = session.scalar(
        select(WorkerSnapshotRow).where(WorkerSnapshotRow.snapshot_id == snapshot.snapshot_id)
    )
    if existing is not None:
        if existing.worker_id != worker_id:
            raise ConflictError("snapshot_id belongs to another worker")
        return existing

    latest = latest_snapshot(session, worker_id)
    current_revision = latest.revision if latest else 0
    if snapshot.revision <= current_revision:
        raise ConflictError(
            "snapshot revision must increase monotonically",
            details={"current_revision": current_revision, "received_revision": snapshot.revision},
        )

    row = WorkerSnapshotRow(
        snapshot_id=snapshot.snapshot_id,
        worker_id=worker_id,
        revision=snapshot.revision,
        created_at=as_utc(snapshot.created_at) or utcnow(),
        discovery_digest=snapshot.discovery_digest or snapshot.compute_discovery_digest(),
        payload_json=snapshot.model_dump(mode="json"),
        hardware_json=snapshot.hardware.model_dump(mode="json"),
        engines_json=[item.model_dump(mode="json") for item in snapshot.engines],
        models_json=[item.model_dump(mode="json") for item in snapshot.models],
        health_json=snapshot.health.model_dump(mode="json"),
    )
    session.add(row)

    worker = session.get(WorkerRow, worker_id)
    if worker is None:
        raise NotFoundError("worker is not registered")
    worker.snapshot_revision = snapshot.revision
    worker.last_heartbeat_at = utcnow()
    worker.status = "online"
    worker.updated_at = utcnow()
    _system_event(
        session,
        "worker.snapshot",
        {
            "worker_id": worker_id,
            "snapshot_id": snapshot.snapshot_id,
            "revision": snapshot.revision,
            "discovery_digest": row.discovery_digest,
            "engines": [item.engine.engine_id.value for item in snapshot.engines],
            "models": [item.model_id for item in snapshot.models],
        },
    )
    try:
        session.flush()
    except IntegrityError as exc:
        raise ConflictError("snapshot revision was committed concurrently; retry") from exc
    return row


def heartbeat(
    session: Session,
    settings: Settings,
    worker_id: str,
    health: WorkerHealth,
    *,
    snapshot_revision: int | None = None,
) -> WorkerRow:
    worker = session.get(WorkerRow, worker_id)
    if worker is None:
        raise NotFoundError("worker is not registered")
    if worker.disabled:
        raise ConflictError("worker is disabled", details={"worker_id": worker_id})
    if snapshot_revision is not None and snapshot_revision > worker.snapshot_revision:
        raise ValidationFailure("heartbeat cannot advance the snapshot revision; upload a snapshot instead")
    worker.serving_json = health.serving.model_dump(mode="json") if health.serving else {}
    worker.last_heartbeat_at = utcnow()
    worker.status = "online"
    worker.updated_at = utcnow()
    session.flush()
    return worker


def snapshot_freshness(
    settings: Settings,
    worker: WorkerRow,
    snapshot: WorkerSnapshotRow | None,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    now = utcnow()
    if worker.disabled:
        reasons.append("WORKER_DISABLED")
    heartbeat_at = as_utc(worker.last_heartbeat_at)
    if heartbeat_at is None:
        reasons.append("NO_WORKER_HEARTBEAT")
    elif now - heartbeat_at > timedelta(seconds=settings.worker_offline_after_seconds):
        reasons.append("WORKER_OFFLINE")
    if snapshot is None:
        reasons.append("NO_SNAPSHOT")
    else:
        created = as_utc(snapshot.created_at)
        if created is None or now - created > timedelta(seconds=settings.snapshot_max_age_seconds):
            reasons.append("SNAPSHOT_STALE")
        if snapshot.revision != worker.snapshot_revision:
            reasons.append("SNAPSHOT_REVISION_MISMATCH")
    return not reasons, tuple(reasons)


def worker_summary(session: Session, worker: WorkerRow) -> WorkerSummary:
    snapshot = latest_snapshot(session, worker.worker_id)
    gpus: tuple[Any, ...] = ()
    warnings: list[str] = []
    if snapshot is not None:
        model = snapshot_model(snapshot)
        gpus = model.hardware.gpus
        warnings.extend(model.hardware.contamination_warnings)
    return WorkerSummary(
        worker_id=worker.worker_id,
        name=worker.name,
        status=worker.status,
        protocol_version=worker.protocol_version,
        last_heartbeat_at=as_utc(worker.last_heartbeat_at),
        snapshot_revision=worker.snapshot_revision or None,
        snapshot_created_at=as_utc(snapshot.created_at) if snapshot else None,
        gpus=gpus,
        warnings=tuple(warnings),
    )


def list_worker_summaries(session: Session) -> list[WorkerSummary]:
    rows = session.scalars(select(WorkerRow).order_by(WorkerRow.name, WorkerRow.worker_id)).all()
    return [worker_summary(session, row) for row in rows]


def find_engine(snapshot: WorkerSnapshot, engine_id: EngineId) -> EngineCapabilityManifest | None:
    return snapshot.engine(engine_id.value)


def find_model(snapshot: WorkerSnapshot, model_id: str) -> ModelArtifact | None:
    return snapshot.model(model_id)


def mark_workers_offline(session: Session, settings: Settings) -> int:
    threshold = utcnow() - timedelta(seconds=settings.worker_offline_after_seconds)
    rows = session.scalars(
        select(WorkerRow).where(
            WorkerRow.status == "online",
            WorkerRow.last_heartbeat_at.is_not(None),
            WorkerRow.last_heartbeat_at < threshold,
        )
    ).all()
    for row in rows:
        row.status = "offline"
        row.updated_at = utcnow()
    if rows:
        session.flush()
    return len(rows)


def active_worker_count(session: Session) -> int:
    return int(
        session.scalar(select(func.count()).select_from(WorkerRow).where(WorkerRow.status == "online")) or 0
    )
