import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, TypeGuard, cast

import numpy as np
from PIL import Image, ImageOps
from pycocotools import mask as mask_utils

from label_platform.datasets.normalize import CANONICAL_FORMAT, CanonicalVersion, SPLIT_NAMES
from label_platform.domain.enums import TaskType


@dataclass(frozen=True)
class ValidationError:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    errors: tuple[ValidationError, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "errors": [asdict(error) for error in self.errors],
        }


def validate_canonical(
    canonical: CanonicalVersion,
    *,
    frozen_schema: list[dict[str, object]] | None = None,
    version_root: Path | None = None,
) -> ValidationReport:
    errors: list[ValidationError] = []
    coco = canonical.coco
    raw_images = coco.get("images")
    raw_annotations = coco.get("annotations")
    raw_categories = coco.get("categories")
    images = raw_images if isinstance(raw_images, list) else []
    annotations = raw_annotations if isinstance(raw_annotations, list) else []
    categories = raw_categories if isinstance(raw_categories, list) else []
    if not isinstance(raw_images, list):
        _add(errors, "coco_section_invalid", "images", "COCO images must be an array")
    if not isinstance(raw_annotations, list):
        _add(errors, "coco_section_invalid", "annotations", "COCO annotations must be an array")
    if not isinstance(raw_categories, list):
        _add(errors, "coco_section_invalid", "categories", "COCO categories must be an array")

    # Path checks run first so containment failures are the primary diagnostic.
    for index, image in enumerate(images):
        file_name = image.get("file_name") if isinstance(image, dict) else None
        if not _valid_image_path(file_name):
            _add(
                errors,
                "image_path_escape",
                f"images[{index}].file_name",
                "image path must be a POSIX path contained under images/",
            )

    schema = _read_categories(categories, errors)
    image_by_id, sample_to_image = _read_images(
        images,
        canonical=canonical,
        errors=errors,
        version_root=version_root,
    )
    task_type = _task_type(canonical.manifest, errors)
    _read_annotations(
        annotations,
        image_by_id=image_by_id,
        category_ids=set(schema),
        task_type=task_type,
        errors=errors,
    )
    _validate_manifest(
        canonical,
        schema=schema,
        frozen_schema=frozen_schema,
        errors=errors,
    )
    _validate_splits(
        canonical,
        sample_to_image=sample_to_image,
        errors=errors,
    )
    return ValidationReport(valid=not errors, errors=tuple(errors))


def _read_categories(
    categories: list[object],
    errors: list[ValidationError],
) -> dict[int, str]:
    schema: dict[int, str] = {}
    names: set[str] = set()
    for index, category in enumerate(categories):
        path = f"categories[{index}]"
        if not isinstance(category, dict):
            _add(errors, "category_invalid", path, "category must be an object")
            continue
        category_id = category.get("id")
        name = category.get("name")
        if not _positive_int(category_id):
            _add(errors, "category_id_invalid", f"{path}.id", "category ID must be positive")
            continue
        if category_id in schema:
            _add(errors, "category_id_duplicate", f"{path}.id", "category ID is duplicated")
            continue
        if not isinstance(name, str) or not name:
            _add(errors, "category_name_invalid", f"{path}.name", "category name is required")
            continue
        if name in names:
            _add(errors, "category_name_duplicate", f"{path}.name", "category name is duplicated")
        names.add(name)
        schema[category_id] = name
    return schema


