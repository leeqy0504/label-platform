import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from dataclasses import dataclass
from typing import Any

from label_platform.datasets.versioning import (
    VersionStorageError,
    load_version_document,
    resolve_version_image,
)


UNITRAIN_EXPORT_PROFILE = "unitrain-coco-split-v1"
UNITRAIN_EXPORT_CONVERTER_VERSION = "label-platform-unitrain-1.0.0"
_SPLIT_DIRECTORIES = {"train": "train", "val": "valid", "test": "test"}


class UnitTrainExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class UnitTrainExportResult:
    root: Path
    annotation_path: str
    profile: str
    converter_version: str
    manifest: dict[str, Any]


class UnitTrainExporter:
    def __init__(self, export_root: Path, *, managed_root: Path | None = None):
        self.export_root = export_root
        self.managed_root = managed_root

    def materialize(
        self,
        version_root: Path,
        *,
        version_id: str,
        profile: str = UNITRAIN_EXPORT_PROFILE,
    ) -> UnitTrainExportResult:
        if profile != UNITRAIN_EXPORT_PROFILE:
            raise UnitTrainExportError(f"Unsupported UnitTrain export profile: {profile}")
        source = version_root.resolve(strict=True)
        if not source.is_dir():
            raise UnitTrainExportError("Canonical version root is not a directory")
        try:
            version = load_version_document(source)
        except VersionStorageError as exc:
            raise UnitTrainExportError(str(exc)) from exc
        coco = version.coco
        canonical_manifest = version.manifest
        self._validate_canonical(coco)
        managed_root = self.managed_root or source.parents[2]

        version_exports = self.export_root / version_id
        final = version_exports / profile
        expected_source_hash = version.source_sha256
        if final.is_dir():
            existing = self._read_object(final / "export-manifest.json")
            if (
                existing.get("source_version_id") == version_id
                and existing.get("source_manifest_sha256") == expected_source_hash
                and existing.get("converter_version") == UNITRAIN_EXPORT_CONVERTER_VERSION
            ):
                self._ensure_relative_image_links(
                    final,
                    version_root=source,
                    managed_root=managed_root,
                    splits=version.splits,
                    images=coco["images"],
                )
                return self._result(final, existing)
            raise UnitTrainExportError("Existing UnitTrain export does not match this version")

        staging = version_exports / f".{profile}.building"
        try:
            version_exports.mkdir(parents=True, exist_ok=True)
            if staging.exists() or staging.is_symlink():
                self._remove_tree(staging)
            staging.mkdir()
            split_members = {
                split: set(version.splits[split]) for split in _SPLIT_DIRECTORIES
            }
            if not split_members["train"]:
                raise UnitTrainExportError("UnitTrain export requires a non-empty train split")
            images = coco["images"]
            annotations = coco["annotations"]
            categories = coco["categories"]
            image_by_sample = {image["sample_key"]: image for image in images}
            assigned = set().union(*split_members.values())
            if assigned != set(image_by_sample):
                raise UnitTrainExportError("Canonical split membership does not cover every sample")
            if sum(len(members) for members in split_members.values()) != len(assigned):
                raise UnitTrainExportError("Canonical split membership overlaps")

            output_counts: dict[str, int] = {}
            for split, destination_name in _SPLIT_DIRECTORIES.items():
                destination = staging / destination_name
                destination.mkdir()
                split_images: list[dict[str, Any]] = []
                split_image_ids: set[int] = set()
                for sample_key in sorted(split_members[split]):
                    image = image_by_sample.get(sample_key)
                    if image is None:
                        raise UnitTrainExportError(f"Unknown sample in {split} split: {sample_key}")
                    try:
                        source_image = resolve_version_image(managed_root, source, image)
                    except VersionStorageError as exc:
                        raise UnitTrainExportError(str(exc)) from exc
                    output_name = self._output_name(image)
                    output_path = destination / output_name
                    output_path.symlink_to(
                        Path(os.path.relpath(source_image, start=output_path.parent))
                    )
                    split_images.append({**image, "file_name": output_name})
                    split_image_ids.add(image["id"])
                split_annotations = [
                    annotation
                    for annotation in annotations
                    if annotation["image_id"] in split_image_ids
                ]
                self._write_json(
                    destination / "_annotations.coco.json",
                    {
                        "info": coco.get("info", {}),
                        "images": split_images,
                        "annotations": split_annotations,
                        "categories": categories,
                    },
                )
                output_counts[split] = len(split_images)

            manifest: dict[str, Any] = {
                "profile": profile,
                "converter_version": UNITRAIN_EXPORT_CONVERTER_VERSION,
                "source_format": canonical_manifest.get("format"),
                "source_version_id": version_id,
                "source_manifest_sha256": expected_source_hash,
                "task_type": canonical_manifest.get("task_type"),
                "split_counts": output_counts,
                "annotation_path": "train/_annotations.coco.json",
            }
            self._write_json(staging / "export-manifest.json", manifest)
            self._make_immutable(staging)
            os.replace(staging, final)
            return self._result(final, manifest)
        except Exception as exc:
            if staging.exists() or staging.is_symlink():
                self._remove_tree(staging)
            if isinstance(exc, UnitTrainExportError):
                raise
            raise UnitTrainExportError(str(exc)) from exc

    @staticmethod
    def _validate_canonical(coco: dict[str, Any]) -> None:
        for key in ("images", "annotations", "categories"):
            if not isinstance(coco.get(key), list):
                raise UnitTrainExportError(f"Canonical COCO {key} must be an array")
        sample_keys: set[str] = set()
        image_ids: set[int] = set()
        for image in coco["images"]:
            if not isinstance(image, dict):
                raise UnitTrainExportError("Canonical COCO image is invalid")
            sample_key = image.get("sample_key")
            image_id = image.get("id")
            file_name = image.get("file_name")
            if (
                not isinstance(sample_key, str)
                or not isinstance(image_id, int)
                or isinstance(image_id, bool)
                or not isinstance(file_name, str)
                or sample_key in sample_keys
                or image_id in image_ids
            ):
                raise UnitTrainExportError("Canonical COCO image identity is invalid")
            sample_keys.add(sample_key)
            image_ids.add(image_id)

    @staticmethod
    def _contained_file(root: Path, relative_path: str) -> Path:
        path = PurePosixPath(relative_path)
        if path.is_absolute() or ".." in path.parts or "\\" in relative_path:
            raise UnitTrainExportError(f"Canonical media path escapes version: {relative_path}")
        cursor = root
        for part in path.parts:
            cursor /= part
            if cursor.is_symlink():
                raise UnitTrainExportError(f"Canonical media path is a symlink: {relative_path}")
        resolved = cursor.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise UnitTrainExportError(f"Canonical media file is missing: {relative_path}")
        return resolved

    @staticmethod
    def _output_name(image: dict[str, Any]) -> str:
        name = PurePosixPath(image["file_name"]).name
        return f"{image['id']:012d}-{name}"

    def _ensure_relative_image_links(
        self,
        export_root: Path,
        *,
        version_root: Path,
        managed_root: Path,
        splits: dict[str, tuple[str, ...]],
        images: list[dict[str, Any]],
    ) -> None:
        image_by_sample = {image["sample_key"]: image for image in images}
        for split, destination_name in _SPLIT_DIRECTORIES.items():
            destination_root = export_root / destination_name
            repairs: list[tuple[Path, Path]] = []
            for sample_key in splits[split]:
                image = image_by_sample.get(sample_key)
                if image is None:
                    raise UnitTrainExportError(
                        f"Existing UnitTrain export references an unknown sample: {sample_key}"
                    )
                destination = destination_root / self._output_name(image)
                if not destination.is_symlink():
                    raise UnitTrainExportError(
                        f"Existing UnitTrain export image is not a symbolic link: {destination.name}"
                    )
                try:
                    expected = resolve_version_image(managed_root, version_root, image)
                    current_target = Path(os.readlink(destination))
                except (OSError, VersionStorageError) as exc:
                    raise UnitTrainExportError(
                        f"Existing UnitTrain export image cannot be resolved: {destination.name}"
                    ) from exc
                expected_target = Path(
                    os.path.relpath(expected, start=destination.parent)
                )
                if current_target == expected_target:
                    continue
                repairs.append((destination, expected))
            if repairs:
                self._replace_image_links(destination_root, repairs)

    @staticmethod
    def _replace_image_links(
        destination_root: Path,
        repairs: list[tuple[Path, Path]],
    ) -> None:
        original_mode = destination_root.stat().st_mode & 0o777
        destination_root.chmod(original_mode | 0o200)
        try:
            for destination, source in repairs:
                temporary = destination.with_name(f".{destination.name}.link-building")
                temporary.unlink(missing_ok=True)
                temporary.symlink_to(
                    Path(os.path.relpath(source, start=destination.parent))
                )
                os.replace(temporary, destination)
        finally:
            destination_root.chmod(original_mode)

    @staticmethod
    def _read_split(path: Path) -> set[str]:
        try:
            members = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        except OSError as exc:
            raise UnitTrainExportError(f"Cannot read canonical split: {path.name}") from exc
        if any(not member for member in members) or len(set(members)) != len(members):
            raise UnitTrainExportError(f"Canonical split is invalid: {path.name}")
        return set(members)

    @staticmethod
    def _read_object(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UnitTrainExportError(f"Cannot read export input: {path.name}") from exc
        if not isinstance(value, dict):
            raise UnitTrainExportError(f"Export input must be an object: {path.name}")
        return value

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _make_immutable(root: Path) -> None:
        for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_symlink():
                continue
            path.chmod(0o555 if path.is_dir() else 0o444)
        root.chmod(0o555)

    @staticmethod
    def _remove_tree(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
            return
        for child in path.rglob("*"):
            child.chmod(0o755 if child.is_dir() else 0o644)
        path.chmod(0o755)
        shutil.rmtree(path)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _result(root: Path, manifest: dict[str, Any]) -> UnitTrainExportResult:
        return UnitTrainExportResult(
            root=root,
            annotation_path=str(manifest["annotation_path"]),
            profile=str(manifest["profile"]),
            converter_version=str(manifest["converter_version"]),
            manifest=manifest,
        )
