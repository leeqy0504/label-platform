import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from label_platform.config import Settings
from label_platform.datasets.analysis import analyze_dataset_source
from label_platform.datasets.service import DatasetRegistrationRequest, RegistrationService
from label_platform.db.models import BackgroundJob, Dataset, DatasetSource, TrainingRun
from label_platform.db.session import create_engine_from_settings, create_session_factory
from label_platform.domain.enums import JobStatus, TaskType, TrainingStatus
from label_platform.integrations.labelstudio import create_label_studio_connector
from label_platform.integrations.unitrain import create_unitrain_connector
from label_platform.reviews.service import ReviewWorkflow
from label_platform.training.service import TrainingWorkflow


logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        managed_root: Path,
        review_workflow: ReviewWorkflow | None = None,
        training_workflow: TrainingWorkflow | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.managed_root = managed_root
        self.review_workflow = review_workflow
        self.training_workflow = training_workflow
        self.log_root = managed_root.parent / "logs" / "jobs"

    def run_analysis(self, job_id: str) -> None:
        request = self._start(job_id, expected_type="dataset_analysis", stage="analyzing")
        if request is None:
            return
        try:
            split = cast(dict[str, Any], request["split"])
            result = analyze_dataset_source(
                Path(cast(str, request["source_path"])),
                dataset_namespace=f"analysis:{job_id}",
                categories=tuple(cast(list[str], request["categories"])),
                task_type=TaskType(cast(str, request["task_type"])),
                split_seed=cast(int, split["seed"]),
                split_ratios={
                    name: float(split[name]) for name in ("train", "val", "test")
                },
            )
            self._succeed(
                job_id,
                public_result=result,
                total_count=cast(int, result["image_count"]),
            )
        except Exception as exc:
            self._fail(job_id, exc)

    def run_registration(self, job_id: str) -> None:
        request = self._start(job_id, expected_type="dataset_registration", stage="registering")
        if request is None:
            return
        try:
            source_id = cast(str, request["dataset_source_id"])
            with self.session_factory() as session:
                source = session.get(DatasetSource, source_id)
                if source is None:
                    raise RuntimeError("Dataset source no longer exists")
                metadata = dict(source.source_metadata)
                source_path = Path(source.normalized_path)
                dataset_id = source.dataset_id
                task_type = source.task_type
            split = cast(dict[str, Any], metadata["split"])
            service = RegistrationService(self.session_factory, managed_root=self.managed_root)
            version = service.register(
                DatasetRegistrationRequest(
                    dataset_id=dataset_id,
                    source_path=source_path,
                    categories=tuple(cast(list[str], metadata["categories"])),
                    task_type=task_type,
                    created_by_id=cast(str, request["created_by_id"]),
                    split_seed=cast(int, split["seed"]),
                    split_ratios={
                        name: float(split[name]) for name in ("train", "val", "test")
                    },
                    source_version=cast(str | None, metadata.get("source_version")),
                    source_lineage={
                        "allowed_root_id": source.allowed_root_id,
                        "relative_path": source.relative_path,
                        "analysis_fingerprint": metadata["analysis_fingerprint"],
                    },
                    expected_fingerprint=cast(str, metadata["analysis_fingerprint"]),
                )
            )
            with self.session_factory() as session, session.begin():
                stored_source = session.get(DatasetSource, source_id)
                dataset = session.get(Dataset, dataset_id)
                if stored_source is not None:
                    stored_source.scan_status = "registered"
                if dataset is not None:
                    dataset.status = (
                        "pending_annotation" if version.annotation_count == 0 else "trainable"
                    )
            self._succeed(
                job_id,
                public_result={
                    "dataset_id": dataset_id,
                    "version_id": version.id,
                    "version_number": version.version_number,
                    "status": version.status.value,
                },
                total_count=version.item_count,
            )
        except Exception as exc:
            self._fail(job_id, exc)

    def run_review_creation(self, job_id: str) -> None:
        request = self._start(job_id, expected_type="review_creation", stage="creating_project")
        if request is None:
            return
        try:
            if self.review_workflow is None:
                raise RuntimeError("Label Studio review workflow is not configured")
            review_id = cast(str, request["review_session_id"])
            review = self.review_workflow.run_creation(
                review_id,
                lambda stage, processed, total: self._progress(
                    job_id,
                    stage=stage,
                    processed=processed,
                    total=total,
                ),
            )
            self._succeed(
                job_id,
                public_result={
                    "review_session_id": review.id,
                    "label_studio_project_id": review.label_studio_project_id,
                    "status": review.status.value,
                },
                total_count=review.total_tasks,
            )
        except Exception as exc:
            self._fail(job_id, exc)

    def run_review_export(self, job_id: str) -> None:
        request = self._start(job_id, expected_type="review_export", stage="exporting")
        if request is None:
            return
        try:
            if self.review_workflow is None:
                raise RuntimeError("Label Studio review workflow is not configured")
            review_id = cast(str, request["review_session_id"])
            version = self.review_workflow.run_export(
                review_id,
                lambda stage, processed, total: self._progress(
                    job_id,
                    stage=stage,
                    processed=processed,
                    total=total,
                ),
            )
            self._succeed(
                job_id,
                public_result={
                    "review_session_id": review_id,
                    "dataset_id": version.dataset_id,
                    "version_id": version.id,
                    "version_number": version.version_number,
                    "status": version.status.value,
                },
                total_count=version.item_count,
            )
        except Exception as exc:
            self._fail(job_id, exc)

    def run_training_submission(self, job_id: str) -> None:
        request = self._start(
            job_id,
            expected_type="training_submission",
            stage="materializing_export",
        )
        if request is None:
            return
        try:
            if self.training_workflow is None:
                raise RuntimeError("UnitTrain workflow is not configured")
            run_id = cast(str, request["training_run_id"])
            run = self.training_workflow.submit(
                run_id,
                lambda stage, processed, total: self._progress(
                    job_id,
                    stage=stage,
                    processed=processed,
                    total=total,
                ),
            )
            self._succeed(
                job_id,
                public_result={
                    "training_run_id": run.id,
                    "unitrain_run_id": run.unitrain_run_id,
                    "status": run.status.value,
                },
                total_count=2,
            )
        except Exception as exc:
            self._fail(job_id, exc)

    def _start(
        self,
        job_id: str,
        *,
        expected_type: str,
        stage: str,
    ) -> dict[str, object] | None:
        with self.session_factory() as session, session.begin():
            job = session.get(BackgroundJob, job_id)
            if job is None or job.job_type != expected_type:
                return None
            if job.status not in {JobStatus.PENDING, JobStatus.FAILED}:
                return None
            request = job.result.get("request")
            if not isinstance(request, dict):
                self._set_failed(job, RuntimeError("Background job request is missing"))
                return None
            job.status = JobStatus.RUNNING
            job.stage = stage
            job.started_at = datetime.now(timezone.utc)
            job.finished_at = None
            job.error_summary = {}
            job.log_path = str(self._log_path(job.id))
            self._append_log(job.id, f"started {expected_type}")
            return cast(dict[str, object], request)

    def _succeed(
        self,
        job_id: str,
        *,
        public_result: dict[str, object],
        total_count: int,
    ) -> None:
        with self.session_factory() as session, session.begin():
            job = session.get(BackgroundJob, job_id)
            if job is None:
                return
            request = job.result.get("request")
            job.result = {"request": request, "output": public_result}
            job.status = JobStatus.SUCCEEDED
            job.stage = "done"
            job.total_count = total_count
            job.processed_count = total_count
            job.finished_at = datetime.now(timezone.utc)
            self._append_log(job.id, "completed")

    def _progress(
        self,
        job_id: str,
        *,
        stage: str,
        processed: int,
        total: int,
    ) -> None:
        with self.session_factory() as session, session.begin():
            job = session.get(BackgroundJob, job_id)
            if job is None or job.status is not JobStatus.RUNNING:
                return
            job.stage = stage
            job.processed_count = max(0, processed)
            job.total_count = max(0, total)

    def _fail(self, job_id: str, error: Exception) -> None:
        with self.session_factory() as session, session.begin():
            job = session.get(BackgroundJob, job_id)
            if job is None:
                return
            self._set_failed(job, error)
            if job.job_type == "dataset_registration" and job.business_object_id is not None:
                dataset = session.get(Dataset, job.business_object_id)
                request = job.result.get("request")
                source_id = request.get("dataset_source_id") if isinstance(request, dict) else None
                source = session.get(DatasetSource, source_id) if isinstance(source_id, str) else None
                if dataset is not None:
                    dataset.status = "validation_failed"
                if source is not None:
                    source.scan_status = "failed"
            if job.job_type == "training_submission" and job.business_object_id is not None:
                run = session.get(TrainingRun, job.business_object_id)
                if run is not None and run.unitrain_run_id is None:
                    run.status = TrainingStatus.FAILED
                    run.completed_at = datetime.now(timezone.utc)
                    run.error_summary = {
                        "code": "submission_failed",
                        "type": type(error).__name__,
                        "message": str(error),
                    }
            self._append_log(job.id, f"failed: {error}")

    @staticmethod
    def _set_failed(job: BackgroundJob, error: Exception) -> None:
        job.status = JobStatus.FAILED
        job.stage = "failed"
        job.finished_at = datetime.now(timezone.utc)
        job.error_summary = {
            "code": "job_failed",
            "type": type(error).__name__,
            "message": str(error),
        }

    def _log_path(self, job_id: str) -> Path:
        return self.log_root / f"{job_id}.log"

    def _append_log(self, job_id: str, message: str) -> None:
        try:
            self.log_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).isoformat()
            with self._log_path(job_id).open("a", encoding="utf-8") as log:
                log.write(f"{timestamp} {message}\n")
        except OSError as exc:
            logger.warning("Could not write background job log %s: %s", job_id, exc)


