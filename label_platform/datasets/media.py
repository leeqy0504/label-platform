import hashlib
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from label_platform.datasets.contracts import SourceFormatError, SourceImage


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SourceFormatError(f"cannot read image: {path.name}") from exc
    return digest.hexdigest()


def read_source_image(
    path: Path,
    *,
    root: Path,
    dataset_id: str,
    relative_path: str | None = None,
    split: str | None = None,
    group_key: str | None = None,
) -> SourceImage:
    normalized_relative = relative_path or path.relative_to(root).as_posix()
    try:
        with Image.open(path) as opened:
            transposed = ImageOps.exif_transpose(opened)
            transposed.load()
            width, height = transposed.size
        file_size = path.stat(follow_symlinks=False).st_size
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise SourceFormatError(f"cannot decode image: {normalized_relative}") from exc

    sample_key = hashlib.sha256(
        f"{dataset_id}\0{normalized_relative}".encode("utf-8")
    ).hexdigest()
    return SourceImage(
        source_path=path,
        relative_path=normalized_relative,
        sample_key=sample_key,
        width=width,
        height=height,
        file_size=file_size,
        sha256=sha256_file(path),
        split=split,
        group_key=group_key,
    )
