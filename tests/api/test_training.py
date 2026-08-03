from datetime import datetime, timezone
import json

from label_platform.db.models import Dataset, DatasetVersion, TrainingRun
from label_platform.domain.enums import TrainingStatus, VersionStatus
from label_platform.integrations.unitrain import (
    UnitTrainArtifact,
    UnitTrainLogs,
    UnitTrainMetrics,
    UnitTrainModel,
    UnitTrainRun,
)
from label_platform.jobs.queue import InlineJobQueue
from label_platform.jobs.tasks import JobRunner
from label_platform.training.service import TrainingWorkflow


class FakeUnitTrainConnector:
    def __init__(self):
        self.create_count = 0
        self.status = TrainingStatus.RUNNING

    def health(self) -> str:
        return "1.0.0"

    def create_run(self, payload):
        self.create_count += 1
        assert payload["dataset_version_id"] == "version-training-api"
        assert payload["dataset_path"].endswith(
            "version-training-api/unitrain-coco-split-v1"
        )
        assert payload["annotation_path"] == "train/_annotations.coco.json"
        assert payload["idempotency_key"]
        return self._run()

    def get_run(self, run_id):
        assert run_id == "remote-run-1"
        return self._run()

    def get_logs(self, run_id, *, offset, limit):
        assert run_id == "remote-run-1"
        return UnitTrainLogs(
            offset=offset,
            next_offset=offset + 1,
            lines=["epoch 3/10"],
            truncated=False,
        )

    def get_metrics(self, run_id):
        assert run_id == "remote-run-1"
        return UnitTrainMetrics(
            summary={"mAP50": 0.82, "mAP50_95": 0.61, "precision": 0.8, "recall": 0.7},
            history=[{"epoch": 3, "train_loss": 0.4, "mAP50": 0.82}],
            evaluation={
                "per_class": [
                    {"category": "cargo", "mAP50": 0.82, "mAP50_95": 0.61}
                ]
            },
        )

    def stop_run(self, run_id):
        assert run_id == "remote-run-1"
        self.status = TrainingStatus.STOPPED
        return self._run()

    def list_models(self, *, page, page_size):
        assert page == 1 and page_size == 500
        return [self._model()], 1

    def get_model(self, model_id):
        assert model_id == "model-1"
        return self._model()

    def get_model_artifact(self, model_id, path):
        assert model_id == "model-1"
        assert path == "artifacts/evaluation/report.md"
        return UnitTrainArtifact(
            content=b"report",
            content_type="text/markdown",
            filename="report.md",
        )

    def close(self):
        pass

    def _run(self):
        now = datetime.now(timezone.utc)
        return UnitTrainRun(
            id="remote-run-1",
            status=self.status,
            detail_url="http://unitrain.test/runs/remote-run-1",
            current_epoch=3,
            total_epochs=10,
            metric_summary={"mAP50": 0.82},
            error=None,
            started_at=now,
            completed_at=now if self.status is TrainingStatus.STOPPED else None,
        )

    def _model(self):
        return UnitTrainModel(
            id="model-1",
            run_id="remote-run-1",
            name="best.pt",
            framework="ultralytics",
            task_type="detection",
            relative_path="artifacts/train/weights/best.pt",
            absolute_path="/srv/unitrain/runs/remote-run-1/artifacts/train/weights/best.pt",
            size_bytes=1024,
            created_at=datetime.now(timezone.utc),
            metrics={"mAP50": 0.82, "mAP50_95": 0.61, "precision": 0.8, "recall": 0.7},
            evaluation_files=["artifacts/evaluation/report.md"],
        )


