from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from label_platform.datasets.contracts import SourceImage


BLOB_URI_PREFIX = "blob://sha256/"


class BlobStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class BlobRecord:
    sha256: str
    size: int
    path: Path

    @property
    def uri(self) -> str:
        return f"{BLOB_URI_PREFIX}{self.sha256}"


class BlobStore:
    def __init__(self, managed_root: Path) -> None:
        self.managed_root = managed_root
        self.root = managed_root / ".blobs" / "sha256"

    def ingest(self, source: SourceImage) -> BlobRecord:
        if _sha256(source.source_path) != source.sha256:
            raise BlobStoreError(f"source image changed during publication: {source.relative_path}")
        self.root.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(prefix=".building-", dir=self.root)
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            self._materialize(source, temporary_path)
            digest = _sha256(temporary_path)
            destination = self.path_for_hash(digest)
            size = temporary_path.stat().st_size
            if destination.exists():
                if not destination.is_file() or destination.is_symlink():
                    raise BlobStoreError(f"blob path is invalid: {digest}")
                if destination.stat().st_size != size or _sha256(destination) != digest:
                    raise BlobStoreError(f"existing blob failed verification: {digest}")
                temporary_path.unlink()
                temporary_path = None
            else:
                temporary_path.chmod(0o444)
                os.replace(temporary_path, destination)
                temporary_path = None
            if _sha256(source.source_path) != source.sha256:
                raise BlobStoreError(
                    f"source image changed during publication: {source.relative_path}"
                )
            return BlobRecord(sha256=digest, size=size, path=destination)
        except BlobStoreError:
            raise
        except OSError as exc:
            raise BlobStoreError(f"cannot store image blob: {source.relative_path}") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def resolve_uri(self, uri: str, *, verify: bool = False) -> Path:
        digest = parse_blob_uri(uri)
        path = self.path_for_hash(digest)
        if not path.is_file() or path.is_symlink():
            raise BlobStoreError(f"blob does not exist: {digest}")
        if verify and _sha256(path) != digest:
            raise BlobStoreError(f"blob failed verification: {digest}")
        return path

    def path_for_hash(self, digest: str) -> Path:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise BlobStoreError("blob SHA-256 is invalid")
        return self.root / digest

    @staticmethod
    def _materialize(source: SourceImage, destination: Path) -> None:
        try:
            with Image.open(source.source_path) as opened:
                orientation = opened.getexif().get(274, 1)
                if orientation != 1:
                    normalized = ImageOps.exif_transpose(opened)
                    normalized.load()
                    if opened.format is None:
                        raise BlobStoreError(
                            f"cannot determine image format: {source.relative_path}"
                        )
                    normalized.save(destination, format=opened.format)
                    return
        except BlobStoreError:
            raise
        except OSError as exc:
            raise BlobStoreError(f"cannot decode image: {source.relative_path}") from exc
        shutil.copyfile(source.source_path, destination, follow_symlinks=False)


def parse_blob_uri(uri: str) -> str:
    if not uri.startswith(BLOB_URI_PREFIX):
        raise BlobStoreError("image URI is not a SHA-256 blob URI")
    digest = uri.removeprefix(BLOB_URI_PREFIX)
    if "/" in digest or len(digest) != 64:
        raise BlobStoreError("blob URI is invalid")
    if any(character not in "0123456789abcdef" for character in digest):
        raise BlobStoreError("blob URI is invalid")
    return digest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
