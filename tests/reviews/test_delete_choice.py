import json

import pytest

from label_platform.datasets.contracts import SourceFormatError
from label_platform.db.models import DatasetItem, DatasetVersion
from label_platform.domain.enums import TaskType, VersionStatus
from label_platform.reviews.export import load_review_export


def test_delete_all_images_is_rejected_before_publication(tmp_path):
    export = tmp_path / "raw-export.json"
    export.write_text(
        json.dumps(
            [
                {
                    "data": {"sample_key": "sample-1", "image": "ignored.jpg"},
                    "annotations": [
                        {
                            "result": [
                                {
                                    "from_name": "image_disposition",
                                    "to_name": "image",
                                    "type": "choices",
                                    "value": {"choices": ["删除图片"]},
                                }
                            ]
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    version = DatasetVersion(
        id="version-1",
        dataset_id="dataset-1",
        version_number=1,
        root_path="dataset-1/versions/v1",
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
            width=20,
            height=10,
            file_size=10,
            sha256="a" * 64,
            split="train",
            status="annotated",
        )
    ]

    with pytest.raises(SourceFormatError, match="zero images"):
        load_review_export(
            export,
            version=version,
            version_root=tmp_path,
            task_type=TaskType.DETECTION,
        )
