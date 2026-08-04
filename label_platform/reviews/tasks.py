from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import quote

import numpy as np
from label_studio_sdk.converter.brush import mask2rle
from pycocotools import mask as mask_utils

from label_platform.db.models import DatasetVersion
from label_platform.datasets.versioning import VersionStorageError, load_version_coco
from label_platform.domain.enums import TaskType, VersionStatus


@dataclass(frozen=True)
class ReviewImportTask:
    sample_key: str
    dataset_item_id: str
    payload: dict[str, object]


def build_label_config(task_type: TaskType, class_schema: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    colors = ("#DC2626", "#2563EB", "#059669", "#D97706", "#7C3AED", "#0891B2")
    for index, category in enumerate(class_schema):
        name = category.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Dataset class schema contains an invalid category")
        labels.append(
            f'<Label value="{escape(name, quote=True)}" background="{colors[index % len(colors)]}"/>'
        )
    if not labels:
        raise ValueError("Dataset class schema cannot be empty")
    control = "RectangleLabels" if task_type is TaskType.DETECTION else "BrushLabels"
    control_name = "bbox" if task_type is TaskType.DETECTION else "brush"
    return (
        "<View>"
        '<Header value="Edit the annotation, then submit the task"/>'
        '<Text name="meta" value="Dataset: $dataset_id | Version: $dataset_version"/>'
        '<Image name="image" value="$image" zoom="true" zoomControl="true"/>'
        '<Choices name="image_disposition" toName="image" choice="single" showInline="true">'
        '<Choice value="删除图片"/>'
        "</Choices>"
        f'<{control} name="{control_name}" toName="image">'
        f"{''.join(labels)}"
        f"</{control}>"
        "</View>"
    )


def build_import_tasks(
    version: DatasetVersion,
    version_root: Path,
    *,
    task_type: TaskType,
    media_root_path: str | None = None,
) -> list[ReviewImportTask]:
    if version.status is not VersionStatus.READY or not version.root_path:
        raise ValueError("Only a ready managed dataset version can be reviewed")
    try:
        document: object = load_version_coco(
            version_root,
            manifest_path=version.manifest_path,
            annotation_path=version.annotation_path,
        )
    except (OSError, VersionStorageError) as exc:
        raise ValueError("Cannot read the canonical annotation document") from exc
    if not isinstance(document, dict):
        raise ValueError("Canonical annotation document must be an object")

    images = _object_list(document, "images")
    annotations = _object_list(document, "annotations")
    categories = _object_list(document, "categories")
    image_by_sample = {
        image["sample_key"]: image
        for image in images
        if isinstance(image.get("sample_key"), str)
    }
    category_by_id = {
        category["id"]: category["name"]
        for category in categories
        if isinstance(category.get("id"), int) and isinstance(category.get("name"), str)
    }
    annotations_by_image: dict[object, list[dict[str, object]]] = {}
    for annotation in annotations:
        annotations_by_image.setdefault(annotation.get("image_id"), []).append(annotation)

    tasks: list[ReviewImportTask] = []
    for item in sorted(version.items, key=lambda candidate: (candidate.relative_path, candidate.id)):
        image = image_by_sample.get(item.sample_key)
        if image is None:
            raise ValueError(f"Canonical image is missing for sample {item.sample_key}")
        results = [
            _annotation_result(
                annotation,
                image=image,
                category_by_id=category_by_id,
                task_type=task_type,
                sample_key=item.sample_key,
            )
            for annotation in annotations_by_image.get(image.get("id"), [])
        ]
        data: dict[str, object] = {
            "image": _local_file_url(
                media_root_path or version.root_path,
                _relative_below_images(item.relative_path) if media_root_path else item.relative_path,
            ),
            "dataset_id": version.dataset_id,
            "dataset_version": f"v{version.version_number}",
            "sample_key": item.sample_key,
            "split": item.split,
            "group_key": item.group_key,
        }
        payload: dict[str, object] = {"data": data}
        if results:
            payload["annotations"] = [{"result": results, "ground_truth": False}]
        tasks.append(
            ReviewImportTask(
                sample_key=item.sample_key,
                dataset_item_id=item.id,
                payload=payload,
            )
        )
    if len(tasks) != version.item_count:
        raise ValueError("Dataset item count does not match the canonical version")
    return tasks


def _annotation_result(
    annotation: dict[str, object],
    *,
    image: dict[str, object],
    category_by_id: dict[object, object],
    task_type: TaskType,
    sample_key: str,
) -> dict[str, object]:
    width = _positive_number(image.get("width"), "image width")
    height = _positive_number(image.get("height"), "image height")
    category = category_by_id.get(annotation.get("category_id"))
    if not isinstance(category, str):
        raise ValueError("Annotation references an unknown category")
    result_id = hashlib.sha256(
        f"{sample_key}\0{annotation.get('id')}".encode("utf-8")
    ).hexdigest()[:10]
    common: dict[str, object] = {
        "id": result_id,
        "to_name": "image",
        "original_width": int(width),
        "original_height": int(height),
        "image_rotation": 0,
        "origin": "manual",
    }
    if task_type is TaskType.DETECTION:
        bbox = annotation.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("Detection annotation has an invalid bounding box")
        x, y, box_width, box_height = (
            _finite_number(value, "bounding box") for value in bbox
        )
        return {
            **common,
            "from_name": "bbox",
            "type": "rectanglelabels",
            "value": {
                "x": x / width * 100,
                "y": y / height * 100,
                "width": box_width / width * 100,
                "height": box_height / height * 100,
                "rotation": 0,
                "rectanglelabels": [category],
            },
        }

    segmentation = annotation.get("segmentation")
    if not isinstance(segmentation, dict):
        raise ValueError("Instance annotation has no segmentation mask")
    encoded = dict(segmentation)
    if isinstance(encoded.get("counts"), str):
        encoded["counts"] = encoded["counts"].encode("utf-8")
    try:
        mask = np.asarray(mask_utils.decode(cast(Any, encoded)), dtype=np.uint8)
    except Exception as exc:
        raise ValueError("Instance annotation contains invalid RLE") from exc
    if mask.shape != (int(height), int(width)) or not np.any(mask):
        raise ValueError("Instance annotation mask dimensions are invalid")
    return {
        **common,
        "from_name": "brush",
        "type": "brushlabels",
        "value": {
            "format": "rle",
            "rle": _mask_to_rle((mask > 0).astype(np.uint8) * 255),
            "brushlabels": [category],
        },
}


def _mask_to_rle(mask: np.ndarray[Any, Any]) -> list[int]:
    return cast(list[int], mask2rle(mask))  # type: ignore[no-untyped-call]


def _local_file_url(root_path: str, relative_path: str) -> str:
    root = PurePosixPath(root_path)
    relative = PurePosixPath(relative_path)
    if root.is_absolute() or relative.is_absolute() or ".." in root.parts or ".." in relative.parts:
        raise ValueError("Managed media path is invalid")
    return f"/data/local-files/?d={quote((root / relative).as_posix(), safe='/')}"


def _relative_below_images(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or "\\" in relative_path:
        raise ValueError("Managed media path is invalid")
    if path.parts and path.parts[0] == "images":
        path = PurePosixPath(*path.parts[1:])
    if str(path) in {"", "."}:
        raise ValueError("Managed media path is invalid")
    return path.as_posix()


def _object_list(document: dict[object, object], key: str) -> list[dict[str, object]]:
    value = document.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"Canonical {key} section is invalid")
    return cast(list[dict[str, object]], value)


def _positive_number(value: object, field: str) -> float:
    number = _finite_number(value, field)
    if number <= 0:
        raise ValueError(f"{field} must be positive")
    return number


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number
