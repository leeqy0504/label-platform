from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from label_platform.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from label_platform.db.models.datasets import Dataset, DatasetItem, DatasetVersion
from label_platform.domain.enums import ReviewStatus


def review_status_type() -> SAEnum:
    return SAEnum(
        ReviewStatus,
        name="review_status",
        native_enum=False,
        values_callable=lambda enum: [member.value for member in enum],
    )


class ReviewSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "review_sessions"

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True, nullable=False)
    input_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.id"), index=True, nullable=False
    )
    output_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("dataset_versions.id"), unique=True
    )
    label_studio_project_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    label_studio_storage_id: Mapped[int | None] = mapped_column(Integer)
    label_studio_base_url: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    total_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        review_status_type(),
        nullable=False,
    )
    recoverable_status: Mapped[ReviewStatus | None] = mapped_column(
        review_status_type(),
        nullable=True,
    )
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_export_path: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dataset: Mapped[Dataset] = relationship()
    input_version: Mapped[DatasetVersion] = relationship(foreign_keys=[input_version_id])
    output_version: Mapped[DatasetVersion | None] = relationship(foreign_keys=[output_version_id])
    task_bindings: Mapped[list["ReviewTaskBinding"]] = relationship(
        back_populates="review_session",
        cascade="all, delete-orphan",
    )


class ReviewTaskBinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "review_task_bindings"
    __table_args__ = (
        UniqueConstraint("review_session_id", "sample_key"),
        UniqueConstraint("review_session_id", "label_studio_task_id"),
    )

    review_session_id: Mapped[str] = mapped_column(
        ForeignKey("review_sessions.id"), index=True, nullable=False
    )
    dataset_item_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_items.id"), nullable=False
    )
    sample_key: Mapped[str] = mapped_column(String(128), nullable=False)
    label_studio_task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    review_session: Mapped[ReviewSession] = relationship(back_populates="task_bindings")
    dataset_item: Mapped[DatasetItem] = relationship()
