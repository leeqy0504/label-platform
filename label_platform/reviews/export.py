from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path, PurePosixPath

from label_platform.datasets.contracts import SourceDataset, SourceFormatError
from label_platform.datasets.labelstudio_adapter import LabelStudioExportAdapter
from label_platform.db.models import DatasetItem, DatasetVersion
from label_platform.domain.enums import SourceFormat, TaskType, VersionStatus


def load_review_export(
    export_path: Path,
    *,
    version: DatasetVersion,
    version_root: Path,
    task_type: TaskType,
) -> SourceDataset:
    if version.status is not VersionStatus.READY:
        raise SourceFormatError("Review input version is not ready")
    try:
        payload: object = json.loads(export_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFormatError("Label Studio raw export is not valid JSON") from exc
    if not isinstance(payload, list) or any(not isinstance(task, dict) for task in payload):
        raise SourceFormatError("Label Studio raw export must contain a task array")

    items = {item.sample_key: item for item in version.items}
    rewritten: list[object] = []
    sample_keys: list[str] = []
    seen: set[str] = set()
    for index, raw_task in enumerate(payload):
        assert isinstance(raw_task, dict)
        task = copy.deepcopy(raw_task)
        data = task.get("data")
        sample_key = data.get("sample_key") if isinstance(data, dict) else None
        if not isinstance(sample_key, str) or sample_key not in items:
            raise SourceFormatError(f"Label Studio task {index} has an unknown sample key")
        if sample_key in seen:
            raise SourceFormatError(f"Label Studio task {index} duplicates a sample key")
        seen.add(sample_key)
        item = items[sample_key]
        assert isinstance(data, dict)
        data["image"] = item.relative_path
        data["split"] = item.split
        data["group_key"] = item.group_key
        rewritten.append(task)
        sample_keys.append(sample_key)
    if seen != set(items):
        raise SourceFormatError("Label Studio export does not contain every input sample")

    category_names = [
        category["name"]
        for category in version.class_schema
        if isinstance(category.get("name"), str)
    ]
    source = LabelStudioExportAdapter().read_native_tasks(
        rewritten,
        media_root=version_root,
        dataset_id=version.dataset_id,
        categories=category_names,
    )

    old_to_new: dict[str, str] = {}
    normalized_images = []
    for sample_key, source_image in zip(sample_keys, source.images, strict=True):
        item = items[sample_key]
        old_to_new[source_image.sample_key] = sample_key
        relative = _relative_below_images(item)
        normalized_images.append(
            replace(
                source_image,
                relative_path=relative,
                sample_key=sample_key,
                split=item.split,
                group_key=item.group_key,
            )
        )
    normalized_annotations = tuple(
        replace(annotation, image_key=old_to_new[annotation.image_key])
        for annotation in source.annotations
    )
    return replace(
        source,
        format=SourceFormat.LABEL_STUDIO,
        task_type=task_type,
        images=tuple(normalized_images),
        annotations=normalized_annotations,
    )


def _relative_below_images(item: DatasetItem) -> str:
    path = PurePosixPath(item.relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise SourceFormatError("Dataset item path is invalid")
    if path.parts and path.parts[0] == "images":
        path = PurePosixPath(*path.parts[1:])
    if str(path) in {"", "."}:
        raise SourceFormatError("Dataset item path is invalid")
    return path.as_posix()
