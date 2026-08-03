from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from unitrain_api.schemas import CreateRunRequest, RunRecord, RunStatus
from unitrain_api.store import RunStore
from unitrain_api.worker import build_runner_config, run_worker


def _request(dataset_root: Path, *, framework: str, model: str) -> CreateRunRequest:
    return CreateRunRequest(
        dataset_version_id="mouse-seg-v1",
        dataset_path=str(dataset_root),
        annotation_path="train/_annotations.coco.json",
        task_type="instance_segmentation",
        export_profile="unitrain-coco-split-v1",
        idempotency_key=f"{framework}-mouse-seg",
        config={
            "framework": framework,
            "model": model,
            "epochs": 1,
            "batch_size": 1,
            "skip_evaluation": False,
        },
    )


def test_build_runner_config_uses_existing_yolo_data_file(tmp_path: Path) -> None:
    dataset_root = tmp_path / "yolo"
    dataset_root.mkdir()
    data_yaml = dataset_root / "data.yaml"
    data_yaml.write_text("path: .\ntrain: images/train\nval: images/val\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "yolo"

    config = build_runner_config(
        _request(dataset_root, framework="ultralytics", model="yolo11n-seg"),
        run_dir,
    )

    assert config["task"] == "segment"
    assert config["data_yaml"] == str(data_yaml)
    assert config["train"]["epochs"] == 1
    assert config["train"]["batch"] == 1


def test_build_runner_config_keeps_rfdetr_on_coco_rle(tmp_path: Path) -> None:
    dataset_root = tmp_path / "coco"
    dataset_root.mkdir()
    run_dir = tmp_path / "runs" / "rfdetr"

    config = build_runner_config(
        _request(dataset_root, framework="rfdetr", model="seg-nano"),
        run_dir,
    )

    assert config["task"] == "segment"
    assert config["model"] == "seg-nano"
    assert config["data"] == {"path": str(dataset_root), "format": "coco"}
    assert "data_yaml" not in config


def test_worker_evaluates_best_weights_and_records_metrics_and_reports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_id = "00000000-0000-4000-8000-000000000001"
    run_root = tmp_path / "runs"
    dataset_root = tmp_path / "coco"
    dataset_root.mkdir()
    request = _request(dataset_root, framework="rfdetr", model="seg-nano")
    store = RunStore(run_root)
    store.create(
        RunRecord(
            id=run_id,
            dataset_version_id=request.dataset_version_id,
            task_type=request.task_type,
            export_profile=request.export_profile,
            framework=request.config.framework,
            model=request.config.model,
            status=RunStatus.RUNNING,
            total_epochs=1,
            detail_url=f"http://unitrain.test/runs/{run_id}",
            created_at=datetime.now(timezone.utc),
        ),
        request,
    )

    class FakeRunner:
        def __init__(self) -> None:
            self.eval_config: dict[str, Any] | None = None

        def train(self, config: dict[str, Any]) -> dict[str, str]:
            artifacts = Path(config["train"]["output_dir"])
            weights = artifacts / "checkpoint_best_total.pth"
            weights.write_bytes(b"weights")
            return {"output_dir": str(artifacts), "best_weights": str(weights)}

        def eval(self, config: dict[str, Any]) -> dict[str, str]:
            self.eval_config = config
            evaluation = Path(config["eval"]["output_dir"])
            evaluation.mkdir(parents=True)
            metrics = evaluation / "eval_metrics.json"
            metrics.write_text('{"overall":{"mAP50":0.9}}', encoding="utf-8")
            return {"metrics_json": str(metrics)}

    runner = FakeRunner()

    def fake_report(metrics_path: str, output_dir: str) -> dict[str, str]:
        report = Path(output_dir) / "eval_report.md"
        report.write_text(f"metrics: {metrics_path}\n", encoding="utf-8")
        return {"markdown": str(report)}

    monkeypatch.setattr("unitrain_api.worker.get_runner", lambda _framework: runner)
    monkeypatch.setattr("unitrain_api.worker.generate_report", fake_report)

    run_worker(run_id, run_root)

    result = store.read_result(run_id)
    assert runner.eval_config is not None
    assert runner.eval_config["eval"]["weights"].endswith("checkpoint_best_total.pth")
    assert result["best_weights"] == "artifacts/checkpoint_best_total.pth"
    assert result["metrics_path"] == "artifacts/evaluation/eval_metrics.json"
    assert result["reports"]["markdown"].endswith("artifacts/evaluation/eval_report.md")
    assert len(store.list_models()) == 1
