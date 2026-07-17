import json
from pathlib import Path
from threading import Event
import time

from fastapi.testclient import TestClient

from unitrain_api.app import create_app
from unitrain_api.config import UnitTrainAPISettings
from unitrain_api.schemas import CreateRunRequest, RunStatus
from unitrain_api.service import RunManager


class FakeProcess:
    def __init__(self, pid: int = 31415):
        self.pid = pid
        self.return_code = 0
        self.finished = Event()
        self.stopped = False

    def wait(self) -> int:
        self.finished.wait(timeout=5)
        return self.return_code

    def stop(self, timeout_seconds: float) -> None:
        self.stopped = True
        self.return_code = -15
        self.finished.set()


class FakeLauncher:
    def __init__(self):
        self.processes: list[FakeProcess] = []
        self.commands: list[list[str]] = []

    def launch(self, command, *, cwd: Path, log_path: Path) -> FakeProcess:
        process = FakeProcess(pid=31415 + len(self.processes))
        self.processes.append(process)
        self.commands.append(list(command))
        log_path.write_text("epoch 1/2\nepoch 2/2\n", encoding="utf-8")
        return process


def make_payload(dataset_root: Path) -> CreateRunRequest:
    (dataset_root / "annotations").mkdir(parents=True)
    (dataset_root / "annotations" / "instances.coco.json").write_text("{}", encoding="utf-8")
    return CreateRunRequest(
        dataset_version_id="warehouse-v2",
        dataset_path=str(dataset_root),
        annotation_path="annotations/instances.coco.json",
        task_type="detection",
        export_profile="unitrain-coco-split-v1",
        idempotency_key="platform-run-1",
        config={"epochs": 2, "batch_size": 4},
    )


def wait_for_status(manager: RunManager, run_id: str, status: RunStatus) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if manager.get_run(run_id).status is status:
            return
        time.sleep(0.01)
    raise AssertionError(f"run did not become {status}")


def test_manager_persists_run_logs_metrics_and_models(tmp_path):
    settings = UnitTrainAPISettings(run_root=tmp_path / "runs", public_url="http://unitrain.test")
    launcher = FakeLauncher()
    manager = RunManager(settings, launcher=launcher, project_root=tmp_path)
    run = manager.create_run(make_payload(tmp_path / "dataset"))

    assert run.status is RunStatus.RUNNING
    assert run.detail_url == f"http://unitrain.test/runs/{run.id}"
    assert "cli/train.py" not in " ".join(launcher.commands[0])
    assert "run.sh" not in " ".join(launcher.commands[0])

    run_dir = manager.store.run_dir(run.id)
    metrics_path = run_dir / "artifacts" / "evaluation" / "eval_metrics.json"
    metrics_path.parent.mkdir(parents=True)
    metrics_path.write_text(
        json.dumps(
            {
                "overall": {"mAP50": 0.91, "precision": 0.88},
                "training_log": {"epochs": [{"epoch": 1, "train_loss": 0.4}]},
            }
        ),
        encoding="utf-8",
    )
    model_path = run_dir / "artifacts" / "train" / "weights" / "best.pt"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"weights")
    report_path = run_dir / "artifacts" / "evaluation" / "report.md"
    report_path.write_text("report", encoding="utf-8")
    manager.store.write_result(run.id, {"metrics_path": "artifacts/evaluation/eval_metrics.json"})
    launcher.processes[0].finished.set()
    wait_for_status(manager, run.id, RunStatus.COMPLETED)

    persisted = manager.get_run(run.id)
    logs = manager.store.read_logs(run.id, offset=1, limit=1)
    metrics = manager.store.read_metrics(run.id)
    models = manager.store.list_models()

    assert persisted.metric_summary["mAP50"] == 0.91
    assert logs.lines == ["epoch 2/2"]
    assert metrics.history == [{"epoch": 1, "train_loss": 0.4}]
    assert len(models) == 1
    assert manager.store.get_model(models[0].id).relative_path.endswith("best.pt")
    assert manager.store.get_model_artifact(
        models[0].id,
        "artifacts/evaluation/report.md",
    ) == report_path


def test_manager_stops_only_owned_process(tmp_path):
    settings = UnitTrainAPISettings(run_root=tmp_path / "runs")
    launcher = FakeLauncher()
    manager = RunManager(settings, launcher=launcher, project_root=tmp_path)
    run = manager.create_run(make_payload(tmp_path / "dataset"))

    stopped = manager.stop_run(run.id)

    assert stopped.status is RunStatus.STOPPED
    assert launcher.processes[0].stopped is True


def test_http_contract_auth_validation_and_pagination(tmp_path):
    settings = UnitTrainAPISettings(
        run_root=tmp_path / "runs",
        api_token="secret-token",
        public_url="http://unitrain.test",
    )
    launcher = FakeLauncher()
    manager = RunManager(settings, launcher=launcher, project_root=tmp_path)
    app = create_app(settings, manager=manager)
    payload = make_payload(tmp_path / "dataset").model_dump(mode="json")

    with TestClient(app) as client:
        assert client.get("/health").status_code == 401
        headers = {"Authorization": "Bearer secret-token"}
        created = client.post("/runs", json=payload, headers=headers)
        assert created.status_code == 202
        run_id = created.json()["id"]
        repeated = client.post("/runs", json=payload, headers=headers)
        assert repeated.json()["id"] == run_id
        assert len(launcher.processes) == 1

        assert client.get(f"/runs/{run_id}", headers=headers).status_code == 200
        logs = client.get(f"/runs/{run_id}/logs?offset=0&limit=1", headers=headers)
        assert logs.json()["truncated"] is True
        assert client.get("/models?page=1&page_size=20", headers=headers).status_code == 200
        assert client.post(f"/runs/{run_id}/stop", headers=headers).json()["status"] == "stopped"

        bad = dict(payload)
        bad["dataset_path"] = "relative/path"
        assert client.post("/runs", json=bad, headers=headers).status_code == 422


def test_http_create_run_reports_storage_errors(tmp_path, monkeypatch):
    settings = UnitTrainAPISettings(run_root=tmp_path / "runs", api_token="secret-token")
    manager = RunManager(settings, launcher=FakeLauncher(), project_root=tmp_path)

    def fail_create_run(_payload):
        raise PermissionError(13, "Permission denied", "/data/runs")

    monkeypatch.setattr(manager, "create_run", fail_create_run)
    app = create_app(settings, manager=manager)
    headers = {"Authorization": "Bearer secret-token"}

    with TestClient(app) as client:
        response = client.post(
            "/runs",
            json=make_payload(tmp_path / "dataset").model_dump(mode="json"),
            headers=headers,
        )

    assert response.status_code == 500
    assert response.json()["detail"].startswith("UnitTrain storage error:")
    assert "/data/runs" in response.json()["detail"]