def prepare_ready_version(api_context):
    settings, session_factory = api_context
    with session_factory() as session, session.begin():
        dataset = Dataset(
            id="dataset-training-api",
            name="training-api",
            description="",
            status="trainable",
        )
        version = DatasetVersion(
            id="version-training-api",
            dataset=dataset,
            version_number=2,
            root_path="dataset-training-api/versions/v2",
            manifest_path="manifest.json",
            annotation_path="annotations/instances.coco.json",
            class_schema=[{"id": 1, "name": "cargo"}],
            item_count=1,
            status=VersionStatus.READY,
        )
        session.add(version)
    root = settings.managed_data_root / "dataset-training-api/versions/v2"
    (root / "images").mkdir(parents=True)
    (root / "annotations").mkdir()
    (root / "splits").mkdir()
    (root / "images/frame.jpg").write_bytes(b"image")
    (root / "manifest.json").write_text(
        json.dumps({"format": "platform-coco-v1", "task_type": "detection"}),
        encoding="utf-8",
    )
    (root / "annotations/instances.coco.json").write_text(
        json.dumps(
            {
                "info": {"format": "platform-coco-v1"},
                "images": [
                    {
                        "id": 1,
                        "sample_key": "sample-1",
                        "file_name": "images/frame.jpg",
                        "width": 10,
                        "height": 10,
                    }
                ],
                "annotations": [],
                "categories": [{"id": 1, "name": "cargo"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "splits/train.txt").write_text("sample-1\n", encoding="utf-8")
    (root / "splits/val.txt").write_text("", encoding="utf-8")
    (root / "splits/test.txt").write_text("", encoding="utf-8")


def test_training_api_submits_ready_version_and_proxies_outputs(
    client,
    api_context,
):
    settings, session_factory = api_context
    prepare_ready_version(api_context)
    connector = FakeUnitTrainConnector()
    workflow = TrainingWorkflow(
        session_factory,
        managed_root=settings.managed_data_root,
        export_root=settings.unitrain_export_root,
        unitrain_mount_root=settings.unitrain_mount_root,
        connector=connector,
    )
    runner = JobRunner(
        session_factory,
        managed_root=settings.managed_data_root,
        training_workflow=workflow,
    )
    queue = InlineJobQueue(training_submission_handler=runner.run_training_submission)
    client.app.state.unitrain_connector = connector
    client.app.state.job_queue = queue

    payload = {
        "name": "warehouse-baseline",
        "dataset_id": "dataset-training-api",
        "dataset_version_id": "version-training-api",
        "idempotency_key": "training-api-1",
        "config": {"framework": "ultralytics", "model": "yolo11n", "epochs": 10},
    }
    created = client.post("/api/training-runs", json=payload)
    repeated = client.post("/api/training-runs", json=payload)

    assert created.status_code == repeated.status_code == 202
    assert created.json()["id"] == repeated.json()["id"]
    assert created.json()["status"] == "running"
    assert created.json()["current_epoch"] == 3
    assert connector.create_count == 1
    assert queue.training_submission_enqueued_count == 1
    run_id = created.json()["id"]

    listing = client.get("/api/training-runs")
    synced = client.post(f"/api/training-runs/{run_id}/sync")
    logs = client.get(f"/api/training-runs/{run_id}/logs")
    metrics = client.get(f"/api/training-runs/{run_id}/metrics")
    models = client.get("/api/models")
    model = client.get("/api/models/model-1")
    artifact = client.get("/api/models/model-1/artifacts/0")
    health = client.get("/api/integrations/unitrain/health")
    stopped = client.post(f"/api/training-runs/{run_id}/stop")

    assert listing.json()["meta"]["total"] == 1
    assert synced.json()["metric_summary"]["mAP50"] == 0.82
    assert logs.json()["lines"] == ["epoch 3/10"]
    assert metrics.json()["history"][0]["epoch"] == 3
    assert models.json()["data"][0]["training_run_id"] == run_id
    assert models.json()["data"][0]["file_path"] == (
        "/srv/unitrain/runs/remote-run-1/artifacts/train/weights/best.pt"
    )
    assert model.json()["category_metrics"][0]["category"] == "cargo"
    assert artifact.content == b"report"
    assert health.json() == {"status": "online", "version": "1.0.0"}
    assert stopped.json()["status"] == "stopped"
    with session_factory() as session:
        stored = session.get(TrainingRun, run_id)
        assert stored is not None and stored.dataset_version.status is VersionStatus.READY
