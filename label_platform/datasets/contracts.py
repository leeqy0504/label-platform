from dataclasses import dataclass
from pathlib import Path

from label_platform.domain.enums import SourceFormat, TaskType


class SourceFormatError(ValueError):
    pass


@dataclass(frozen=True)
class SourceImage:
    source_path: Path
    relative_path: str
    sample_key: str
    width: int
    height: int
    file_size: int
    sha256: str
    split: str | None = None
    group_key: str | None = None


@dataclass(frozen=True)
class SourceAnnotation:
    image_key: str
    category_name: str
    bbox: tuple[float, float, float, float] | None
    segmentation: dict[str, object] | list[list[float]] | None


@dataclass(frozen=True)
class SourceDataset:
    format: SourceFormat
    task_type: TaskType
    images: tuple[SourceImage, ...]
    annotations: tuple[SourceAnnotation, ...]
    categories: tuple[str, ...]
    category_id_mapping: dict[str, int]
