"""release intelligence and engine comparison records

Revision ID: 9f2a7c1e4b6d
Revises: b151f9870480
Create Date: 2026-10-21 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f2a7c1e4b6d"
down_revision: str | None = "b151f9870480"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "release_notices",
        sa.Column("notice_id", sa.String(length=128), nullable=False),
        sa.Column("engine_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("build", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("metadata_digest", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("notice_id", name=op.f("pk_release_notices")),
        sa.UniqueConstraint("metadata_digest", name=op.f("uq_release_notices_metadata_digest")),
    )
    op.create_index(
        "ix_release_notices_engine_version",
        "release_notices",
        ["engine_id", "version"],
        unique=False,
    )
    op.create_table(
        "release_assessments",
        sa.Column("assessment_id", sa.String(length=128), nullable=False),
        sa.Column("notice_id", sa.String(length=128), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("model_digest", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("current_engine_sha256", sa.String(length=64), nullable=False),
        sa.Column("inventory_snapshot_revision", sa.Integer(), nullable=False),
        sa.Column("inventory_fresh", sa.Boolean(), nullable=False),
        sa.Column("applicable", sa.Boolean(), nullable=False),
        sa.Column("impact", sa.String(length=8), nullable=False),
        sa.Column("requires_ab", sa.Boolean(), nullable=False),
        sa.Column("recommended_action", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            ["release_notices.notice_id"],
            name=op.f("fk_release_assessments_notice_id_release_notices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.worker_id"],
            name=op.f("fk_release_assessments_worker_id_workers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("assessment_id", name=op.f("pk_release_assessments")),
        sa.UniqueConstraint(
            "notice_id",
            "worker_id",
            "model_id",
            "model_digest",
            "policy_version",
            "current_engine_sha256",
            "inventory_snapshot_revision",
            "inventory_fresh",
            name="uq_release_assessment_identity",
        ),
    )
    op.create_index(
        "ix_release_assessments_notice_worker",
        "release_assessments",
        ["notice_id", "worker_id"],
        unique=False,
    )
    op.create_table(
        "engine_comparisons",
        sa.Column("comparison_id", sa.String(length=128), nullable=False),
        sa.Column("notice_id", sa.String(length=128), nullable=False),
        sa.Column("assessment_id", sa.String(length=128), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("model_digest", sa.String(length=64), nullable=False),
        sa.Column("objective", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("evidence_digest", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["release_assessments.assessment_id"],
            name=op.f("fk_engine_comparisons_assessment_id_release_assessments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id"],
            ["release_notices.notice_id"],
            name=op.f("fk_engine_comparisons_notice_id_release_notices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["workers.worker_id"],
            name=op.f("fk_engine_comparisons_worker_id_workers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("comparison_id", name=op.f("pk_engine_comparisons")),
    )
    op.create_index(
        "ix_engine_comparisons_notice_status",
        "engine_comparisons",
        ["notice_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_engine_comparisons_worker",
        "engine_comparisons",
        ["worker_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_engine_comparisons_worker", table_name="engine_comparisons")
    op.drop_index("ix_engine_comparisons_notice_status", table_name="engine_comparisons")
    op.drop_table("engine_comparisons")
    op.drop_index("ix_release_assessments_notice_worker", table_name="release_assessments")
    op.drop_table("release_assessments")
    op.drop_index("ix_release_notices_engine_version", table_name="release_notices")
    op.drop_table("release_notices")
