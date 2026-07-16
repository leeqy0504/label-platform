import copy
import json
import os

import pytest
from PIL import Image

from label_platform.datasets.image_adapter import ImageDirectoryAdapter
from label_platform.datasets.normalize import CanonicalVersion, normalize_source
from label_platform.datasets.publisher import DatasetPublisher, DatasetPublicationError


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
    assert (version_root / "annotations/instances.coco.json").is_file()
    assert (version_root / "splits/train.txt").is_file()
    assert (version_root / "splits/val.txt").is_file()
    assert (version_root / "splits/test.txt").is_file()
    assert (version_root / "manifest.json").is_file()
    assert (managed / "dataset-1" / "latest").resolve() == version_root.resolve()
    with Image.open(version_root / "images/frame-0.jpg") as image:
        assert image.size == (10, 20)
        assert image.getexif().get(274, 1) == 1
    assert result.validation_report.valid is True
    assert json.loads((version_root / "manifest.json").read_text(encoding="utf-8"))[
        "files"
    ]["images/frame-0.jpg"]["sha256"] == result.canonical.manifest["files"][
        "images/frame-0.jpg"
    ]["sha256"]
    assert (version_root / "manifest.json").stat().st_mode & 0o222 == 0


def test_publish_writes_deterministic_json_with_trailing_newline(image_factory, tmp_path):
    canonical = build_canonical(image_factory, tmp_path)
    result = DatasetPublisher(tmp_path / "managed").publish(
        canonical,
        dataset_id="dataset-1",
        version_number=1,
        version_id="version-1",
    )

    annotation_bytes = (result.version_root / "annotations/instances.coco.json").read_bytes()
    manifest_bytes = (result.version_root / "manifest.json").read_bytes()
    assert annotation_bytes.endswith(b"\n")
    assert manifest_bytes.endswith(b"\n")
    assert b'"annotations":[]' not in annotation_bytes


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
        def _materialize_image(self, source, destination):
            if destination.name == "frame-1.jpg":
                raise OSError("simulated copy failure")
            return super()._materialize_image(source, destination)

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
