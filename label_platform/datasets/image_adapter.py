from pathlib import Path

from label_platform.datasets.contracts import SourceDataset, SourceFormatError, SourceImage
from label_platform.datasets.detection import IMAGE_EXTENSIONS
from label_platform.datasets.media import read_source_image
from label_platform.datasets.paths import SourcePathError, iter_safe_files, resolve_approved_root
from label_platform.domain.enums import SourceFormat, TaskType


def _normalize_categories(categories: list[str]) -> tuple[str, ...]:
    normalized = tuple(category.strip() for category in categories)
    if not normalized or any(not category for category in normalized):
        raise SourceFormatError("categories must contain at least one non-empty name")
    if len(set(normalized)) != len(normalized):
        raise SourceFormatError("categories must contain unique names")
    return normalized


class ImageDirectoryAdapter:
    def read(
        self,
        source_path: Path,
        *,
        dataset_id: str,
        categories: list[str],
        task_type: TaskType = TaskType.DETECTION,
    ) -> SourceDataset:
        normalized_categories = _normalize_categories(categories)
        try:
            root = resolve_approved_root(source_path)
            image_paths = tuple(
                path for path in iter_safe_files(root) if path.suffix.lower() in IMAGE_EXTENSIONS
            )
        except SourcePathError as exc:
            raise SourceFormatError(str(exc)) from exc

        if not image_paths:
            raise SourceFormatError("source directory contains no supported images")

        images: list[SourceImage] = []
        relative_paths: set[str] = set()
        for image_path in image_paths:
            relative_path = image_path.relative_to(root).as_posix()
            if relative_path in relative_paths:
                raise SourceFormatError(f"duplicate normalized image path: {relative_path}")
            relative_paths.add(relative_path)

            images.append(
                read_source_image(
                    image_path,
                    root=root,
                    dataset_id=dataset_id,
                    relative_path=relative_path,
                )
            )

        return SourceDataset(
            format=SourceFormat.IMAGE_DIRECTORY,
            task_type=task_type,
            images=tuple(images),
            annotations=(),
            categories=normalized_categories,
            category_id_mapping={
                f"source:{category}": category_id
                for category_id, category in enumerate(normalized_categories, start=1)
            },
        )
