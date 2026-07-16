from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from label_platform.config import Settings
from label_platform.datasets.analysis import analyze_dataset_source
from label_platform.datasets.service import DatasetRegistrationRequest, RegistrationService
from label_platform.db.models import BackgroundJob, Dataset, DatasetSource
from label_platform.db.session import create_engine_from_settings, create_session_factory
from label_platform.domain.enums import JobStatus, TaskType


class JobRunner:
    def __init__(self, session_factory: sessionmaker[Session], *, managed_root: Path) -> None:
        self.session_factory = session_factory
        self.managed_root = managed_root
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
        self.log_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._log_path(job_id).open("a", encoding="utf-8") as log:
            log.write(f"{timestamp} {message}\n")


def run_analysis_job(job_id: str) -> None:
    _run_default(job_id, registration=False)


def run_registration_job(job_id: str) -> None:
    _run_default(job_id, registration=True)


def _run_default(job_id: str, *, registration: bool) -> None:
    settings = Settings()
    engine = create_engine_from_settings(settings)
    try:
        runner = JobRunner(
            create_session_factory(engine),
            managed_root=settings.managed_data_root,
        )
        if registration:
            runner.run_registration(job_id)
        else:
            runner.run_analysis(job_id)
    finally:
        engine.dispose()