def run_analysis_job(job_id: str) -> None:
    _run_default(job_id, job_kind="analysis")


def run_registration_job(job_id: str) -> None:
    _run_default(job_id, job_kind="registration")


def run_review_creation_job(job_id: str) -> None:
    _run_default(job_id, job_kind="review_creation")


def run_review_export_job(job_id: str) -> None:
    _run_default(job_id, job_kind="review_export")


def run_training_submission_job(job_id: str) -> None:
    _run_default(job_id, job_kind="training_submission")


def _run_default(job_id: str, *, job_kind: str) -> None:
    settings = Settings()
    engine = create_engine_from_settings(settings)
    connectors: list[object] = []
    try:
        session_factory = create_session_factory(engine)
        review_workflow = None
        training_workflow = None
        if job_kind in {"review_creation", "review_export"}:
            label_studio = create_label_studio_connector(settings)
            connectors.append(label_studio)
            review_workflow = ReviewWorkflow(
                session_factory,
                managed_root=settings.managed_data_root,
                export_root=settings.label_studio_export_root,
                label_studio_mount_root=settings.label_studio_mount_root,
                label_studio_base_url=settings.label_studio_public_url,
                connector=label_studio,
            )
        if job_kind == "training_submission":
            unitrain = create_unitrain_connector(settings)
            connectors.append(unitrain)
            training_workflow = TrainingWorkflow(
                session_factory,
                managed_root=settings.managed_data_root,
                export_root=settings.unitrain_export_root,
                unitrain_mount_root=settings.unitrain_mount_root,
                connector=unitrain,
            )
        runner = JobRunner(
            session_factory,
            managed_root=settings.managed_data_root,
            review_workflow=review_workflow,
            training_workflow=training_workflow,
        )
        if job_kind == "registration":
            runner.run_registration(job_id)
        elif job_kind == "analysis":
            runner.run_analysis(job_id)
        elif job_kind == "review_creation":
            runner.run_review_creation(job_id)
        elif job_kind == "review_export":
            runner.run_review_export(job_id)
        elif job_kind == "training_submission":
            runner.run_training_submission(job_id)
        else:
            raise RuntimeError(f"Unknown job kind: {job_kind}")
    finally:
        for connector in connectors:
            close = getattr(connector, "close", None)
            if callable(close):
                close()
        engine.dispose()
