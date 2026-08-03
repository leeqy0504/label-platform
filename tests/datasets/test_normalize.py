from dataclasses import replace

import numpy as np
import pytest
from pycocotools import mask as mask_utils

from label_platform.datasets.contracts import SourceAnnotation
from label_platform.datasets.image_adapter import ImageDirectoryAdapter
from label_platform.datasets.normalize import NormalizationError, normalize_source
from label_platform.domain.enums import TaskType


def source_with_annotations(image_factory, tmp_path, *, task_type, annotations):
    image_factory(tmp_path / "frame.jpg", size=(10, 8))
    raw = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["cargo"],
        task_type=task_type,
    )
    image_key = raw.images[0].sample_key
    return replace(
        raw,
        annotations=tuple(
            SourceAnnotation(
                image_key=image_key,
                category_name="cargo",
                bbox=annotation.get("bbox"),
                segmentation=annotation.get("segmentation"),
            )
            for annotation in annotations
        ),
    )


def test_instance_mask_derives_bbox_and_area(image_factory, tmp_path):
    mask = np.zeros((8, 10), dtype=np.uint8)
    mask[1:5, 2:5] = 1
    encoded = mask_utils.encode(np.asfortranarray(mask))
    encoded["counts"] = encoded["counts"].decode("utf-8")
    source = source_with_annotations(
        image_factory,
        tmp_path,
        task_type=TaskType.INSTANCE_SEGMENTATION,
        annotations=[{"bbox": (0.0, 0.0, 1.0, 1.0), "segmentation": encoded}],
    )

    canonical = normalize_source(source, split_seed=42)
    annotation = canonical.coco["annotations"][0]

    assert annotation["bbox"] == [2.0, 1.0, 3.0, 4.0]
    assert annotation["area"] == 12.0
    assert annotation["segmentation"]["size"] == [8, 10]


def test_detection_keeps_bbox_and_assigns_stable_positive_ids(image_factory, tmp_path):
    source = source_with_annotations(
        image_factory,
        tmp_path,
        task_type=TaskType.DETECTION,
        annotations=[{"bbox": (1.0, 2.0, 3.0, 4.0), "segmentation": None}],
    )

    canonical = normalize_source(source, split_seed=42)

    assert canonical.coco["images"][0]["id"] == 1
    assert canonical.coco["annotations"][0] == {
        "id": 1,
        "image_id": 1,
        "category_id": 1,
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "area": 12.0,
        "iscrowd": 0,
    }
    assert canonical.coco["categories"] == [{"id": 1, "name": "cargo"}]


def test_normalization_is_deterministic_and_keeps_groups_in_one_split(
    image_factory,
    tmp_path,
):
    image_factory(tmp_path / "b.jpg")
    image_factory(tmp_path / "a.jpg")
    raw = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["cargo"],
    )
    source = replace(
        raw,
        images=(replace(raw.images[0], group_key="same"), replace(raw.images[1], group_key="same")),
    )

    first = normalize_source(source, split_seed=99)
    second = normalize_source(source, split_seed=99)

    assert first == second
    assert [image["sample_key"] for image in first.coco["images"]] == sorted(
        image.sample_key for image in source.images
    )
    populated = [members for members in first.splits.values() if members]
    assert len(populated) == 1
    assert set(populated[0]) == {image.sample_key for image in source.images}


def test_automatic_splits_are_stable_across_dataset_namespaces(image_factory, tmp_path):
    for index in range(64):
        image_factory(tmp_path / f"{index:05d}.png")
    analysis_source = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="analysis:job-1",
        categories=["object"],
    )
    registration_source = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["object"],
    )

    analysis = normalize_source(analysis_source, split_seed=42)
    registration = normalize_source(registration_source, split_seed=42)

    def splits_by_relative_path(source, canonical):
        relative_by_key = {image.sample_key: image.relative_path for image in source.images}
        return {
            relative_by_key[sample_key]: split
            for split, sample_keys in canonical.splits.items()
            for sample_key in sample_keys
        }

    assert splits_by_relative_path(analysis_source, analysis) == splits_by_relative_path(
        registration_source,
        registration,
    )
    assert analysis.manifest["split_counts"] == {"train": 52, "val": 12, "test": 0}
    assert registration.manifest["split_counts"] == analysis.manifest["split_counts"]


