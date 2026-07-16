import mimetypes
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from label_platform.datasets.coco_adapter import CocoAdapter
from label_platform.datasets.analysis import source_fingerprint
from label_platform.datasets.contracts import SourceDataset
from label_platform.datasets.detection import detect_source
from label_platform.datasets.image_adapter import ImageDirectoryAdapter
from label_platform.datasets.labelstudio_adapter import LabelStudioExportAdapter
from label_platform.datasets.normalize import normalize_source
from label_platform.datasets.publisher import (
    DatasetPublicationError,
    DatasetPublisher,
    PublicationResult,
)
from label_platform.db.models import AuditEvent, Dataset, DatasetItem, DatasetVersion
from label_platform.domain.enums import SourceFormat, TaskType, VersionStatus


class DatasetRegistrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatasetRegistrationRequest:
    dataset_id: str
    source_path: Path
    categories: tuple[str, ...]
    task_type: TaskType
    created_by_id: str
    split_seed: int = 42
    split_ratios: dict[str, float] | None = None
    source_version: str | None = None
    source_lineage: dict[str, object] = field(default_factory=dict)
    expected_fingerprint: str | None = None
    parent_version_id: str | None = None
    review_session_id: str | None = None


class RegistrationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        managed_root: Path,
        publisher: DatasetPublisher | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.managed_root = managed_root
        self.publisher = publisher or DatasetPublisher(managed_root)

    def register(self, request: DatasetRegistrationRequest) -> DatasetVersion:
        version = self._allocate_version(request)
        if version.status is VersionStatus.READY:
            return version
        try:
            source = adapt_source(
                request.source_path,
                dataset_id=request.dataset_id,
                categories=request.categories,
                task_type=request.task_type,
            )
            if request.expected_fingerprint is not None:
                current_fingerprint = source_fingerprint(
                    source,
                    split_seed=request.split_seed,
                    split_ratios=request.split_ratios,
                )
                if current_fingerprint != request.expected_fingerprint:
                    raise DatasetRegistrationError("Source changed since analysis")
        except Exception as exc:
            self._fail_registration(version, request, None, exc)
        return self._publish_source(version, request, source)

    def register_source(
        self,
        request: DatasetRegistrationRequest,
        source: SourceDataset,
        *,
        frozen_schema: list[dict[str, object]],
    ) -> DatasetVersion:
        version = self._allocate_version(request)
        if version.status is VersionStatus.READY:
            return version
        return self._publish_source(version, request, source, frozen_schema=frozen_schema)

    def record_invalid_version(
        self,
        request: DatasetRegistrationRequest,
        error: Exception,
    ) -> DatasetVersion:
        version = self._allocate_version(request)
        if version.status is VersionStatus.READY:
            return version
        self._mark_invalid(version.id, error)
        with self.session_factory() as session:
            stored = session.get(DatasetVersion, version.id)
            if stored is None:
                raise DatasetRegistrationError("Invalid dataset version was not persisted")
            session.expunge(stored)
            return stored

    def _publish_source(
        self,
        version: DatasetVersion,
        request: DatasetRegistrationRequest,
        source: SourceDataset,
        *,
        frozen_schema: list[dict[str, object]] | None = None,
    ) -> DatasetVersion:
        publication: PublicationResult | None = None
        try:
            canonical = normalize_source(
                source,
                split_seed=request.split_seed,
                split_ratios=request.split_ratios,
                source_version=request.source_version,
                source_lineage=request.source_lineage,
            )
            class_schema = cast(list[dict[str, object]], canonical.manifest["categories"])
            publication = self.publisher.publish(
                canonical,
                dataset_id=request.dataset_id,
                version_number=version.version_number,
                version_id=version.id,
                frozen_schema=frozen_schema if frozen_schema is not None else class_schema,
            )
            return self._mark_ready(
                version.id,
                request,
                publication.canonical,
                publication.validation_report.as_dict(),
            )
        except Exception as exc:
            self._fail_registration(version, request, publication, exc)

    def _fail_registration(
        self,
        version: DatasetVersion,
        request: DatasetRegistrationRequest,
        publication: PublicationResult | None,
        error: Exception,
    ) -> NoReturn:
        if publication is not None:
            self.publisher.rollback_publication(
                dataset_id=request.dataset_id,
                version_number=version.version_number,
                version_id=version.id,
                previous_version_number=self._parent_version_number(version.parent_id),
            )
        self._mark_invalid(version.id, error)
        if isinstance(error, DatasetRegistrationError):
            raise error
        raise DatasetRegistrationError(str(error)) from error

    def _parent_version_number(self, parent_id: str | None) -> int | None:
        if parent_id is None:
            return None
        with self.session_factory() as session:
            return session.scalar(
                select(DatasetVersion.version_number).where(DatasetVersion.id == parent_id)
            )

    def _allocate_version(self, request: DatasetRegistrationRequest) -> DatasetVersion:
        with self.session_factory() as session, session.begin():
            dataset = session.scalar(
                select(Dataset).where(Dataset.id == request.dataset_id).with_for_update()
            )
            if dataset is None:
                raise DatasetRegistrationError("Dataset not found")
            if request.review_session_id is not None:
                existing = session.scalar(
                    select(DatasetVersion).where(
                        DatasetVersion.review_session_id == request.review_session_id
                    )
                )
                if existing is not None:
                    if existing.status is VersionStatus.READY:
                        session.expunge(existing)
                        return existing
                    existing.status = VersionStatus.BUILDING
                    existing.root_path = None
                    existing.manifest_path = None
                    existing.annotation_path = None
                    existing.class_schema = []
                    existing.category_counts = {}
                    existing.item_count = 0
                    existing.annotation_count = 0
                    existing.validation_result = {}
                    session.flush()
                    session.expunge(existing)
                    return existing
            maximum = session.scalar(
                select(func.max(DatasetVersion.version_number)).where(
                    DatasetVersion.dataset_id == dataset.id
                )
            )
            if request.parent_version_id is not None:
                parent = session.scalar(
                    select(DatasetVersion).where(
                        DatasetVersion.id == request.parent_version_id,
                        DatasetVersion.dataset_id == dataset.id,
                        DatasetVersion.status == VersionStatus.READY,
                    )
                )
                if parent is None:
                    raise DatasetRegistrationError("Review parent version is not ready")
            else:
                parent = session.scalar(
                    select(DatasetVersion)
                    .where(
                        DatasetVersion.dataset_id == dataset.id,
                        DatasetVersion.status == VersionStatus.READY,
                    )
                    .order_by(DatasetVersion.version_number.desc())
                    .limit(1)
                )
            version = DatasetVersion(
                dataset_id=dataset.id,
                version_number=(maximum or 0) + 1,
                parent_id=parent.id if parent is not None else None,
                status=VersionStatus.BUILDING,
                review_session_id=request.review_session_id,
                class_schema=[],
                created_by_id=request.created_by_id,
            )
            session.add(version)
            session.flush()
            session.refresh(version)
            session.expunge(version)
            return version

    def _mark_ready(
        self,
        version_id: str,
        request: DatasetRegistrationRequest,
        canonical: Any,
        validation_result: dict[str, object],
    ) -> DatasetVersion:
        with self.session_factory() as session, session.begin():
            version = session.get(DatasetVersion, version_id)
            if version is None:
                raise DatasetRegistrationError("Allocated dataset version no longer exists")
            if version.status is VersionStatus.READY:
                raise DatasetRegistrationError("READY dataset versions are immutable")

            images = cast(list[dict[str, object]], canonical.coco["images"])
            annotations = cast(list[dict[str, object]], canonical.coco["annotations"])
            annotation_counts_by_image = Counter(
                cast(int, annotation["image_id"]) for annotation in annotations
            )
            category_counts = Counter(
                cast(int, annotation["category_id"]) for annotation in annotations
            )
            annotated_image_ids = {annotation["image_id"] for annotation in annotations}
            split_by_sample = {
                sample_key: split
                for split, sample_keys in canonical.splits.items()
                for sample_key in sample_keys
            }
            files = cast(dict[str, dict[str, object]], canonical.manifest["files"])
            for image in images:
                sample_key = cast(str, image["sample_key"])
                file_name = cast(str, image["file_name"])
                source = canonical.source_images[sample_key]
                metadata = files[file_name]
                media_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
                version.items.append(
                    DatasetItem(
                        sample_key=sample_key,
                        relative_path=file_name,
                        media_type=media_type,
                        width=cast(int, image["width"]),
                        height=cast(int, image["height"]),
                        file_size=cast(int, metadata["size"]),
                        sha256=cast(str, metadata["sha256"]),
                        split=split_by_sample[sample_key],
                        status=(
                            "annotated" if image["id"] in annotated_image_ids else "unannotated"
                        ),
                        annotation_count=annotation_counts_by_image[cast(int, image["id"])],
                        group_key=source.group_key,
                    )
                )
            version.root_path = f"{request.dataset_id}/versions/v{version.version_number}"
            version.manifest_path = "manifest.json"
            version.annotation_path = "annotations/instances.coco.json"
            version.class_schema = cast(list[dict[str, Any]], canonical.manifest["categories"])
            version.category_counts = {
                str(cast(int, category["id"])): category_counts[cast(int, category["id"])]
                for category in version.class_schema
            }
            version.item_count = len(images)
            version.annotation_count = len(annotations)
            version.validation_result = validation_result
            version.status = VersionStatus.READY
            session.flush()
            session.add(
                AuditEvent(
                    actor_user_id=request.created_by_id,
                    action="dataset.version_published",
                    resource_type="version",
                    resource_id=version.id,
                    details={
                        "dataset_id": version.dataset_id,
                        "version_number": version.version_number,
                        "review_session_id": request.review_session_id,
                    },
                )
            )
            session.refresh(version)
            session.expunge(version)
            return version

    def _mark_invalid(self, version_id: str, error: Exception) -> None:
        with self.session_factory() as session, session.begin():
            version = session.get(DatasetVersion, version_id)
            if version is None or version.status is VersionStatus.READY:
                return
            report = error.validation_report if isinstance(error, DatasetPublicationError) else None
            version.validation_result = (
                report.as_dict()
                if report is not None
                else {"valid": False, "errors": [{"code": "registration_failed", "message": str(error)}]}
            )
            version.status = VersionStatus.INVALID


def adapt_source(
    source_path: Path,
    *,
    dataset_id: str,
    categories: tuple[str, ...],
    task_type: TaskType,
) -> SourceDataset:
    detected = detect_source(source_path)
    if detected.format is SourceFormat.IMAGE_DIRECTORY:
        return ImageDirectoryAdapter().read(
            source_path,
            dataset_id=dataset_id,
            categories=list(categories),
            task_type=task_type,
        )
    if detected.format in {SourceFormat.COCO_DETECTION, SourceFormat.COCO_INSTANCE}:
        return CocoAdapter().read(source_path, dataset_id=dataset_id)
    if detected.format is SourceFormat.LABEL_STUDIO:
        if detected.annotation_path is None:
            raise DatasetRegistrationError("Label Studio export file was not detected")
        return LabelStudioExportAdapter().read(
            detected.annotation_path,
            dataset_id=dataset_id,
            categories=list(categories) or None,
        )
    raise DatasetRegistrationError(f"Unsupported source format: {detected.format}")