def _read_images(
    images: list[object],
    *,
    canonical: CanonicalVersion,
    errors: list[ValidationError],
    version_root: Path | None,
) -> tuple[dict[int, dict[str, object]], dict[str, dict[str, object]]]:
    image_by_id: dict[int, dict[str, object]] = {}
    sample_to_image: dict[str, dict[str, object]] = {}
    for index, image in enumerate(images):
        path = f"images[{index}]"
        if not isinstance(image, dict):
            _add(errors, "image_invalid", path, "image must be an object")
            continue
        image_id = image.get("id")
        sample_key = image.get("sample_key")
        width = image.get("width")
        height = image.get("height")
        if not _positive_int(image_id):
            _add(errors, "image_id_invalid", f"{path}.id", "image ID must be positive")
        elif image_id in image_by_id:
            _add(errors, "image_id_duplicate", f"{path}.id", "image ID is duplicated")
        else:
            image_by_id[image_id] = cast(dict[str, object], image)
        if not isinstance(sample_key, str) or not sample_key:
            _add(errors, "sample_key_invalid", f"{path}.sample_key", "sample key is required")
            continue
        if sample_key in sample_to_image:
            _add(errors, "sample_key_duplicate", f"{path}.sample_key", "sample key is duplicated")
        sample_to_image[sample_key] = cast(dict[str, object], image)
        if not _positive_int(width) or not _positive_int(height):
            _add(errors, "image_dimensions_invalid", path, "image dimensions must be positive integers")

        source = canonical.source_images.get(sample_key)
        if source is None:
            _add(errors, "source_image_missing", path, "source image mapping is missing")
            continue
        if width != source.width or height != source.height:
            _add(
                errors,
                "image_dimensions_mismatch",
                path,
                "stored dimensions do not match scanned source dimensions",
            )
        expected_path = (PurePosixPath("images") / PurePosixPath(source.relative_path)).as_posix()
        if image.get("file_name") != expected_path:
            _add(
                errors,
                "image_path_mismatch",
                f"{path}.file_name",
                "canonical path does not match source-relative path",
            )
        _validate_source_file(source.source_path, source.sha256, source.width, source.height, path, errors)
        if version_root is not None and isinstance(image.get("file_name"), str):
            _validate_materialized_file(
                version_root,
                image["file_name"],
                width=width,
                height=height,
                manifest=canonical.manifest,
                path=path,
                errors=errors,
            )
    return image_by_id, sample_to_image


def _read_annotations(
    annotations: list[object],
    *,
    image_by_id: dict[int, dict[str, object]],
    category_ids: set[int],
    task_type: TaskType | None,
    errors: list[ValidationError],
) -> None:
    seen_ids: set[int] = set()
    for index, annotation in enumerate(annotations):
        path = f"annotations[{index}]"
        if not isinstance(annotation, dict):
            _add(errors, "annotation_invalid", path, "annotation must be an object")
            continue
        annotation_id = annotation.get("id")
        if not _positive_int(annotation_id):
            _add(
                errors,
                "annotation_id_invalid",
                f"{path}.id",
                "annotation ID must be positive",
            )
        elif annotation_id in seen_ids:
            _add(
                errors,
                "annotation_id_duplicate",
                f"{path}.id",
                "annotation ID is duplicated",
            )
        else:
            seen_ids.add(annotation_id)

        image_id = annotation.get("image_id")
        category_id = annotation.get("category_id")
        image = image_by_id.get(image_id) if _positive_int(image_id) else None
        if image is None:
            _add(errors, "image_unknown", f"{path}.image_id", "annotation image is unknown")
        if not _positive_int(category_id) or category_id not in category_ids:
            _add(errors, "category_unknown", f"{path}.category_id", "annotation category is unknown")

        bbox = _validate_bbox(annotation.get("bbox"), image=image, path=path, errors=errors)
        area = annotation.get("area")
        if isinstance(area, bool) or not isinstance(area, (int, float)) or not math.isfinite(area):
            _add(errors, "area_non_finite", f"{path}.area", "annotation area must be finite")
        elif area <= 0:
            _add(errors, "area_non_positive", f"{path}.area", "annotation area must be positive")

        segmentation = annotation.get("segmentation")
        if task_type is TaskType.INSTANCE_SEGMENTATION:
            mask = _decode_segmentation(segmentation, image=image, path=path, errors=errors)
            if mask is not None:
                pixel_area = float(np.count_nonzero(mask))
                if pixel_area <= 0:
                    _add(
                        errors,
                        "segmentation_empty",
                        f"{path}.segmentation",
                        "segmentation mask is empty",
                    )
                else:
                    if isinstance(area, (int, float)) and math.isfinite(area) and not math.isclose(
                        float(area), pixel_area, rel_tol=0.0, abs_tol=0.5
                    ):
                        _add(
                            errors,
                            "mask_area_mismatch",
                            f"{path}.area",
                            "annotation area does not match mask pixels",
                        )
                    mask_bbox = _bbox_from_mask(mask)
                    if bbox is not None and any(
                        abs(left - right) > 1.0 for left, right in zip(bbox, mask_bbox, strict=True)
                    ):
                        _add(
                            errors,
                            "mask_bbox_mismatch",
                            f"{path}.bbox",
                            "bounding box does not match mask extent",
                        )
        elif segmentation not in (None, [], {}):
            _add(
                errors,
                "segmentation_unexpected",
                f"{path}.segmentation",
                "detection annotations cannot contain segmentation",
            )


