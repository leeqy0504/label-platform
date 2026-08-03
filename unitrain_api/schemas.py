from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class TrainingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework: Literal["ultralytics", "yolo", "rfdetr", "rf-detr"] = "ultralytics"
    model: str = Field(default="yolo11n", min_length=1, max_length=120)
    epochs: int = Field(default=100, ge=1, le=10_000)
    batch_size: int = Field(default=16, ge=1, le=4_096)
    learning_rate: float = Field(default=1e-4, gt=0, le=1)
    image_size: int = Field(default=640, ge=32, le=8_192)
    device: int | str = 0
    grad_accum_steps: int = Field(default=4, ge=1, le=1_024)
    early_stopping: bool = False
    early_stopping_patience: int = Field(default=10, ge=1, le=10_000)
    early_stopping_min_delta: float = Field(default=0.001, ge=0, le=1)
    skip_evaluation: bool = False

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError("model must be a plain model name")
        return value

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: int | str) -> int | str:
        if isinstance(value, int):
            if value < 0:
                raise ValueError("device must be a non-negative GPU index")
            return value
        normalized = value.strip().lower()
        if normalized == "cpu" or re.fullmatch(r"(?:cuda:)?\d+(?:,\d+)*", normalized):
            return normalized
        raise ValueError("device must be cpu, a GPU index, or a comma-separated GPU list")


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: str = Field(min_length=1, max_length=180)
    dataset_path: str = Field(min_length=1, max_length=4_096)
    annotation_path: str = Field(min_length=1, max_length=1_024)
    task_type: Literal["detection", "instance_segmentation"]
    export_profile: Literal["unitrain-coco-split-v1"]
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=180)
    config: TrainingOptions = Field(default_factory=TrainingOptions)

    @field_validator("dataset_path")
    @classmethod
    def validate_dataset_path(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("dataset_path must be absolute")
        return str(path)

    @field_validator("annotation_path")
    @classmethod
    def validate_annotation_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("annotation_path must be a relative file path within dataset_path")
        return str(path)

    @model_validator(mode="after")
    def validate_framework_task(self) -> "CreateRunRequest":
        is_segmentation = self.task_type == "instance_segmentation"
        if is_segmentation and self.config.framework in {"rfdetr", "rf-detr"}:
            if not self.config.model.startswith("seg"):
                raise ValueError("RF-DETR instance segmentation requires a seg model")
        return self


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dataset_version_id: str
    task_type: Literal["detection", "instance_segmentation"]
    export_profile: str
    framework: str
    model: str
    status: RunStatus
    current_epoch: int = 0
    total_epochs: int
    pid: int | None = None
    detail_url: str
    metric_summary: dict[str, float] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    stopped_at: datetime | None = None


class RunLogs(BaseModel):
    run_id: str
    offset: int
    next_offset: int
    lines: list[str]
    truncated: bool


class RunMetrics(BaseModel):
    run_id: str
    summary: dict[str, float] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    evaluation: dict[str, Any] = Field(default_factory=dict)


class ModelRecord(BaseModel):
    id: str
    run_id: str
    name: str
    framework: str
    task_type: str
    relative_path: str
    absolute_path: str
    size_bytes: int
    created_at: datetime
    metrics: dict[str, float] = Field(default_factory=dict)
    evaluation_files: list[str] = Field(default_factory=list)


PositiveLimit = Annotated[int, Field(ge=1, le=500)]
