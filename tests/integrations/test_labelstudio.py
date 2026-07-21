import json

import httpx

from label_platform.integrations.labelstudio import LabelStudioHttpConnector


def test_connector_uses_rest_api_for_project_storage_import_progress_and_export(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers.get("authorization") == "Token test-token"
        if request.url.path == "/api/projects" and request.method == "POST":
            return httpx.Response(201, json={"id": 17})
        if request.url.path == "/api/projects/17" and request.method == "PATCH":
            return httpx.Response(200, json={"id": 17})
        if request.url.path == "/api/storages/localfiles" and request.method == "GET":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/storages/localfiles" and request.method == "POST":
            return httpx.Response(201, json={"id": 23})
        if request.url.path == "/api/projects/17/import":
            payload = json.loads(request.content)
            assert payload[0]["data"]["sample_key"] == "sample-1"
            return httpx.Response(201, json={"task_ids": [41]})
        if request.url.path == "/api/tasks":
            return httpx.Response(
                200,
                json={"tasks": [{"id": 41, "data": {"sample_key": "sample-1"}}]},
            )
        if request.url.path == "/api/projects/17" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "task_number": 1,
                    "finished_task_number": 1,
                    "skipped_annotations_number": 0,
                },
            )
        if request.url.path == "/api/projects/17" and request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path == "/api/projects/17/export":
            return httpx.Response(200, json=[{"id": 41, "data": {"sample_key": "sample-1"}}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(
        base_url="http://label.test",
        transport=httpx.MockTransport(handler),
    )
    connector = LabelStudioHttpConnector(
        base_url="http://label.test",
        token="test-token",
        client=client,
    )

    project_id = connector.create_project("warehouse v1 review", "traceable review")
    connector.configure_labels(project_id, "<View />")
    storage_id = connector.create_local_storage(project_id, "/datasets/warehouse/v1/images")
    imported = connector.import_tasks(
        project_id,
        [{"data": {"sample_key": "sample-1", "image": "/data/local-files/?d=a.jpg"}}],
    )
    existing = connector.get_task_bindings(project_id)
    progress = connector.get_progress(project_id)
    export_path = connector.export_annotations(project_id, tmp_path / "raw-export.json")
    connector.delete_project(project_id)

    assert project_id == 17
    assert storage_id == 23
    assert imported == {"sample-1": 41}
    assert existing == {"sample-1": 41}
    assert progress.total == 1
    assert progress.completed == 1
    assert export_path.read_text(encoding="utf-8").startswith("[")
    assert connector.get_review_url(project_id) == "http://label.test/projects/17/data"
    assert any(
        request.method == "DELETE" and request.url.path == "/api/projects/17"
        for request in requests
    )
    assert all("sqlite" not in str(request.url) for request in requests)


def test_connector_reuses_matching_local_storage():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[{"id": 9, "path": "/datasets/warehouse/v1/images"}],
        )

    connector = LabelStudioHttpConnector(
        base_url="http://label.test",
        token="test-token",
        client=httpx.Client(base_url="http://label.test", transport=httpx.MockTransport(handler)),
    )

    assert connector.create_local_storage(17, "/datasets/warehouse/v1/images") == 9


def test_connector_treats_missing_project_as_already_deleted():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/projects/17"
        return httpx.Response(404)

    connector = LabelStudioHttpConnector(
        base_url="http://label.test",
        token="test-token",
        client=httpx.Client(base_url="http://label.test", transport=httpx.MockTransport(handler)),
    )

    connector.delete_project(17)
