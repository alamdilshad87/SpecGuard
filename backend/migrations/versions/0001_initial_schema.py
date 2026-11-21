"""Initial schema: projects, spec versions, test runs and code scans.

Revision ID: 0001
Revises:
Create Date: 2026-11-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_name", "projects", ["name"], unique=True)

    op.create_table(
        "spec_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("openapi", sa.String(length=20), nullable=False),
        sa.Column("operation_count", sa.Integer(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "label", name="uq_project_label"),
    )
    op.create_index("ix_spec_versions_project_id", "spec_versions", ["project_id"])

    op.create_table(
        "test_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spec_version_id", sa.Integer(), sa.ForeignKey("spec_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_test_runs_spec_version_id", "test_runs", ["spec_version_id"])

    op.create_table(
        "code_scans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spec_version_id", sa.Integer(), sa.ForeignKey("spec_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("files_scanned", sa.Integer(), nullable=False),
        sa.Column("in_sync", sa.Boolean(), nullable=False),
        sa.Column("routes", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_code_scans_spec_version_id", "code_scans", ["spec_version_id"])


def downgrade() -> None:
    op.drop_index("ix_code_scans_spec_version_id", table_name="code_scans")
    op.drop_table("code_scans")
    op.drop_index("ix_test_runs_spec_version_id", table_name="test_runs")
    op.drop_table("test_runs")
    op.drop_index("ix_spec_versions_project_id", table_name="spec_versions")
    op.drop_table("spec_versions")
    op.drop_index("ix_projects_name", table_name="projects")
    op.drop_table("projects")
