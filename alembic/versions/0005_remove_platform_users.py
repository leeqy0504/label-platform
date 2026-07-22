"""Remove platform authentication and user identity fields.

Revision ID: 0005_remove_platform_users
Revises: 0004_training_runs
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_remove_platform_users"
down_revision: str | Sequence[str] | None = "0004_training_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    tables = _table_names()

    if "audit_events" in tables:
        indexes = {
            index["name"]
            for index in sa.inspect(op.get_bind()).get_indexes("audit_events")
        }
        if "ix_audit_events_actor_user_id" in indexes:
            op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")

    identity_columns = {
        "allowed_roots": ("created_by_id",),
        "datasets": ("created_by_id",),
        "dataset_versions": ("created_by_id",),
        "background_jobs": ("created_by_id",),
        "audit_events": ("actor_user_id", "ip_address"),
        "review_sessions": ("created_by_id",),
        "training_runs": ("created_by_id",),
    }
    for table_name, candidates in identity_columns.items():
        if table_name not in tables:
            continue
        existing = _column_names(table_name)
        columns = [name for name in candidates if name in existing]
        if not columns:
            continue
        with op.batch_alter_table(table_name) as batch_op:
            for column_name in columns:
                batch_op.drop_column(column_name)

    if "users" in tables:
        op.drop_table("users")


def downgrade() -> None:
    # User credentials and authorship links cannot be reconstructed after removal.
    pass
