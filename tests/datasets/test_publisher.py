import copy
import json
import os

import pytest
from PIL import Image

from label_platform.datasets.image_adapter import ImageDirectoryAdapter
from label_platform.datasets.normalize import CanonicalVersion, normalize_source
from label_platform.datasets.publisher import DatasetPublisher, DatasetPublicationError
from label_platform.datasets.versioning import PLATFORM_DATASET_FORMAT


def build_canonical(image_factory, tmp_path, *, count=1, orientation=None):
    source = tmp_path / "source"
    for index in range(count):
        image_factory(
            source / f"frame-{index}.jpg",
            size=(20, 10),
            orientation=orientation,
        )
    adapted = ImageDirectoryAdapter().read(
        source,
        dataset_id="dataset-1",
        categories=["cargo"],
    )
    return normalize_source(adapted)


def clone(canonical):
    return CanonicalVersion(
        coco=copy.deepcopy(canonical.coco),
        splits=copy.deepcopy(canonical.splits),
        manifest=copy.deepcopy(canonical.manifest),
        source_images=canonical.source_images.copy(),
    )


def test_publish_creates_complete_immutable_layout_and_latest_link(image_factory, tmp_path):
    canonical = build_canonical(image_factory, tmp_path, orientation=6)
    managed = tmp_path / "managed"
    publisher = DatasetPublisher(managed)

    result = publisher.publish(
        canonical,
        dataset_id="dataset-1",
        version_number=1,
        version_id="version-1",
    )

    version_root = managed / "dataset-1" / "versions" / "v1"
    assert result.version_root == version_root
    assert [path.name for path in version_root.iterdir()] == ["version.json"]
    assert (managed / "dataset-1" / "latest").resolve() == version_root.resolve()
    document = json.loads((version_root / "version.json").read_text(encoding="utf-8"))
    assert document["format"] == PLATFORM_DATASET_FORMAT
    blob = managed / ".blobs" / "sha256" / document["images"][0]["sha256"]
    with Image.open(blob) as image:
        assert image.size == (10, 20)
        assert image.getexif().get(274, 1) == 1
    assert result.validation_report.valid is True
    assert document["images"][0]["sha256"] == result.canonical.manifest["files"][
        "images/frame-0.jpg"
    ]["sha256"]
    assert (version_root / "version.json").stat().st_mode & 0o222 == 0


def test_publish_writes_deterministic_json_with_trailing_newline(image_factory, tmp_path):
    canonical = build_canonical(image_factory, tmp_path)
    result = DatasetPublisher(tmp_path / "managed").publish(
        canonical,
        dataset_id="dataset-1",
        version_number=1,
        version_id="version-1",
    )

    version_bytes = (result.version_root / "version.json").read_bytes()
    assert version_bytes.endswith(b"\n")
    assert b'"annotations":[]' not in version_bytes


def test_publish_failure_never_exposes_partial_version(image_factory, tmp_path):
    canonical = build_canonical(image_factory, tmp_path)
    canonical.coco["images"][0]["file_name"] = "../outside.jpg"
    managed = tmp_path / "managed"

    with pytest.raises(DatasetPublicationError) as error:
        DatasetPublisher(managed).publish(
            canonical,
            dataset_id="dataset-1",
            version_number=1,
            version_id="version-1",
        )

    assert error.value.validation_report is not None
    assert not list(managed.rglob("v1"))
    assert not list(managed.rglob(".building-*"))


def test_materialization_failure_cleans_only_current_staging_and_keeps_latest(
    image_factory,
    tmp_path,
):
    canonical = build_canonical(image_factory, tmp_path, count=2)
    managed = tmp_path / "managed"
    normal = DatasetPublisher(managed)
    first = normal.publish(
        canonical,
        dataset_id="dataset-1",
        version_number=1,
        version_id="version-1",
    )

    class FailingPublisher(DatasetPublisher):
        def _ingest_images(self, canonical):
            raise OSError("simulated copy failure")

    with pytest.raises(DatasetPublicationError, match="simulated copy failure"):
        FailingPublisher(managed).publish(
            canonical,
            dataset_id="dataset-1",
            version_number=2,
            version_id="version-2",
        )

    assert first.version_root.is_dir()
    assert not (managed / "dataset-1/versions/v2").exists()
    assert not list((managed / "dataset-1/versions").glob(".building-*"))
    assert (managed / "dataset-1/latest").resolve() == first.version_root.resolve()


def test_second_publish_atomically_advances_latest(image_factory, tmp_path):
    canonical = build_canonical(image_factory, tmp_path)
    managed = tmp_path / "managed"
    publisher = DatasetPublisher(managed)
    publisher.publish(
        canonical,
        dataset_id="dataset-1",
        version_number=1,
        version_id="version-1",
    )

    second = publisher.publish(
        canonical,
        dataset_id="dataset-1",
        version_number=2,
        version_id="version-2",
    )

    assert (managed / "dataset-1/latest").resolve() == second.version_root.resolve()
    assert os.readlink(managed / "dataset-1/latest") == "versions/v2"


def test_repeated_content_reuses_one_blob_across_versions(image_factory, tmp_path):
    canonical = build_canonical(image_factory, tmp_path)
    managed = tmp_path / "managed"
    publisher = DatasetPublisher(managed)

    first = publisher.publish(
        canonical,
        dataset_id="dataset-1",
        version_number=1,
        version_id="version-1",
    )
    second = publisher.publish(
        canonical,
        dataset_id="dataset-1",
        version_number=2,
        version_id="version-2",
    )

    blobs = list((managed / ".blobs/sha256").iterdir())
    assert len(blobs) == 1
    assert not list(first.version_root.rglob("*.jpg"))
    assert not list(second.version_root.rglob("*.jpg"))
