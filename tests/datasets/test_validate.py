import copy

import numpy as np
import pytest
from pycocotools import mask as mask_utils

from label_platform.datasets.contracts import SourceAnnotation, SourceDataset, SourceImage
from label_platform.datasets.normalize import CanonicalVersion, normalize_source
from label_platform.datasets.validate import validate_canonical
from label_platform.domain.enums import SourceFormat, TaskType


def make_source(image_factory, tmp_path, *, instance=False):
    image = image_factory(tmp_path / "frame.jpg", size=(10, 8))
    source_image = SourceImage(
        source_path=image.resolve(),
        relative_path="frame.jpg",
        sample_key="sample-1",
        width=10,
        height=8,
        file_size=image.stat().st_size,
        sha256=__import__("hashlib").sha256(image.read_bytes()).hexdigest(),
        group_key="group-1",
    )
    if instance:
        mask = np.zeros((8, 10), dtype=np.uint8)
        mask[1:5, 2:5] = 1
        encoded = mask_utils.encode(np.asfortranarray(mask))
        encoded["counts"] = encoded["counts"].decode("utf-8")
        annotation = SourceAnnotation("sample-1", "cargo", None, encoded)
    else:
        annotation = SourceAnnotation("sample-1", "cargo", (1.0, 1.0, 3.0, 4.0), None)
    return SourceDataset(
        format=SourceFormat.COCO_INSTANCE if instance else SourceFormat.COCO_DETECTION,
        task_type=(TaskType.INSTANCE_SEGMENTATION if instance else TaskType.DETECTION),
        images=(source_image,),
        annotations=(annotation,),
        categories=("cargo",),
        category_id_mapping={"source:8": 1},
    )


@pytest.fixture
def canonical_version(image_factory, tmp_path):
    return normalize_source(make_source(image_factory, tmp_path))


@pytest.fixture
def instance_version(image_factory, tmp_path):
    return normalize_source(make_source(image_factory, tmp_path, instance=True))


def clone(canonical: CanonicalVersion) -> CanonicalVersion:
    return CanonicalVersion(
        coco=copy.deepcopy(canonical.coco),
        splits=copy.deepcopy(canonical.splits),
        manifest=copy.deepcopy(canonical.manifest),
        source_images=canonical.source_images.copy(),
    )


def assert_error(canonical, code, *, frozen_schema=None, version_root=None):
    report = validate_canonical(
        canonical,
        frozen_schema=frozen_schema,
        version_root=version_root,
    )
    assert report.valid is False
    assert code in {error.code for error in report.errors}


def test_valid_canonical_detection_and_instance_pass(canonical_version, instance_version):
    assert validate_canonical(canonical_version).valid is True
    assert validate_canonical(instance_version).valid is True


def test_validator_rejects_path_escape(canonical_version):
    canonical = clone(canonical_version)
    canonical.coco["images"][0]["file_name"] = "../outside.jpg"

    report = validate_canonical(canonical)

    assert report.valid is False
    assert report.errors[0].code == "image_path_escape"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda version: version.coco["images"].append(dict(version.coco["images"][0])), "image_id_duplicate"),
        (
            lambda version: version.coco["annotations"].append(
                dict(version.coco["annotations"][0])
            ),
            "annotation_id_duplicate",
        ),
        (lambda version: version.coco["images"][0].update(id=0), "image_id_invalid"),
        (lambda version: version.coco["annotations"][0].update(category_id=99), "category_unknown"),
        (lambda version: version.coco["annotations"][0].update(image_id=99), "image_unknown"),
        (lambda version: version.coco["annotations"][0].update(bbox=[-1, 0, 2, 2]), "bbox_out_of_bounds"),
        (lambda version: version.coco["annotations"][0].update(bbox=[1, 1, 0, 2]), "bbox_non_positive"),
        (lambda version: version.coco["annotations"][0].update(bbox=[1, 1, float("nan"), 2]), "bbox_non_finite"),
        (lambda version: version.coco["images"][0].update(width=11), "image_dimensions_mismatch"),
    ],
)
def test_validator_rejects_id_reference_bbox_and_dimension_errors(
    canonical_version,
    mutation,
    code,
):
    canonical = clone(canonical_version)
    mutation(canonical)
    assert_error(canonical, code)