def _validate_bbox(
    value: object,
    *,
    image: dict[str, object] | None,
    path: str,
    errors: list[ValidationError],
) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list) or len(value) != 4 or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) for item in value
    ):
        _add(errors, "bbox_invalid", f"{path}.bbox", "bbox must contain four numbers")
        return None
    bbox = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in bbox):
        _add(errors, "bbox_non_finite", f"{path}.bbox", "bbox values must be finite")
        return None
    x, y, width, height = bbox
    if width <= 0 or height <= 0:
        _add(errors, "bbox_non_positive", f"{path}.bbox", "bbox width and height must be positive")
        return cast(tuple[float, float, float, float], bbox)
    if image is not None:
        image_width = image.get("width")
        image_height = image.get("height")
        if (
            isinstance(image_width, int)
            and isinstance(image_height, int)
            and (x < 0 or y < 0 or x + width > image_width or y + height > image_height)
        ):
            _add(
                errors,
                "bbox_out_of_bounds",
                f"{path}.bbox",
                "bbox must stay inside image bounds",
            )
    return cast(tuple[float, float, float, float], bbox)


def _decode_segmentation(
    value: object,
    *,
    image: dict[str, object] | None,
    path: str,
    errors: list[ValidationError],
) -> np.ndarray[Any, np.dtype[np.uint8]] | None:
    if image is None or not isinstance(image.get("height"), int) or not isinstance(image.get("width"), int):
        return None
    height = cast(int, image["height"])
    width = cast(int, image["width"])
    if value in (None, [], {}):
        _add(
            errors,
            "segmentation_missing",
            f"{path}.segmentation",
            "instance annotation requires segmentation",
        )
        return None
    try:
        if isinstance(value, list):
            rles = mask_utils.frPyObjects(cast(Any, value), height, width)
            rle = mask_utils.merge(rles)
        elif isinstance(value, dict):
            size = value.get("size")
            counts = value.get("counts")
            if size != [height, width] or not isinstance(counts, (str, list)):
                raise ValueError("invalid RLE contract")
            rle = (
                mask_utils.frPyObjects(cast(Any, value), height, width)
                if isinstance(counts, list)
                else {"size": [height, width], "counts": counts.encode("utf-8")}
            )
        else:
            raise ValueError("invalid segmentation type")
        mask = np.asarray(mask_utils.decode(rle), dtype=np.uint8)
    except Exception:
        _add(
            errors,
            "segmentation_invalid",
            f"{path}.segmentation",
            "segmentation cannot be decoded",
        )
        return None
    if mask.ndim == 3:
        mask = np.any(mask, axis=2).astype(np.uint8)
    if mask.shape != (height, width):
        _add(
            errors,
            "segmentation_dimensions",
            f"{path}.segmentation",
            "segmentation dimensions do not match image",
        )
        return None
    return mask


