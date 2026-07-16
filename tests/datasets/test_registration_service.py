import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select

from label_platform.datasets.service import (
    DatasetRegistrationError,
    DatasetRegistrationRequest,
    RegistrationService,
)
from label_platform.db.models import Dataset, DatasetItem, DatasetVersion
from label_platform.domain.enums import TaskType, VersionStatus


@pytest.fixture
def registration_context(api_context, user_factory, tmp_path):
    settings, session_factory = api_context
    creator = user_factory(email="engineer@example.test", password="engineer-password")
    with session_factory() as session:
        dataset = Dataset(
            name="warehouse",
            description="cargo",
            created_by_id=creator.id,
        )
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        dataset_id = dataset.id
    service = RegistrationService(session_factory, managed_root=settings.managed_data_root)
    return service, session_factory, creator, dataset_id


def request_for(source: Path, creator_id: str, dataset_id: str):
    return DatasetRegistrationRequest(
        dataset_id=dataset_id,
        source_path=source,
        categories=("cargo",),
        task_type=TaskType.INSTANCE_SEGMENTATION,
        created_by_id=creator_id,
        split_seed=42,
        source_version="source-v1",
        source_lineage={"allowed_root_id": "root-1", "relative_path": "incoming/warehouse"},
    )


def test_registration_persists_ready_v1_and_items(
    registration_context,
    image_factory,
    tmp_path,
):
    service, session_factory, creator, dataset_id = registration_context
    source = tmp_path / "source"
    image_factory(source / "a.jpg", size=(20, 10))
    image_factory(source / "b.png", size=(12, 8))

    version = service.register(request_for(source, creator.id, dataset_id))

    assert version.status is VersionStatus.READY
    assert version.version_number == 1
    assert version.parent_id is None
    assert version.item_count == 2
    assert version.root_path == f"{dataset_id}/versions/v1"
    assert version.manifest_path == "manifest.json"
    assert version.annotation_path == "annotations/instances.coco.json"
    assert version.class_schema == [{"id": 1, "name": "cargo"}]
    assert version.category_counts == {"1": 0}
    assert version.validation_result["valid"] is True
    with session_factory() as session:
        items = list(session.scalars(select(DatasetItem).where(DatasetItem.version_id == version.id)))
    assert len(items) == 2
    assert {item.status for item in items} == {"unannotated"}
    assert {item.annotation_count for item in items} == {0}
    assert {item.split for item in items}.issubset({"train", "val", "test"})


def test_registration_persists_category_and_per_item_annotation_counts(
    registration_context,
    image_factory,
    tmp_path,
):
    service, session_factory, creator, dataset_id = registration_context
    source = tmp_path / "coco-source"
    image_factory(source / "frame.jpg", size=(20, 10))
    (source / "annotations.json").write_text(
        json.dumps(
            {
                "images": [{"id": 3, "file_name": "frame.jpg", "width": 20, "height": 10}],
                "categories": [{"id": 7, "name": "cargo"}],
                "annotations": [
                    {
                        "id": annotation_id,
                        "image_id": 3,
                        "category_id": 7,
                        "bbox": [1, 1, 5, 5],
                        "area": 25,
                        "iscrowd": 0,
                        "segmentation": [[1, 1, 6, 1, 6, 6, 1, 6]],
                    }
                    for annotation_id in (11, 12)
                ],
            }
        ),
        encoding="utf-8",
    )

    version = service.register(request_for(source, creator.id, dataset_id))

    assert version.category_counts == {"1": 2}
    with session_factory() as session:
        item = session.scalar(select(DatasetItem).where(DatasetItem.version_id == version.id))
        assert item is not None
        assert item.annotation_count == 2


def test_registration_allocates_v2_with_ready_parent(
    registration_context,
    image_factory,
    tmp_path,
):
    service, _, creator, dataset_id = registration_context
    source = tmp_path / "source"
    image_factory(source / "frame.jpg")
    request = request_for(source, creator.id, dataset_id)
    first = service.register(request)

    second = service.register(request)

    assert second.version_number == 2
    assert second.parent_id == first.id
    assert second.status is VersionStatus.READY


def test_review_registration_reuses_its_ready_child_version(
    registration_context,
    image_factory,
    tmp_path,
):
    service, _, creator, dataset_id = registration_context
    source = tmp_path / "source"
    image_factory(source / "frame.jpg")
    first = service.register(request_for(source, creator.id, dataset_id))
    review_request = replace(
        request_for(source, creator.id, dataset_id),
        parent_version_id=first.id,
        review_session_id="review-1",
        source_lineage={"review_session_id": "review-1"},
    )

    published = service.register(review_request)
    repeated = service.register(review_request)

    assert published.version_number == 2
    assert published.parent_id == first.id
    assert published.review_session_id == "review-1"
    assert repeated.id == published.id


def test_registration_failure_marks_version_invalid_without_publishing(
    registration_context,
    tmp_path,
):
    service, session_factory, creator, dataset_id = registration_context
    source = tmp_path / "corrupt"
    source.mkdir()
    (source / "broken.jpg").write_bytes(b"not an image")

    with pytest.raises(DatasetRegistrationError, match="cannot decode image"):
        service.register(request_for(source, creator.id, dataset_id))

    with session_factory() as session:
        version = session.scalar(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id))
        assert version is not None
        assert version.status is VersionStatus.INVALID
        assert version.validation_result["valid"] is False
    assert not list(service.managed_root.rglob("v1"))


def test_registration_rejects_missing_dataset(registration_context, image_factory, tmp_path):
    service, _, creator, _ = registration_context
    source = tmp_path / "source"
    image_factory(source / "frame.jpg")

    with pytest.raises(DatasetRegistrationError, match="Dataset not found"):
        service.register(request_for(source, creator.id, "missing-dataset"))


def test_database_ready_failure_rolls_back_files_and_latest(
    registration_context,
    image_factory,
    monkeypatch,
    tmp_path,
):
    service, _, creator, dataset_id = registration_context
    source = tmp_path / "source"
    image_factory(source / "frame.jpg")
    request = request_for(source, creator.id, dataset_id)
    first = service.register(request)

    def fail_ready(*args, **kwargs):
        raise RuntimeError("simulated database commit failure")

    monkeypatch.setattr(service, "_mark_ready", fail_ready)
    with pytest.raises(DatasetRegistrationError, match="simulated database commit failure"):
        service.register(request)

    assert not (service.managed_root / dataset_id / "versions/v2").exists()
    assert (service.managed_root / dataset_id / "latest").resolve() == (
        service.managed_root / dataset_id / "versions" / f"v{first.version_number}"
    ).resolve()
