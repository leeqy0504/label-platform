from __future__ import annotations

import math
import stat
from pathlib import Path, PurePosixPath
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from label_platform.datasets.contracts import (
    SourceAnnotation,
    SourceDataset,
    SourceFormatError,
    SourceImage,
)
from label_platform.datasets.detection import IMAGE_EXTENSIONS
from label_platform.datasets.media import read_source_image
from label_platform.datasets.paths import (
    SourcePathError,
    iter_safe_files,
    resolve_approved_root,
    resolve_source_path,
)
from label_platform.domain.enums import SourceFormat, TaskType


MAX_CONFIG_BYTES = 1024 * 1024
SPLIT_NAMES = ("train", "val", "test")
_BOUNDARY_EPSILON = 1e-6


class YoloDetectionAdapter:
    def read(
        self,
        source_path: Path,
        *,
        dataset_id: str,
        config_path: Path | None = None,
    ) -> SourceDataset:
        try:
            root = resolve_approved_root(source_path)
            config = self._config_path(root, config_path)
            payload = self._read_config(config)
            categories = self._read_categories(payload)
            split_directories = self._read_split_directories(payload, root=root)
        except SourcePathError as exc:
            raise SourceFormatError(str(exc)) from exc

        images: list[SourceImage] = []
        annotations: list[SourceAnnotation] = []
        consumed_files = {config.relative_to(root).as_posix()}
        configured_directories: set[Path] = set()

        for split, image_directory in split_directories.items():
            if any(
                image_directory.is_relative_to(configured)
                or configured.is_relative_to(image_directory)
                for configured in configured_directories
            ):
                raise SourceFormatError(
                    "YOLO split image directories must be unique and non-overlapping"
                )
            configured_directories.add(image_directory)
            split_images, split_annotations, split_consumed = self._read_split(
                root=root,
                image_directory=image_directory,
                split=split,
                dataset_id=dataset_id,
                categories=categories,
            )
            if split == "train" and not split_images:
                raise SourceFormatError("YOLO train split contains no supported images")
            images.extend(split_images)
            annotations.extend(split_annotations)
            consumed_files.update(split_consumed)

        if not images:
            raise SourceFormatError("YOLO dataset contains no supported images")

        return SourceDataset(
            format=SourceFormat.YOLO_DETECTION,
            task_type=TaskType.DETECTION,
            images=tuple(images),
            annotations=tuple(annotations),
            categories=categories,
            category_id_mapping={
                f"source:{source_id}": source_id + 1 for source_id in range(len(categories))
            },
            consumed_files=tuple(sorted(consumed_files)),
        )

    @staticmethod
    def _config_path(root: Path, supplied: Path | None) -> Path:
        if supplied is not None:
            if supplied.is_symlink():
                raise SourceFormatError("YOLO config cannot be a symbolic link")
            try:
                config = supplied.resolve(strict=True)
            except OSError as exc:
                raise SourceFormatError("YOLO data.yaml does not exist") from exc
            if config.parent != root or config.name.lower() not in {"data.yaml", "data.yml"}:
                raise SourceFormatError(
                    "YOLO config must be data.yaml or data.yml at the dataset root"
                )
            if not stat.S_ISREG(config.stat(follow_symlinks=False).st_mode):
                raise SourceFormatError("YOLO config must be a regular file")
            return config

        candidates = [
            path for path in root.iterdir() if path.name.lower() in {"data.yaml", "data.yml"}
        ]
        if len(candidates) != 1:
            raise SourceFormatError("YOLO dataset must contain exactly one data.yaml or data.yml")
        return YoloDetectionAdapter._config_path(root, candidates[0])

    @staticmethod
    def _read_config(path: Path) -> dict[str, Any]:
        try:
            if path.stat(follow_symlinks=False).st_size > MAX_CONFIG_BYTES:
                raise SourceFormatError("YOLO data.yaml exceeds the 1 MiB limit")
            loaded: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        except SourceFormatError:
            raise
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise SourceFormatError("YOLO data.yaml is not valid UTF-8 YAML") from exc
        if not isinstance(loaded, dict):
            raise SourceFormatError("YOLO data.yaml must contain an object")
        return cast(dict[str, Any], loaded)

    @staticmethod
    def _read_categories(payload: dict[str, Any]) -> tuple[str, ...]:
        raw_names = payload.get("names")
        names: list[object]
        if isinstance(raw_names, list):
            names = list(raw_names)
        elif isinstance(raw_names, dict):
            indexed: dict[int, object] = {}
            for raw_key, value in raw_names.items():
                if isinstance(raw_key, int) and not isinstance(raw_key, bool):
                    key = raw_key
                elif (
                    isinstance(raw_key, str)
                    and raw_key.isascii()
                    and raw_key.isdecimal()
                    and raw_key == str(int(raw_key))
                ):
                    key = int(raw_key)
                else:
                    raise SourceFormatError("YOLO category IDs must start at 0 and be contiguous")
                if key in indexed:
                    raise SourceFormatError("YOLO category IDs must be unique")
                indexed[key] = value
            if set(indexed) != set(range(len(indexed))):
                raise SourceFormatError("YOLO category IDs must start at 0 and be contiguous")
            names = [indexed[index] for index in range(len(indexed))]
        else:
            raise SourceFormatError("YOLO data.yaml requires a names list or mapping")

        categories = tuple(name.strip() for name in names if isinstance(name, str))
        if len(categories) != len(names) or not categories or any(not name for name in categories):
            raise SourceFormatError("YOLO categories must contain non-empty names")
        if len(set(categories)) != len(categories):
            raise SourceFormatError("YOLO categories must contain unique names")

        raw_nc = payload.get("nc")
        if raw_nc is not None and (
            isinstance(raw_nc, bool) or not isinstance(raw_nc, int) or raw_nc != len(categories)
        ):
            raise SourceFormatError("YOLO nc must match the number of category names")
        return categories

    @staticmethod
    def _read_split_directories(payload: dict[str, Any], *, root: Path) -> dict[str, Path]:
        directories: dict[str, Path] = {}
        for split in SPLIT_NAMES:
            raw = payload.get(split)
            if raw is None:
                if split == "train":
                    raise SourceFormatError("YOLO data.yaml requires a train image directory")
                continue
            if not isinstance(raw, str) or not raw.strip():
                raise SourceFormatError(f"YOLO {split} must be a relative image directory")
            relative = raw.strip()
            relative_path = PurePosixPath(relative)
            if (
                "\x00" in relative
                or "\\" in relative
                or "://" in relative
                or (len(relative) >= 2 and relative[1] == ":")
                or relative_path.is_absolute()
                or ".." in relative_path.parts
                or str(relative_path) == "."
            ):
                raise SourceFormatError(f"YOLO {split} must be a safe relative image directory")
            try:
                directory = resolve_source_path(root, relative)
            except SourcePathError as exc:
                raise SourceFormatError(f"YOLO {split} image directory is invalid: {exc}") from exc
            directories[split] = directory
        return directories

    def _read_split(
        self,
        *,
        root: Path,
        image_directory: Path,
        split: str,
        dataset_id: str,
        categories: tuple[str, ...],
    ) -> tuple[list[SourceImage], list[SourceAnnotation], set[str]]:
        try:
            image_paths = sorted(
                (
                    path
                    for path in iter_safe_files(image_directory)
                    if path.suffix.lower() in IMAGE_EXTENSIONS
                ),
                key=lambda path: path.as_posix(),
            )
        except SourcePathError as exc:
            raise SourceFormatError(str(exc)) from exc

        label_directory = image_directory.parent / "labels"
        label_paths: list[Path] = []
        if label_directory.exists() or label_directory.is_symlink():
            if label_directory.is_symlink():
                raise SourceFormatError(f"YOLO {split} labels directory cannot be a symbolic link")
            if not label_directory.is_dir():
                raise SourceFormatError(f"YOLO {split} labels path is not a directory")
            try:
                label_paths = sorted(
                    (
                        path
                        for path in iter_safe_files(label_directory)
                        if path.suffix.lower() == ".txt"
                    ),
                    key=lambda path: path.as_posix(),
                )
            except SourcePathError as exc:
                raise SourceFormatError(str(exc)) from exc

        image_by_label_key: dict[str, SourceImage] = {}
        images: list[SourceImage] = []
        for image_path in image_paths:
            within_split = image_path.relative_to(image_directory)
            label_key = within_split.with_suffix("").as_posix()
            if label_key in image_by_label_key:
                raise SourceFormatError(
                    f"YOLO {split} contains images with the same label path: {label_key}"
                )
            canonical_relative = (
                PurePosixPath(split) / PurePosixPath(within_split.as_posix())
            ).as_posix()
            image = read_source_image(
                image_path,
                root=root,
                dataset_id=dataset_id,
                relative_path=canonical_relative,
                split=split,
            )
            image_by_label_key[label_key] = image
            images.append(image)

        label_by_key: dict[str, Path] = {}
        consumed: set[str] = set()
        for label_path in label_paths:
            label_key = label_path.relative_to(label_directory).with_suffix("").as_posix()
            if label_key in label_by_key:
                raise SourceFormatError(f"YOLO {split} contains duplicate label paths: {label_key}")
            if label_key not in image_by_label_key:
                relative = label_path.relative_to(root).as_posix()
                raise SourceFormatError(f"YOLO label has no corresponding image: {relative}")
            label_by_key[label_key] = label_path
            consumed.add(label_path.relative_to(root).as_posix())

        annotations: list[SourceAnnotation] = []
        for label_key, image in image_by_label_key.items():
            current_label = label_by_key.get(label_key)
            if current_label is not None:
                annotations.extend(
                    self._read_annotations(current_label, image=image, categories=categories)
                )
        return images, annotations, consumed

    @staticmethod
    def _read_annotations(
        label_path: Path,
        *,
        image: SourceImage,
        categories: tuple[str, ...],
    ) -> list[SourceAnnotation]:
        try:
            lines = label_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise SourceFormatError(f"cannot read YOLO label file: {label_path.name}") from exc

        annotations: list[SourceAnnotation] = []
        for line_number, raw_line in enumerate(lines, start=1):
            if not raw_line.strip():
                continue
            fields = raw_line.split()
            location = f"{label_path.name}:{line_number}"
            if len(fields) != 5:
                raise SourceFormatError(
                    f"YOLO detection label {location} must contain exactly five fields"
                )
            try:
                category_id = int(fields[0])
                center_x, center_y, width, height = (float(value) for value in fields[1:])
            except ValueError as exc:
                raise SourceFormatError(
                    f"YOLO label {location} contains an invalid number"
                ) from exc
            values = (center_x, center_y, width, height)
            if not all(math.isfinite(value) for value in values):
                raise SourceFormatError(f"YOLO label {location} contains a non-finite value")
            if category_id < 0 or category_id >= len(categories):
                raise SourceFormatError(f"YOLO label {location} category ID is out of range")
            if not 0 <= center_x <= 1 or not 0 <= center_y <= 1:
                raise SourceFormatError(f"YOLO label {location} center must stay within 0 and 1")
            if width <= 0 or height <= 0 or width > 1 or height > 1:
                raise SourceFormatError(
                    f"YOLO label {location} width and height must be within 0 and 1"
                )

            left = center_x - width / 2
            top = center_y - height / 2
            right = center_x + width / 2
            bottom = center_y + height / 2
            if (
                left < -_BOUNDARY_EPSILON
                or top < -_BOUNDARY_EPSILON
                or right > 1 + _BOUNDARY_EPSILON
                or bottom > 1 + _BOUNDARY_EPSILON
            ):
                raise SourceFormatError(f"YOLO label {location} bounding box exceeds image bounds")

            normalized_left = 0.0 if left < 0 else 1.0 - width if right > 1 else left
            normalized_top = 0.0 if top < 0 else 1.0 - height if bottom > 1 else top
            annotations.append(
                SourceAnnotation(
                    image_key=image.sample_key,
                    category_name=categories[category_id],
                    bbox=(
                        normalized_left * image.width,
                        normalized_top * image.height,
                        width * image.width,
                        height * image.height,
                    ),
                    segmentation=None,
                )
            )
        return annotations


__all__ = ["MAX_CONFIG_BYTES", "YoloDetectionAdapter"]
