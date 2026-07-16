from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from label_platform.config import Settings


class LabelStudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class LabelStudioProgress:
    total: int
    completed: int
    skipped: int


class LabelStudioConnector(Protocol):
    def health(self) -> str: ...

    def create_project(self, title: str, description: str) -> int: ...

    def configure_labels(self, project_id: int, label_config: str) -> None: ...

    def create_local_storage(self, project_id: int, version_path: str) -> int: ...

    def import_tasks(
        self,
        project_id: int,
        tasks: list[dict[str, object]],
    ) -> dict[str, int]: ...

    def get_task_bindings(self, project_id: int) -> dict[str, int]: ...

    def get_review_url(self, project_id: int) -> str: ...

    def get_progress(self, project_id: int) -> LabelStudioProgress: ...

    def export_annotations(self, project_id: int, output_path: Path) -> Path: ...

    def archive_project(self, project_id: int) -> None: ...


class LabelStudioHttpConnector:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = 120,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def health(self) -> str:
        self._request("GET", "/health", timeout=5)
        response = self._request("GET", "/api/version/", timeout=5)
        payload = self._json_object(response)
        return str(payload.get("label-studio-version") or payload.get("version") or "unknown")

    def create_project(self, title: str, description: str) -> int:
        response = self._request(
            "POST",
            "/api/projects",
            json={"title": title, "description": description},
        )
        return self._required_int(self._json_object(response), "id")

    def configure_labels(self, project_id: int, label_config: str) -> None:
        self._request(
            "PATCH",
            f"/api/projects/{project_id}",
            json={"label_config": label_config},
        )

    def create_local_storage(self, project_id: int, version_path: str) -> int:
        response = self._request(
            "GET",
            "/api/storages/localfiles",
            params={"project": project_id},
        )
        payload: object = response.json()
        storages = payload if isinstance(payload, list) else []
        for storage in storages:
            if isinstance(storage, dict) and storage.get("path") == version_path:
                return self._required_int(storage, "id")
        created = self._request(
            "POST",
            "/api/storages/localfiles",
            json={
                "project": project_id,
                "title": "Platform managed dataset",
                "path": version_path,
                "use_blob_urls": True,
                "regex_filter": r".*\.(jpg|jpeg|png|webp)$",
            },
        )
        return self._required_int(self._json_object(created), "id")

    def import_tasks(
        self,
        project_id: int,
        tasks: list[dict[str, object]],
    ) -> dict[str, int]:
        if not tasks:
            return {}
        response = self._request(
            "POST",
            f"/api/projects/{project_id}/import",
            params={"commit_to_project": "true", "return_task_ids": "true"},
            json=tasks,
        )
        payload = self._json_object(response)
        task_ids = payload.get("task_ids")
        if not isinstance(task_ids, list) or len(task_ids) != len(tasks):
            raise LabelStudioError("Label Studio returned an incomplete task ID list")
        bindings: dict[str, int] = {}
        for task, task_id in zip(tasks, task_ids, strict=True):
            data = task.get("data")
            sample_key = data.get("sample_key") if isinstance(data, dict) else None
            if not isinstance(sample_key, str) or isinstance(task_id, bool) or not isinstance(task_id, int):
                raise LabelStudioError("Label Studio task binding response is invalid")
            bindings[sample_key] = task_id
        return bindings

    def get_task_bindings(self, project_id: int) -> dict[str, int]:
        bindings: dict[str, int] = {}
        page = 1
        while True:
            response = self._request(
                "GET",
                "/api/tasks",
                params={
                    "project": project_id,
                    "page": page,
                    "page_size": 100,
                    "fields": "all",
                },
            )
            payload: object = response.json()
            total: int | None
            if isinstance(payload, list):
                tasks = payload
                total = len(tasks)
            elif isinstance(payload, dict):
                tasks = payload.get("tasks") or payload.get("results") or []
                raw_total = payload.get("total") or payload.get("count")
                total = raw_total if isinstance(raw_total, int) else None
            else:
                raise LabelStudioError("Label Studio task list response is invalid")
            if not isinstance(tasks, list):
                raise LabelStudioError("Label Studio task list response is invalid")
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                task_id = task.get("id")
                data = task.get("data")
                sample_key = data.get("sample_key") if isinstance(data, dict) else None
                if (
                    isinstance(task_id, int)
                    and not isinstance(task_id, bool)
                    and isinstance(sample_key, str)
                ):
                    previous = bindings.get(sample_key)
                    if previous is not None and previous != task_id:
                        raise LabelStudioError("Label Studio contains duplicate platform sample keys")
                    bindings[sample_key] = task_id
            if isinstance(payload, list) or len(tasks) < 100:
                break
            if total is not None and page * 100 >= total:
                break
            page += 1
            if page > 100_000:
                raise LabelStudioError("Label Studio task pagination did not terminate")
        return bindings

    def get_review_url(self, project_id: int) -> str:
        return f"{self.base_url}/projects/{project_id}/data"

    def get_progress(self, project_id: int) -> LabelStudioProgress:
        payload = self._json_object(self._request("GET", f"/api/projects/{project_id}"))
        return LabelStudioProgress(
            total=self._optional_int(payload, "task_number"),
            completed=self._optional_int(payload, "finished_task_number"),
            skipped=self._optional_int(payload, "skipped_annotations_number"),
        )

    def export_annotations(self, project_id: int, output_path: Path) -> Path:
        response = self._request(
            "GET",
            f"/api/projects/{project_id}/export",
            params={"exportType": "JSON", "download_all_tasks": "true"},
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(response.content)
            os.replace(temporary, output_path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise LabelStudioError("Cannot persist the Label Studio raw export") from exc
        return output_path

    def archive_project(self, project_id: int) -> None:
        self._request("PATCH", f"/api/projects/{project_id}", json={"is_published": False})

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self.token:
            raise LabelStudioError("Label Studio token is not configured")
        headers = dict(cast(dict[str, str], kwargs.pop("headers", {})))
        headers["Authorization"] = self._authorization_header()
        try:
            response = self.client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LabelStudioError(f"Label Studio request failed: {method} {path}") from exc
        return response

    def _authorization_header(self) -> str:
        if self.token.lower().startswith(("token ", "bearer ")):
            return self.token
        return f"Bearer {self.token}" if self.token.count(".") == 2 else f"Token {self.token}"

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, object]:
        try:
            payload: object = response.json()
        except json.JSONDecodeError as exc:
            raise LabelStudioError("Label Studio returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise LabelStudioError("Label Studio returned an unexpected response")
        return payload

    @staticmethod
    def _required_int(payload: dict[str, object], key: str) -> int:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise LabelStudioError(f"Label Studio response is missing {key}")
        return value

    @staticmethod
    def _optional_int(payload: dict[str, object], key: str) -> int:
        value = payload.get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0


def create_label_studio_connector(settings: Settings) -> LabelStudioHttpConnector:
    return LabelStudioHttpConnector(
        base_url=settings.label_studio_url,
        token=settings.label_studio_api_token,
        timeout_seconds=settings.label_studio_timeout_seconds,
    )
