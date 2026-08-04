from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
from threading import Lock, Thread
from uuid import uuid4

from unitrain_api.config import UnitTrainAPISettings
from unitrain_api.launcher import (
    ProcessHandle,
    ProcessLauncher,
    SubprocessLauncher,
    recover_process,
)
from unitrain_api.schemas import CreateRunRequest, RunRecord, RunStatus
from unitrain_api.store import RunStore


class RunConflictError(RuntimeError):
    pass


class RunManager:
    def __init__(
        self,
        settings: UnitTrainAPISettings,
        *,
        launcher: ProcessLauncher | None = None,
        project_root: Path | None = None,
    ):
        self.settings = settings
        self.store = RunStore(settings.run_root)
        self.launcher = launcher or SubprocessLauncher()
        self.project_root = (project_root or Path(__file__).parent.parent).resolve()
        self._lock = Lock()
        self._handles: dict[str, ProcessHandle] = {}
        self._recover_active_runs()
        self._cleanup_terminal_prepared()

    def create_run(self, payload: CreateRunRequest) -> RunRecord:
        self._validate_paths(payload)
        with self._lock:
            self._cleanup_terminal_prepared()
            if payload.idempotency_key is not None:
                existing = self.store.find_by_idempotency_key(payload.idempotency_key)
                if existing is not None:
                    record, stored_payload = existing
                    if stored_payload != payload:
                        raise RunConflictError(
                            "Idempotency key was already used with a different request"
                        )
                    return self._refresh_metrics(record)
            active = sum(
                run.status in {RunStatus.QUEUED, RunStatus.RUNNING}
                for run in self.store.list_runs()
            )
            if active >= self.settings.max_concurrent_runs:
                raise RunConflictError("UnitTrain concurrency limit reached")

            run_id = str(uuid4())
            created_at = datetime.now(timezone.utc)
            record = RunRecord(
                id=run_id,
                dataset_version_id=payload.dataset_version_id,
                task_type=payload.task_type,
                export_profile=payload.export_profile,
                framework=payload.config.framework,
                model=payload.config.model,
                status=RunStatus.QUEUED,
                total_epochs=payload.config.epochs,
                detail_url=f"{self.settings.public_url.rstrip('/')}/runs/{run_id}",
                created_at=created_at,
            )
            self.store.create(record, payload)

            command = [
                sys.executable,
                "-u",
                "-m",
                "unitrain_api.worker",
                "--run-id",
                run_id,
                "--run-root",
                str(self.store.root),
            ]
            try:
                handle = self.launcher.launch(
                    command,
                    cwd=self.project_root,
                    log_path=self.store.run_dir(run_id) / "run.log",
                )
            except Exception as exc:
                record.status = RunStatus.FAILED
                record.error = f"Could not start training process: {exc}"
                record.completed_at = datetime.now(timezone.utc)
                self.store.save(record)
                return record

            record.status = RunStatus.RUNNING
            record.pid = handle.pid
            record.started_at = datetime.now(timezone.utc)
            self._handles[run_id] = handle
            self.store.save(record)
            Thread(
                target=self._monitor,
                args=(run_id, handle),
                name=f"unitrain-run-{run_id}",
                daemon=True,
            ).start()
            return record

    def get_run(self, run_id: str) -> RunRecord:
        self._cleanup_terminal_prepared()
        return self._refresh_metrics(self.store.get(run_id))

    def list_runs(self) -> list[RunRecord]:
        self._cleanup_terminal_prepared()
        return [self._refresh_metrics(run) for run in self.store.list_runs()]

    def stop_run(self, run_id: str) -> RunRecord:
        with self._lock:
            record = self.store.get(run_id)
            if record.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                raise RunConflictError(f"Run is already {record.status.value}")
            handle = self._handles.get(run_id)
            if handle is None:
                raise RunConflictError("Run process is not owned by this service instance")
            handle.stop(self.settings.stop_timeout_seconds)
            record = self.store.get(run_id)
            record.status = RunStatus.STOPPED
            record.stopped_at = datetime.now(timezone.utc)
            record.completed_at = record.stopped_at
            record.error = None
            self.store.save(record)
            self._handles.pop(run_id, None)
            self._cleanup_prepared(record)
            return record

    def _monitor(self, run_id: str, handle: ProcessHandle) -> None:
        return_code = handle.wait()
        with self._lock:
            record = self.store.get(run_id)
            self._handles.pop(run_id, None)
            if record.status is RunStatus.STOPPED:
                return
            record.completed_at = datetime.now(timezone.utc)
            if return_code == 0 and self.store.read_result(run_id):
                record.status = RunStatus.COMPLETED
                record.error = None
            else:
                record.status = RunStatus.FAILED
                record.error = (
                    f"Training process exited with code {return_code}"
                    if return_code != 0
                    else "Training process exited without a result"
                )
            self.store.save(self._refresh_metrics(record))
            self._cleanup_prepared(record)

    def _refresh_metrics(self, record: RunRecord) -> RunRecord:
        metrics = self.store.read_metrics(record.id)
        if metrics.summary != record.metric_summary:
            record.metric_summary = metrics.summary
        history_epochs: list[int] = []
        for item in metrics.history:
            epoch = item.get("epoch")
            if isinstance(epoch, int) and not isinstance(epoch, bool):
                history_epochs.append(epoch)
        if history_epochs:
            record.current_epoch = max(record.current_epoch, max(history_epochs))
        inferred = self.store.infer_epoch(record.id)
        if inferred is not None:
            record.current_epoch = max(record.current_epoch, inferred[0])
            record.total_epochs = max(record.total_epochs, inferred[1])
        return record

    def _recover_active_runs(self) -> None:
        for record in self.store.list_runs():
            if record.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                continue
            if self.store.read_result(record.id):
                record.status = RunStatus.COMPLETED
                record.completed_at = datetime.now(timezone.utc)
                self.store.save(self._refresh_metrics(record))
                continue
            handle = (
                recover_process(record.pid, record.id)
                if record.pid is not None
                else None
            )
            if handle is None:
                record.status = RunStatus.FAILED
                record.error = "Training process was not running when the service restarted"
                record.completed_at = datetime.now(timezone.utc)
                self.store.save(record)
                continue
            self._handles[record.id] = handle
            Thread(
                target=self._monitor,
                args=(record.id, handle),
                name=f"unitrain-recovered-{record.id}",
                daemon=True,
            ).start()

    def _cleanup_terminal_prepared(self) -> None:
        for record in self.store.list_runs():
            self._cleanup_prepared(record)

    def _cleanup_prepared(self, record: RunRecord) -> None:
        remove = record.status in {RunStatus.COMPLETED, RunStatus.STOPPED}
        if record.status is RunStatus.FAILED and record.completed_at is not None:
            age_hours = (
                datetime.now(timezone.utc) - record.completed_at
            ).total_seconds() / 3600
            remove = age_hours >= self.settings.failed_prepared_retention_hours
        if not remove:
            return
        prepared = self.store.run_dir(record.id) / "prepared"
        if prepared.is_symlink() or prepared.is_file():
            prepared.unlink(missing_ok=True)
        elif prepared.is_dir():
            shutil.rmtree(prepared)

    @staticmethod
    def _validate_paths(payload: CreateRunRequest) -> None:
        dataset_path = Path(payload.dataset_path).resolve()
        if not dataset_path.is_dir():
            raise ValueError("dataset_path does not exist or is not a directory")
        annotation_path = (dataset_path / payload.annotation_path).resolve()
        try:
            annotation_path.relative_to(dataset_path)
        except ValueError as exc:
            raise ValueError("annotation_path escapes dataset_path") from exc
        if not annotation_path.is_file():
            raise ValueError("annotation_path does not exist")
