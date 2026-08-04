import json

import numpy as np
from label_studio_sdk.converter.brush import decode_rle
from pycocotools import mask as mask_utils

from label_platform.db.models import DatasetItem, DatasetVersion
from label_platform.domain.enums import TaskType, VersionStatus
from label_platform.reviews.tasks import build_import_tasks, build_label_config


def test_builds_editable_brush_annotations_from_canonical_rle(tmp_path):
    version_root = tmp_path / "dataset-1/versions/v1"
    (version_root / "annotations").mkdir(parents=True)
    (version_root / "images").mkdir()
    (version_root / "images/frame.jpg").write_bytes(b"image")
    mask = np.zeros((8, 10), dtype=np.uint8)
    mask[1:5, 2:6] = 1
    encoded = mask_utils.encode(np.asfortranarray(mask))
    encoded["counts"] = encoded["counts"].decode("utf-8")
    (version_root / "annotations/instances.coco.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "id": 1,
                        "file_name": "images/frame.jpg",
                        "width": 10,
                        "height": 8,
                        "sample_key": "sample-1",
                    }
                ],
                "categories": [{"id": 1, "name": "cargo"}],
                "annotations": [
                    {
                        "id": 5,
                        "image_id": 1,
                        "category_id": 1,
                        "bbox": [2, 1, 4, 4],
                        "area": 16,
                        "iscrowd": 0,
                        "segmentation": encoded,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    version = DatasetVersion(
        id="version-1",
        dataset_id="dataset-1",
        version_number=1,
        root_path="dataset-1/versions/v1",
        annotation_path="annotations/instances.coco.json",
        class_schema=[{"id": 1, "name": "cargo"}],
        item_count=1,
        status=VersionStatus.READY,
    )
    version.items = [
        DatasetItem(
            id="item-1",
            version_id=version.id,
            sample_key="sample-1",
            relative_path="images/frame.jpg",
            media_type="image/jpeg",
            width=10,
            height=8,
            file_size=100,
            sha256="a" * 64,
            split="train",
            status="annotated",
        )
    ]

    tasks = build_import_tasks(version, version_root, task_type=TaskType.INSTANCE_SEGMENTATION)

    assert len(tasks) == 1
    assert tasks[0].sample_key == "sample-1"
    assert tasks[0].payload["data"]["image"] == (
        "/data/local-files/?d=dataset-1/versions/v1/images/frame.jpg"
    )
    assert "predictions" not in tasks[0].payload
    annotation = tasks[0].payload["annotations"][0]
    assert annotation["ground_truth"] is False
    result = annotation["result"][0]
    decoded = np.asarray(decode_rle(result["value"]["rle"]), dtype=np.uint8)
    decoded_mask = decoded.reshape((8, 10, 4))[:, :, 3] > 0
    assert np.array_equal(decoded_mask, mask > 0)


def test_label_config_escapes_categories_and_selects_task_control():
    detection = build_label_config(
        TaskType.DETECTION,
        [{"id": 1, "name": 'cargo & "crate"'}],
    )
    segmentation = build_label_config(
        TaskType.INSTANCE_SEGMENTATION,
        [{"id": 1, "name": "cargo"}],
    )

    assert "RectangleLabels" in detection
    assert 'name="image_disposition"' in detection
    assert "删除图片" in detection
    assert "cargo &amp; &quot;crate&quot;" in detection
    assert "BrushLabels" in segmentation
