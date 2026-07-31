from pathlib import Path

import pytest
import yaml

from label_platform.datasets.contracts import SourceFormatError
from label_platform.datasets.yolo_adapter import MAX_CONFIG_BYTES, YoloDetectionAdapter
from label_platform.domain.enums import SourceFormat, TaskType


def write_config(root: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "path": "/ignored/by/platform",
        "train": "train/images",
        "names": ["person", "rack"],
        "nc": 2,
    }
    payload.update(overrides)
    path = root / "data.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def write_label(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_yolo_adapter_converts_boxes_categories_and_explicit_splits(image_factory, tmp_path):
    write_config(tmp_path, val="val/images", test="test/images")
    image_factory(tmp_path / "train/images/nested/train.jpg", size=(20, 10))
    image_factory(tmp_path / "val/images/val.png", size=(12, 8))
    image_factory(tmp_path / "test/images/test.webp", size=(16, 16), image_format="WEBP")
    write_label(tmp_path, "train/labels/nested/train.txt", "1 0.5 0.5 0.4 0.6\n")
    write_label(tmp_path, "val/labels/val.txt", "")

    source = YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")

    assert source.format is SourceFormat.YOLO_DETECTION
    assert source.task_type is TaskType.DETECTION
    assert source.categories == ("person", "rack")
    assert source.category_id_mapping == {"source:0": 1, "source:1": 2}
    assert {(image.relative_path, image.split) for image in source.images} == {
        ("train/nested/train.jpg", "train"),
        ("val/val.png", "val"),
        ("test/test.webp", "test"),
    }
    assert source.annotations[0].category_name == "rack"
    assert source.annotations[0].bbox == pytest.approx((6.0, 2.0, 8.0, 6.0))
    assert source.consumed_files == (
        "data.yaml",
        "train/labels/nested/train.txt",
        "val/labels/val.txt",
    )


@pytest.mark.parametrize(
    "names",
    [
        {0: "person", 1: "rack"},
        {"0": "person", "1": "rack"},
    ],
)
def test_yolo_adapter_accepts_contiguous_category_mappings(image_factory, tmp_path, names):
    write_config(tmp_path, names=names)
    image_factory(tmp_path / "train/images/frame.jpg")

    source = YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")

    assert source.categories == ("person", "rack")


def test_yolo_adapter_preserves_images_with_missing_or_empty_labels(image_factory, tmp_path):
    write_config(tmp_path)
    image_factory(tmp_path / "train/images/missing.jpg")
    image_factory(tmp_path / "train/images/empty.jpg")
    write_label(tmp_path, "train/labels/empty.txt", "\n")

    source = YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")

    assert len(source.images) == 2
    assert source.annotations == ()


def test_yolo_adapter_accepts_relative_image_directory_with_a_custom_name(
    image_factory,
    tmp_path,
):
    write_config(tmp_path, train="train/pictures")
    image_factory(tmp_path / "train/pictures/frame.jpg")
    write_label(tmp_path, "train/labels/frame.txt", "0 0.5 0.5 1 1\n")

    source = YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")

    assert source.images[0].relative_path == "train/frame.jpg"
    assert source.annotations[0].bbox == pytest.approx((0.0, 0.0, 32.0, 24.0))


def test_yolo_adapter_snaps_six_decimal_boundary_rounding_without_resizing_box(
    image_factory,
    tmp_path,
):
    write_config(tmp_path)
    image_factory(tmp_path / "train/images/frame.jpg", size=(20, 10))
    write_label(tmp_path, "train/labels/frame.txt", "0 0.0999995 0.5 0.2 0.2\n")

    source = YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")

    assert source.annotations[0].bbox == pytest.approx((0.0, 4.0, 4.0, 2.0))


