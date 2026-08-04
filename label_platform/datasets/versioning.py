from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from label_platform.datasets.blobs import BlobStore, BlobStoreError
from label_platform.datasets.normalize import CanonicalVersion, SPLIT_NAMES


PLATFORM_DATASET_FORMAT = "platform-dataset-v2"
VERSION_FILE_NAME = "version.json"


class VersionStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class VersionDocument:
    document: dict[str, Any]
    coco: dict[str, Any]
    manifest: dict[str, Any]
    splits: dict[str, tuple[str, ...]]
    source_path: Path
    is_v2: bool

    @property
    def source_sha256(self) -> str:
        return _sha256(self.source_path)


def build_version_document(canonical: CanonicalVersion) -> dict[str, Any]:
    images = cast(list[dict[str, Any]], canonical.coco.get("images"))
    split_by_sample = {
        sample_key: split
        for split, sample_keys in canonical.splits.items()
        for sample_key in sample_keys
    }
    version_images: list[dict[str, Any]] = []
    for image in images:
        sample_key = image.get("sample_key")
        if not isinstance(sample_key, str) or sample_key not in split_by_sample:
            raise VersionStorageError("canonical image has no split assignment")
        source = canonical.source_images.get(sample_key)
        if source is None:
            raise VersionStorageError("canonical image has no source mapping")
        sha256 = image.get("sha256")
        image_uri = image.get("image_uri")
        file_size = image.get("file_size")
        if not isinstance(sha256, str) or not isinstance(image_uri, str):
            raise VersionStorageError("canonical image has no blob identity")
        if not isinstance(file_size, int) or isinstance(file_size, bool) or file_size < 0:
            raise VersionStorageError("canonical image has an invalid file size")
        version_images.append(
            {
                **image,
                "split": split_by_sample[sample_key],
                "sha256": sha256,
                "image_uri": image_uri,
                "file_size": file_size,
                "original_file_name": PurePosixPath(source.relative_path).name,
                "source_relative_path": source.relative_path,
                "group_key": source.group_key,
            }
        )

    manifest = canonical.manifest
    return {
        "format": PLATFORM_DATASET_FORMAT,
        "converter_version": manifest.get("converter_version"),
        "task_type": manifest.get("task_type"),
        "source_format": manifest.get("source_format"),
        "source_version": manifest.get("source_version"),
        "source_lineage": manifest.get("source_lineage", {}),
        "category_id_mapping": manifest.get("category_id_mapping", {}),
        "split_config": manifest.get("split_config", {}),
        "split_counts": {split: len(canonical.splits[split]) for split in SPLIT_NAMES},
        "image_count": len(version_images),
        "annotation_count": len(canonical.coco.get("annotations", [])),
        "category_count": len(canonical.coco.get("categories", [])),
        "categories": canonical.coco.get("categories", []),
        "images": version_images,
        "annotations": canonical.coco.get("annotations", []),
        "validation_result": manifest.get("validation_result", {}),
    }


def load_version_document(
    version_root: Path,
    *,
    manifest_path: str | None = None,
    annotation_path: str | None = None,
) -> VersionDocument:
    root = version_root.resolve(strict=True)
    if not root.is_dir():
        raise VersionStorageError("dataset version root is not a directory")
    configured = manifest_path or "manifest.json"
    version_file = root / VERSION_FILE_NAME
    if configured == VERSION_FILE_NAME or (
        manifest_path is None and version_file.is_file() and not version_file.is_symlink()
    ):
        document = _read_object(_contained_file(root, VERSION_FILE_NAME))
        if document.get("format") != PLATFORM_DATASET_FORMAT:
            raise VersionStorageError("version.json has an unsupported format")
        return _load_v2(version_file, document)
    configured_path = _contained_file(root, configured)
    manifest = _read_object(configured_path)
    if manifest.get("format") == PLATFORM_DATASET_FORMAT:
        return _load_v2(configured_path, manifest)
    if version_file.is_file() and not version_file.is_symlink():
        document = _read_object(version_file)
        if document.get("format") == PLATFORM_DATASET_FORMAT:
            return _load_v2(version_file, document)

    annotation = _contained_file(root, annotation_path or "annotations/instances.coco.json")
    coco = _read_object(annotation)
    splits = {
        split: _read_split(_contained_file(root, f"splits/{split}.txt"))
        for split in SPLIT_NAMES
    }
    _validate_sections(coco)
    return VersionDocument(
        document=manifest,
        coco=coco,
        manifest=manifest,
        splits=splits,
        source_path=configured_path,
        is_v2=False,
    )


