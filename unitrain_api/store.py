from collections.abc import Iterator
from datetime import datetime, timezone
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
from typing import Any

from unitrain_api.schemas import (
    CreateRunRequest,
    ModelRecord,
    RunLogs,
    RunMetrics,
    RunRecord,
)


_RUN_ID_PATTERN = re.compile(r"^[0-9a-f-]{36}$")
_MODEL_SUFFIXES = {".pt", ".pth", ".onnx", ".engine", ".torchscript"}
_EPOCH_PATTERNS = (
    re.compile(r"\b[Ee]poch\s+(\d+)\s*/\s*(\d+)"),
    re.compile(r"\b(\d+)\s*/\s*(\d+)\s+[Ee]pochs?\b"),
)


class RunNotFoundError(LookupError):
    pass


class ModelNotFoundError(LookupError):
    pass


class RunStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._lock = RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise RunNotFoundError(run_id)
        return self.root / run_id

    def create(self, record: RunRecord, request: CreateRunRequest) -> None:
        run_dir = self.run_dir(record.id)
        with self._lock:
            run_dir.mkdir(mode=0o750)
            (run_dir / "artifacts").mkdir()
            self._write_json(run_dir / "request.json", request.model_dump(mode="json"))
            self.save(record)
            (run_dir / "run.log").touch(mode=0o640)

    def save(self, record: RunRecord) -> None:
        with self._lock:
            self._write_json(
                self.run_dir(record.id) / "status.json",
                record.model_dump(mode="json"),
            )

    def get(self, run_id: str) -> RunRecord:
        path = self.run_dir(run_id) / "status.json"
        if not path.is_file():
            raise RunNotFoundError(run_id)
        return RunRecord.model_validate(self._read_json(path))

    def get_request(self, run_id: str) -> CreateRunRequest:
        path = self.run_dir(run_id) / "request.json"
        if not path.is_file():
            raise RunNotFoundError(run_id)
        return CreateRunRequest.model_validate(self._read_json(path))

    def list_runs(self) -> list[RunRecord]:
        records: list[RunRecord] = []
        for path in self.root.glob("*/status.json"):
            try:
                records.append(RunRecord.model_validate(self._read_json(path)))
            except (OSError, ValueError):
                continue
        return sorted(records, key=lambda run: (run.created_at, run.id), reverse=True)

    def find_by_idempotency_key(
        self,
        key: str,
    ) -> tuple[RunRecord, CreateRunRequest] | None:
        for record in self.list_runs():
            request = self.get_request(record.id)
            if request.idempotency_key == key:
                return record, request
        return None

    def read_logs(self, run_id: str, *, offset: int, limit: int) -> RunLogs:
        log_path = self.run_dir(run_id) / "run.log"
        if not log_path.is_file():
            raise RunNotFoundError(run_id)
        with log_path.open("r", encoding="utf-8", errors="replace") as stream:
            page = list(islice(stream, offset, offset + limit + 1))
        selected = [line.rstrip("\n") for line in page[:limit]]
        next_offset = offset + len(selected)
        return RunLogs(
            run_id=run_id,
            offset=offset,
            next_offset=next_offset,
            lines=selected,
            truncated=len(page) > limit,
        )

    def infer_epoch(self, run_id: str) -> tuple[int, int] | None:
        log_path = self.run_dir(run_id) / "run.log"
        if not log_path.is_file():
            return None
        current = 0
        total = 0
        with log_path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                for pattern in _EPOCH_PATTERNS:
                    match = pattern.search(line)
                    if match is not None:
                        current = max(current, int(match.group(1)))
                        total = max(total, int(match.group(2)))
        return (current, total) if current > 0 and total > 0 else None

    def read_result(self, run_id: str) -> dict[str, Any]:
        result_path = self.run_dir(run_id) / "result.json"
        if not result_path.is_file():
            return {}
        value = self._read_json(result_path)
        return value if isinstance(value, dict) else {}

    def write_result(self, run_id: str, result: dict[str, Any]) -> None:
        self._write_json(self.run_dir(run_id) / "result.json", result)

    def read_metrics(self, run_id: str) -> RunMetrics:
        record = self.get(run_id)
        run_dir = self.run_dir(run_id)
        candidates = self._metrics_candidates(run_dir, self.read_result(run_id))
        raw: dict[str, Any] = {}
        for candidate in candidates:
            if candidate.is_file():
                value = self._read_json(candidate)
                if isinstance(value, dict):
                    raw = value
                    break
        summary = self._numeric_values(raw.get("overall", {}))
        history_value = raw.get("training_log", {})
        if isinstance(history_value, dict):
            history_value = history_value.get("epochs", [])
        history = (
            [item for item in history_value if isinstance(item, dict)]
            if isinstance(history_value, list)
            else []
        )
        if not summary:
            summary = record.metric_summary
        return RunMetrics(
            run_id=run_id,
            summary=summary,
            history=history,
            evaluation=raw,
        )

    def list_models(self) -> list[ModelRecord]:
        models: list[ModelRecord] = []
        for run in self.list_runs():
            models.extend(self._models_for_run(run))
        return sorted(models, key=lambda model: (model.created_at, model.id), reverse=True)

    def get_model(self, model_id: str) -> ModelRecord:
        for model in self.list_models():
            if model.id == model_id:
                return model
        raise ModelNotFoundError(model_id)

    def get_model_artifact(self, model_id: str, relative_path: str) -> Path:
        model = self.get_model(model_id)
        if relative_path not in model.evaluation_files:
            raise ModelNotFoundError(relative_path)
        run_dir = self.run_dir(model.run_id)
        candidate = (run_dir / relative_path).resolve(strict=True)
        if not candidate.is_relative_to(run_dir) or not candidate.is_file():
            raise ModelNotFoundError(relative_path)
        return candidate

    def _models_for_run(self, run: RunRecord) -> list[ModelRecord]:
        run_dir = self.run_dir(run.id)
        artifacts = run_dir / "artifacts"
        if not artifacts.is_dir():
            return []
        evaluation_files = [
            str(path.relative_to(run_dir))
            for path in sorted(artifacts.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".json", ".csv", ".md", ".png"}
            and (
                any(part.startswith("eval") for part in path.parts)
                or "report" in path.name.lower()
            )
        ]
        metrics = self.read_metrics(run.id).summary
        records: list[ModelRecord] = []
        for path in sorted(artifacts.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _MODEL_SUFFIXES:
                continue
            relative = str(path.relative_to(run_dir))
            model_id = hashlib.sha256(f"{run.id}:{relative}".encode()).hexdigest()[:24]
            stat = path.stat()
            records.append(
                ModelRecord(
                    id=model_id,
                    run_id=run.id,
                    name=path.name,
                    framework=run.framework,
                    task_type=run.task_type,
                    relative_path=relative,
                    size_bytes=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    metrics=metrics,
                    evaluation_files=evaluation_files,
                )
            )
        return records

    def _metrics_candidates(self, run_dir: Path, result: dict[str, Any]) -> Iterator[Path]:
        metrics_path = result.get("metrics_path")
        if isinstance(metrics_path, str) and metrics_path:
            candidate = Path(metrics_path)
            if not candidate.is_absolute():
                candidate = run_dir / candidate
            try:
                candidate.resolve().relative_to(run_dir)
            except ValueError:
                pass
            else:
                yield candidate
        yield from sorted((run_dir / "artifacts").rglob("eval_metrics.json"))

    @staticmethod
    def _numeric_values(value: object) -> dict[str, float]:
        if not isinstance(value, dict):
            return {}
        return {
            str(key): float(item)
            for key, item in value.items()
            if isinstance(item, int | float) and not isinstance(item, bool)
        }

    @staticmethod
    def _read_json(path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
