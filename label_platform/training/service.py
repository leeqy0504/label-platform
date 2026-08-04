from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from label_platform.db.models import AuditEvent, Dataset, DatasetVersion, TrainingRun
from label_platform.domain.enums import TaskType, TrainingStatus, VersionStatus
from label_platform.integrations.unitrain import (
    UnitTrainConnector,
    UnitTrainLogs,
    UnitTrainMetrics,
    UnitTrainRun,
)
from label_platform.training.export import UNITRAIN_EXPORT_PROFILE, UnitTrainExporter


class TrainingWorkflowError(RuntimeError):
    pass


class TrainingConflictError(TrainingWorkflowError):
    pass


class TrainingWorkflow:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        managed_root: Path,
        export_root: Path,
        unitrain_mount_root: Path,
        connector: UnitTrainConnector,
    ) -> None:
        self.session_factory = session_factory
        self.managed_root = managed_root.resolve()
        self.export_root = export_root.resolve()
        self.unitrain_mount_root = unitrain_mount_root
        self.connector = connector
        self.exporter = UnitTrainExporter(self.export_root, managed_root=self.managed_root)

    def create_run(
        self,
        *,
        dataset_id: str,
        dataset_version_id: str,
        name: str,
        config: dict[str, Any],
        idempotency_key: str,
    ) -> TrainingRun:
        with self.session_factory() as session, session.begin():
            existing = session.scalar(
                select(TrainingRun).where(TrainingRun.idempotency_key == idempotency_key)
            )
            if existing is not None:
                if (
                    existing.dataset_id != dataset_id
                    or existing.dataset_version_id != dataset_version_id
                    or existing.name != name
                    or existing.config != config
                ):
                    raise TrainingConflictError(
                        "Training idempotency key was used for a different request"
                    )
                session.expunge(existing)
                return existing

            dataset = session.get(Dataset, dataset_id)
            version = session.scalar(
                select(DatasetVersion).where(
                    DatasetVersion.id == dataset_version_id,
                    DatasetVersion.dataset_id == dataset_id,
                )
            )
            if dataset is None or version is None:
                raise TrainingWorkflowError("Dataset version was not found")
            if dataset.status == "archived" or version.status is not VersionStatus.READY:
                raise TrainingConflictError(
                    "Only a ready version from an active dataset can be submitted"
                )
            task_type = self._task_type(version)
            run = TrainingRun(
                dataset_id=dataset.id,
                dataset_version_id=version.id,
                idempotency_key=idempotency_key,
                name=name,
                task_type=task_type,
                export_profile=UNITRAIN_EXPORT_PROFILE,
                config=config,
                status=TrainingStatus.QUEUED,
                total_epochs=int(config["epochs"]),
            )
            session.add(run)
            session.flush()
            session.add(
                AuditEvent(
                    action="training.submission_requested",
                    resource_type="training",
                    resource_id=run.id,
                    details={
                        "dataset_id": dataset.id,
                        "dataset_version_id": version.id,
                        "export_profile": UNITRAIN_EXPORT_PROFILE,
                    },
                )
            )
            session.flush()
            session.expunge(run)
            return run

    def submit(
        self,
        run_id: str,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> TrainingRun:
        try:
            snapshot = self._submission_snapshot(run_id)
            if snapshot.unitrain_run_id is not None:
                return self.reconcile(run_id)
            self._progress(progress_callback, "materializing_export", 0, 2)
            version_root = self._version_root(snapshot.dataset_version)
            exported = self.exporter.materialize(
                version_root,
                version_id=snapshot.dataset_version_id,
                profile=snapshot.export_profile,
            )
            relative_bundle = exported.root.relative_to(self.export_root)
            mounted_bundle = (self.unitrain_mount_root / relative_bundle).absolute()
            self._record_export(
                run_id,
                bundle_path=str(relative_bundle),
                converter_version=exported.converter_version,
            )
            self._progress(progress_callback, "submitting_unitrain", 1, 2)
            remote = self.connector.create_run(
                {
                    "dataset_version_id": snapshot.dataset_version_id,
                    "dataset_path": str(mounted_bundle),
                    "annotation_path": exported.annotation_path,
                    "task_type": snapshot.task_type.value,
                    "export_profile": snapshot.export_profile,
                    "idempotency_key": snapshot.id,
                    "config": snapshot.config,
                }
            )
            stored = self._apply_remote(run_id, remote, audit_action="training.submitted")
            self._progress(progress_callback, "submitted", 2, 2)
            return stored
        except Exception as exc:
            self.fail_submission(run_id, exc)
            if isinstance(exc, TrainingWorkflowError):
                raise
            raise TrainingWorkflowError(str(exc)) from exc

    def reconcile(self, run_id: str) -> TrainingRun:
        with self.session_factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise TrainingWorkflowError("Training run was not found")
            external_id = run.unitrain_run_id
            session.expunge(run)
        if external_id is None:
            return run
        remote = self.connector.get_run(external_id)
        if remote.status is TrainingStatus.COMPLETED:
            metrics = self.connector.get_metrics(external_id)
            if metrics.summary:
                remote = replace(remote, metric_summary=metrics.summary)
        return self._apply_remote(run_id, remote)

    def logs(self, run_id: str, *, offset: int, limit: int) -> UnitTrainLogs:
        external_id = self._external_id(run_id)
        return self.connector.get_logs(external_id, offset=offset, limit=limit)

    def metrics(self, run_id: str) -> UnitTrainMetrics:
        external_id = self._external_id(run_id)
        metrics = self.connector.get_metrics(external_id)
        if metrics.summary:
            with self.session_factory() as session, session.begin():
                run = session.get(TrainingRun, run_id)
                if run is not None:
                    run.metric_summary = metrics.summary
        return metrics

    def stop(self, run_id: str) -> TrainingRun:
        external_id = self._external_id(run_id)
        remote = self.connector.stop_run(external_id)
        return self._apply_remote(run_id, remote, audit_action="training.stopped")

    def prepare_retry(self, run_id: str) -> TrainingRun:
        with self.session_factory() as session, session.begin():
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise TrainingWorkflowError("Training run was not found")
            if run.status is not TrainingStatus.FAILED or run.unitrain_run_id is not None:
                raise TrainingConflictError("Only an unsubmitted failed run can be retried")
            run.status = TrainingStatus.QUEUED
            run.error_summary = {}
            run.completed_at = None
            session.flush()
            session.expunge(run)
            return run

    def fail_submission(self, run_id: str, error: Exception) -> None:
        with self.session_factory() as session, session.begin():
            run = session.get(TrainingRun, run_id)
            if run is None or run.unitrain_run_id is not None:
                return
            run.status = TrainingStatus.FAILED
            run.completed_at = datetime.now(timezone.utc)
            run.error_summary = {
                "code": "submission_failed",
                "type": type(error).__name__,
                "message": str(error),
            }

    def _submission_snapshot(self, run_id: str) -> TrainingRun:
        with self.session_factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise TrainingWorkflowError("Training run was not found")
            if run.status not in {TrainingStatus.QUEUED, TrainingStatus.FAILED}:
                if run.unitrain_run_id is not None:
                    session.expunge(run)
                    return run
                raise TrainingConflictError(f"Training run is already {run.status.value}")
            _ = run.dataset_version
            session.expunge(run)
            return run

    def _record_export(self, run_id: str, *, bundle_path: str, converter_version: str) -> None:
        with self.session_factory() as session, session.begin():
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise TrainingWorkflowError("Training run was not found")
            run.export_bundle_path = bundle_path
            run.export_converter_version = converter_version

    def _apply_remote(
        self,
        run_id: str,
        remote: UnitTrainRun,
        *,
        audit_action: str | None = None,
    ) -> TrainingRun:
        with self.session_factory() as session, session.begin():
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise TrainingWorkflowError("Training run was not found")
            if run.unitrain_run_id is not None and run.unitrain_run_id != remote.id:
                raise TrainingConflictError("Training run is bound to a different UniTrain run")
            run.unitrain_run_id = remote.id
            run.status = remote.status
            run.current_epoch = remote.current_epoch
            run.total_epochs = remote.total_epochs
            run.external_detail_url = remote.detail_url
            run.metric_summary = remote.metric_summary
            run.error_summary = (
                {"code": "unitrain_run_failed", "message": remote.error}
                if remote.error
                else {}
            )
            run.started_at = remote.started_at
            run.completed_at = remote.completed_at
            if audit_action is not None:
                session.add(
                    AuditEvent(
                        action=audit_action,
                        resource_type="training",
                        resource_id=run.id,
                        details={"unitrain_run_id": remote.id, "status": remote.status.value},
                    )
                )
            session.flush()
            session.expunge(run)
            return run

    def _external_id(self, run_id: str) -> str:
        with self.session_factory() as session:
            run = session.get(TrainingRun, run_id)
            if run is None:
                raise TrainingWorkflowError("Training run was not found")
            if run.unitrain_run_id is None:
                raise TrainingConflictError("Training run has not been submitted to UniTrain")
            return run.unitrain_run_id

    def _version_root(self, version: DatasetVersion) -> Path:
        if version.root_path is None:
            raise TrainingWorkflowError("Dataset version has no published root")
        root = (self.managed_root / version.root_path).resolve(strict=True)
        if not root.is_relative_to(self.managed_root):
            raise TrainingWorkflowError("Dataset version root escapes managed storage")
        return root

    def _task_type(self, version: DatasetVersion) -> TaskType:
        root = self._version_root(version)
        try:
            from label_platform.datasets.versioning import (
                VersionStorageError,
                load_version_manifest,
            )

            manifest = load_version_manifest(
                root,
                manifest_path=version.manifest_path,
            )
            return TaskType(manifest["task_type"])
        except (OSError, ValueError, KeyError, TypeError, VersionStorageError) as exc:
            raise TrainingWorkflowError("Dataset version manifest has an invalid task type") from exc

    @staticmethod
    def _progress(
        callback: Callable[[str, int, int], None] | None,
        stage: str,
        processed: int,
        total: int,
    ) -> None:
        if callback is not None:
            callback(stage, processed, total)