def _validate_manifest(
    canonical: CanonicalVersion,
    *,
    schema: dict[int, str],
    frozen_schema: list[dict[str, object]] | None,
    errors: list[ValidationError],
) -> None:
    manifest = canonical.manifest
    if manifest.get("format") != CANONICAL_FORMAT:
        _add(errors, "manifest_format", "manifest.format", "manifest format is not platform-coco-v1")
    info = canonical.coco.get("info")
    if not isinstance(info, dict) or info.get("format") != CANONICAL_FORMAT:
        _add(errors, "coco_format", "info.format", "COCO info format is not platform-coco-v1")
    for key, actual in (
        ("images", len(canonical.coco.get("images", []))),
        ("annotations", len(canonical.coco.get("annotations", []))),
    ):
        if manifest.get(key) != actual:
            _add(
                errors,
                "manifest_count_mismatch",
                f"manifest.{key}",
                f"manifest {key} count does not match COCO",
            )
    canonical_schema = [{"id": category_id, "name": name} for category_id, name in schema.items()]
    if manifest.get("categories") != canonical_schema:
        _add(
            errors,
            "category_schema_mismatch",
            "manifest.categories",
            "manifest categories do not match COCO categories",
        )
    if frozen_schema is not None and _normalize_schema(frozen_schema) != canonical_schema:
        _add(
            errors,
            "category_schema_mismatch",
            "categories",
            "canonical categories do not match the frozen schema",
        )
    mapping = manifest.get("category_id_mapping")
    mapped_ids = {
        value for value in mapping.values() if _positive_int(value)
    } if isinstance(mapping, dict) else set()
    if mapped_ids != set(schema):
        _add(
            errors,
            "category_mapping_incomplete",
            "manifest.category_id_mapping",
            "source-to-canonical category mapping is incomplete",
        )
    expected_split_counts = {name: len(canonical.splits.get(name, ())) for name in SPLIT_NAMES}
    if manifest.get("split_counts") != expected_split_counts:
        _add(
            errors,
            "manifest_split_mismatch",
            "manifest.split_counts",
            "manifest split counts do not match split membership",
        )
    files = manifest.get("files")
    expected_files = {
        image.get("file_name")
        for image in canonical.coco.get("images", [])
        if isinstance(image, dict) and isinstance(image.get("file_name"), str)
    }
    if not isinstance(files, dict) or set(files) != expected_files:
        _add(
            errors,
            "manifest_files_mismatch",
            "manifest.files",
            "manifest file inventory does not match canonical images",
        )


def _validate_splits(
    canonical: CanonicalVersion,
    *,
    sample_to_image: dict[str, dict[str, object]],
    errors: list[ValidationError],
) -> None:
    if set(canonical.splits) != set(SPLIT_NAMES):
        _add(errors, "split_contract", "splits", "splits must define train, val, and test")
    memberships: dict[str, list[str]] = {}
    for split in SPLIT_NAMES:
        members = canonical.splits.get(split, ())
        for sample_key in members:
            if sample_key not in sample_to_image:
                _add(
                    errors,
                    "split_sample_unknown",
                    f"split.{split}",
                    f"split references unknown sample {sample_key}",
                )
            memberships.setdefault(sample_key, []).append(split)
    for sample_key, splits in memberships.items():
        if len(splits) > 1:
            _add(
                errors,
                "split_overlap",
                "splits",
                f"sample {sample_key} appears in multiple splits",
            )
    for sample_key in sample_to_image:
        if sample_key not in memberships:
            _add(
                errors,
                "split_missing",
                "splits",
                f"sample {sample_key} has no split membership",
            )
    groups: dict[str, set[str]] = {}
    for sample_key, source in canonical.source_images.items():
        if source.group_key is not None and sample_key in memberships:
            groups.setdefault(source.group_key, set()).update(memberships[sample_key])
    for group, group_splits in groups.items():
        if len(group_splits) > 1:
            _add(
                errors,
                "split_group_leakage",
                "splits",
                f"group {group} appears in multiple splits",
            )


