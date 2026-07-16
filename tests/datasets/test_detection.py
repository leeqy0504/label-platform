import pytest

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
