import hashlib
import json
from pathlib import Path
from typing import Any

from label_platform.datasets.contracts import SourceDataset, SourceFormatError
from label_platform.datasets.normalize import NormalizationError, normalize_source
from label_platform.datasets.paths import SourcePathError, iter_safe_files


def source_fingerprint(
    source: SourceDataset,
    *,
    split_seed: int,
    split_ratios: dict[str, float] | None,
) -> str:
    relative_by_key = {image.sample_key: image.relative_path for image in source.images}
    payload = {
        "source_format": source.format.value,
        "task_type": source.task_type.value,
        "categories": list(source.categories),
        "category_id_mapping": source.category_id_mapping,
        "images": [
            {
                "relative_path": image.relative_path,
                "width": image.width,
                "height": image.height,
                "size": image.file_size,
                "sha256": image.sha256,
                "split": image.split,
                "group_key": image.group_key,
            }
            for image in sorted(source.images, key=lambda item: item.relative_path)
        ],
        "annotations": [
            {
                "image": relative_by_key[annotation.image_key],
                "category": annotation.category_name,
                "bbox": annotation.bbox,
                "segmentation": annotation.segmentation,
            }
            for annotation in source.annotations
        ],
        "split_seed": split_seed,
        "split_ratios": split_ratios,
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def analyze_dataset_source(
    source_path: Path,
    *,
    dataset_namespace: str,
    categories: tuple[str, ...],
    task_type: Any,
    split_seed: int,
    split_ratios: dict[str, float] | None,
) -> dict[str, object]:
    from label_platform.datasets.service import adapt_source

    try:
        source = adapt_source(
            source_path,
            dataset_id=dataset_namespace,
            categories=categories,
            task_type=task_type,
        )
        canonical = normalize_source(
            source,
            split_seed=split_seed,
            split_ratios=split_ratios,
        )
        unsupported = _unsupported_files(source_path, consumed_files=source.consumed_files)
        return {
            "valid": True,
            "source_format": source.format.value,
            "task_type": source.task_type.value,
            "image_count": len(source.images),
            "annotation_count": len(source.annotations),
            "categories": list(source.categories),
            "split_counts": canonical.manifest["split_counts"],
            "unsupported_files": unsupported,
            "errors": [],
            "fingerprint": source_fingerprint(
                source,
                split_seed=split_seed,
                split_ratios=split_ratios,
            ),
        }
    except (NormalizationError, SourceFormatError, SourcePathError, OSError, ValueError) as exc:
        return {
            "valid": False,
            "source_format": None,
            "task_type": None,
            "image_count": 0,
            "annotation_count": 0,
            "categories": list(categories),
            "split_counts": {"train": 0, "val": 0, "test": 0},
            "unsupported_files": [],
            "errors": [{"code": "source_invalid", "path": "source", "message": str(exc)}],
            "fingerprint": None,
        }


def _unsupported_files(source_path: Path, *, consumed_files: tuple[str, ...] = ()) -> list[str]:
    supported = {".jpg", ".jpeg", ".png", ".webp", ".json", ".zip"}
    consumed = set(consumed_files)
    try:
        root = source_path.resolve(strict=True)
        return [
            path.relative_to(root).as_posix()
            for path in iter_safe_files(root)
            if path.suffix.lower() not in supported
            and path.relative_to(root).as_posix() not in consumed
        ]
    except (OSError, SourcePathError):
        return []