def _validate_source_file(
    path: Path,
    expected_sha256: str,
    expected_width: int,
    expected_height: int,
    error_path: str,
    errors: list[ValidationError],
) -> None:
    if path.is_symlink() or not path.is_file():
        _add(errors, "source_file_missing", error_path, "source image file no longer exists")
        return
    try:
        digest = _sha256(path)
    except OSError:
        _add(errors, "source_file_missing", error_path, "source image file cannot be read")
        return
    if digest != expected_sha256:
        _add(errors, "source_file_changed", error_path, "source image checksum changed after scan")
        return
    try:
        with Image.open(path) as opened:
            normalized = ImageOps.exif_transpose(opened)
            normalized.load()
            dimensions = normalized.size
    except OSError:
        _add(errors, "source_file_changed", error_path, "source image can no longer be decoded")
        return
    if dimensions != (expected_width, expected_height):
        _add(errors, "source_file_changed", error_path, "source image dimensions changed after scan")


def _validate_materialized_file(
    root: Path,
    relative: str,
    *,
    width: object,
    height: object,
    manifest: dict[str, Any],
    path: str,
    errors: list[ValidationError],
) -> None:
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        _add(errors, "version_root_missing", str(root), "version root does not exist")
        return
    candidate = resolved_root / PurePosixPath(relative)
    cursor = resolved_root
    for component in PurePosixPath(relative).parts:
        cursor = cursor / component
        if cursor.is_symlink():
            _add(
                errors,
                "image_file_escape",
                f"{path}.file_name",
                "materialized image path contains a symbolic link",
            )
            return
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        _add(errors, "image_file_missing", f"{path}.file_name", "materialized image is missing")
        return
    if candidate.is_symlink() or not resolved.is_relative_to(resolved_root):
        _add(errors, "image_file_escape", f"{path}.file_name", "materialized image escapes version root")
        return
    if not resolved.is_file():
        _add(errors, "image_file_missing", f"{path}.file_name", "materialized image is not a file")
        return
    try:
        with Image.open(resolved) as opened:
            opened.load()
            dimensions = opened.size
    except OSError:
        _add(errors, "image_file_invalid", f"{path}.file_name", "materialized image cannot be decoded")
        return
    if dimensions != (width, height):
        _add(
            errors,
            "image_dimensions_mismatch",
            path,
            "materialized image dimensions do not match COCO",
        )
    files = manifest.get("files")
    metadata = files.get(relative) if isinstance(files, dict) else None
    expected = metadata.get("sha256") if isinstance(metadata, dict) else None
    if not isinstance(expected, str) or _sha256(resolved) != expected:
        _add(
            errors,
            "image_checksum_mismatch",
            f"manifest.files.{relative}",
            "materialized image checksum does not match manifest",
        )


def _task_type(manifest: dict[str, Any], errors: list[ValidationError]) -> TaskType | None:
    value = manifest.get("task_type")
    if not isinstance(value, str):
        _add(errors, "manifest_task_type", "manifest.task_type", "manifest task type is invalid")
        return None
    try:
        return TaskType(value)
    except ValueError:
        _add(errors, "manifest_task_type", "manifest.task_type", "manifest task type is invalid")
        return None


def _normalize_schema(schema: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{"id": category.get("id"), "name": category.get("name")} for category in schema]


def _valid_image_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and len(path.parts) > 1
        and path.parts[0] == "images"
    )


def _bbox_from_mask(mask: np.ndarray[Any, np.dtype[np.uint8]]) -> tuple[float, float, float, float]:
    ys, xs = np.where(mask > 0)
    return (
        float(xs.min()),
        float(ys.min()),
        float(xs.max() - xs.min() + 1),
        float(ys.max() - ys.min() + 1),
    )


def _positive_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _add(
    errors: list[ValidationError],
    code: str,
    path: str,
    message: str,
) -> None:
    errors.append(ValidationError(code=code, path=path, message=message))
