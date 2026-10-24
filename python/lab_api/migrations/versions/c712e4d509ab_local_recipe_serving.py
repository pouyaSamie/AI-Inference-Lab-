"""Store current lab-owned serving health independently of immutable snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "c712e4d509ab"
down_revision = "9f2a7c1e4b6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workers", sa.Column("serving_json", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("workers", "serving_json")
