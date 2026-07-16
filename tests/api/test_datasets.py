import hashlib

import pytest
from sqlalchemy import select

from label_platform.db.models import AllowedRoot, AuditEvent, DatasetItem
from label_platform.jobs.queue import InlineJobQueue
from label_platform.jobs.tasks import JobRunner


def login(client, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200


@pytest.fixture
def dataset_api(client, api_context, user_factory, tmp_path):
    settings, session_factory = api_context
    engineer = user_factory(email="engineer@example.test", password="engineer-password")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    with session_factory() as session:
        root = AllowedRoot(
            path=str(source_root.resolve()),
            label="Sources",
            created_by_id=engineer.id,
        )
        session.add(root)
        session.commit()
        session.refresh(root)
        root_id = root.id
    runner = JobRunner(session_factory, managed_root=settings.managed_data_root)
    queue = InlineJobQueue(
        analysis_handler=runner.run_analysis,
        registration_handler=runner.run_registration,
    )
    client.app.state.job_queue = queue
    login(client, engineer.email, "engineer-password")
    return client, session_factory, queue, engineer, root_id, source_root, settings.managed_data_root


def analysis_payload(root_id, *, key="analysis-1"):
    return {
        "source_root_id": root_id,
        "relative_path": "incoming",
        "categories": ["cargo"],
        "task_type": "detection",
        "split": {"train": 0.8, "val": 0.2, "test": 0.0, "seed": 42},
        "idempotency_key": key,
    }


def registration_payload(root_id, fingerprint, *, key="register-1", name="warehouse"):
    return {
        "name": name,
        "description": "cargo images",
        "source_root_id": root_id,
        "relative_path": "incoming",
        "categories": ["cargo"],
        "task_type": "detection",
        "split": {"train": 0.8, "val": 0.2, "test": 0.0, "seed": 42},
        "analysis_fingerprint": fingerprint,
        "idempotency_key": key,
    }


def analyze(client, root_id, *, key="analysis-1"):
    response = client.post("/api/datasets/analyze", json=analysis_payload(root_id, key=key))
    assert response.status_code == 202
    job = client.get(f"/api/jobs/{response.json()['job_id']}")
    assert job.status_code == 200
    return job.json()


def test_analysis_returns_format_counts_splits_and_fingerprint(
    dataset_api,
    image_factory,
):
    client, _, queue, _, root_id, source_root, _ = dataset_api
    image_factory(source_root / "incoming/a.jpg", size=(20, 10))
    image_factory(source_root / "incoming/b.png", size=(12, 8))

    job = analyze(client, root_id)

    assert job["status"] == "succeeded"
    assert job["stage"] == "done"
    assert job["result"]["valid"] is True
    assert job["result"]["source_format"] == "image_directory"
    assert job["result"]["task_type"] == "detection"
    assert job["result"]["image_count"] == 2
    assert job["result"]["annotation_count"] == 0
    assert job["result"]["categories"] == ["cargo"]
    assert sum(job["result"]["split_counts"].values()) == 2
    assert len(job["result"]["fingerprint"]) == 64
    assert queue.analysis_enqueued_count == 1


def test_invalid_analysis_succeeds_with_structured_errors_and_cannot_register(
    dataset_api,
):
    client, _, _, _, root_id, source_root, _ = dataset_api
    incoming = source_root / "incoming"
    incoming.mkdir()
    (incoming / "broken.jpg").write_bytes(b"not an image")

    job = analyze(client, root_id)

    assert job["status"] == "succeeded"
    assert job["result"]["valid"] is False
    assert job["result"]["fingerprint"] is None
    assert job["result"]["errors"]
    response = client.post(
        "/api/datasets/register",
        json=registration_payload(root_id, "0" * 64),
    )
    assert response.status_code == 409


def test_registration_is_idempotent_and_publishes_ready_dataset(
    dataset_api,
    image_factory,
):
    client, _, queue, _, root_id, source_root, _ = dataset_api
    image_factory(source_root / "incoming/frame.jpg", size=(20, 10))
    analysis = analyze(client, root_id)
    payload = registration_payload(root_id, analysis["result"]["fingerprint"])

    first = client.post("/api/datasets/register", json=payload)
    second = client.post("/api/datasets/register", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert queue.registration_enqueued_count == 1
    job = client.get(f"/api/jobs/{first.json()['job_id']}").json()
    assert job["status"] == "succeeded"
    assert job["result"]["version_number"] == 1

    listing = client.get("/api/datasets")
    assert listing.status_code == 200
    assert listing.json()["meta"] == {"page": 1, "page_size": 20, "total": 1}
    assert listing.json()["data"][0]["name"] == "warehouse"
    assert listing.json()["data"][0]["current_version"] == 1


def test_dataset_listing_filters_before_pagination(
    dataset_api,
    image_factory,
):
    client, _, _, _, root_id, source_root, _ = dataset_api
    image_factory(source_root / "incoming/frame.jpg")
    analysis = analyze(client, root_id)
    client.post(
        "/api/datasets/register",
        json=registration_payload(root_id, analysis["result"]["fingerprint"]),
    )

    matching = client.get(
        "/api/datasets",
        params={"search": "CARGO", "status": "pending_annotation"},
    )
    missing = client.get("/api/datasets", params={"search": "missing"})
    invalid_status = client.get("/api/datasets", params={"status": "not-a-status"})

    assert matching.status_code == 200
    assert matching.json()["meta"]["total"] == 1
    assert matching.json()["data"][0]["name"] == "warehouse"
    assert missing.status_code == 200
    assert missing.json()["meta"]["total"] == 0
    assert invalid_status.status_code == 422


def test_registration_detects_source_change_and_retry_succeeds_after_restore(
    dataset_api,
    image_factory,
):
    client, _, queue, _, root_id, source_root, _ = dataset_api
    image_path = image_factory(source_root / "incoming/frame.jpg", size=(20, 10))
    original = image_path.read_bytes()
    analysis = analyze(client, root_id)
    image_factory(image_path, size=(21, 10))

    response = client.post(
        "/api/datasets/register",
        json=registration_payload(root_id, analysis["result"]["fingerprint"]),
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    failed = client.get(f"/api/jobs/{job_id}").json()
    assert failed["status"] == "failed"
    assert "changed since analysis" in failed["error_summary"]["message"]

    image_path.write_bytes(original)
    retried = client.post(f"/api/jobs/{job_id}/retry")
    assert retried.status_code == 202
    completed = client.get(f"/api/jobs/{job_id}").json()
    assert completed["status"] == "succeeded"
    assert completed["retry_count"] == 1
    assert queue.registration_enqueued_count == 2


def test_dataset_detail_versions_items_and_media_are_scoped(
    dataset_api,
    image_factory,
):
    client, session_factory, _, _, root_id, source_root, _ = dataset_api
    image = image_factory(source_root / "incoming/frame.jpg", size=(20, 10))
    analysis = analyze(client, root_id)
    registration = client.post(
        "/api/datasets/register",
        json=registration_payload(root_id, analysis["result"]["fingerprint"]),
    ).json()
    result = client.get(f"/api/jobs/{registration['job_id']}").json()["result"]
    dataset_id = result["dataset_id"]
    version_id = result["version_id"]

    detail = client.get(f"/api/datasets/{dataset_id}")
    versions = client.get(f"/api/datasets/{dataset_id}/versions")
    items = client.get(
        f"/api/datasets/{dataset_id}/versions/{version_id}/items",
        params={"page": 1, "page_size": 10},
    )

    assert detail.status_code == 200
    assert detail.json()["id"] == dataset_id
    assert detail.json()["category_counts"] == {"1": 0}
    assert versions.status_code == 200
    assert versions.json()["data"][0]["status"] == "ready"
    assert items.status_code == 200
    item = items.json()["data"][0]
    assert item["annotation_count"] == 0
    filtered = client.get(
        f"/api/datasets/{dataset_id}/versions/{version_id}/items",
        params={
            "search": "FRAME",
            "split": item["split"],
            "annotation_status": item["status"],
        },
    )
    missing = client.get(
        f"/api/datasets/{dataset_id}/versions/{version_id}/items",
        params={"search": "missing"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["meta"]["total"] == 1
    assert missing.status_code == 200
    assert missing.json()["meta"]["total"] == 0
    media = client.get(
        f"/api/datasets/{dataset_id}/versions/{version_id}/items/{item['id']}/media"
    )
    assert media.status_code == 200
    assert hashlib.sha256(media.content).hexdigest() == hashlib.sha256(image.read_bytes()).hexdigest()

    with session_factory() as session:
        stored = session.get(DatasetItem, item["id"])
        assert stored is not None
        stored.relative_path = "../outside.jpg"
        session.commit()
    escaped = client.get(
        f"/api/datasets/{dataset_id}/versions/{version_id}/items/{item['id']}/media"
    )
    assert escaped.status_code == 404


def test_archive_is_audited_and_does_not_delete_managed_files(
    dataset_api,
    image_factory,
):
    client, session_factory, _, _, root_id, source_root, managed_root = dataset_api
    image_factory(source_root / "incoming/frame.jpg")
    analysis = analyze(client, root_id)
    response = client.post(
        "/api/datasets/register",
        json=registration_payload(root_id, analysis["result"]["fingerprint"]),
    )
    result = client.get(f"/api/jobs/{response.json()['job_id']}").json()["result"]

    archived = client.post(f"/api/datasets/{result['dataset_id']}/archive")

    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert (managed_root / result["dataset_id"] / "versions/v1").is_dir()
    with session_factory() as session:
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == result["dataset_id"],
                AuditEvent.action == "dataset.archived",
            )
        )
        assert event is not None


def test_reviewer_cannot_analyze_register_or_archive(
    client,
    api_context,
    user_factory,
    tmp_path,
):
    _, session_factory = api_context
    reviewer = user_factory(
        email="reviewer@example.test",
        password="reviewer-password",
        role="reviewer",
    )
    source = tmp_path / "sources"
    source.mkdir()
    with session_factory() as session:
        root = AllowedRoot(path=str(source), label="Sources", created_by_id=reviewer.id)
        session.add(root)
        session.commit()
        root_id = root.id
    login(client, reviewer.email, "reviewer-password")

    assert client.post("/api/datasets/analyze", json=analysis_payload(root_id)).status_code == 403
    assert (
        client.post(
            "/api/datasets/register",
            json=registration_payload(root_id, "fingerprint"),
        ).status_code
        == 403
    )
    assert client.post("/api/datasets/missing/archive").status_code == 403
