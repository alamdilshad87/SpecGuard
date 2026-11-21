"""Turn test_runs into a job queue: status, attempts, error and timing columns.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("test_runs") as batch:
        # Runs created before the queue existed all ran synchronously and finished.
        batch.add_column(sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"))
        batch.add_column(sa.Column("categories", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch.alter_column("total", server_default="0")
        batch.alter_column("passed", server_default="0")
    # The backfill default is only for existing rows; new rows get "queued" from the app.
    with op.batch_alter_table("test_runs") as batch:
        batch.alter_column("status", server_default=None)
    op.create_index("ix_test_runs_status_created", "test_runs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_test_runs_status_created", table_name="test_runs")
    with op.batch_alter_table("test_runs") as batch:
        batch.alter_column("passed", server_default=None)
        batch.alter_column("total", server_default=None)
        for column in ("finished_at", "started_at", "error", "attempts", "categories", "status"):
            batch.drop_column(column)
