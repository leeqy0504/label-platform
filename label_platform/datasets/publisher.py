import copy
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from label_platform.datasets.blobs import BlobStore
from label_platform.datasets.normalize import CanonicalVersion
from label_platform.datasets.validate import ValidationReport, validate_canonical
from label_platform.datasets.versioning import (
    PLATFORM_DATASET_FORMAT,
    VERSION_FILE_NAME,
    build_version_document,
    load_version_document,
    resolve_version_image,
)


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

            self._ingest_images(published)
            report = initial_report
            published.manifest["format"] = PLATFORM_DATASET_FORMAT
            published.manifest["validation_result"] = report.as_dict()
            document = build_version_document(published)
            self._write_json(staging / VERSION_FILE_NAME, document)
            stored = load_version_document(staging, manifest_path=VERSION_FILE_NAME)
            for image in stored.coco["images"]:
                if not isinstance(image, dict):
                    raise DatasetPublicationError("stored version image is invalid")
                resolve_version_image(
                    self.managed_root,
                    staging,
                    image,
                    verify_blob=True,
                )
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

    def _ingest_images(self, canonical: CanonicalVersion) -> None:
        files = canonical.manifest.get("files")
        if not isinstance(files, dict):
            raise DatasetPublicationError("canonical manifest file inventory is invalid")
        blob_store = BlobStore(self.managed_root)
        for image in canonical.coco["images"]:
            if not isinstance(image, dict):
                raise DatasetPublicationError("canonical image entry is invalid")
            sample_key = image.get("sample_key")
            file_name = image.get("file_name")
            if not isinstance(sample_key, str) or not isinstance(file_name, str):
                raise DatasetPublicationError("canonical image identity is invalid")
            source = canonical.source_images[sample_key]
            blob = blob_store.ingest(source)
            metadata = files.get(file_name)
            if not isinstance(metadata, dict):
                raise DatasetPublicationError(f"manifest metadata is missing for {file_name}")
            metadata["sha256"] = blob.sha256
            metadata["size"] = blob.size
            image["sha256"] = blob.sha256
            image["image_uri"] = blob.uri
            image["file_size"] = blob.size

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