def test_validator_rejects_invalid_empty_and_mismatched_segmentation(instance_version):
    invalid = clone(instance_version)
    invalid.coco["annotations"][0]["segmentation"] = {"size": [8, 10], "counts": "bad"}
    assert_error(invalid, "segmentation_invalid")

    empty = clone(instance_version)
    mask = np.zeros((8, 10), dtype=np.uint8)
    encoded = mask_utils.encode(np.asfortranarray(mask))
    encoded["counts"] = encoded["counts"].decode("utf-8")
    empty.coco["annotations"][0]["segmentation"] = encoded
    empty.coco["annotations"][0]["area"] = 0.0
    assert_error(empty, "segmentation_empty")

    mismatch = clone(instance_version)
    mismatch.coco["annotations"][0]["bbox"] = [0.0, 0.0, 1.0, 1.0]
    assert_error(mismatch, "mask_bbox_mismatch")


def test_validator_rejects_split_overlap_unknown_missing_and_group_leak(canonical_version):
    overlap = clone(canonical_version)
    overlap.splits["train"] = ("sample-1",)
    overlap.splits["val"] = ("sample-1",)
    assert_error(overlap, "split_overlap")

    unknown = clone(canonical_version)
    unknown.splits["test"] = ("missing",)
    assert_error(unknown, "split_sample_unknown")

    missing = clone(canonical_version)
    missing.splits = {"train": (), "val": (), "test": ()}
    assert_error(missing, "split_missing")

    second = copy.deepcopy(canonical_version.source_images["sample-1"])
    second = SourceImage(
        source_path=second.source_path,
        relative_path="other.jpg",
        sample_key="sample-2",
        width=second.width,
        height=second.height,
        file_size=second.file_size,
        sha256=second.sha256,
        group_key="group-1",
    )
    leaked = clone(canonical_version)
    leaked.source_images["sample-2"] = second
    leaked.coco["images"].append(
        {
            "id": 2,
            "file_name": "images/other.jpg",
            "width": 10,
            "height": 8,
            "sample_key": "sample-2",
        }
    )
    leaked.splits = {"train": ("sample-1",), "val": ("sample-2",), "test": ()}
    assert_error(leaked, "split_group_leakage")


def test_validator_rejects_manifest_and_frozen_schema_mismatch(canonical_version):
    bad_format = clone(canonical_version)
    bad_format.manifest["format"] = "other"
    assert_error(bad_format, "manifest_format")

    bad_count = clone(canonical_version)
    bad_count.manifest["images"] = 99
    assert_error(bad_count, "manifest_count_mismatch")

    bad_mapping = clone(canonical_version)
    bad_mapping.manifest["category_id_mapping"] = {}
    assert_error(bad_mapping, "category_mapping_incomplete")

    assert_error(
        canonical_version,
        "category_schema_mismatch",
        frozen_schema=[{"id": 1, "name": "other"}],
    )


def test_validator_detects_changed_or_missing_source_file(canonical_version):
    changed = clone(canonical_version)
    source = changed.source_images["sample-1"].source_path
    source.write_bytes(b"changed")
    assert_error(changed, "source_file_changed")

    source.unlink()
    assert_error(changed, "source_file_missing")


def test_validator_checks_materialized_version_root(canonical_version, tmp_path):
    version_root = tmp_path / "version"
    (version_root / "images").mkdir(parents=True)

    assert_error(canonical_version, "image_file_missing", version_root=version_root)

    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    (version_root / "images" / "frame.jpg").symlink_to(outside)
    assert_error(canonical_version, "image_file_escape", version_root=version_root)
