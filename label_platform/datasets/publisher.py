import copy
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from PIL import Image, ImageOps

from label_platform.datasets.contracts import SourceImage
from label_platform.datasets.normalize import CanonicalVersion, SPLIT_NAMES
from label_platform.datasets.validate import ValidationReport, validate_canonical


class CloneFile(Protocol):
    def __call__(self, source: Path, destination: Path) -> object: ...


class DatasetPublicationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        validation_report: ValidationReport | None = None,
    ) -> None:
        super().__init__(message)
        self.validation_report = validation_report


@dataclass(frozen=True)
class PublicationResult:
    version_root: Path
    canonical: CanonicalVersion
    validation_report: ValidationReport


class DatasetPublisher:
    def __init__(self, managed_root: Path) -> None:
        self.managed_root = managed_root

    def publish(
        self,
        canonical: CanonicalVersion,
        *,
        dataset_id: str,
        version_number: int,
        version_id: str,
        frozen_schema: list[dict[str, object]] | None = None,
    ) -> PublicationResult:
        if version_number <= 0 or not dataset_id or not version_id:
            raise DatasetPublicationError("dataset and version identity must be valid")
        initial_report = validate_canonical(canonical, frozen_schema=frozen_schema)
        if not initial_report.valid:
            raise DatasetPublicationError(
                "canonical dataset failed pre-publication validation",
                validation_report=initial_report,
            )

        published = CanonicalVersion(
            coco=copy.deepcopy(canonical.coco),
            splits=copy.deepcopy(canonical.splits),
            manifest=copy.deepcopy(canonical.manifest),
            source_images=canonical.source_images.copy(),
        )
        dataset_root = self.managed_root / dataset_id
        versions_root = dataset_root / "versions"
        staging = versions_root / f".building-{version_id}"
        final = versions_root / f"v{version_number}"
        latest_temp = dataset_root / f".latest-{version_id}"
        final_created = False

        try:
            self.managed_root.mkdir(parents=True, exist_ok=True)
            versions_root.mkdir(parents=True, exist_ok=True)
            if final.exists() or final.is_symlink():
                raise DatasetPublicationError(f"dataset version v{version_number} already exists")
            if staging.exists() or staging.is_symlink():
                self._remove_tree(staging)
            staging.mkdir()
            (staging / "images").mkdir()
            (staging / "annotations").mkdir()
            (staging / "splits").mkdir()

            self._materialize_images(published, staging)
            annotation_path = staging / "annotations" / "instances.coco.json"
            self._write_json(annotation_path, published.coco)
            split_paths: list[Path] = []
            for split in SPLIT_NAMES:
                split_path = staging / "splits" / f"{split}.txt"
                self._write_split(split_path, published.splits[split])
                split_paths.append(split_path)

            report = validate_canonical(
                published,
                frozen_schema=frozen_schema,
                version_root=staging,
            )
            if not report.valid:
                raise DatasetPublicationError(
                    "staged dataset failed validation",
                    validation_report=report,
                )
            published.manifest["validation_result"] = report.as_dict()
            published.manifest["artifacts"] = {
                annotation_path.relative_to(staging).as_posix(): {
                    "sha256": _sha256(annotation_path),
                    "size": annotation_path.stat().st_size,
                },
                **{
                    path.relative_to(staging).as_posix(): {
                        "sha256": _sha256(path),
                        "size": path.stat().st_size,
                    }
                    for path in split_paths
                },
            }
            self._write_json(staging / "manifest.json", published.manifest)
            self._make_immutable(staging)
            os.replace(staging, final)
            final_created = True

            if latest_temp.exists() or latest_temp.is_symlink():
                latest_temp.unlink()
            latest_temp.symlink_to(Path("versions") / final.name, target_is_directory=True)
            os.replace(latest_temp, dataset_root / "latest")
            return PublicationResult(
                version_root=final,
                canonical=published,
                validation_report=report,
            )
        except Exception as exc:
            if latest_temp.exists() or latest_temp.is_symlink():
                latest_temp.unlink()
            if staging.exists() or staging.is_symlink():
                self._remove_tree(staging)
            if final_created and (final.exists() or final.is_symlink()):
                self._remove_tree(final)
            if isinstance(exc, DatasetPublicationError):
                raise
            raise DatasetPublicationError(str(exc)) from exc

    def rollback_publication(
        self,
        *,
        dataset_id: str,
        version_number: int,
        version_id: str,
        previous_version_number: int | None,
    ) -> None:
        dataset_root = self.managed_root / dataset_id
        final = dataset_root / "versions" / f"v{version_number}"
        latest = dataset_root / "latest"
        expected_target = f"versions/v{version_number}"
        current_target = os.readlink(latest) if latest.is_symlink() else None
        if final.exists() or final.is_symlink():
            self._remove_tree(final)
        if current_target != expected_target:
            return
        if previous_version_number is None:
            latest.unlink(missing_ok=True)
            return
        previous = dataset_root / "versions" / f"v{previous_version_number}"
        if not previous.is_dir():
            latest.unlink(missing_ok=True)
            return
        temporary = dataset_root / f".latest-rollback-{version_id}"
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        temporary.symlink_to(
            Path("versions") / f"v{previous_version_number}",
            target_is_directory=True,
        )
        os.replace(temporary, latest)

    def _materialize_images(self, canonical: CanonicalVersion, staging: Path) -> None:
        files = canonical.manifest.get("files")
        if not isinstance(files, dict):
            raise DatasetPublicationError("canonical manifest file inventory is invalid")
        for image in canonical.coco["images"]:
            if not isinstance(image, dict):
                raise DatasetPublicationError("canonical image entry is invalid")
            sample_key = image.get("sample_key")
            file_name = image.get("file_name")
            if not isinstance(sample_key, str) or not isinstance(file_name, str):
                raise DatasetPublicationError("canonical image identity is invalid")
            source = canonical.source_images[sample_key]
            destination = staging / file_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._materialize_image(source, destination)
            if _sha256(source.source_path) != source.sha256:
                raise DatasetPublicationError(
                    f"source image changed during publication: {source.relative_path}"
                )
            metadata = files.get(file_name)
            if not isinstance(metadata, dict):
                raise DatasetPublicationError(f"manifest metadata is missing for {file_name}")
            metadata["sha256"] = _sha256(destination)
            metadata["size"] = destination.stat().st_size

    def _materialize_image(self, source: SourceImage, destination: Path) -> None:
        try:
            with Image.open(source.source_path) as opened:
                orientation = opened.getexif().get(274, 1)
                if orientation != 1:
                    normalized = ImageOps.exif_transpose(opened)
                    normalized.load()
                    image_format = opened.format
                    if image_format is None:
                        raise DatasetPublicationError(
                            f"cannot determine image format: {source.relative_path}"
                        )
                    normalized.save(destination, format=image_format)
                    return
        except DatasetPublicationError:
            raise
        except OSError as exc:
            raise DatasetPublicationError(
                f"cannot materialize image: {source.relative_path}"
            ) from exc
        self._copy_file(source.source_path, destination)

    @staticmethod
    def _copy_file(source: Path, destination: Path) -> None:
        clonefile = getattr(os, "clonefile", None)
        if callable(clonefile):
            try:
                cast(CloneFile, clonefile)(source, destination)
                shutil.copystat(source, destination, follow_symlinks=False)
                return
            except OSError:
                if destination.exists():
                    destination.unlink()
        shutil.copy2(source, destination, follow_symlinks=False)

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        path.write_text(f"{serialized}\n", encoding="utf-8")

    @staticmethod
    def _write_split(path: Path, members: tuple[str, ...]) -> None:
        content = "".join(f"{member}\n" for member in members)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _make_immutable(root: Path) -> None:
        for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            path.chmod(0o555 if path.is_dir() else 0o444)
        root.chmod(0o555)

    @staticmethod
    def _remove_tree(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
            return
        if not path.exists():
            return
        for child in path.rglob("*"):
            if child.is_dir():
                child.chmod(0o755)
            else:
                child.chmod(0o644)
        path.chmod(0o755)
        shutil.rmtree(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
