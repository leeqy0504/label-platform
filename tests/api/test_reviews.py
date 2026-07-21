import json

from sqlalchemy import select

from label_platform.db.models import AuditEvent, BackgroundJob, Dataset, DatasetVersion, ReviewSession, User
from label_platform.domain.enums import JobStatus, ReviewStatus, VersionStatus
from label_platform.jobs.queue import InlineJobQueue


class HealthOnlyConnector:
    def __init__(self) -> None:
        self.deleted_projects: list[int] = []

    def health(self) -> str:
        return "1.13.1"

    def delete_project(self, project_id: int) -> None:
        self.deleted_projects.append(project_id)


def test_review_api_queues_creation_exposes_deep_link_and_queues_export(
    authenticated_client,
    api_context,
):
    settings, session_factory = api_context
    settings.label_studio_url = "http://label-studio:8080"
    settings.label_studio_public_url = "https://labels.example.test"
    with session_factory() as session, session.begin():
        user = session.scalar(select(User).where(User.email == "engineer@example.test"))
        assert user is not None
        dataset = Dataset(
            id="dataset-review-api",
            name="review-api",
            description="",
            status="trainable",
            created_by_id=user.id,
        )
        version = DatasetVersion(
            id="version-review-api",
            dataset=dataset,
            version_number=1,
            root_path="dataset-review-api/versions/v1",
            manifest_path="manifest.json",
            annotation_path="annotations/instances.coco.json",
            class_schema=[{"id": 1, "name": "cargo"}],
            item_count=1,
            status=VersionStatus.READY,
            created_by_id=user.id,
        )
        session.add(version)
    version_root = settings.managed_data_root / "dataset-review-api/versions/v1"
    version_root.mkdir(parents=True)
    (version_root / "manifest.json").write_text(
        json.dumps({"task_type": "detection"}),
        encoding="utf-8",
    )
    queue = InlineJobQueue()
    authenticated_client.app.state.job_queue = queue
    authenticated_client.app.state.label_studio_connector = HealthOnlyConnector()

    created = authenticated_client.post(
        "/api/reviews",
        json={
            "dataset_id": "dataset-review-api",
            "input_version_id": "version-review-api",
            "idempotency_key": "review-api-request",
        },
    )

    assert created.status_code == 202
    assert created.json()["status"] == "creating"
    assert created.json()["job_id"]
    assert queue.review_creation_enqueued_count == 1
    review_id = created.json()["id"]
    with session_factory() as session, session.begin():
        review = session.get(ReviewSession, review_id)
        assert review is not None
        review.status = ReviewStatus.READY
        review.recoverable_status = ReviewStatus.READY
        review.label_studio_project_id = 17
        review.total_tasks = 1

    detail = authenticated_client.get(f"/api/reviews/{review_id}")
    health = authenticated_client.get("/api/integrations/label-studio/health")
    completed = authenticated_client.post(f"/api/reviews/{review_id}/complete")

    assert detail.status_code == 200
    assert detail.json()["label_studio_project_url"] == (
        "https://labels.example.test/projects/17/data"
    )
    assert health.json() == {"status": "online", "version": "1.13.1"}
    assert completed.status_code == 202
    assert completed.json()["status"] == "exporting"
    assert queue.review_export_enqueued_count == 1


def test_review_api_deletes_active_session_and_label_studio_project(
    authenticated_client,
    api_context,
):
    _, session_factory = api_context
    connector = HealthOnlyConnector()
    authenticated_client.app.state.label_studio_connector = connector
    with session_factory() as session, session.begin():
        user = session.scalar(select(User).where(User.email == "engineer@example.test"))
        assert user is not None
        dataset = Dataset(
            id="dataset-review-delete",
            name="review-delete",
            description="",
            status="reviewing",
            created_by_id=user.id,
        )
        version = DatasetVersion(
            id="version-review-delete",
            dataset=dataset,
            version_number=1,
            root_path="dataset-review-delete/versions/v1",
            manifest_path="manifest.json",
            annotation_path="annotations/instances.coco.json",
            class_schema=[],
            annotation_count=1,
            status=VersionStatus.READY,
            created_by_id=user.id,
        )
        review = ReviewSession(
            id="review-delete",
            dataset=dataset,
            input_version=version,
            label_studio_project_id=17,
            label_studio_base_url="http://label-studio:8080",
            idempotency_key="review-delete-key",
            status=ReviewStatus.IN_REVIEW,
            recoverable_status=ReviewStatus.IN_REVIEW,
            config_hash="a" * 64,
            created_by_id=user.id,
        )
        session.add(review)
        session.add(
            BackgroundJob(
                id="review-delete-job",
                business_object_id=review.id,
                job_type="review_creation",
                idempotency_key="review-creation:review-delete",
                status=JobStatus.SUCCEEDED,
                created_by_id=user.id,
            )
        )

    response = authenticated_client.delete("/api/reviews/review-delete")

    assert response.status_code == 204
    assert connector.deleted_projects == [17]
    with session_factory() as session:
        assert session.get(ReviewSession, "review-delete") is None
        assert session.get(BackgroundJob, "review-delete-job") is None
        dataset = session.get(Dataset, "dataset-review-delete")
        assert dataset is not None
        assert dataset.status == "trainable"
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "review.deleted",
                AuditEvent.resource_id == "review-delete",
            )
        )
        assert event is not None
        assert event.details["label_studio_project_id"] == 17


def test_review_api_rejects_deleting_completed_session(
    authenticated_client,
    api_context,
):
    _, session_factory = api_context
    connector = HealthOnlyConnector()
    authenticated_client.app.state.label_studio_connector = connector
    with session_factory() as session, session.begin():
        user = session.scalar(select(User).where(User.email == "engineer@example.test"))
        assert user is not None
        dataset = Dataset(
            id="dataset-review-completed",
            name="review-completed",
            description="",
            status="trainable",
            created_by_id=user.id,
        )
        version = DatasetVersion(
            id="version-review-completed",
            dataset=dataset,
            version_number=1,
            root_path="dataset-review-completed/versions/v1",
            class_schema=[],
            status=VersionStatus.READY,
            created_by_id=user.id,
        )
        session.add(
            ReviewSession(
                id="review-completed",
                dataset=dataset,
                input_version=version,
                label_studio_project_id=18,
                label_studio_base_url="http://label-studio:8080",
                idempotency_key="review-completed-key",
                status=ReviewStatus.COMPLETED,
                config_hash="b" * 64,
                created_by_id=user.id,
            )
        )

    response = authenticated_client.delete("/api/reviews/review-completed")

    assert response.status_code == 409
    assert connector.deleted_projects == []
    with session_factory() as session:
        assert session.get(ReviewSession, "review-completed") is not None
