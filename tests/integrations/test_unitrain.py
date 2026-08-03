import json

import httpx
import pytest

from label_platform.domain.enums import TrainingStatus
from label_platform.integrations.unitrain import (
    RestUnitTrainConnector,
    UnitTrainConnectorError,
    UnitTrainUnavailableError,
)


def run_payload(run_id="run-1", status="running"):
    return {
        "id": run_id,
        "dataset_version_id": "version-2",
        "task_type": "detection",
        "export_profile": "unitrain-coco-split-v1",
        "framework": "ultralytics",
        "model": "yolo11n",
        "status": status,
        "current_epoch": 2,
        "total_epochs": 10,
        "pid": 42,
        "detail_url": f"http://unitrain.test/runs/{run_id}",
        "metric_summary": {"mAP50": 0.75},
        "error": None,
        "created_at": "2026-07-16T01:00:00Z",
        "started_at": "2026-07-16T01:00:01Z",
        "completed_at": None,
        "stopped_at": None,
    }


def test_unitrain_connector_covers_run_logs_metrics_stop_and_models():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "online", "version": "1.0.0"})
        if request.url.path == "/runs" and request.method == "POST":
            assert json.loads(request.content)["idempotency_key"] == "platform-run-1"
            return httpx.Response(202, json=run_payload())
        if request.url.path == "/runs/run-1/logs":
            return httpx.Response(
                200,
                json={
                    "run_id": "run-1",
                    "offset": 0,
                    "next_offset": 1,
                    "lines": ["epoch 1"],
                    "truncated": False,
                },
            )
        if request.url.path == "/runs/run-1/metrics":
            return httpx.Response(
                200,
                json={
                    "run_id": "run-1",
                    "summary": {"mAP50": 0.75},
                    "history": [{"epoch": 1}],
                    "evaluation": {"overall": {"mAP50": 0.75}},
                },
            )
        if request.url.path == "/runs/run-1/stop":
            return httpx.Response(200, json=run_payload(status="stopped"))
        if request.url.path == "/models":
            return httpx.Response(200, json={"data": [model_payload()], "meta": {"total": 1}})
        if request.url.path == "/models/model-1":
            return httpx.Response(200, json=model_payload())
        if request.url.path == "/models/model-1/artifacts/artifacts/evaluation/report.md":
            return httpx.Response(200, content=b"report", headers={"content-type": "text/markdown"})
        return httpx.Response(200, json=run_payload())

    connector = RestUnitTrainConnector(
        "http://unitrain.test",
        "secret",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )
    assert connector.health() == "1.0.0"
    created = connector.create_run({"idempotency_key": "platform-run-1"})
    assert created.status is TrainingStatus.RUNNING
    assert connector.get_run("run-1").metric_summary == {"mAP50": 0.75}
    assert connector.get_logs("run-1", offset=0, limit=100).lines == ["epoch 1"]
    assert connector.get_metrics("run-1").history == [{"epoch": 1}]
    assert connector.stop_run("run-1").status is TrainingStatus.STOPPED
    models, total = connector.list_models(page=1, page_size=20)
    assert total == 1 and models[0].id == "model-1"
    assert connector.get_model("model-1").run_id == "run-1"
    artifact = connector.get_model_artifact("model-1", "artifacts/evaluation/report.md")
    assert artifact.content == b"report" and artifact.content_type == "text/markdown"
    assert all(request.headers["x-api-key"] == "secret" for request in requests)


def model_payload():
    return {
        "id": "model-1",
        "run_id": "run-1",
        "name": "best.pt",
        "framework": "ultralytics",
        "task_type": "detection",
        "relative_path": "artifacts/train/weights/best.pt",
        "absolute_path": "/srv/unitrain/runs/run-1/artifacts/train/weights/best.pt",
        "size_bytes": 100,
        "created_at": "2026-07-16T02:00:00Z",
        "metrics": {"mAP50": 0.75},
        "evaluation_files": ["artifacts/evaluation/report.md"],
    }


@pytest.mark.parametrize("status_code", [401, 500])
def test_unitrain_connector_classifies_http_failures(status_code):
    connector = RestUnitTrainConnector(
        "http://unitrain.test",
        "",
        timeout_seconds=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status_code, json={"detail": "offline"})
        ),
    )
    expected = UnitTrainUnavailableError if status_code == 500 else UnitTrainConnectorError
    with pytest.raises(expected, match="offline"):
        connector.health()
