import json
import zipfile

import numpy as np
import pytest
from label_studio_sdk.converter.brush import mask2rle
from pycocotools import mask as mask_utils

from label_platform.datasets.contracts import SourceFormatError
from label_platform.datasets.labelstudio_adapter import LabelStudioExportAdapter
from label_platform.domain.enums import SourceFormat, TaskType


def write_native_export(tmp_path, image_factory, *, annotations, name="tasks.json"):
    image_factory(tmp_path / "images" / "frame.jpg", size=(20, 10))
    tasks = [
        {
            "id": 1,
            "data": {"image": "images/frame.jpg", "episode_id": "episode-1"},
            "annotations": annotations,
        },
        {
            "id": 2,
            "data": {"image": "images/unannotated.jpg"},
            "annotations": [],
        },
    ]
    image_factory(tmp_path / "images" / "unannotated.jpg", size=(8, 6))
    path = tmp_path / name
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return path, tasks


def rectangle_result(*, x, label="cargo"):
    return {
        "type": "rectanglelabels",
        "original_width": 20,
        "original_height": 10,
        "value": {"x": x, "y": 20, "width": 25, "height": 40, "rectanglelabels": [label]},
    }


def test_native_rectangle_uses_last_non_cancelled_annotation(image_factory, tmp_path):
    export, _ = write_native_export(
        tmp_path,
        image_factory,
        annotations=[
            {"id": 1, "result": [rectangle_result(x=0)]},
            {"id": 2, "was_cancelled": True, "result": [rectangle_result(x=50)]},
            {"id": 3, "result": [rectangle_result(x=10)]},
        ],
    )

    source = LabelStudioExportAdapter().read(
        export,
        dataset_id="dataset-1",
        categories=["cargo"],
    )

    assert source.format is SourceFormat.LABEL_STUDIO
    assert source.task_type is TaskType.DETECTION
    assert len(source.images) == 2
    assert len(source.annotations) == 1
    assert source.annotations[0].bbox == (2.0, 2.0, 5.0, 4.0)
    assert source.images[0].group_key == "episode-1"


def test_native_polygon_converts_percentage_points(image_factory, tmp_path):
    result = {
        "type": "polygonlabels",
        "original_width": 20,
        "original_height": 10,
        "value": {
            "points": [[10, 20], [50, 20], [50, 80]],
            "polygonlabels": ["cargo"],
        },
    }
    export, _ = write_native_export(
        tmp_path,
        image_factory,
        annotations=[{"result": [result]}],
    )

    source = LabelStudioExportAdapter().read(export, dataset_id="dataset-1")

    assert source.task_type is TaskType.INSTANCE_SEGMENTATION
    assert source.annotations[0].segmentation == [[2.0, 2.0, 10.0, 2.0, 10.0, 8.0]]


def test_native_brush_decodes_label_studio_rle_to_coco_rle(image_factory, tmp_path):
    mask = np.zeros((10, 20), dtype=np.uint8)
    mask[2:6, 3:8] = 255
    result = {
        "type": "brushlabels",
        "original_width": 20,
        "original_height": 10,
        "value": {"rle": mask2rle(mask), "brushlabels": ["cargo"]},
    }
    export, _ = write_native_export(
        tmp_path,
        image_factory,
        annotations=[{"result": [result]}],
    )

    source = LabelStudioExportAdapter().read(export, dataset_id="dataset-1")

    segmentation = source.annotations[0].segmentation
    assert source.task_type is TaskType.INSTANCE_SEGMENTATION
    assert isinstance(segmentation, dict)
    decoded = mask_utils.decode(
        {"size": segmentation["size"], "counts": str(segmentation["counts"]).encode("utf-8")}
    )
    assert np.array_equal(decoded, mask > 0)


def test_native_export_rejects_label_outside_frozen_categories(image_factory, tmp_path):
    export, _ = write_native_export(
        tmp_path,
        image_factory,
        annotations=[{"result": [rectangle_result(x=0, label="unknown")]}],
    )

    with pytest.raises(SourceFormatError, match="unknown label"):
        LabelStudioExportAdapter().read(
            export,
            dataset_id="dataset-1",
            categories=["cargo"],
        )


def test_labelstudio_zip_reads_native_json_but_keeps_external_media(
    image_factory,
    tmp_path,
):
    export, tasks = write_native_export(
        tmp_path,
        image_factory,
        annotations=[{"result": [rectangle_result(x=0)]}],
    )
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("result.json", json.dumps(tasks))
    export.unlink()

    source = LabelStudioExportAdapter().read(archive, dataset_id="dataset-1")

    assert source.format is SourceFormat.LABEL_STUDIO
    assert len(source.images) == 2


def test_labelstudio_brush_to_coco_zip_is_supported(image_factory, tmp_path):
    image_factory(tmp_path / "frame.jpg", size=(20, 10))
    coco = {
        "images": [{"id": 1, "file_name": "frame.jpg", "width": 20, "height": 10}],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 1,
                "segmentation": [[1, 1, 5, 1, 5, 5]],
            }
        ],
        "categories": [{"id": 1, "name": "target"}],
    }
    archive = tmp_path / "result.json"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("result_coco.json", json.dumps(coco))

    source = LabelStudioExportAdapter().read(archive, dataset_id="dataset-1")

    assert source.format is SourceFormat.LABEL_STUDIO
    assert source.task_type is TaskType.INSTANCE_SEGMENTATION
    assert source.categories == ("target",)


def test_labelstudio_zip_rejects_escaping_member(tmp_path):
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.json", "{}")

    with pytest.raises(SourceFormatError, match="unsafe archive member"):
        LabelStudioExportAdapter().read(archive, dataset_id="dataset-1")


def test_labelstudio_zip_rejects_absolute_member(tmp_path):
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("/absolute.json", "{}")

    with pytest.raises(SourceFormatError, match="unsafe archive member"):
        LabelStudioExportAdapter().read(archive, dataset_id="dataset-1")
