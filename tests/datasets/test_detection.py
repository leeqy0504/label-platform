import pytest
import yaml

from label_platform.datasets.detection import SourceFormatError, detect_source
from label_platform.domain.enums import SourceFormat


def test_detects_plain_image_directory(image_factory, tmp_path):
    image_factory(tmp_path / "camera-a" / "frame.jpg", size=(20, 10))

    detected = detect_source(tmp_path)

    assert detected.format is SourceFormat.IMAGE_DIRECTORY
    assert detected.source_path == tmp_path.resolve()


def test_detects_supported_image_extensions_case_insensitively(image_factory, tmp_path):
    image_factory(tmp_path / "frame.WEBP", image_format="WEBP")

    assert detect_source(tmp_path).format is SourceFormat.IMAGE_DIRECTORY


def test_detection_rejects_empty_or_unsupported_directory(tmp_path):
    (tmp_path / "notes.txt").write_text("not a dataset", encoding="utf-8")

    with pytest.raises(SourceFormatError, match="supported dataset source"):
        detect_source(tmp_path)


def test_detection_rejects_a_file_instead_of_directory(tmp_path):
    source = tmp_path / "frame.jpg"
    source.write_bytes(b"image")

    with pytest.raises(SourceFormatError, match="directory"):
        detect_source(source)


@pytest.mark.parametrize("config_name", ["data.yaml", "data.yml"])
def test_detects_yolo_detection_source(image_factory, tmp_path, config_name):
    image_factory(tmp_path / "train/images/frame.jpg")
    config = tmp_path / config_name
    config.write_text(
        yaml.safe_dump({"train": "train/images", "names": ["person"]}),
        encoding="utf-8",
    )

    detected = detect_source(tmp_path)

    assert detected.format is SourceFormat.YOLO_DETECTION
    assert detected.annotation_path == config.resolve()


def test_detection_rejects_multiple_yolo_configs(tmp_path):
    (tmp_path / "data.yaml").write_text("train: train/images\n", encoding="utf-8")
    (tmp_path / "data.yml").write_text("train: train/images\n", encoding="utf-8")

    with pytest.raises(SourceFormatError, match="multiple supported annotation sources"):
        detect_source(tmp_path)


def test_detection_rejects_yolo_and_coco_sources_together(image_factory, tmp_path):
    image_factory(tmp_path / "train/images/frame.jpg")
    (tmp_path / "data.yaml").write_text(
        yaml.safe_dump({"train": "train/images", "names": ["person"]}),
        encoding="utf-8",
    )
    (tmp_path / "annotations.json").write_text(
        '{"images": [], "annotations": [], "categories": []}',
        encoding="utf-8",
    )

    with pytest.raises(SourceFormatError, match="multiple supported annotation sources"):
        detect_source(tmp_path)
