from pathlib import Path


def test_source_roots_are_public_and_only_active_roots_are_listed(client, api_context, tmp_path):
    _, session_factory = api_context
    active_path = tmp_path / "active"
    inactive_path = tmp_path / "inactive"
    active_path.mkdir()
    inactive_path.mkdir()

    with session_factory() as session, session.begin():
        from label_platform.db.models import AllowedRoot

        session.add_all(
            [
                AllowedRoot(path=str(active_path), label="Active", description=""),
                AllowedRoot(path=str(inactive_path), label="Inactive", description="", is_active=False),
            ]
        )

    response = client.get("/api/source-roots")
    assert response.status_code == 200
    assert [root["label"] for root in response.json()] == ["Active"]


def test_source_root_mutations_are_public(client, tmp_path: Path):
    root_path = tmp_path / "source"
    root_path.mkdir()
    created = client.post(
        "/api/admin/source-roots",
        json={"path": str(root_path), "label": "Source", "description": ""},
    )
    assert created.status_code == 201
    updated = client.patch(
        f"/api/admin/source-roots/{created.json()['id']}",
        json={"is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False
