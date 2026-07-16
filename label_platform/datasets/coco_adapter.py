import json
import math
from pathlib import Path
from typing import Any, Hashable, cast

from pycocotools import mask as mask_utils

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


class CocoAdapter:
    def read(self, source_path: Path, *, dataset_id: str) -> SourceDataset:
        image_root = source_path if source_path.is_dir() else source_path.parent
        annotation_path = self._find_annotation(source_path)
        try:
            payload: Any = json.loads(annotation_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceFormatError("COCO annotation file is not valid UTF-8 JSON") from exc
        return self.read_data(payload, image_root=image_root, dataset_id=dataset_id)

    def read_data(
        self,
        payload: object,
        *,
        image_root: Path,
        dataset_id: str,
    ) -> SourceDataset:
        if not isinstance(payload, dict):
            raise SourceFormatError("COCO document must be an object")
        for section in ("images", "annotations", "categories"):
            if not isinstance(payload.get(section), list):
                raise SourceFormatError(f"COCO document requires a {section} array")

        try:
            root = resolve_approved_root(image_root)
        except SourcePathError as exc:
            raise SourceFormatError(str(exc)) from exc

        raw_images = cast(list[object], payload["images"])
        raw_annotations = cast(list[object], payload["annotations"])
        raw_categories = cast(list[object], payload["categories"])
        categories, category_ids = self._read_categories(raw_categories)
        images, image_keys = self._read_images(raw_images, root=root, dataset_id=dataset_id)
        annotations, has_segmentation = self._read_annotations(
            raw_annotations,
            image_keys=image_keys,
            category_ids=category_ids,
            categories=categories,
            images=images,
        )

        task_type = (
            TaskType.INSTANCE_SEGMENTATION if has_segmentation else TaskType.DETECTION
        )
        return SourceDataset(
            format=(
                SourceFormat.COCO_INSTANCE
                if has_segmentation
                else SourceFormat.COCO_DETECTION
            ),
            task_type=task_type,
            images=tuple(images),
            annotations=tuple(annotations),
            categories=tuple(categories),
            category_id_mapping={
                f"source:{source_id}": canonical_id
                for canonical_id, source_id in enumerate(category_ids, start=1)
            },
        )

    def _find_annotation(self, source_path: Path) -> Path:
        if source_path.is_file():
            return source_path.resolve(strict=True)
        try:
            candidates = [
                path
                for path in iter_safe_files(source_path)
                if path.suffix.lower() == ".json"
            ]
        except SourcePathError as exc:
            raise SourceFormatError(str(exc)) from exc
        recognized: list[Path] = []
        for path in candidates:
            try:
                payload: Any = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and all(
                isinstance(payload.get(section), list)
                for section in ("images", "annotations", "categories")
            ):
                recognized.append(path)
        if len(recognized) != 1:
            raise SourceFormatError("source directory must contain exactly one COCO annotation file")
        return recognized[0]

    def _read_categories(
        self,
        raw_categories: list[object],
    ) -> tuple[list[str], list[Hashable]]:
        names: list[str] = []
        source_ids: list[Hashable] = []
        for index, raw in enumerate(raw_categories):
            if not isinstance(raw, dict):
                raise SourceFormatError(f"category at index {index} must be an object")
            source_id = self._hashable_id(raw.get("id"), "category", index)
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                raise SourceFormatError(f"category at index {index} has an invalid name")
            if source_id in source_ids:
                raise SourceFormatError(f"duplicate category id: {source_id}")
            normalized_name = name.strip()
            if normalized_name in names:
                raise SourceFormatError(f"duplicate category name: {normalized_name}")
            source_ids.append(source_id)
            names.append(normalized_name)
        if not names:
            raise SourceFormatError("COCO document must contain at least one category")
        return names, source_ids

    def _read_images(
        self,
        raw_images: list[object],
        *,
        root: Path,
        dataset_id: str,
    ) -> tuple[list[SourceImage], dict[Hashable, str]]:
        images: list[SourceImage] = []
        image_keys: dict[Hashable, str] = {}
        relative_paths: set[str] = set()
        for index, raw in enumerate(raw_images):
            if not isinstance(raw, dict):
                raise SourceFormatError(f"image at index {index} must be an object")
            source_id = self._hashable_id(raw.get("id"), "image", index)
            if source_id in image_keys:
                raise SourceFormatError(f"duplicate image id: {source_id}")
            file_name = raw.get("file_name")
            if not isinstance(file_name, str) or not file_name:
                raise SourceFormatError(f"image at index {index} has an invalid file_name")
            try:
                path = resolve_source_file(root, file_name)
            except SourcePathError as exc:
                raise SourceFormatError(str(exc)) from exc
            relative_path = path.relative_to(root).as_posix()
            if relative_path in relative_paths:
                raise SourceFormatError(f"duplicate normalized image path: {relative_path}")
            relative_paths.add(relative_path)
            image = read_source_image(
                path,
                root=root,
                dataset_id=dataset_id,
                relative_path=relative_path,
                split=self._optional_string(raw.get("split")),
                group_key=self._optional_string(raw.get("group_key")),
            )
            for dimension_name, actual in (("width", image.width), ("height", image.height)):
                declared = raw.get(dimension_name)
                if declared is not None and declared != actual:
                    raise SourceFormatError(
                        f"image {source_id} {dimension_name} does not match the image file"
                    )
            images.append(image)
            image_keys[source_id] = image.sample_key
        if not images:
            raise SourceFormatError("COCO document must contain at least one image")
        return images, image_keys

    def _read_annotations(
        self,
        raw_annotations: list[object],
        *,
        image_keys: dict[Hashable, str],
        category_ids: list[Hashable],
        categories: list[str],
        images: list[SourceImage],
    ) -> tuple[list[SourceAnnotation], bool]:
        annotations: list[SourceAnnotation] = []
        annotation_ids: set[Hashable] = set()
        image_by_key = {image.sample_key: image for image in images}
        category_by_id = dict(zip(category_ids, categories, strict=True))
        has_segmentation = False
        for index, raw in enumerate(raw_annotations):
            if not isinstance(raw, dict):
                raise SourceFormatError(f"annotation at index {index} must be an object")
            annotation_id = self._hashable_id(raw.get("id"), "annotation", index)
            if annotation_id in annotation_ids:
                raise SourceFormatError(f"duplicate annotation id: {annotation_id}")
            annotation_ids.add(annotation_id)
            image_id = self._hashable_id(raw.get("image_id"), "annotation image", index)
            category_id = self._hashable_id(raw.get("category_id"), "annotation category", index)
            if image_id not in image_keys:
                raise SourceFormatError(f"annotation {annotation_id} references unknown image {image_id}")
            if category_id not in category_by_id:
                raise SourceFormatError(
                    f"annotation {annotation_id} references unknown category {category_id}"
                )

            bbox = self._bbox(raw.get("bbox"), annotation_id)
            image = image_by_key[image_keys[image_id]]
            segmentation = self._segmentation(
                raw.get("segmentation"),
                height=image.height,
                width=image.width,
                annotation_id=annotation_id,
            )
            has_segmentation = has_segmentation or segmentation is not None
            if bbox is None and segmentation is None:
                raise SourceFormatError(
                    f"annotation {annotation_id} requires bbox or segmentation geometry"
                )
            annotations.append(
                SourceAnnotation(
                    image_key=image_keys[image_id],
                    category_name=category_by_id[category_id],
                    bbox=bbox,
                    segmentation=segmentation,
                )
            )
        return annotations, has_segmentation

    @staticmethod
    def _hashable_id(value: object, kind: str, index: int) -> Hashable:
        if value is None or isinstance(value, bool):
            raise SourceFormatError(f"{kind} at index {index} has an invalid id")
        try:
            hash(value)
        except TypeError as exc:
            raise SourceFormatError(f"{kind} at index {index} has an invalid id") from exc
        return value

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _bbox(value: object, annotation_id: Hashable) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        if not isinstance(value, list) or len(value) != 4:
            raise SourceFormatError(f"annotation {annotation_id} bbox must contain four numbers")
        if any(isinstance(number, bool) or not isinstance(number, (int, float)) for number in value):
            raise SourceFormatError(f"annotation {annotation_id} bbox must contain four numbers")
        bbox = tuple(float(number) for number in value)
        if not all(math.isfinite(number) for number in bbox):
            raise SourceFormatError(f"annotation {annotation_id} bbox values must be finite")
        return cast(tuple[float, float, float, float], bbox)

    @staticmethod
    def _segmentation(
        value: object,
        *,
        height: int,
        width: int,
        annotation_id: Hashable,
    ) -> dict[str, object] | list[list[float]] | None:
        if value is None or value == [] or value == {}:
            return None
        if isinstance(value, list):
            polygons: list[list[float]] = []
            for polygon in value:
                if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2:
                    raise SourceFormatError(f"annotation {annotation_id} has an invalid polygon")
                if any(
                    isinstance(number, bool) or not isinstance(number, (int, float))
                    for number in polygon
                ):
                    raise SourceFormatError(f"annotation {annotation_id} has an invalid polygon")
                normalized = [float(number) for number in polygon]
                if not all(math.isfinite(number) for number in normalized):
                    raise SourceFormatError(
                        f"annotation {annotation_id} polygon values must be finite"
                    )
                polygons.append(normalized)
            return polygons
        if not isinstance(value, dict):
            raise SourceFormatError(f"annotation {annotation_id} has invalid segmentation")
        size = value.get("size")
        counts = value.get("counts")
        if size != [height, width] or not isinstance(counts, (list, str)):
            raise SourceFormatError(f"annotation {annotation_id} has invalid RLE segmentation")
        try:
            if isinstance(counts, list):
                rle: Any = mask_utils.frPyObjects(cast(Any, value), height, width)
            else:
                rle = {"size": size, "counts": counts.encode("utf-8")}
                mask_utils.decode(rle)
        except (TypeError, ValueError, IndexError) as exc:
            raise SourceFormatError(
                f"annotation {annotation_id} has invalid RLE segmentation"
            ) from exc
        normalized_counts = rle["counts"]
        if isinstance(normalized_counts, bytes):
            normalized_counts = normalized_counts.decode("utf-8")
        return {"size": [height, width], "counts": normalized_counts}
