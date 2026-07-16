import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from label_platform.datasets.contracts import SourceFormatError
from label_platform.datasets.paths import SourcePathError, iter_safe_files
from label_platform.domain.enums import SourceFormat, TaskType


IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})


@dataclass(frozen=True)
class DetectedSource:
    format: SourceFormat
    source_path: Path
    task_type: TaskType | None = None
    annotation_path: Path | None = None


def detect_source(source_path: Path) -> DetectedSource:
    try:
        files = tuple(iter_safe_files(source_path))
    except SourcePathError as exc:
        raise SourceFormatError(f"source must be an existing safe directory: {exc}") from exc

    detected_annotations: list[DetectedSource] = []
    for path in files:
        suffix = path.suffix.lower()
        if suffix == ".zip":
            detected_annotations.append(
                DetectedSource(
                    format=SourceFormat.LABEL_STUDIO,
                    source_path=source_path.resolve(strict=True),
                    annotation_path=path,
                )
            )
        elif suffix == ".json":
            detected = _detect_json(path, source_path.resolve(strict=True))
            if detected is not None:
                detected_annotations.append(detected)

    if len(detected_annotations) > 1:
        raise SourceFormatError("directory contains multiple supported annotation sources")
    if detected_annotations:
        return detected_annotations[0]

    if any(path.suffix.lower() in IMAGE_EXTENSIONS for path in files):
        return DetectedSource(
            format=SourceFormat.IMAGE_DIRECTORY,
            source_path=source_path.resolve(strict=True),
        )

    raise SourceFormatError("directory does not contain a supported dataset source")


def _detect_json(path: Path, source_path: Path) -> DetectedSource | None:
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if isinstance(loaded, list):
        return DetectedSource(
            format=SourceFormat.LABEL_STUDIO,
            source_path=source_path,
            annotation_path=path,
            task_type=_labelstudio_task_type(loaded),
        )
    if not isinstance(loaded, dict):
        return None
    if not all(isinstance(loaded.get(key), list) for key in ("images", "annotations", "categories")):
        return None

    has_segmentation = any(
        isinstance(annotation, dict) and bool(annotation.get("segmentation"))
        for annotation in loaded["annotations"]
    )
    return DetectedSource(
        format=SourceFormat.COCO_INSTANCE if has_segmentation else SourceFormat.COCO_DETECTION,
        source_path=source_path,
        annotation_path=path,
        task_type=TaskType.INSTANCE_SEGMENTATION if has_segmentation else TaskType.DETECTION,
    )


def _labelstudio_task_type(tasks: list[Any]) -> TaskType | None:
    has_rectangle = False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for annotation in task.get("annotations", []):
            if not isinstance(annotation, dict):
                continue
            for result in annotation.get("result", []):
                if isinstance(result, dict) and result.get("type") in {
                    "brushlabels",
                    "polygonlabels",
                }:
                    return TaskType.INSTANCE_SEGMENTATION
                if isinstance(result, dict) and result.get("type") == "rectanglelabels":
                    has_rectangle = True
    return TaskType.DETECTION if has_rectangle else None


__all__ = ["DetectedSource", "SourceFormatError", "detect_source"]
