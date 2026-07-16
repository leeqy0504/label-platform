from dataclasses import dataclass
from pathlib import Path

from label_platform.datasets.contracts import SourceFormatError
from label_platform.datasets.paths import SourcePathError, iter_safe_files
from label_platform.domain.enums import SourceFormat, TaskType


IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})


@dataclass(frozen=True)
class DetectedSource:
    format: SourceFormat
    source_path: Path
    task_type: TaskType | None = None
    annotation_path: Path | None = None


def detect_source(source_path: Path) -> DetectedSource:
    try:
        files = tuple(iter_safe_files(source_path))
    except SourcePathError as exc:
        raise SourceFormatError(f"source must be an existing safe directory: {exc}") from exc

    if any(path.suffix.lower() in IMAGE_EXTENSIONS for path in files):
        return DetectedSource(
            format=SourceFormat.IMAGE_DIRECTORY,
            source_path=source_path.resolve(strict=True),
        )

    raise SourceFormatError("directory does not contain a supported dataset source")


__all__ = ["DetectedSource", "SourceFormatError", "detect_source"]
