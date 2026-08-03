from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast
from urllib.parse import quote

import httpx

from label_platform.config import Settings
from label_platform.domain.enums import TrainingStatus


class UnitTrainConnectorError(RuntimeError):
    pass


class UnitTrainUnavailableError(UnitTrainConnectorError):
    pass


@dataclass(frozen=True)
class UnitTrainRun:
    id: str
    status: TrainingStatus
    detail_url: str
    current_epoch: int
    total_epochs: int
    metric_summary: dict[str, float]
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class UnitTrainLogs:
    offset: int
    next_offset: int
    lines: list[str]
    truncated: bool


@dataclass(frozen=True)
class UnitTrainMetrics:
    summary: dict[str, float]
    history: list[dict[str, Any]]
    evaluation: dict[str, Any]


@dataclass(frozen=True)
class UnitTrainModel:
    id: str
    run_id: str
    name: str
    framework: str
    task_type: str
    relative_path: str
    absolute_path: str
    size_bytes: int
    created_at: datetime
    metrics: dict[str, float]
    evaluation_files: list[str]


@dataclass(frozen=True)
class UnitTrainArtifact:
    content: bytes
    content_type: str
    filename: str


class UnitTrainConnector(Protocol):
    def health(self) -> str: ...

    def create_run(self, payload: dict[str, Any]) -> UnitTrainRun: ...

    def get_run(self, run_id: str) -> UnitTrainRun: ...

    def get_logs(self, run_id: str, *, offset: int, limit: int) -> UnitTrainLogs: ...

    def get_metrics(self, run_id: str) -> UnitTrainMetrics: ...

    def stop_run(self, run_id: str) -> UnitTrainRun: ...

    def list_models(self, *, page: int, page_size: int) -> tuple[list[UnitTrainModel], int]: ...

    def get_model(self, model_id: str) -> UnitTrainModel: ...

    def get_model_artifact(self, model_id: str, path: str) -> UnitTrainArtifact: ...

    def close(self) -> None: ...


