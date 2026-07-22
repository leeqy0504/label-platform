import pytest
from sqlalchemy.exc import IntegrityError

from label_platform.db.models import (
    AllowedRoot,
    AuditEvent,
    BackgroundJob,
    Dataset,
    DatasetItem,
    DatasetSource,
    DatasetVersion,
    ReviewSession,
    ReviewTaskBinding,
    TrainingRun,
)
from label_platform.domain.enums import (
    JobStatus,
    ReviewStatus,
    SourceFormat,
    TaskType,
    TrainingStatus,
    VersionStatus,
)


def test_dataset_version_keeps_schema_and_parent(db_session, allowed_root):
    dataset = Dataset(name="warehouse", description="")
    source = DatasetSource(
        dataset=dataset,
        allowed_root_id=allowed_root.id,
        relative_path="incoming/warehouse",
        normalized_path="/srv/data/incoming/warehouse",
        source_format=SourceFormat.COCO_INSTANCE,
        task_type=TaskType.INSTANCE_SEGMENTATION,
    )
    v1 = DatasetVersion(
        dataset=dataset,
        version_number=1,
        status=VersionStatus.READY,
        root_path="warehouse/versions/v1",
        manifest_path="manifest.json",
        annotation_path="annotations/instances.coco.json",
        class_schema=[{"id": 1, "name": "cargo"}],
    )
    v2 = DatasetVersion(
        dataset=dataset,
        version_number=2,
        parent=v1,
        status=VersionStatus.BUILDING,
        class_schema=v1.class_schema,
    )
    db_session.add_all([source, v2])
    db_session.commit()

    assert v2.parent_id == v1.id
    assert v2.class_schema == [{"id": 1, "name": "cargo"}]
    assert dataset.sources == [source]


def test_item_job_and_audit_keep_operational_metadata(db_session):
    dataset = Dataset(name="operations", description="")
    version = DatasetVersion(
        dataset=dataset,
        version_number=1,
        status=VersionStatus.BUILDING,
        class_schema=[],
    )
    db_session.add(version)
    db_session.flush()

    item = DatasetItem(
        version_id=version.id,
        sample_key="camera-a/frame-001",
        relative_path="images/camera-a/frame-001.jpg",
        media_type="image/jpeg",
        width=1920,
        height=1080,
        file_size=123_456,
        sha256="a" * 64,
        split="train",
        status="ready",
        group_key="camera-a",
    )
    job = BackgroundJob(
        business_object_id=dataset.id,
        job_type="dataset.register",
        idempotency_key="register-operations-v1",
        status=JobStatus.FAILED,
        stage="validating",
        processed_count=9,
        total_count=10,
        error_summary={"code": "invalid_bbox", "count": 1},
        log_path="logs/register-operations-v1.log",
        retry_count=2,
    )
    db_session.add_all([item, job])
    db_session.flush()
    audit = AuditEvent(
        action="dataset.registration_failed",
        resource_type="dataset",
        resource_id=dataset.id,
        details={"job_id": job.id},
    )
    db_session.add(audit)
    db_session.commit()

    assert item.version is version
    assert job.error_summary == {"code": "invalid_bbox", "count": 1}
    assert job.retry_count == 2
    assert audit.details == {"job_id": job.id}


def test_sample_key_is_unique_within_a_version(db_session):
    dataset = Dataset(name="unique-items", description="")
    version = DatasetVersion(
        dataset=dataset,
        version_number=1,
        status=VersionStatus.BUILDING,
        class_schema=[],
    )
    first = DatasetItem(
        version=version,
        sample_key="same-key",
        relative_path="images/one.jpg",
        media_type="image/jpeg",
        width=10,
        height=10,
        file_size=100,
        sha256="1" * 64,
        status="ready",
    )
    second = DatasetItem(
        version=version,
        sample_key="same-key",
        relative_path="images/two.jpg",
        media_type="image/jpeg",
        width=10,
        height=10,
        file_size=100,
        sha256="2" * 64,
        status="ready",
    )
    db_session.add_all([first, second])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_allowed_root_path_is_unique(db_session, tmp_path):
    path = str(tmp_path / "shared-root")
    db_session.add_all(
        [
            AllowedRoot(path=path, label="First"),
            AllowedRoot(path=path, label="Second"),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_version_number_is_unique_within_a_dataset(db_session):
    dataset = Dataset(name="unique-versions", description="")
    db_session.add_all(
        [
            DatasetVersion(
                dataset=dataset,
                version_number=1,
                status=VersionStatus.BUILDING,
                class_schema=[],
            ),
            DatasetVersion(
                dataset=dataset,
                version_number=1,
                status=VersionStatus.BUILDING,
                class_schema=[],
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_review_session_binds_label_studio_tasks_to_input_items(db_session):
    dataset = Dataset(name="review-model", description="")
    version = DatasetVersion(
        dataset=dataset,
        version_number=1,
        status=VersionStatus.READY,
        class_schema=[{"id": 1, "name": "cargo"}],
    )
    item = DatasetItem(
        version=version,
        sample_key="sample-1",
        relative_path="images/frame.jpg",
        media_type="image/jpeg",
        width=20,
        height=10,
        file_size=100,
        sha256="a" * 64,
        split="train",
        status="annotated",
    )
    review = ReviewSession(
        dataset=dataset,
        input_version=version,
        label_studio_base_url="http://127.0.0.1:8081",
        idempotency_key="review-model-v1",
        status=ReviewStatus.IMPORTING,
        recoverable_status=ReviewStatus.IMPORTING,
        config_hash="b" * 64,
    )
    binding = ReviewTaskBinding(
        review_session=review,
        dataset_item=item,
        sample_key=item.sample_key,
        label_studio_task_id=41,
    )
    db_session.add(binding)
    db_session.commit()

    assert review.input_version_id == version.id
    assert review.task_bindings == [binding]
    assert binding.dataset_item is item
    assert review.status is ReviewStatus.IMPORTING


def test_training_run_binds_ready_version_to_external_run(db_session):
    dataset = Dataset(name="training-model", description="")
    version = DatasetVersion(
        dataset=dataset,
        version_number=2,
        status=VersionStatus.READY,
        class_schema=[{"id": 1, "name": "cargo"}],
    )
    run = TrainingRun(
        dataset=dataset,
        dataset_version=version,
        unitrain_run_id="unitrain-run-7",
        idempotency_key="training-model-v2",
        name="baseline",
        task_type=TaskType.DETECTION,
        export_profile="unitrain-coco-split-v1",
        config={"epochs": 10},
        status=TrainingStatus.RUNNING,
        current_epoch=2,
        total_epochs=10,
        external_detail_url="http://unitrain.test/runs/unitrain-run-7",
        metric_summary={"mAP50": 0.5},
    )
    db_session.add(run)
    db_session.commit()

    assert run.dataset_version is version
    assert run.dataset is dataset
    assert run.metric_summary == {"mAP50": 0.5}
