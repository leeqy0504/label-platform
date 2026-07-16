import copy
import json
import math
import stat
import zipfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np
from label_studio_sdk.converter.brush import decode_rle
from pycocotools import mask as mask_utils

from label_platform.datasets.coco_adapter import CocoAdapter
from label_platform.datasets.contracts import (
    SourceAnnotation,
    SourceDataset,
    SourceFormatError,
    SourceImage,
)
from label_platform.datasets.media import read_source_image
from label_platform.datasets.paths import (
    SourcePathError,
    iter_safe_files,
    resolve_approved_root,
    resolve_source_file,
)
from label_platform.domain.enums import SourceFormat, TaskType


MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


class LabelStudioExportAdapter:
    def read(
        self,
        source_path: Path,
        *,
        dataset_id: str,
        categories: list[str] | None = None,
    ) -> SourceDataset:
        if source_path.is_symlink():
            raise SourceFormatError("Label Studio export cannot be a symbolic link")
        payload = self._load_document(source_path)
        try:
            media_root = resolve_approved_root(source_path.parent)
        except SourcePathError as exc:
            raise SourceFormatError(str(exc)) from exc

        if isinstance(payload, dict):
            rewritten = self._rewrite_coco_paths(payload, media_root)
            source = CocoAdapter().read_data(
                rewritten,
                image_root=media_root,
                dataset_id=dataset_id,
            )
            if categories is not None and source.categories != self._normalize_categories(categories):
                raise SourceFormatError("Label Studio categories do not match frozen categories")
            return replace(source, format=SourceFormat.LABEL_STUDIO)
        if not isinstance(payload, list):
            raise SourceFormatError("Label Studio export must contain a task array or COCO object")
        return self._read_native(
            payload,
            media_root=media_root,
            dataset_id=dataset_id,
            frozen_categories=categories,
        )

    def _load_document(self, source_path: Path) -> object:
        try:
            is_archive = zipfile.is_zipfile(source_path)
        except OSError as exc:
            raise SourceFormatError("cannot read Label Studio export") from exc
        if not is_archive:
            try:
                return cast(Any, json.loads(source_path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SourceFormatError("Label Studio export is not valid UTF-8 JSON") from exc

        try:
            with zipfile.ZipFile(source_path) as archive:
                members = archive.infolist()
                self._validate_archive_members(members)
                json_members = [member for member in members if member.filename.lower().endswith(".json")]
                ordered = sorted(
                    json_members,
                    key=lambda member: (
                        PurePosixPath(member.filename).name not in {"result_coco.json", "result.json"},
                        PurePosixPath(member.filename).name != "result_coco.json",
                        member.filename,
                    ),
                )
                for member in ordered:
                    try:
                        candidate: Any = json.loads(archive.read(member).decode("utf-8"))
                    except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if isinstance(candidate, list) or self._is_coco(candidate):
                        return candidate
        except (OSError, zipfile.BadZipFile) as exc:
            raise SourceFormatError("Label Studio export archive is invalid") from exc
        raise SourceFormatError("Label Studio archive does not contain a supported JSON export")

    @staticmethod
    def _validate_archive_members(members: list[zipfile.ZipInfo]) -> None:
        names: set[str] = set()
        total_size = 0
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (
                not member.filename
                or "\\" in member.filename
                or path.is_absolute()
                or ".." in path.parts
                or stat.S_ISLNK(mode)
            ):
                raise SourceFormatError(f"unsafe archive member: {member.filename}")
            if member.filename in names:
                raise SourceFormatError(f"duplicate archive member: {member.filename}")
            names.add(member.filename)
            total_size += member.file_size
            if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise SourceFormatError("Label Studio archive exceeds the extraction size limit")

    @staticmethod
    def _is_coco(payload: object) -> bool:
        return isinstance(payload, dict) and all(
            isinstance(payload.get(section), list)
            for section in ("images", "annotations", "categories")
        )

    def _rewrite_coco_paths(
        self,
        payload: dict[object, object],
        media_root: Path,
    ) -> dict[object, object]:
        rewritten = copy.deepcopy(payload)
        images = rewritten.get("images")
        if not isinstance(images, list):
            return rewritten
        for index, image in enumerate(images):
            if not isinstance(image, dict) or not isinstance(image.get("file_name"), str):
                raise SourceFormatError(f"COCO image at index {index} has an invalid file_name")
            resolved = self._resolve_media_reference(media_root, image["file_name"])
            image["file_name"] = resolved.relative_to(media_root).as_posix()
        return rewritten

    def _read_native(
        self,
        tasks: list[object],
        *,
        media_root: Path,
        dataset_id: str,
        frozen_categories: list[str] | None,
    ) -> SourceDataset:
        selected_results: list[list[dict[str, object]]] = []
        discovered_categories: list[str] = []
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                raise SourceFormatError(f"Label Studio task at index {index} must be an object")
            results = self._selected_results(task, index)
            selected_results.append(results)
            for result in results:
                label = self._result_label(result, index)
                if label is not None and label not in discovered_categories:
                    discovered_categories.append(label)

        categories = (
            self._normalize_categories(frozen_categories)
            if frozen_categories is not None
            else tuple(discovered_categories)
        )
        if not categories:
            raise SourceFormatError("Label Studio categories cannot be discovered from the export")
        unknown = set(discovered_categories).difference(categories)
        if unknown:
            raise SourceFormatError(f"unknown label outside frozen categories: {sorted(unknown)[0]}")

        images: list[SourceImage] = []
        annotations: list[SourceAnnotation] = []
        relative_paths: set[str] = set()
        has_segmentation = False
        for index, (task, results) in enumerate(zip(tasks, selected_results, strict=True)):
            assert isinstance(task, dict)
            data = task.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("image"), str):
                raise SourceFormatError(f"Label Studio task at index {index} has no image reference")
            image_path = self._resolve_media_reference(media_root, data["image"])
            relative_path = image_path.relative_to(media_root).as_posix()
            if relative_path in relative_paths:
                raise SourceFormatError(f"duplicate normalized image path: {relative_path}")
            relative_paths.add(relative_path)
            image = read_source_image(
                image_path,
                root=media_root,
                dataset_id=dataset_id,
                relative_path=relative_path,
                split=self._optional_string(data.get("split")),
                group_key=self._optional_string(
                    data.get("group_key") or data.get("episode_id")
                ),
            )
            images.append(image)

            for result in results:
                annotation = self._convert_result(result, image=image, task_index=index)
                if annotation is not None:
                    if annotation.category_name not in categories:
                        raise SourceFormatError(
                            f"unknown label outside frozen categories: {annotation.category_name}"
                        )
                    annotations.append(annotation)
                    has_segmentation = has_segmentation or annotation.segmentation is not None

        if not images:
            raise SourceFormatError("Label Studio export contains no tasks")
        return SourceDataset(
            format=SourceFormat.LABEL_STUDIO,
            task_type=(
                TaskType.INSTANCE_SEGMENTATION
                if has_segmentation
                else TaskType.DETECTION
            ),
            images=tuple(images),
            annotations=tuple(annotations),
            categories=categories,
            category_id_mapping={
                f"source:{category}": category_id
                for category_id, category in enumerate(categories, start=1)
            },
        )

    @staticmethod
    def _selected_results(task: dict[object, object], task_index: int) -> list[dict[str, object]]:
        annotations = task.get("annotations", [])
        if not isinstance(annotations, list):
            raise SourceFormatError(f"Label Studio task at index {task_index} has invalid annotations")
        candidates: list[dict[object, object]] = []
        for annotation in annotations:
            if not isinstance(annotation, dict):
                raise SourceFormatError(
                    f"Label Studio task at index {task_index} has an invalid annotation"
                )
            if annotation.get("was_cancelled") or annotation.get("cancelled"):
                continue
            candidates.append(annotation)
        if not candidates:
            return []
        results = candidates[-1].get("result", [])
        if not isinstance(results, list) or any(not isinstance(result, dict) for result in results):
            raise SourceFormatError(f"Label Studio task at index {task_index} has invalid results")
        return cast(list[dict[str, object]], results)

    @staticmethod
    def _result_label(result: dict[str, object], task_index: int) -> str | None:
        result_type = result.get("type")
        if not isinstance(result_type, str):
            return None
        key_by_type = {
            "rectanglelabels": "rectanglelabels",
            "polygonlabels": "polygonlabels",
            "brushlabels": "brushlabels",
        }
        key = key_by_type.get(result_type)
        if key is None:
            return None
        value = result.get("value")
        labels = value.get(key) if isinstance(value, dict) else None
        if not isinstance(labels, list) or len(labels) != 1 or not isinstance(labels[0], str):
            raise SourceFormatError(
                f"Label Studio task at index {task_index} has an invalid result label"
            )
        return labels[0]

    def _convert_result(
        self,
        result: dict[str, object],
        *,
        image: SourceImage,
        task_index: int,
    ) -> SourceAnnotation | None:
        result_type = result.get("type")
        if result_type not in {"rectanglelabels", "polygonlabels", "brushlabels"}:
            return None
        label = self._result_label(result, task_index)
        assert label is not None
        value = result.get("value")
        if not isinstance(value, dict):
            raise SourceFormatError(f"Label Studio task at index {task_index} has invalid result value")
        width, height = self._result_dimensions(result, image=image, task_index=task_index)

        if result_type == "rectanglelabels":
            values = self._finite_values(value, ("x", "y", "width", "height"), task_index)
            x, y, box_width, box_height = values
            return SourceAnnotation(
                image_key=image.sample_key,
                category_name=label,
                bbox=(
                    x * width / 100.0,
                    y * height / 100.0,
                    box_width * width / 100.0,
                    box_height * height / 100.0,
                ),
                segmentation=None,
            )
        if result_type == "polygonlabels":
            points = value.get("points")
            if not isinstance(points, list) or len(points) < 3:
                raise SourceFormatError(f"Label Studio task at index {task_index} has invalid polygon")
            polygon: list[float] = []
            for point in points:
                if not isinstance(point, list) or len(point) != 2:
                    raise SourceFormatError(
                        f"Label Studio task at index {task_index} has invalid polygon"
                    )
                coordinates = self._finite_sequence(point, task_index)
                polygon.extend(
                    [coordinates[0] * width / 100.0, coordinates[1] * height / 100.0]
                )
            return SourceAnnotation(
                image_key=image.sample_key,
                category_name=label,
                bbox=None,
                segmentation=[polygon],
            )

        rle = value.get("rle")
        if not isinstance(rle, list):
            raise SourceFormatError(f"Label Studio task at index {task_index} has invalid brush RLE")
        try:
            decoded = np.asarray(decode_rle(rle), dtype=np.uint8)
            if decoded.size != width * height * 4:
                raise ValueError("RLE dimensions do not match")
            mask = decoded.reshape((height, width, 4))[:, :, 3] > 0
            encoded: Any = mask_utils.encode(np.asfortranarray(mask.astype(np.uint8)))
        except Exception as exc:
            raise SourceFormatError(
                f"Label Studio task at index {task_index} has invalid brush RLE"
            ) from exc
        counts = encoded["counts"]
        if isinstance(counts, bytes):
            counts = counts.decode("utf-8")
        return SourceAnnotation(
            image_key=image.sample_key,
            category_name=label,
            bbox=None,
            segmentation={"size": [height, width], "counts": counts},
        )

    @staticmethod
    def _result_dimensions(
        result: dict[str, object],
        *,
        image: SourceImage,
        task_index: int,
    ) -> tuple[int, int]:
        width = result.get("original_width")
        height = result.get("original_height")
        if (
            isinstance(width, bool)
            or not isinstance(width, (int, float))
            or isinstance(height, bool)
            or not isinstance(height, (int, float))
            or not math.isfinite(width)
            or not math.isfinite(height)
            or width <= 0
            or height <= 0
            or int(width) != image.width
            or int(height) != image.height
        ):
            raise SourceFormatError(
                f"Label Studio task at index {task_index} result dimensions do not match image"
            )
        return int(width), int(height)

    @staticmethod
    def _finite_values(
        value: dict[object, object],
        keys: tuple[str, ...],
        task_index: int,
    ) -> tuple[float, ...]:
        return LabelStudioExportAdapter._finite_sequence(
            [value.get(key) for key in keys],
            task_index,
        )

    @staticmethod
    def _finite_sequence(values: list[object], task_index: int) -> tuple[float, ...]:
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        ):
            raise SourceFormatError(
                f"Label Studio task at index {task_index} geometry must contain finite numbers"
            )
        return tuple(float(value) for value in values if isinstance(value, (int, float)))

    @staticmethod
    def _normalize_categories(categories: list[str]) -> tuple[str, ...]:
        normalized = tuple(category.strip() for category in categories)
        if not normalized or any(not category for category in normalized):
            raise SourceFormatError("categories must contain at least one non-empty name")
        if len(set(normalized)) != len(normalized):
            raise SourceFormatError("categories must contain unique names")
        return normalized

    def _resolve_media_reference(self, root: Path, reference: str) -> Path:
        parsed = urlparse(reference)
        query = parse_qs(parsed.query)
        relative = unquote(query["d"][0]) if query.get("d") else unquote(reference)
        relative = relative.replace("\\", "/")
        marker = "labelstudio_media/"
        if marker in relative:
            relative = relative.split(marker, 1)[1]
            direct_candidates = [f"labelstudio_media/{relative}", relative]
        else:
            direct_candidates = [relative]

        if parsed.scheme and not query.get("d"):
            raise SourceFormatError("Label Studio image URL is not a local media reference")
        for candidate in direct_candidates:
            try:
                return resolve_source_file(root, candidate)
            except SourcePathError:
                continue

        basename = PurePosixPath(relative).name
        try:
            matches = [path for path in iter_safe_files(root) if path.name == basename]
        except SourcePathError as exc:
            raise SourceFormatError(str(exc)) from exc
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise SourceFormatError(f"Label Studio image reference is ambiguous: {basename}")
        raise SourceFormatError(f"Label Studio image file does not exist: {basename}")

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return value if isinstance(value, str) and value else None
