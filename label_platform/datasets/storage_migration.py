from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from label_platform.datasets.blobs import BlobStore
from label_platform.datasets.contracts import SourceImage
from label_platform.datasets.media import sha256_file
from label_platform.datasets.normalize import CanonicalVersion
from label_platform.datasets.versioning import (
    PLATFORM_DATASET_FORMAT,
    VERSION_FILE_NAME,
    build_version_document,
    load_version_document,
    resolve_version_image,
)
from label_platform.db.models import DatasetVersion
from label_platform.domain.enums import VersionStatus
from label_platform.training.export import UnitTrainExporter


@dataclass(frozen=True)
class StorageMigrationResult:
    scanned: int = 0
    migrated: int = 0
    skipped: int = 0
    blobs_created: int = 0
    exports_rebuilt: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "migrated": self.migrated,
            "skipped": self.skipped,
            "blobs_created": self.blobs_created,
            "exports_rebuilt": self.exports_rebuilt,
        }


def migrate_version_storage(
    session_factory: sessionmaker[Session],
    *,
    managed_root: Path,
    export_root: Path,
    dry_run: bool,
) -> StorageMigrationResult:
    with session_factory() as session:
        versions = session.scalars(
            select(DatasetVersion)
            .where(DatasetVersion.status == VersionStatus.READY)
            .order_by(DatasetVersion.dataset_id, DatasetVersion.version_number)
        ).all()
        version_ids = [version.id for version in versions]

    migrated = 0
    skipped = 0
    blobs_created = 0
    exports_rebuilt = 0
    for version_id in version_ids:
        with session_factory() as session:
            version = session.get(DatasetVersion, version_id)
            if version is None or version.root_path is None:
                skipped += 1
                continue
            if version.manifest_path == VERSION_FILE_NAME:
                skipped += 1
                continue
            if dry_run:
                migrated += 1
                continue
            version_root = _version_root(managed_root, version.root_path)
            document = load_version_document(
                version_root,
                manifest_path=version.manifest_path,
                annotation_path=version.annotation_path,
            )
            canonical, created = _migrate_document(
                managed_root,
                version_root,
                document,
                version,
            )
            blobs_created += created
            payload = build_version_document(canonical)
            _publish_version_json(version_root, payload, managed_root)

        with session_factory() as session, session.begin():
            stored = session.get(DatasetVersion, version_id)
            if stored is None:
                raise RuntimeError("dataset version disappeared during storage migration")
            migrated_images = image_by_sample_from_canonical(canonical)
            for item in stored.items:
                image = migrated_images.get(item.sample_key)
                if image is None:
                    raise RuntimeError(f"migrated dataset item is missing: {item.sample_key}")
                item.sha256 = cast(str, image["sha256"])
                item.file_size = cast(int, image["file_size"])
            stored.manifest_path = VERSION_FILE_NAME
            stored.annotation_path = VERSION_FILE_NAME

        _remove_legacy_artifacts(version_root)
        export = export_root / version_id
        if export.exists() or export.is_symlink():
            _remove_tree(export)
            UnitTrainExporter(export_root, managed_root=managed_root).materialize(
                version_root,
                version_id=version_id,
            )
            exports_rebuilt += 1
        migrated += 1

    return StorageMigrationResult(
        scanned=len(version_ids),
        migrated=migrated,
        skipped=skipped,
        blobs_created=blobs_created,
        exports_rebuilt=exports_rebuilt,
    )


def _migrate_document(
    managed_root: Path,
    version_root: Path,
    document: Any,
    version: DatasetVersion,
) -> tuple[CanonicalVersion, int]:
    coco = copy.deepcopy(document.coco)
    manifest = copy.deepcopy(document.manifest)
    images = cast(list[dict[str, Any]], coco["images"])
    items = {item.sample_key: item for item in version.items}
    sources: dict[str, SourceImage] = {}
    blob_store = BlobStore(managed_root)
    created = 0
    files = manifest.get("files")
    if not isinstance(files, dict):
        files = {}
        manifest["files"] = files
    for image in images:
        sample_key = image.get("sample_key")
        file_name = image.get("file_name")
        if not isinstance(sample_key, str) or not isinstance(file_name, str):
            raise RuntimeError("legacy dataset image identity is invalid")
        item = items.get(sample_key)
        if item is None:
            raise RuntimeError(f"legacy dataset item is missing: {sample_key}")
        source_path = resolve_version_image(managed_root, version_root, image)
        digest = sha256_file(source_path)
        source = SourceImage(
            source_path=source_path,
            relative_path=_relative_below_images(file_name),
            sample_key=sample_key,
            width=item.width,
            height=item.height,
            file_size=source_path.stat().st_size,
            sha256=digest,
            split=item.split,
            group_key=item.group_key,
        )
        existed = blob_store.path_for_hash(digest).is_file()
        blob = blob_store.ingest(source)
        created += int(not existed)
        image["sha256"] = blob.sha256
        image["image_uri"] = blob.uri
        image["file_size"] = blob.size
        files[file_name] = {
            "sha256": blob.sha256,
            "size": blob.size,
            "source_relative_path": source.relative_path,
        }
        sources[sample_key] = source
    manifest["format"] = PLATFORM_DATASET_FORMAT
    return CanonicalVersion(coco=coco, splits=document.splits, manifest=manifest, source_images=sources), created


def image_by_sample_from_canonical(
    canonical: CanonicalVersion,
) -> dict[str, dict[str, Any]]:
    images = cast(list[dict[str, Any]], canonical.coco["images"])
    return {
        cast(str, image["sample_key"]): image
        for image in images
        if isinstance(image.get("sample_key"), str)
    }


def _publish_version_json(version_root: Path, payload: object, managed_root: Path) -> None:
    version_root.chmod(0o755)
    temporary = version_root / ".version.json.building"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o444)
    os.replace(temporary, version_root / VERSION_FILE_NAME)
    stored = load_version_document(version_root, manifest_path=VERSION_FILE_NAME)
    for image in stored.coco["images"]:
        resolve_version_image(managed_root, version_root, image, verify_blob=True)


def _remove_legacy_artifacts(version_root: Path) -> None:
    for relative in ("images", "annotations", "splits", "manifest.json"):
        path = version_root / relative
        if path.exists() or path.is_symlink():
            _remove_tree(path)
    (version_root / VERSION_FILE_NAME).chmod(0o444)
    version_root.chmod(0o555)


def _version_root(managed_root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in relative_path:
        raise RuntimeError("dataset version root escapes managed storage")
    managed = managed_root.resolve(strict=True)
    root = (managed / relative).resolve(strict=True)
    if not root.is_relative_to(managed) or not root.is_dir():
        raise RuntimeError("dataset version root escapes managed storage")
    return root


def _relative_below_images(file_name: str) -> str:
    path = PurePosixPath(file_name)
    if path.parts and path.parts[0] == "images":
        path = PurePosixPath(*path.parts[1:])
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise RuntimeError("legacy dataset image path is invalid")
    return path.as_posix()


def _remove_tree(path: Path) -> None:
    if path.is_symlink():
        path.unlink(missing_ok=True)
        return
    if path.is_file():
        path.chmod(0o644)
        path.unlink(missing_ok=True)
        return
    for child in path.rglob("*"):
        if child.is_symlink():
            continue
        child.chmod(0o755 if child.is_dir() else 0o644)
    path.chmod(0o755)
    shutil.rmtree(path)
