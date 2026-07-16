"""Non-interactive UniTrain worker launched by the HTTP service."""

import argparse
from pathlib import Path
from typing import Any

from unitrain import generate_report, get_runner
from unitrain_api.schemas import CreateRunRequest
from unitrain_api.store import RunStore


def build_runner_config(payload: CreateRunRequest, run_dir: Path) -> dict[str, Any]:
    options = payload.config
    task = "segment" if payload.task_type == "instance_segmentation" else "detect"
    artifacts = run_dir / "artifacts"
    config: dict[str, Any] = {
        "framework": options.framework,
        "model": options.model,
        "task": task,
        "data": {"path": payload.dataset_path, "format": "coco"},
        "train": {
            "epochs": options.epochs,
            "imgsz": options.image_size,
            "batch": options.batch_size,
            "device": options.device,
            "lr": options.learning_rate,
            "grad_accum_steps": options.grad_accum_steps,
            "output_dir": str(artifacts),
            "early_stopping": options.early_stopping,
            "early_stopping_patience": options.early_stopping_patience,
            "early_stopping_min_delta": options.early_stopping_min_delta,
            "resume": "",
        },
        "config_file": str(run_dir / "request.json"),
    }
    if options.framework in {"ultralytics", "yolo"}:
        config["data_yaml"] = _prepare_yolo_data(payload, run_dir, task)
    return config


def _prepare_yolo_data(payload: CreateRunRequest, run_dir: Path, task: str) -> str:
    dataset_root = Path(payload.dataset_path)
    existing = dataset_root / "data.yaml"
    if existing.is_file():
        return str(existing)
    yolo_root = run_dir / "prepared" / "yolo"
    from unitrain.data_converter import convert_coco_dataset

    convert_coco_dataset(dataset_root, yolo_root, task=task, framework="yolo")
    data_yaml = yolo_root / "data.yaml"
    if not data_yaml.is_file():
        raise RuntimeError("unitrain-coco-split-v1 could not be converted to YOLO data.yaml")
    return str(data_yaml)


def run_worker(run_id: str, run_root: Path) -> None:
    store = RunStore(run_root)
    payload = store.get_request(run_id)
    run_dir = store.run_dir(run_id)
    config = build_runner_config(payload, run_dir)
    runner = get_runner(payload.config.framework)

    print(f">>> UniTrain API run {run_id}", flush=True)
    print(f">>> Training with {payload.config.framework} / {payload.config.model}", flush=True)
    train_info = runner.train(config)
    if not train_info:
        raise RuntimeError("Runner did not return training artifacts")

    result: dict[str, Any] = dict(train_info)
    best_weights = train_info.get("best_weights")
    if not payload.config.skip_evaluation and best_weights and Path(best_weights).is_file():
        eval_dir = run_dir / "artifacts" / "evaluation"
        eval_config = {
            **config,
            "eval": {
                "weights": best_weights,
                "output_dir": str(eval_dir),
                "conf_threshold": 0.001,
                "iou_threshold": 0.5,
            },
        }
        try:
            evaluation = runner.eval(eval_config)
            metrics_path = evaluation.get("metrics_json")
            if metrics_path and Path(metrics_path).is_file():
                result["metrics_path"] = str(Path(metrics_path).relative_to(run_dir))
                result["reports"] = generate_report(str(metrics_path), str(eval_dir))
        except Exception as exc:
            result["evaluation_error"] = str(exc)
            print(f">>> Evaluation failed after successful training: {exc}", flush=True)

    for key in ("output_dir", "best_weights"):
        value = result.get(key)
        if isinstance(value, str):
            try:
                result[key] = str(Path(value).resolve().relative_to(run_dir.resolve()))
            except ValueError:
                result.pop(key)
    store.write_result(run_id, result)
    print(">>> Training complete", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one non-interactive UniTrain job")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    run_worker(args.run_id, args.run_root)


if __name__ == "__main__":
    main()
