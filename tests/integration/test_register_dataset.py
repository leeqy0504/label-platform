from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration.fixtures import IntegrationContext


pytestmark = pytest.mark.integration


def wait_for_job(context: IntegrationContext, job_id: str) -> dict[str, object]:
    context.run_queued_jobs()
    response = context.client.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    job = response.json()
    assert job["status"] in {"succeeded", "failed"}
    return job


def test_registers_ten_images_into_ready_v1_idempotently(
    integration_context: IntegrationContext,
    image_factory,
):
    context = integration_context
    for index in range(10):
        image_factory(
            context.source_root / "incoming" / f"image-{index:02d}.jpg",
            size=(64, 48),
        )

    selection = {
        "source_root_id": context.root_id,
        "relative_path": "incoming",
        "categories": ["cargo"],
        "task_type": "detection",
        "split": {"train": 0.8, "val": 0.2, "test": 0.0, "seed": 42},
    }
    analysis_response = context.client.post(
        "/api/datasets/analyze",
        json={**selection, "idempotency_key": "integration-analysis"},
    )
    assert analysis_response.status_code == 202
    analysis = wait_for_job(context, analysis_response.json()["job_id"])
    assert analysis["status"] == "succeeded"
    assert analysis["result"]["image_count"] == 10

    registration_payload = {
        **selection,
        "name": "integration-warehouse",
        "description": "ten-image PostgreSQL and Redis integration dataset",
        "analysis_fingerprint": analysis["result"]["fingerprint"],
        "idempotency_key": "integration-registration",
    }
    first = context.client.post("/api/datasets/register", json=registration_payload)
    assert first.status_code == 202
    registration = wait_for_job(context, first.json()["job_id"])
    assert registration["status"] == "succeeded"

    repeated = context.client.post("/api/datasets/register", json=registration_payload)
    assert repeated.status_code == 202
    assert repeated.json()["job_id"] == first.json()["job_id"]

    dataset_id = registration["business_object_id"]
    dataset = context.client.get(f"/api/datasets/{dataset_id}").json()
    versions = context.client.get(f"/api/datasets/{dataset_id}/versions").json()["data"]
    manifest_path = (
        context.managed_root / str(dataset_id) / "versions" / "v1" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert dataset["current_version"] == 1
    assert dataset["item_count"] == 10
    assert versions[0]["status"] == "ready"
    assert versions[0]["validation_result"]["valid"] is True
    assert manifest["format"] == "platform-coco-v1"
    assert sum(manifest["split_counts"].values()) == 10
    assert context.redis.llen("rq:queue:dataset-operations") == 0
    assert Path(context.managed_root / str(dataset_id) / "latest").resolve() == (
        context.managed_root / str(dataset_id) / "versions" / "v1"
    ).resolve()