class RestUnitTrainConnector:
    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Accept": "application/json"}
        if api_token:
            headers["X-API-Key"] = api_token
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    def health(self) -> str:
        payload = self._object("GET", "/health", timeout=5)
        return self._string(payload, "version")

    def create_run(self, payload: dict[str, Any]) -> UnitTrainRun:
        return self._run(self._object("POST", "/runs", json=payload))

    def get_run(self, run_id: str) -> UnitTrainRun:
        return self._run(self._object("GET", f"/runs/{run_id}"))

    def get_logs(self, run_id: str, *, offset: int, limit: int) -> UnitTrainLogs:
        payload = self._object(
            "GET",
            f"/runs/{run_id}/logs",
            params={"offset": offset, "limit": limit},
        )
        lines = payload.get("lines")
        if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
            raise UnitTrainConnectorError("UniTrain logs response is invalid")
        return UnitTrainLogs(
            offset=self._integer(payload, "offset"),
            next_offset=self._integer(payload, "next_offset"),
            lines=cast(list[str], lines),
            truncated=self._boolean(payload, "truncated"),
        )

    def get_metrics(self, run_id: str) -> UnitTrainMetrics:
        payload = self._object("GET", f"/runs/{run_id}/metrics")
        history = payload.get("history")
        evaluation = payload.get("evaluation")
        if not isinstance(history, list) or not all(isinstance(item, dict) for item in history):
            raise UnitTrainConnectorError("UniTrain metrics history is invalid")
        if not isinstance(evaluation, dict):
            raise UnitTrainConnectorError("UniTrain evaluation response is invalid")
        return UnitTrainMetrics(
            summary=self._metrics(payload.get("summary")),
            history=cast(list[dict[str, Any]], history),
            evaluation=cast(dict[str, Any], evaluation),
        )

    def stop_run(self, run_id: str) -> UnitTrainRun:
        return self._run(self._object("POST", f"/runs/{run_id}/stop"))

    def list_models(self, *, page: int, page_size: int) -> tuple[list[UnitTrainModel], int]:
        payload = self._object(
            "GET",
            "/models",
            params={"page": page, "page_size": page_size},
        )
        data = payload.get("data")
        meta = payload.get("meta")
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise UnitTrainConnectorError("UniTrain model list response is invalid")
        return [self._model(item) for item in data], self._integer(meta, "total")

    def get_model(self, model_id: str) -> UnitTrainModel:
        return self._model(self._object("GET", f"/models/{model_id}"))

    def get_model_artifact(self, model_id: str, path: str) -> UnitTrainArtifact:
        try:
            encoded_path = quote(path, safe="/")
            response = self.client.get(f"/models/{model_id}/artifacts/{encoded_path}")
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise UnitTrainUnavailableError(f"UniTrain is unavailable: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            message = self._error_message(exc.response)
            if code >= 500:
                raise UnitTrainUnavailableError(f"UniTrain returned {code}: {message}") from exc
            raise UnitTrainConnectorError(f"UniTrain returned {code}: {message}") from exc
        disposition = response.headers.get("content-disposition", "")
        filename = path.rsplit("/", 1)[-1]
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip('" ')
        return UnitTrainArtifact(
            content=response.content,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            filename=filename,
        )

    def close(self) -> None:
        self.client.close()

    def _object(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise UnitTrainUnavailableError(f"UniTrain is unavailable: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            message = self._error_message(exc.response)
            if code >= 500:
                raise UnitTrainUnavailableError(f"UniTrain returned {code}: {message}") from exc
            raise UnitTrainConnectorError(f"UniTrain returned {code}: {message}") from exc
        except (ValueError, TypeError) as exc:
            raise UnitTrainConnectorError("UniTrain returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise UnitTrainConnectorError("UniTrain response must be an object")
        return cast(dict[str, Any], payload)

    def _run(self, payload: dict[str, Any]) -> UnitTrainRun:
        try:
            run_status = TrainingStatus(self._string(payload, "status"))
        except ValueError as exc:
            raise UnitTrainConnectorError("UniTrain run status is invalid") from exc
        return UnitTrainRun(
            id=self._string(payload, "id"),
            status=run_status,
            detail_url=self._string(payload, "detail_url"),
            current_epoch=self._integer(payload, "current_epoch"),
            total_epochs=self._integer(payload, "total_epochs"),
            metric_summary=self._metrics(payload.get("metric_summary")),
            error=self._optional_string(payload, "error"),
            started_at=self._optional_datetime(payload, "started_at"),
            completed_at=self._optional_datetime(payload, "completed_at"),
        )

    def _model(self, value: object) -> UnitTrainModel:
        if not isinstance(value, dict):
            raise UnitTrainConnectorError("UniTrain model response is invalid")
        payload = cast(dict[str, Any], value)
        evaluation_files = payload.get("evaluation_files")
        if not isinstance(evaluation_files, list) or not all(
            isinstance(item, str) for item in evaluation_files
        ):
            raise UnitTrainConnectorError("UniTrain model evaluation files are invalid")
        return UnitTrainModel(
            id=self._string(payload, "id"),
            run_id=self._string(payload, "run_id"),
            name=self._string(payload, "name"),
            framework=self._string(payload, "framework"),
            task_type=self._string(payload, "task_type"),
            relative_path=self._string(payload, "relative_path"),
            absolute_path=self._string(payload, "absolute_path"),
            size_bytes=self._integer(payload, "size_bytes"),
            created_at=self._datetime(payload, "created_at"),
            metrics=self._metrics(payload.get("metrics")),
            evaluation_files=cast(list[str], evaluation_files),
        )

    @staticmethod
    def _metrics(value: object) -> dict[str, float]:
        if not isinstance(value, dict):
            raise UnitTrainConnectorError("UniTrain metric summary is invalid")
        if any(
            not isinstance(item, int | float) or isinstance(item, bool)
            for item in value.values()
        ):
            raise UnitTrainConnectorError("UniTrain metric summary contains non-numeric values")
        return {str(key): float(item) for key, item in value.items()}

    @staticmethod
    def _string(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            raise UnitTrainConnectorError(f"UniTrain response field {key} is invalid")
        return value

    @staticmethod
    def _optional_string(payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            raise UnitTrainConnectorError(f"UniTrain response field {key} is invalid")
        return value

    @staticmethod
    def _integer(payload: dict[str, Any], key: str) -> int:
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise UnitTrainConnectorError(f"UniTrain response field {key} is invalid")
        return value

    @staticmethod
    def _boolean(payload: dict[str, Any], key: str) -> bool:
        value = payload.get(key)
        if not isinstance(value, bool):
            raise UnitTrainConnectorError(f"UniTrain response field {key} is invalid")
        return value

    @classmethod
    def _datetime(cls, payload: dict[str, Any], key: str) -> datetime:
        value = cls._optional_datetime(payload, key)
        if value is None:
            raise UnitTrainConnectorError(f"UniTrain response field {key} is invalid")
        return value

    @staticmethod
    def _optional_datetime(payload: dict[str, Any], key: str) -> datetime | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise UnitTrainConnectorError(f"UniTrain response field {key} is invalid")
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise UnitTrainConnectorError(f"UniTrain response field {key} is invalid") from exc

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
            return cast(str, payload["detail"])
        return response.text[:500]


def create_unitrain_connector(settings: Settings) -> RestUnitTrainConnector:
    return RestUnitTrainConnector(
        settings.unitrain_url,
        settings.unitrain_api_token,
        timeout_seconds=settings.unitrain_timeout_seconds,
    )
