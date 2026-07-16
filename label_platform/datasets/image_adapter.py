import hashlib
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from label_platform.datasets.contracts import SourceDataset, SourceFormatError, SourceImage
from label_platform.datasets.detection import IMAGE_EXTENSIONS
from label_platform.datasets.paths import SourcePathError, iter_safe_files, resolve_approved_root
from label_platform.domain.enums import SourceFormat, TaskType


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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

            try:
                with Image.open(image_path) as opened:
                    transposed = ImageOps.exif_transpose(opened)
                    transposed.load()
                    width, height = transposed.size
            except (OSError, UnidentifiedImageError, ValueError) as exc:
                raise SourceFormatError(f"cannot decode image: {relative_path}") from exc

            sample_key = hashlib.sha256(
                f"{dataset_id}\0{relative_path}".encode("utf-8")
            ).hexdigest()
            try:
                file_size = image_path.stat(follow_symlinks=False).st_size
                sha256 = _sha256_file(image_path)
            except OSError as exc:
                raise SourceFormatError(f"cannot read image: {relative_path}") from exc

            images.append(
                SourceImage(
                    source_path=image_path,
                    relative_path=relative_path,
                    sample_key=sample_key,
                    width=width,
                    height=height,
                    file_size=file_size,
                    sha256=sha256,
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
