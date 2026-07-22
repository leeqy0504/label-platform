"""Add Label Studio review sessions and task bindings.

Revision ID: 0003_review_sessions
Revises: 0002_dataset_statistics
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_review_sessions"
down_revision: str | Sequence[str] | None = "0002_dataset_statistics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "dataset_versions",
        sa.Column("review_session_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_dataset_versions_review_session_id",
        "dataset_versions",
        ["review_session_id"],
        unique=True,
    )
    op.create_table(
        "review_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("input_version_id", sa.String(length=36), nullable=False),
        sa.Column("output_version_id", sa.String(length=36), nullable=True),
        sa.Column("label_studio_project_id", sa.Integer(), nullable=True),
        sa.Column("label_studio_storage_id", sa.Integer(), nullable=True),
        sa.Column("label_studio_base_url", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("total_tasks", sa.Integer(), nullable=False),
        sa.Column("completed_tasks", sa.Integer(), nullable=False),
        sa.Column("skipped_tasks", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("recoverable_status", sa.String(length=32), nullable=True),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("error_summary", sa.JSON(), nullable=False),
        sa.Column("raw_export_path", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["input_version_id"], ["dataset_versions.id"]),
        sa.ForeignKeyConstraint(["output_version_id"], ["dataset_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label_studio_project_id"),
        sa.UniqueConstraint("output_version_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_review_sessions_dataset_id", "review_sessions", ["dataset_id"])
    op.create_index(
        "ix_review_sessions_input_version_id",
        "review_sessions",
        ["input_version_id"],
    )

    op.create_table(
        "review_task_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("review_session_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_item_id", sa.String(length=36), nullable=False),
        sa.Column("sample_key", sa.String(length=128), nullable=False),
        sa.Column("label_studio_task_id", sa.Integer(), nullable=False),
        sa.Column("is_completed", sa.Boolean(), nullable=False),
        sa.Column("is_skipped", sa.Boolean(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["dataset_item_id"], ["dataset_items.id"]),
        sa.ForeignKeyConstraint(["review_session_id"], ["review_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_session_id", "label_studio_task_id"),
        sa.UniqueConstraint("review_session_id", "sample_key"),
    )
    op.create_index(
        "ix_review_task_bindings_review_session_id",
        "review_task_bindings",
        ["review_session_id"],
    )


def downgrade() -> None:
    op.drop_table("review_task_bindings")
    op.drop_table("review_sessions")
    op.drop_index("ix_dataset_versions_review_session_id", table_name="dataset_versions")
    op.drop_column("dataset_versions", "review_session_id")
