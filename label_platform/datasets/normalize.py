import hashlib
import math
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, cast

import numpy as np
from pycocotools import mask as mask_utils

from label_platform.datasets.contracts import SourceDataset, SourceImage
from label_platform.domain.enums import TaskType


CANONICAL_FORMAT = "platform-coco-v1"
CONVERTER_VERSION = "label-platform-0.1.0"
SPLIT_NAMES = ("train", "val", "test")
DEFAULT_SPLIT_RATIOS = {"train": 0.8, "val": 0.2, "test": 0.0}


class NormalizationError(ValueError):
    pass


@dataclass
class CanonicalVersion:
    coco: dict[str, Any]
    splits: dict[str, tuple[str, ...]]
    manifest: dict[str, Any]
    source_images: dict[str, SourceImage]


def normalize_source(
    source: SourceDataset,
    *,
    split_seed: int = 42,
    split_ratios: dict[str, float] | None = None,
    source_version: str | None = None,
    source_lineage: dict[str, object] | None = None,
) -> CanonicalVersion:
    ratios = _validate_split_ratios(split_ratios or DEFAULT_SPLIT_RATIOS)
    categories = [
        {"id": category_id, "name": category}
        for category_id, category in enumerate(source.categories, start=1)
    ]
    category_ids = {category: category_id for category_id, category in enumerate(source.categories, 1)}
    if len(category_ids) != len(source.categories) or not category_ids:
        raise NormalizationError("source categories must be non-empty and unique")

    sorted_images = sorted(source.images, key=lambda image: image.sample_key)
    source_images: dict[str, SourceImage] = {}
    image_ids: dict[str, int] = {}
    coco_images: list[dict[str, object]] = []
    manifest_files: dict[str, dict[str, object]] = {}
    for image_id, image in enumerate(sorted_images, start=1):
        if image.sample_key in source_images:
            raise NormalizationError(f"duplicate sample key: {image.sample_key}")
        canonical_path = _canonical_image_path(image.relative_path)
        source_images[image.sample_key] = image
        image_ids[image.sample_key] = image_id
        coco_images.append(
            {
                "id": image_id,
                "file_name": canonical_path,
                "width": image.width,
                "height": image.height,
                "sample_key": image.sample_key,
            }
        )
        manifest_files[canonical_path] = {
            "sha256": image.sha256,
            "size": image.file_size,
            "source_relative_path": image.relative_path,
        }
    if not coco_images:
        raise NormalizationError("source dataset must contain at least one image")

    coco_annotations: list[dict[str, object]] = []
    for annotation_id, annotation in enumerate(source.annotations, start=1):
        resolved_image_id = image_ids.get(annotation.image_key)
        if resolved_image_id is None:
            raise NormalizationError(
                f"annotation {annotation_id} references unknown image {annotation.image_key}"
            )
        category_id = category_ids.get(annotation.category_name)
        if category_id is None:
            raise NormalizationError(
                f"annotation {annotation_id} references unknown category {annotation.category_name}"
            )
        image = source_images[annotation.image_key]
        if source.task_type is TaskType.INSTANCE_SEGMENTATION:
            if annotation.segmentation is None:
                raise NormalizationError(
                    f"instance annotation {annotation_id} requires a segmentation mask"
                )
            mask = _decode_segmentation(
                annotation.segmentation,
                height=image.height,
                width=image.width,
                annotation_id=annotation_id,
            )
            encoded = mask_utils.encode(np.asfortranarray(mask.astype(np.uint8)))
            counts = encoded["counts"]
            if isinstance(counts, bytes):
                counts = counts.decode("utf-8")
            canonical_rle: dict[str, object] = {
                "size": [image.height, image.width],
                "counts": counts,
            }
            area = float(mask_utils.area(encoded))
            if area <= 0:
                raise NormalizationError(f"instance annotation {annotation_id} has an empty mask")
            bbox = [float(value) for value in mask_utils.toBbox(encoded).tolist()]
            coco_annotations.append(
                {
                    "id": annotation_id,
                    "image_id": resolved_image_id,
                    "category_id": category_id,
                    "bbox": bbox,
                    "area": area,
                    "iscrowd": 0,
                    "segmentation": canonical_rle,
                }
            )
        else:
            if annotation.bbox is None:
                raise NormalizationError(
                    f"detection annotation {annotation_id} requires a bounding box"
                )
            bbox = [float(value) for value in annotation.bbox]
            coco_annotations.append(
                {
                    "id": annotation_id,
                    "image_id": resolved_image_id,
                    "category_id": category_id,
                    "bbox": bbox,
                    "area": bbox[2] * bbox[3],
                    "iscrowd": 0,
                }
            )

    splits = _assign_splits(sorted_images, seed=split_seed, ratios=ratios)
    split_counts = {name: len(members) for name, members in splits.items()}
    manifest: dict[str, Any] = {
        "format": CANONICAL_FORMAT,
        "converter_version": CONVERTER_VERSION,
        "task_type": source.task_type.value,
        "source_format": source.format.value,
        "source_version": source_version,
        "images": len(coco_images),
        "annotations": len(coco_annotations),
        "categories": categories,
        "category_id_mapping": dict(source.category_id_mapping),
        "split_counts": split_counts,
        "split_config": {"seed": split_seed, "ratios": ratios},
        "source_lineage": dict(source_lineage or {}),
        "files": manifest_files,
    }
    return CanonicalVersion(
        coco={
            "info": {"format": CANONICAL_FORMAT, "converter_version": CONVERTER_VERSION},
            "images": coco_images,
            "annotations": coco_annotations,
            "categories": categories,
        },
        splits=splits,
        manifest=manifest,
        source_images=source_images,
    )


