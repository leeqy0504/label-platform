import json

import pytest

from label_platform.datasets.coco_adapter import CocoAdapter
from label_platform.datasets.contracts import SourceFormatError
from label_platform.datasets.detection import detect_source
from label_platform.domain.enums import SourceFormat, TaskType


def write_coco(tmp_path, image_factory, *, annotations=None, categories=None):
    image_factory(tmp_path / "images" / "frame.jpg", size=(20, 10))
    payload = {
        "images": [{"id": 4, "file_name": "images/frame.jpg", "width": 20, "height": 10}],
        "annotations": annotations
        if annotations is not None
        else [{"id": 9, "image_id": 4, "category_id": 0, "bbox": [1, 2, 3, 4]}],
        "categories": categories
        if categories is not None
        else [{"id": 0, "name": "person"}, {"id": 8, "name": "rack"}],
    }
    annotation_path = tmp_path / "annotations.json"
    annotation_path.write_text(json.dumps(payload), encoding="utf-8")
    return annotation_path, payload


def test_coco_detection_adapter_preserves_source_category_mapping(image_factory, tmp_path):
    annotation_path, _ = write_coco(tmp_path, image_factory)

    source = CocoAdapter().read(annotation_path, dataset_id="dataset-1")

    assert source.format is SourceFormat.COCO_DETECTION
    assert source.task_type is TaskType.DETECTION
    assert source.categories == ("person", "rack")
    assert source.category_id_mapping == {"source:0": 1, "source:8": 2}
    assert source.annotations[0].bbox == (1.0, 2.0, 3.0, 4.0)
    assert source.annotations[0].category_name == "person"
    assert source.images[0].relative_path == "images/frame.jpg"


def test_coco_instance_adapter_detects_polygon(image_factory, tmp_path):
    annotation_path, _ = write_coco(
        tmp_path,
        image_factory,
        annotations=[
            {
                "id": 9,
                "image_id": 4,
                "category_id": 8,
                "bbox": [1, 1, 5, 5],
                "segmentation": [[1, 1, 6, 1, 6, 6, 1, 6]],
            }
        ],
    )

    source = CocoAdapter().read(annotation_path, dataset_id="dataset-1")

    assert source.format is SourceFormat.COCO_INSTANCE
    assert source.task_type is TaskType.INSTANCE_SEGMENTATION
    assert source.annotations[0].segmentation == [[1.0, 1.0, 6.0, 1.0, 6.0, 6.0, 1.0, 6.0]]


def test_detection_prefers_coco_metadata_over_plain_images(image_factory, tmp_path):
    annotation_path, _ = write_coco(tmp_path, image_factory)

    detected = detect_source(tmp_path)

    assert detected.format is SourceFormat.COCO_DETECTION
    assert detected.task_type is TaskType.DETECTION
    assert detected.annotation_path == annotation_path.resolve()


def test_coco_directory_resolves_images_from_dataset_root(image_factory, tmp_path):
    image_factory(tmp_path / "images" / "frame.jpg", size=(20, 10))
    annotations = tmp_path / "annotations"
    annotations.mkdir()
    (annotations / "instances.json").write_text(
        json.dumps(
            {
                "images": [
                    {"id": 1, "file_name": "images/frame.jpg", "width": 20, "height": 10}
                ],
                "annotations": [
                    {"id": 1, "image_id": 1, "category_id": 1, "bbox": [1, 1, 2, 2]}
                ],
                "categories": [{"id": 1, "name": "cargo"}],
            }
        ),
        encoding="utf-8",
    )

    source = CocoAdapter().read(tmp_path, dataset_id="dataset-1")

    assert source.images[0].relative_path == "images/frame.jpg"


def test_coco_adapter_accepts_uncompressed_rle(image_factory, tmp_path):
    annotation_path, _ = write_coco(
        tmp_path,
        image_factory,
        annotations=[
            {
                "id": 1,
                "image_id": 4,
                "category_id": 0,
                "segmentation": {"size": [10, 20], "counts": [0, 1, 199]},
            }
        ],
    )

    source = CocoAdapter().read(annotation_path, dataset_id="dataset-1")

    segmentation = source.annotations[0].segmentation
    assert isinstance(segmentation, dict)
    assert segmentation["size"] == [10, 20]
    assert isinstance(segmentation["counts"], str)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["images"].append(dict(payload["images"][0])), "duplicate image id"),
        (
            lambda payload: payload["categories"].append(dict(payload["categories"][0])),
            "duplicate category id",
        ),
        (lambda payload: payload["annotations"][0].update(image_id=999), "unknown image"),
        (lambda payload: payload["annotations"][0].update(category_id=999), "unknown category"),
        (lambda payload: payload["annotations"][0].update(bbox=[0, 0, float("nan"), 2]), "finite"),
    ],
)
def test_coco_adapter_rejects_invalid_references_and_geometry(
    image_factory,
    tmp_path,
    mutation,
    message,
):
    annotation_path, payload = write_coco(tmp_path, image_factory)
    mutation(payload)
    annotation_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceFormatError, match=message):
        CocoAdapter().read(annotation_path, dataset_id="dataset-1")


def test_coco_adapter_rejects_missing_image(image_factory, tmp_path):
    annotation_path, _ = write_coco(tmp_path, image_factory)
    (tmp_path / "images" / "frame.jpg").unlink()

    with pytest.raises(SourceFormatError, match="image file"):
        CocoAdapter().read(annotation_path, dataset_id="dataset-1")


def test_coco_adapter_rejects_image_path_escape(image_factory, tmp_path):
    annotation_path, payload = write_coco(tmp_path, image_factory)
    payload["images"][0]["file_name"] = "../outside.jpg"
    annotation_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceFormatError, match="escapes"):
        CocoAdapter().read(annotation_path, dataset_id="dataset-1")
