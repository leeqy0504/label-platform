from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from label_platform.datasets.service import DatasetRegistrationRequest, RegistrationService
from label_platform.datasets.versioning import (
    VersionStorageError,
    image_by_sample,
    load_version_document,
    load_version_manifest,
    resolve_version_image,
)
from label_platform.db.models import (
    AuditEvent,
    BackgroundJob,
    Dataset,
    DatasetVersion,
    ReviewSession,
    ReviewTaskBinding,
)
from label_platform.domain.enums import ReviewStatus, TaskType, VersionStatus
from label_platform.integrations.labelstudio import LabelStudioConnector, LabelStudioProgress
from label_platform.reviews.export import load_review_export
from label_platform.reviews.tasks import ReviewImportTask, build_import_tasks, build_label_config


class ReviewWorkflowError(RuntimeError):
    pass


class ReviewConflictError(ReviewWorkflowError):
    pass


class ReviewWorkflow:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        managed_root: Path,
        export_root: Path,
        label_studio_mount_root: Path,
        label_studio_base_url: str,
        connector: LabelStudioConnector,
    ) -> None:
        self.session_factory = session_factory
        self.managed_root = managed_root
        self.export_root = export_root
        self.label_studio_mount_root = label_studio_mount_root.resolve()
        self.label_studio_base_url = label_studio_base_url.rstrip("/")
        self.connector = connector

    def create_session(
        self,
        *,
        dataset_id: str,
        input_version_id: str,
        idempotency_key: str,
    ) -> ReviewSession:
        with self.session_factory() as session, session.begin():
            existing = session.scalar(
                select(ReviewSession).where(ReviewSession.idempotency_key == idempotency_key)
            )
            if existing is not None:
                if (
                    existing.dataset_id != dataset_id
                    or existing.input_version_id != input_version_id
                ):
                    raise ReviewConflictError(
                        "Review idempotency key was used for a different request"
                    )
                session.expunge(existing)
                return existing

            dataset = session.get(Dataset, dataset_id)
            version = session.scalar(
                select(DatasetVersion).where(
                    DatasetVersion.id == input_version_id,
                    DatasetVersion.dataset_id == dataset_id,
                )
            )
            if dataset is None or version is None:
                raise ReviewWorkflowError("Dataset version was not found")
            if dataset.status == "archived" or version.status is not VersionStatus.READY:
                raise ReviewConflictError("Only a ready, active dataset version can be reviewed")
            task_type = self._task_type(version)
            label_config = build_label_config(task_type, version.class_schema)
            review = ReviewSession(
                dataset_id=dataset.id,
                input_version_id=version.id,
                label_studio_base_url=self.label_studio_base_url,
                idempotency_key=idempotency_key,
                status=ReviewStatus.CREATING,
                recoverable_status=ReviewStatus.CREATING,
                config_hash=hashlib.sha256(label_config.encode("utf-8")).hexdigest(),
            )
            session.add(review)
            session.flush()
            session.add(
                AuditEvent(
                    action="review.creation_requested",
                    resource_type="review",
                    resource_id=review.id,
                    details={"dataset_id": dataset.id, "input_version_id": version.id},
                )
            )
            session.flush()
            session.expunge(review)
            return review

    def run_creation(
        self,
        review_id: str,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> ReviewSession:
        try:
            snapshot = self._creation_snapshot(review_id)
            tasks = cast(list[ReviewImportTask], snapshot["tasks"])
            self._progress(progress_callback, "creating_project", 0, len(tasks))
            project_id = snapshot["project_id"]
            if project_id is not None and (
                isinstance(project_id, bool) or not isinstance(project_id, int)
            ):
                raise ReviewWorkflowError("Review project binding is invalid")
            if project_id is None:
                project_id = self.connector.create_project(
                    cast(str, snapshot["title"]),
                    cast(str, snapshot["description"]),
                )
                self._record_project(review_id, project_id)

            label_config = cast(str, snapshot["label_config"])
            self._progress(progress_callback, "configuring_project", 0, len(tasks))
            self.connector.configure_labels(project_id, label_config)
            self._set_stage(review_id, ReviewStatus.IMPORTING)
            storage_id = self.connector.create_local_storage(
                project_id,
                cast(str, snapshot["storage_path"]),
            )
            remote = self.connector.get_task_bindings(project_id)
            missing = [task for task in tasks if task.sample_key not in remote]
            imported: dict[str, int] = {}
            processed = len(set(remote).intersection(task.sample_key for task in tasks))
            self._progress(progress_callback, "importing_tasks", processed, len(tasks))
            for offset in range(0, len(missing), 500):
                batch = missing[offset : offset + 500]
                imported.update(
                    self.connector.import_tasks(
                        project_id,
                        [task.payload for task in batch],
                    )
                )
                processed += len(batch)
                self._progress(progress_callback, "importing_tasks", processed, len(tasks))
            bindings = {**remote, **imported}
            return self._finish_import(review_id, storage_id, tasks, bindings)
        except Exception as exc:
            self.fail_session(review_id, exc)
            if isinstance(exc, ReviewWorkflowError):
                raise
            raise ReviewWorkflowError(str(exc)) from exc

    def reconcile(self, review_id: str) -> ReviewSession:
        with self.session_factory() as session:
            review = session.get(ReviewSession, review_id)
            if review is None or review.label_studio_project_id is None:
                raise ReviewWorkflowError("Review project is not ready")
            if review.status in {ReviewStatus.COMPLETED, ReviewStatus.EXPORTING}:
                session.expunge(review)
                return review
            project_id = review.label_studio_project_id
        try:
            progress = self.connector.get_progress(project_id)
        except Exception as exc:
            raise ReviewWorkflowError(str(exc)) from exc
        with self.session_factory() as session, session.begin():
            review = session.get(ReviewSession, review_id)
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            review.total_tasks = progress.total
            review.completed_tasks = progress.completed
            review.skipped_tasks = progress.skipped
            if review.status is ReviewStatus.READY and progress.completed > 0:
                review.status = ReviewStatus.IN_REVIEW
                review.recoverable_status = ReviewStatus.IN_REVIEW
            session.flush()
            session.expunge(review)
            return review

    def start_export(self, review_id: str) -> ReviewSession:
        with self.session_factory() as session, session.begin():
            review = session.scalar(
                select(ReviewSession).where(ReviewSession.id == review_id).with_for_update()
            )
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            if review.status is ReviewStatus.COMPLETED:
                session.expunge(review)
                return review
            if review.status is ReviewStatus.FAILED:
                if review.recoverable_status is not ReviewStatus.EXPORTING:
                    raise ReviewConflictError("Review creation must be retried before export")
            elif review.status not in {
                ReviewStatus.READY,
                ReviewStatus.IN_REVIEW,
                ReviewStatus.EXPORTING,
            }:
                raise ReviewConflictError("Review is not ready for export")
            review.status = ReviewStatus.EXPORTING
            review.recoverable_status = ReviewStatus.EXPORTING
            review.error_summary = {}
            session.flush()
            session.expunge(review)
            return review

    def prepare_retry(self, review_id: str) -> ReviewSession:
        with self.session_factory() as session, session.begin():
            review = session.scalar(
                select(ReviewSession).where(ReviewSession.id == review_id).with_for_update()
            )
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            if review.status is not ReviewStatus.FAILED or review.recoverable_status is None:
                raise ReviewConflictError("Only a failed review can be retried")
            review.status = review.recoverable_status
            review.error_summary = {}
            session.flush()
            session.expunge(review)
            return review

    def delete_session(self, review_id: str) -> None:
        with self.session_factory() as session, session.begin():
            review = session.scalar(
                select(ReviewSession).where(ReviewSession.id == review_id).with_for_update()
            )
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            if review.status not in {
                ReviewStatus.READY,
                ReviewStatus.IN_REVIEW,
            }:
                raise ReviewConflictError("Review cannot be deleted in its current state")

            project_id = review.label_studio_project_id
            review_status = review.status
            if project_id is not None:
                try:
                    self.connector.delete_project(project_id)
                except Exception as exc:
                    raise ReviewWorkflowError(
                        "Label Studio project could not be deleted"
                    ) from exc

            remaining_reviews = session.scalars(
                select(ReviewSession).where(
                    ReviewSession.dataset_id == review.dataset_id,
                    ReviewSession.id != review.id,
                )
            ).all()
            active_statuses = {
                ReviewStatus.READY,
                ReviewStatus.IN_REVIEW,
                ReviewStatus.EXPORTING,
            }
            has_other_active_review = any(
                candidate.status in active_statuses
                or (
                    candidate.status is ReviewStatus.FAILED
                    and candidate.recoverable_status in active_statuses
                )
                for candidate in remaining_reviews
            )
            if not has_other_active_review:
                review.dataset.status = (
                    "pending_annotation"
                    if review.input_version.annotation_count == 0
                    else "trainable"
                )

            session.execute(
                delete(BackgroundJob).where(BackgroundJob.business_object_id == review.id)
            )
            session.delete(review)
            session.add(
                AuditEvent(
                    action="review.deleted",
                    resource_type="review",
                    resource_id=review_id,
                    details={
                        "dataset_id": review.dataset_id,
                        "input_version_id": review.input_version_id,
                        "label_studio_project_id": project_id,
                        "status": review_status.value,
                    },
                )
            )
        self._cleanup_review_view(review_id)

    def run_export(
        self,
        review_id: str,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> DatasetVersion:
        try:
            with self.session_factory() as session:
                review = session.get(ReviewSession, review_id)
                if review is None:
                    raise ReviewWorkflowError("Review session was not found")
                if review.status is ReviewStatus.COMPLETED and review.output_version_id:
                    output = session.get(DatasetVersion, review.output_version_id)
                    if output is None:
                        raise ReviewWorkflowError("Review output version was not found")
                    session.expunge(output)
                    self._cleanup_review_view(review_id)
                    return output
                if review.status is not ReviewStatus.EXPORTING:
                    raise ReviewConflictError("Review export has not been requested")
                if review.label_studio_project_id is None:
                    raise ReviewWorkflowError("Review project is not ready")
                project_id = review.label_studio_project_id
                input_version_id = review.input_version_id
                dataset_id = review.dataset_id

            progress = self.connector.get_progress(project_id)
            export_path = self.export_root / review_id / "raw-export.json"
            self._progress(progress_callback, "exporting", 0, max(progress.total, 1))
            self.connector.export_annotations(project_id, export_path)
            self._record_export_path(review_id, export_path)
            self._progress(progress_callback, "converting", 1, max(progress.total, 1))

            with self.session_factory() as session:
                version = session.get(DatasetVersion, input_version_id)
                if version is None or version.root_path is None:
                    raise ReviewWorkflowError("Review input version is unavailable")
                task_type = self._task_type(version)
                version_root = self.managed_root / version.root_path
                categories = tuple(
                    cast(str, category["name"]) for category in version.class_schema
                )
                frozen_schema = [dict(category) for category in version.class_schema]
                registration_request = DatasetRegistrationRequest(
                    dataset_id=dataset_id,
                    source_path=version_root,
                    categories=categories,
                    task_type=task_type,
                    source_version=f"label-studio-project-{project_id}",
                    source_lineage={
                        "review_session_id": review_id,
                        "label_studio_project_id": project_id,
                        "input_version_id": input_version_id,
                    },
                    parent_version_id=input_version_id,
                    review_session_id=review_id,
                )

                try:
                    source = load_review_export(
                        export_path,
                        version=version,
                        version_root=version_root,
                        task_type=task_type,
                        managed_root=self.managed_root,
                    )
                except Exception as exc:
                    session.close()
                    RegistrationService(
                        self.session_factory,
                        managed_root=self.managed_root,
                    ).record_invalid_version(registration_request, exc)
                    raise

            output = RegistrationService(
                self.session_factory,
                managed_root=self.managed_root,
            ).register_source(
                registration_request,
                source,
                frozen_schema=frozen_schema,
            )
            self._progress(
                progress_callback,
                "publishing",
                output.item_count,
                output.item_count,
            )
            finished = self._finish_export(review_id, output, export_path, progress)
            self._cleanup_review_view(review_id)
            return finished
        except Exception as exc:
            self.fail_session(review_id, exc, recoverable=ReviewStatus.EXPORTING)
            if isinstance(exc, ReviewWorkflowError):
                raise
            raise ReviewWorkflowError(str(exc)) from exc

    def fail_session(
        self,
        review_id: str,
        error: Exception,
        *,
        recoverable: ReviewStatus | None = None,
    ) -> None:
        with self.session_factory() as session, session.begin():
            review = session.get(ReviewSession, review_id)
            if review is None or review.status is ReviewStatus.COMPLETED:
                return
            if recoverable is not None:
                review.recoverable_status = recoverable
            elif review.status is not ReviewStatus.FAILED:
                review.recoverable_status = review.status
            review.status = ReviewStatus.FAILED
            review.error_summary = {
                "code": "review_workflow_failed",
                "type": type(error).__name__,
                "message": str(error),
            }

    def _creation_snapshot(self, review_id: str) -> dict[str, object]:
        with self.session_factory() as session:
            review = session.get(ReviewSession, review_id)
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            if review.status is ReviewStatus.COMPLETED:
                raise ReviewConflictError("Completed review cannot be imported again")
            version = review.input_version
            if version.root_path is None:
                raise ReviewWorkflowError("Review input version has no managed path")
            task_type = self._task_type(version)
            config = build_label_config(task_type, version.class_schema)
            if hashlib.sha256(config.encode("utf-8")).hexdigest() != review.config_hash:
                raise ReviewConflictError("Review label configuration changed after creation")
            version_root = self.managed_root / version.root_path
            view_relative = self._ensure_review_view(review_id, version, version_root)
            tasks = build_import_tasks(
                version,
                version_root,
                task_type=task_type,
                media_root_path=view_relative,
            )
            storage_path = (self.label_studio_mount_root / view_relative).as_posix()
            return {
                "project_id": review.label_studio_project_id,
                "title": f"{review.dataset.name} v{version.version_number} review",
                "description": f"Platform review session {review.id}",
                "label_config": config,
                "storage_path": storage_path,
                "tasks": tasks,
            }

    def _record_project(self, review_id: str, project_id: int) -> None:
        with self.session_factory() as session, session.begin():
            review = session.get(ReviewSession, review_id)
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            if review.label_studio_project_id not in {None, project_id}:
                raise ReviewConflictError("Review is already bound to another project")
            review.label_studio_project_id = project_id

    def _record_export_path(self, review_id: str, export_path: Path) -> None:
        with self.session_factory() as session, session.begin():
            review = session.get(ReviewSession, review_id)
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            review.raw_export_path = str(export_path)

    def _set_stage(self, review_id: str, stage: ReviewStatus) -> None:
        with self.session_factory() as session, session.begin():
            review = session.get(ReviewSession, review_id)
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            review.status = stage
            review.recoverable_status = stage
            review.error_summary = {}

    def _finish_import(
        self,
        review_id: str,
        storage_id: int,
        tasks: list[ReviewImportTask],
        remote_bindings: dict[str, int],
    ) -> ReviewSession:
        expected = {task.sample_key: task for task in tasks}
        if not set(expected).issubset(remote_bindings):
            raise ReviewWorkflowError("Label Studio import did not bind every sample")
        with self.session_factory() as session, session.begin():
            review = session.get(ReviewSession, review_id)
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            already_ready = review.status in {ReviewStatus.READY, ReviewStatus.IN_REVIEW}
            stored = {binding.sample_key: binding for binding in review.task_bindings}
            for sample_key, task in expected.items():
                task_id = remote_bindings[sample_key]
                binding = stored.get(sample_key)
                if binding is not None and binding.label_studio_task_id != task_id:
                    raise ReviewConflictError("A review sample is bound to another remote task")
                if binding is None:
                    review.task_bindings.append(
                        ReviewTaskBinding(
                            dataset_item_id=task.dataset_item_id,
                            sample_key=sample_key,
                            label_studio_task_id=task_id,
                        )
                    )
            review.label_studio_storage_id = storage_id
            review.total_tasks = len(tasks)
            review.status = ReviewStatus.READY
            review.recoverable_status = ReviewStatus.READY
            review.error_summary = {}
            review.started_at = review.started_at or datetime.now(timezone.utc)
            review.dataset.status = "reviewing"
            if not already_ready:
                session.add(
                    AuditEvent(
                        action="review.ready",
                        resource_type="review",
                        resource_id=review.id,
                        details={
                            "label_studio_project_id": review.label_studio_project_id,
                            "task_count": len(tasks),
                        },
                    )
                )
            session.flush()
            session.expunge(review)
            return review

    def _finish_export(
        self,
        review_id: str,
        output: DatasetVersion,
        export_path: Path,
        progress: LabelStudioProgress,
    ) -> DatasetVersion:
        with self.session_factory() as session, session.begin():
            review = session.get(ReviewSession, review_id)
            if review is None:
                raise ReviewWorkflowError("Review session was not found")
            review.output_version_id = output.id
            review.raw_export_path = str(export_path)
            review.total_tasks = progress.total
            review.completed_tasks = progress.completed
            review.skipped_tasks = progress.skipped
            review.status = ReviewStatus.COMPLETED
            review.recoverable_status = None
            review.error_summary = {}
            review.completed_at = datetime.now(timezone.utc)
            review.dataset.status = (
                "pending_annotation" if output.annotation_count == 0 else "trainable"
            )
            session.add(
                AuditEvent(
                    action="review.completed",
                    resource_type="review",
                    resource_id=review.id,
                    details={"output_version_id": output.id},
                )
            )
        return output

    def _task_type(self, version: DatasetVersion) -> TaskType:
        if version.root_path is None:
            raise ReviewWorkflowError("Dataset version has no managed path")
        try:
            version_root = self.managed_root / version.root_path
            manifest = load_version_manifest(
                version_root,
                manifest_path=version.manifest_path,
            )
            value = manifest.get("task_type")
            if not isinstance(value, str):
                raise ValueError("task_type must be a string")
            return TaskType(value)
        except (OSError, ValueError, VersionStorageError) as exc:
            raise ReviewWorkflowError("Dataset version manifest has an invalid task type") from exc

    def _ensure_review_view(
        self,
        review_id: str,
        version: DatasetVersion,
        version_root: Path,
    ) -> str:
        relative_root = Path(".reviews") / review_id / "images"
        final = self.managed_root / relative_root
        staging = final.parent / ".images-building"
        document = load_version_document(
            version_root,
            manifest_path=version.manifest_path,
            annotation_path=version.annotation_path,
        )
        stored_images = image_by_sample(document)
        if staging.exists() or staging.is_symlink():
            self._remove_view(staging)
        staging.mkdir(parents=True)
        try:
            for item in version.items:
                image = stored_images.get(item.sample_key)
                if image is None:
                    raise ReviewWorkflowError(
                        f"Canonical image is missing for sample {item.sample_key}"
                    )
                relative = self._relative_below_images(item.relative_path)
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                target = resolve_version_image(self.managed_root, version_root, image)
                relative_target = Path(os.path.relpath(target, start=destination.parent))
                destination.symlink_to(relative_target)
            if final.exists() or final.is_symlink():
                self._remove_view(final)
            os.replace(staging, final)
        except Exception:
            if staging.exists() or staging.is_symlink():
                self._remove_view(staging)
            raise
        return relative_root.as_posix()

    def _cleanup_review_view(self, review_id: str) -> None:
        root = self.managed_root / ".reviews" / review_id
        if root.exists() or root.is_symlink():
            self._remove_view(root)

    @staticmethod
    def _relative_below_images(relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ReviewWorkflowError("Dataset item path is invalid")
        if relative.parts and relative.parts[0] == "images":
            relative = Path(*relative.parts[1:])
        if str(relative) in {"", "."}:
            raise ReviewWorkflowError("Dataset item path is invalid")
        return relative

    @staticmethod
    def _remove_view(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.exists():
            shutil.rmtree(path)

    @staticmethod
    def _progress(
        callback: Callable[[str, int, int], None] | None,
        stage: str,
        processed: int,
        total: int,
    ) -> None:
        if callback is not None:
            callback(stage, processed, total)
