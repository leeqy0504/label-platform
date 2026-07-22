from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import BigInteger, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from label_platform.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from label_platform.db.models.accounts import AllowedRoot
from label_platform.domain.enums import SourceFormat, TaskType, VersionStatus


class Dataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "datasets"

    name: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    sources: Mapped[list["DatasetSource"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
    )
    versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        foreign_keys="DatasetVersion.dataset_id",
    )


class DatasetSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dataset_sources"

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    allowed_root_id: Mapped[str] = mapped_column(ForeignKey("allowed_roots.id"), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_format: Mapped[SourceFormat] = mapped_column(
        SAEnum(
            SourceFormat,
            name="source_format",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )
    task_type: Mapped[TaskType] = mapped_column(
        SAEnum(
            TaskType,
            name="task_type",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )
    scan_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    dataset: Mapped[Dataset] = relationship(back_populates="sources")
    allowed_root: Mapped[AllowedRoot] = relationship()


class DatasetVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number"),)

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_versions.id"))
    root_path: Mapped[str | None] = mapped_column(Text)
    manifest_path: Mapped[str | None] = mapped_column(Text)
    annotation_path: Mapped[str | None] = mapped_column(Text)
    review_session_id: Mapped[str | None] = mapped_column(String(36), unique=True, index=True)
    class_schema: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    category_counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    annotation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[VersionStatus] = mapped_column(
        SAEnum(
            VersionStatus,
            name="version_status",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )
    validation_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    dataset: Mapped[Dataset] = relationship(
        back_populates="versions",
        foreign_keys=[dataset_id],
    )
    parent: Mapped["DatasetVersion | None"] = relationship(
        remote_side="DatasetVersion.id",
        foreign_keys=[parent_id],
    )
    items: Mapped[list["DatasetItem"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )


class DatasetItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dataset_items"
    __table_args__ = (UniqueConstraint("version_id", "sample_key"),)

    version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), nullable=False)
    sample_key: Mapped[str] = mapped_column(String(128), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    duration: Mapped[float | None] = mapped_column(Float)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    split: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    annotation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    group_key: Mapped[str | None] = mapped_column(String(255))

    version: Mapped[DatasetVersion] = relationship(back_populates="items")