@pytest.mark.parametrize(
    ("train", "message"),
    [
        ("/absolute/images", "safe relative"),
        ("../outside/images", "safe relative"),
        ("https://example.test/images", "safe relative"),
        ("C:/dataset/images", "safe relative"),
        (".", "safe relative"),
    ],
)
def test_yolo_adapter_rejects_unsafe_split_paths(image_factory, tmp_path, train, message):
    write_config(tmp_path, train=train)

    with pytest.raises(SourceFormatError, match=message):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")


def test_yolo_adapter_rejects_image_list_configuration(tmp_path):
    write_config(tmp_path, train=["train/images"])

    with pytest.raises(SourceFormatError, match="relative image directory"):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")


def test_yolo_adapter_rejects_symbolic_linked_split_directory(image_factory, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    image_factory(outside / "frame.jpg")
    (tmp_path / "train").mkdir()
    (tmp_path / "train/images").symlink_to(outside, target_is_directory=True)
    write_config(tmp_path)

    with pytest.raises(SourceFormatError, match="symbolic link"):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")


def test_yolo_adapter_rejects_symbolic_linked_config(tmp_path):
    real_config = tmp_path.parent / f"{tmp_path.name}-data.yaml"
    real_config.write_text("train: train/images\nnames: [person]\n", encoding="utf-8")
    (tmp_path / "data.yaml").symlink_to(real_config)

    with pytest.raises(SourceFormatError, match="symbolic link"):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")


def test_yolo_adapter_rejects_duplicate_split_directories(image_factory, tmp_path):
    write_config(tmp_path, val="train/images")
    image_factory(tmp_path / "train/images/frame.jpg")

    with pytest.raises(SourceFormatError, match="unique and non-overlapping"):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")


def test_yolo_adapter_rejects_nested_split_directories(image_factory, tmp_path):
    write_config(tmp_path, val="train/images/nested")
    image_factory(tmp_path / "train/images/nested/frame.jpg")

    with pytest.raises(SourceFormatError, match="unique and non-overlapping"):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")


def test_yolo_adapter_rejects_orphan_label(image_factory, tmp_path):
    write_config(tmp_path)
    image_factory(tmp_path / "train/images/frame.jpg")
    write_label(tmp_path, "train/labels/orphan.txt", "0 0.5 0.5 0.2 0.2\n")

    with pytest.raises(SourceFormatError, match="no corresponding image"):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")


@pytest.mark.parametrize(
    ("label", "message"),
    [
        ("0 0.5 0.5 0.2 0.2 0.1", "exactly five fields"),
        ("2 0.5 0.5 0.2 0.2", "category ID is out of range"),
        ("0 nan 0.5 0.2 0.2", "non-finite"),
        ("0 0.5 0.5 0 0.2", "width and height"),
        ("0 0.05 0.5 0.2 0.2", "exceeds image bounds"),
    ],
)
def test_yolo_adapter_rejects_invalid_detection_rows(
    image_factory,
    tmp_path,
    label,
    message,
):
    write_config(tmp_path)
    image_factory(tmp_path / "train/images/frame.jpg")
    write_label(tmp_path, "train/labels/frame.txt", f"{label}\n")

    with pytest.raises(SourceFormatError, match=message):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"names": ["person", "person"]}, "unique names"),
        ({"names": {0: "person", 2: "rack"}}, "contiguous"),
        ({"names": {0.0: "person"}, "nc": 1}, "contiguous"),
        ({"nc": 3}, "nc must match"),
    ],
)
def test_yolo_adapter_rejects_invalid_category_definitions(
    image_factory,
    tmp_path,
    overrides,
    message,
):
    write_config(tmp_path, **overrides)
    image_factory(tmp_path / "train/images/frame.jpg")

    with pytest.raises(SourceFormatError, match=message):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")


def test_yolo_adapter_limits_config_size(tmp_path):
    (tmp_path / "data.yaml").write_bytes(b"#" * (MAX_CONFIG_BYTES + 1))

    with pytest.raises(SourceFormatError, match="1 MiB"):
        YoloDetectionAdapter().read(tmp_path, dataset_id="dataset-1")