def load_version_coco(
    version_root: Path,
    *,
    manifest_path: str | None = None,
    annotation_path: str | None = None,
) -> dict[str, Any]:
    root = version_root.resolve(strict=True)
    if manifest_path == VERSION_FILE_NAME or annotation_path == VERSION_FILE_NAME:
        return load_version_document(
            root,
            manifest_path=VERSION_FILE_NAME,
            annotation_path=VERSION_FILE_NAME,
        ).coco
    version_file = root / VERSION_FILE_NAME
    if manifest_path is None and version_file.is_file() and not version_file.is_symlink():
        return load_version_document(root, manifest_path=VERSION_FILE_NAME).coco
    annotation = _contained_file(root, annotation_path or "annotations/instances.coco.json")
    coco = _read_object(annotation)
    _validate_sections(coco)
    return coco


def load_version_manifest(
    version_root: Path,
    *,
    manifest_path: str | None = None,
) -> dict[str, Any]:
    root = version_root.resolve(strict=True)
    configured = manifest_path or (
        VERSION_FILE_NAME if (root / VERSION_FILE_NAME).is_file() else "manifest.json"
    )
    document = _read_object(_contained_file(root, configured))
    if document.get("format") == PLATFORM_DATASET_FORMAT:
        return {
            key: value
            for key, value in document.items()
            if key not in {"images", "annotations"}
        }
    return document


def resolve_version_image(
    managed_root: Path,
    version_root: Path,
    image: dict[str, Any],
    *,
    verify_blob: bool = False,
) -> Path:
    image_uri = image.get("image_uri")
    if isinstance(image_uri, str):
        try:
            return BlobStore(managed_root).resolve_uri(image_uri, verify=verify_blob)
        except BlobStoreError as exc:
            raise VersionStorageError(str(exc)) from exc
    file_name = image.get("file_name")
    if not isinstance(file_name, str):
        raise VersionStorageError("dataset image file_name is invalid")
    return _contained_file(version_root.resolve(strict=True), file_name)


def image_by_sample(document: VersionDocument) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for image in cast(list[dict[str, Any]], document.coco["images"]):
        sample_key = image.get("sample_key")
        if not isinstance(sample_key, str) or not sample_key or sample_key in result:
            raise VersionStorageError("dataset version contains invalid sample keys")
        result[sample_key] = image
    return result


def _load_v2(path: Path, document: dict[str, Any]) -> VersionDocument:
    _validate_sections(document)
    images = cast(list[dict[str, Any]], document["images"])
    splits: dict[str, list[str]] = {split: [] for split in SPLIT_NAMES}
    for image in images:
        sample_key = image.get("sample_key")
        split = image.get("split")
        if not isinstance(sample_key, str) or split not in splits:
            raise VersionStorageError("version.json contains an invalid image split")
        splits[cast(str, split)].append(sample_key)
        if not isinstance(image.get("sha256"), str) or not isinstance(
            image.get("image_uri"), str
        ):
            raise VersionStorageError("version.json image has no blob identity")
    manifest = {
        key: value
        for key, value in document.items()
        if key not in {"images", "annotations"}
    }
    return VersionDocument(
        document=document,
        coco={
            "info": {
                "format": PLATFORM_DATASET_FORMAT,
                "converter_version": document.get("converter_version"),
            },
            "images": document["images"],
            "annotations": document["annotations"],
            "categories": document["categories"],
        },
        manifest=manifest,
        splits={split: tuple(sorted(members)) for split, members in splits.items()},
        source_path=path,
        is_v2=True,
    )


def _validate_sections(document: dict[str, Any]) -> None:
    for section in ("images", "annotations", "categories"):
        value = document.get(section)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise VersionStorageError(f"dataset version {section} must be an object array")
    if not document["images"]:
        raise VersionStorageError("dataset version cannot contain zero images")


def _contained_file(root: Path, relative_path: str) -> Path:
    if "\x00" in relative_path or "\\" in relative_path:
        raise VersionStorageError("dataset version path is invalid")
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or str(relative) in {"", "."}:
        raise VersionStorageError("dataset version path escapes its root")
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise VersionStorageError("dataset version metadata cannot be a symbolic link")
    try:
        resolved = cursor.resolve(strict=True)
    except OSError as exc:
        raise VersionStorageError(f"dataset version file does not exist: {relative_path}") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise VersionStorageError("dataset version path escapes its root")
    return resolved


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VersionStorageError(f"cannot read dataset version file: {path.name}") from exc
    if not isinstance(value, dict):
        raise VersionStorageError(f"dataset version file must contain an object: {path.name}")
    return value


def _read_split(path: Path) -> tuple[str, ...]:
    try:
        members = tuple(line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError) as exc:
        raise VersionStorageError(f"cannot read dataset split: {path.name}") from exc
    if any(not member for member in members) or len(set(members)) != len(members):
        raise VersionStorageError(f"dataset split is invalid: {path.name}")
    return members


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