def _canonical_image_path(relative_path: str) -> str:
    if "\x00" in relative_path or "\\" in relative_path:
        raise NormalizationError(f"invalid source image path: {relative_path}")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise NormalizationError(f"source image path escapes the dataset: {relative_path}")
    return (PurePosixPath("images") / path).as_posix()


def _validate_split_ratios(ratios: dict[str, float]) -> dict[str, float]:
    if set(ratios) != set(SPLIT_NAMES):
        raise NormalizationError("split ratios must define train, val, and test")
    normalized: dict[str, float] = {}
    for name in SPLIT_NAMES:
        value = ratios[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise NormalizationError("split ratios must be finite non-negative numbers")
        normalized[name] = float(value)
        if not math.isfinite(normalized[name]) or normalized[name] < 0:
            raise NormalizationError("split ratios must be finite non-negative numbers")
    if not math.isclose(sum(normalized.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise NormalizationError("split ratios must sum to one")
    return normalized


def _assign_splits(
    images: list[SourceImage],
    *,
    seed: int,
    ratios: dict[str, float],
) -> dict[str, tuple[str, ...]]:
    groups: dict[str, list[SourceImage]] = {}
    for image in images:
        group = image.group_key or _relative_path_split_key(image.relative_path)
        groups.setdefault(group, []).append(image)

    assignments: dict[str, str] = {}
    for group, group_images in groups.items():
        explicit = {image.split for image in group_images if image.split is not None}
        if not explicit.issubset(SPLIT_NAMES):
            raise NormalizationError(f"group {group} contains an unknown explicit split")
        if len(explicit) > 1:
            raise NormalizationError(f"group {group} contains conflicting explicit splits")
        assignments[group] = explicit.pop() if explicit else _hashed_split(group, seed, ratios)

    members: dict[str, list[str]] = {name: [] for name in SPLIT_NAMES}
    for group, group_images in groups.items():
        members[assignments[group]].extend(image.sample_key for image in group_images)
    return {name: tuple(sorted(members[name])) for name in SPLIT_NAMES}


def _relative_path_split_key(relative_path: str) -> str:
    return hashlib.sha256(f"path\0{relative_path}".encode("utf-8")).hexdigest()


def _hashed_split(group: str, seed: int, ratios: dict[str, float]) -> str:
    digest = hashlib.sha256(f"{seed}\0{group}".encode("utf-8")).digest()
    score = int.from_bytes(digest[:8], "big") / 2**64
    cumulative = 0.0
    for name in SPLIT_NAMES:
        cumulative += ratios[name]
        if score < cumulative:
            return name
    return SPLIT_NAMES[-1]


def _decode_segmentation(
    segmentation: dict[str, object] | list[list[float]],
    *,
    height: int,
    width: int,
    annotation_id: int,
) -> np.ndarray[Any, np.dtype[np.uint8]]:
    try:
        if isinstance(segmentation, list):
            rles = mask_utils.frPyObjects(cast(Any, segmentation), height, width)
            rle = mask_utils.merge(rles)
        else:
            size = segmentation.get("size")
            counts = segmentation.get("counts")
            if size != [height, width] or not isinstance(counts, (str, list)):
                raise ValueError("invalid RLE shape")
            if isinstance(counts, list):
                rle = mask_utils.frPyObjects(cast(Any, segmentation), height, width)
            else:
                rle = {"size": [height, width], "counts": counts.encode("utf-8")}
        decoded = np.asarray(mask_utils.decode(rle), dtype=np.uint8)
    except Exception as exc:
        raise NormalizationError(
            f"instance annotation {annotation_id} has invalid segmentation"
        ) from exc
    if decoded.ndim == 3:
        decoded = np.any(decoded, axis=2).astype(np.uint8)
    if decoded.shape != (height, width):
        raise NormalizationError(
            f"instance annotation {annotation_id} segmentation dimensions do not match image"
        )
    return decoded
