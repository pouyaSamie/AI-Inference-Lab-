"""SQLAlchemy 2.x persistence model for the controller database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class WorkerRow(Base):
    __tablename__ = "workers"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(64))
    protocol_version: Mapped[str] = mapped_column(String(32))
    platform: Mapped[str] = mapped_column(String(200))
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="online")
    snapshot_revision: Mapped[int] = mapped_column(Integer, default=0)
    token_prefix: Mapped[str] = mapped_column(String(16))
    token_sha256: Mapped[str] = mapped_column(String(64))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkerSnapshotRow(Base):
    __tablename__ = "worker_snapshots"
    __table_args__ = (UniqueConstraint("worker_id", "revision", name="uq_worker_snapshots_worker_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(String(128), unique=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    discovery_digest: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    hardware_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    engines_json: Mapped[list[Any]] = mapped_column(JSON)
    models_json: Mapped[list[Any]] = mapped_column(JSON)
    health_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class GpuLeaseRow(Base):
    __tablename__ = "gpu_leases"
    __table_args__ = (
        Index(
            "uq_gpu_leases_active_gpu",
            "gpu_uuid",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    lease_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id", ondelete="CASCADE"))
    gpu_uuid: Mapped[str] = mapped_column(String(128))
    command_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExperimentRow(Base):
    __tablename__ = "experiments"

    experiment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"))
    engine_id: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), default="queued")
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    spec_digest: Mapped[str] = mapped_column(String(64))
    plan_digest: Mapped[str] = mapped_column(String(64))
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    inventory_snapshot_digest: Mapped[str] = mapped_column(String(64))
    worker_snapshot_revision: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    preflight_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    preflight_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExperimentContextRow(Base):
    __tablename__ = "experiment_contexts"
    __table_args__ = (
        UniqueConstraint("experiment_id", "context_tokens", name="uq_experiment_contexts_context"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.experiment_id", ondelete="CASCADE"))
    context_tokens: Mapped[int] = mapped_column(Integer)
    feasibility_status: Mapped[str] = mapped_column(String(32), default="unknown")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_vram_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_full_context_proof: Mapped[bool] = mapped_column(Boolean, default=True)
    evidence_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudyRow(Base):
    __tablename__ = "studies"

    study_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.experiment_id", ondelete="CASCADE"), unique=True
    )
    engine_id: Mapped[str] = mapped_column(String(32))
    model_digest: Mapped[str] = mapped_column(String(64))
    worker_profile_digest: Mapped[str] = mapped_column(String(64))
    search_depth: Mapped[str] = mapped_column(String(32))
    study_name: Mapped[str] = mapped_column(String(200), unique=True)
    state: Mapped[str] = mapped_column(String(32), default="pending")
    search_space_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    maximum_trials: Mapped[int] = mapped_column(Integer)
    proposal_attempts: Mapped[int] = mapped_column(Integer, default=0)
    seed: Mapped[int] = mapped_column(Integer)
    objective: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CandidateRow(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("study_id", "trial_number", name="uq_candidates_study_trial"),
        UniqueConstraint("study_id", "semantic_digest", name="uq_candidates_study_semantic"),
    )

    candidate_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.study_id", ondelete="CASCADE"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.experiment_id", ondelete="CASCADE"))
    trial_number: Mapped[int] = mapped_column(Integer)
    context_tokens: Mapped[int] = mapped_column(Integer)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    parameter_digest: Mapped[str] = mapped_column(String(64))
    semantic_digest: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="proposed")
    optimizer_finalized: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)


class ObservationRow(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "attempt",
            "context_tokens",
            "evidence_kind",
            name="uq_observations_candidate_attempt_lane",
        ),
    )

    observation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.experiment_id", ondelete="CASCADE"))
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.study_id", ondelete="CASCADE"))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.candidate_id", ondelete="CASCADE"))
    trial_number: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    context_tokens: Mapped[int] = mapped_column(Integer)
    evidence_kind: Mapped[str] = mapped_column(String(32))
    measurement_status: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    content_digest: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobEventRow(Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_experiment_sequence", "experiment_id", "sequence"),)

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.experiment_id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(64))
    state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkerCommandRow(Base):
    __tablename__ = "worker_commands"
    __table_args__ = (
        Index("ix_worker_commands_worker_status", "worker_id", "status"),
        Index("ix_worker_commands_status_lease", "status", "lease_expires_at"),
    )

    command_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id", ondelete="CASCADE"))
    command_type: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiments.experiment_id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidates.candidate_id", ondelete="SET NULL"), nullable=True
    )
    expected_snapshot_revision: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OptimizerRequestRow(Base):
    __tablename__ = "optimizer_requests"
    __table_args__ = (
        Index("ix_optimizer_requests_status_id", "status", "id"),
        Index("ix_optimizer_requests_lease", "status", "lease_expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.study_id", ondelete="CASCADE"))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OptimizerHeartbeatRow(Base):
    __tablename__ = "optimizer_heartbeats"

    optimizer_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    pid: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="ready")
    studies_open: Mapped[int] = mapped_column(Integer, default=0)


class FeasibilityLedgerRow(Base):
    __tablename__ = "feasibility_ledger"
    __table_args__ = (Index("ix_feasibility_study_candidate", "study_id", "candidate_digest"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.study_id", ondelete="CASCADE"))
    candidate_digest: Mapped[str] = mapped_column(String(64))
    assumption_signature: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    oom_stage: Mapped[str] = mapped_column(String(32), default="unknown")
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_vram_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_ram_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecipeRow(Base):
    __tablename__ = "recipes"

    recipe_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.experiment_id", ondelete="CASCADE"))
    candidate_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    digest: Mapped[str] = mapped_column(String(64))
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromotionRow(Base):
    __tablename__ = "promotions"

    promotion_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.recipe_id", ondelete="CASCADE"))
    target_slot: Mapped[str] = mapped_column(String(120))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReplayFloorRow(Base):
    __tablename__ = "replay_floors"

    experiment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    floor_sequence: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str] = mapped_column(String(200))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemEventRow(Base):
    __tablename__ = "system_events"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    type: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
