import json

from sqlalchemy import select

from label_platform.db.models import Dataset, DatasetVersion, ReviewSession, User
from label_platform.domain.enums import ReviewStatus, VersionStatus
from label_platform.jobs.queue import InlineJobQueue


class HealthOnlyConnector:
    def health(self) -> str:
        return "1.13.1"


def test_review_api_queues_creation_exposes_deep_link_and_queues_export(
    authenticated_client,
    api_context,
):
    settings, session_factory = api_context
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
    assert detail.json()["label_studio_project_url"].endswith("/projects/17/data")
    assert health.json() == {"status": "online", "version": "1.13.1"}
    assert completed.status_code == 202
    assert completed.json()["status"] == "exporting"
    assert queue.review_export_enqueued_count == 1