def test_normalization_preserves_explicit_split_for_a_group(image_factory, tmp_path):
    image_factory(tmp_path / "a.jpg")
    image_factory(tmp_path / "b.jpg")
    raw = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["cargo"],
    )
    source = replace(
        raw,
        images=(
            replace(raw.images[0], split="val", group_key="same"),
            replace(raw.images[1], group_key="same"),
        ),
    )

    canonical = normalize_source(source)

    assert set(canonical.splits["val"]) == {image.sample_key for image in source.images}


def test_manifest_contains_contract_lineage_splits_and_source_checksums(image_factory, tmp_path):
    source = source_with_annotations(
        image_factory,
        tmp_path,
        task_type=TaskType.DETECTION,
        annotations=[{"bbox": (1.0, 2.0, 3.0, 4.0), "segmentation": None}],
    )

    canonical = normalize_source(
        source,
        source_version="camera-export-7",
        source_lineage={"allowed_root_id": "root-1", "relative_path": "incoming"},
    )

    assert canonical.manifest["format"] == "platform-coco-v1"
    assert canonical.manifest["source_format"] == "image_directory"
    assert canonical.manifest["source_version"] == "camera-export-7"
    assert canonical.manifest["source_lineage"]["allowed_root_id"] == "root-1"
    assert canonical.manifest["images"] == 1
    assert canonical.manifest["annotations"] == 1
    assert canonical.manifest["split_counts"] == {
        split: len(members) for split, members in canonical.splits.items()
    }
    assert canonical.manifest["files"]["images/frame.jpg"]["sha256"] == source.images[0].sha256


@pytest.mark.parametrize(
    "ratios",
    [
        {"train": 0.7, "val": 0.2, "test": 0.0},
        {"train": -0.1, "val": 0.6, "test": 0.5},
        {"train": 1.0, "val": 0.0},
    ],
)
def test_normalization_rejects_invalid_split_ratios(image_factory, tmp_path, ratios):
    image_factory(tmp_path / "frame.jpg")
    source = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["cargo"],
    )

    with pytest.raises(NormalizationError, match="split ratios"):
        normalize_source(source, split_ratios=ratios)


def test_normalization_rejects_conflicting_group_splits(image_factory, tmp_path):
    image_factory(tmp_path / "a.jpg")
    image_factory(tmp_path / "b.jpg")
    raw = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["cargo"],
    )
    source = replace(
        raw,
        images=(
            replace(raw.images[0], split="train", group_key="same"),
            replace(raw.images[1], split="val", group_key="same"),
        ),
    )

    with pytest.raises(NormalizationError, match="conflicting explicit splits"):
        normalize_source(source)


def test_normalization_rejects_empty_instance_mask(image_factory, tmp_path):
    mask = np.zeros((8, 10), dtype=np.uint8)
    encoded = mask_utils.encode(np.asfortranarray(mask))
    encoded["counts"] = encoded["counts"].decode("utf-8")
    source = source_with_annotations(
        image_factory,
        tmp_path,
        task_type=TaskType.INSTANCE_SEGMENTATION,
        annotations=[{"bbox": None, "segmentation": encoded}],
    )

    with pytest.raises(NormalizationError, match="empty mask"):
        normalize_source(source)


def test_normalization_rejects_unknown_annotation_image_or_category(image_factory, tmp_path):
    source = source_with_annotations(
        image_factory,
        tmp_path,
        task_type=TaskType.DETECTION,
        annotations=[{"bbox": (1.0, 1.0, 2.0, 2.0), "segmentation": None}],
    )

    with pytest.raises(NormalizationError, match="unknown image"):
        normalize_source(
            replace(
                source,
                annotations=(replace(source.annotations[0], image_key="missing"),),
            )
        )
    with pytest.raises(NormalizationError, match="unknown category"):
        normalize_source(
            replace(
                source,
                annotations=(replace(source.annotations[0], category_name="missing"),),
            )
        )
