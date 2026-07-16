import hashlib

import pytest

from label_platform.datasets.contracts import SourceFormatError
from label_platform.datasets.image_adapter import ImageDirectoryAdapter
from label_platform.domain.enums import SourceFormat, TaskType


def test_image_adapter_uses_relative_path_in_sample_key(image_factory, tmp_path):
    image_factory(tmp_path / "a" / "frame.jpg", size=(20, 10))
    image_factory(tmp_path / "b" / "frame.jpg", size=(30, 15))

    source = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["cargo"],
    )

    assert len(source.images) == 2
    assert source.images[0].sample_key != source.images[1].sample_key
    assert {item.relative_path for item in source.images} == {"a/frame.jpg", "b/frame.jpg"}
    expected_key = hashlib.sha256(b"dataset-1\0a/frame.jpg").hexdigest()
    assert next(item for item in source.images if item.relative_path == "a/frame.jpg").sample_key == expected_key


def test_image_adapter_returns_source_contract_and_hash(image_factory, tmp_path):
    image = image_factory(tmp_path / "frame.PNG", size=(17, 9), image_format="PNG")

    source = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["person", "rack"],
        task_type=TaskType.INSTANCE_SEGMENTATION,
    )

    item = source.images[0]
    assert source.format is SourceFormat.IMAGE_DIRECTORY
    assert source.task_type is TaskType.INSTANCE_SEGMENTATION
    assert source.annotations == ()
    assert source.categories == ("person", "rack")
    assert source.category_id_mapping == {"source:person": 1, "source:rack": 2}
    assert (item.width, item.height) == (17, 9)
    assert item.file_size == image.stat().st_size
    assert item.sha256 == hashlib.sha256(image.read_bytes()).hexdigest()
    assert item.source_path == image.resolve()


def test_image_adapter_applies_exif_orientation(image_factory, tmp_path):
    image_factory(tmp_path / "rotated.jpg", size=(20, 10), orientation=6)

    source = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["cargo"],
    )

    assert (source.images[0].width, source.images[0].height) == (10, 20)


def test_image_adapter_supports_all_image_extensions_and_ignores_other_files(
    image_factory,
    tmp_path,
):
    image_factory(tmp_path / "a.jpg")
    image_factory(tmp_path / "b.JPEG", image_format="JPEG")
    image_factory(tmp_path / "c.png")
    image_factory(tmp_path / "d.WEBP", image_format="WEBP")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    source = ImageDirectoryAdapter().read(
        tmp_path,
        dataset_id="dataset-1",
        categories=["cargo"],
    )

    assert [image.relative_path for image in source.images] == [
        "a.jpg",
        "b.JPEG",
        "c.png",
        "d.WEBP",
    ]


def test_image_adapter_rejects_corrupt_media(tmp_path):
    (tmp_path / "broken.jpg").write_bytes(b"not an image")

    with pytest.raises(SourceFormatError, match="cannot decode image"):
        ImageDirectoryAdapter().read(
            tmp_path,
            dataset_id="dataset-1",
            categories=["cargo"],
        )


def test_image_adapter_rejects_empty_directory(tmp_path):
    with pytest.raises(SourceFormatError, match="no supported images"):
        ImageDirectoryAdapter().read(
            tmp_path,
            dataset_id="dataset-1",
            categories=["cargo"],
        )


@pytest.mark.parametrize("categories", [[], [""], ["cargo", "cargo"]])
def test_image_adapter_rejects_invalid_categories(image_factory, tmp_path, categories):
    image_factory(tmp_path / "frame.jpg")

    with pytest.raises(SourceFormatError, match="categories"):
        ImageDirectoryAdapter().read(
            tmp_path,
            dataset_id="dataset-1",
            categories=categories,
        )
