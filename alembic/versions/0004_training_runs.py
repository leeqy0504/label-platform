"""Add UnitTrain run bindings.

Revision ID: 0004_training_runs
Revises: 0003_review_sessions
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_training_runs"
down_revision: str | Sequence[str] | None = "0003_review_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=False),
        sa.Column("unitrain_run_id", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("export_profile", sa.String(length=100), nullable=False),
        sa.Column("export_converter_version", sa.String(length=100), nullable=True),
        sa.Column("export_bundle_path", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_epoch", sa.Integer(), nullable=False),
        sa.Column("total_epochs", sa.Integer(), nullable=False),
        sa.Column("external_detail_url", sa.Text(), nullable=True),
        sa.Column("metric_summary", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("unitrain_run_id"),
    )
    op.create_index("ix_training_runs_dataset_id", "training_runs", ["dataset_id"])
    op.create_index(
        "ix_training_runs_dataset_version_id",
        "training_runs",
        ["dataset_version_id"],
    )
    op.create_index("ix_training_runs_unitrain_run_id", "training_runs", ["unitrain_run_id"])


def downgrade() -> None:
    op.drop_table("training_runs")
