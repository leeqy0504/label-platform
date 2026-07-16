from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from label_platform.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from label_platform.db.models.accounts import User
from label_platform.db.models.datasets import Dataset, DatasetVersion
from label_platform.domain.enums import TaskType, TrainingStatus


class TrainingRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "training_runs"

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True, nullable=False)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.id"),
        index=True,
        nullable=False,
    )
    unitrain_run_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    task_type: Mapped[TaskType] = mapped_column(
        SAEnum(
            TaskType,
            name="training_task_type",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )
    export_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    export_converter_version: Mapped[str | None] = mapped_column(String(100))
    export_bundle_path: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[TrainingStatus] = mapped_column(
        SAEnum(
            TrainingStatus,
            name="training_status",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=TrainingStatus.QUEUED,
        nullable=False,
    )
    current_epoch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_epochs: Mapped[int] = mapped_column(Integer, nullable=False)
    external_detail_url: Mapped[str | None] = mapped_column(Text)
    metric_summary: Mapped[dict[str, float]] = mapped_column(JSON, default=dict, nullable=False)
    error_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dataset: Mapped[Dataset] = relationship()
    dataset_version: Mapped[DatasetVersion] = relationship()
    created_by: Mapped[User] = relationship()
