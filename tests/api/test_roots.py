from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from label_platform.db.models import AllowedRoot, User


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200


def create_root(
    session_factory: sessionmaker[Session],
    *,
    user: User,
    path: Path,
    label: str,
    is_active: bool = True,
) -> AllowedRoot:
    path.mkdir(parents=True, exist_ok=True)
    with session_factory() as session:
        root = AllowedRoot(
            path=str(path.resolve()),
            label=label,
            description=f"{label} description",
            is_active=is_active,
            created_by_id=user.id,
        )
        session.add(root)
        session.commit()
        session.refresh(root)
        session.expunge(root)
        return root


def test_source_roots_require_authentication(client):
    response = client.get("/api/source-roots")

    assert response.status_code == 401


def test_data_engineer_sees_only_active_source_roots(
    client,
    user_factory,
    api_context,
    tmp_path,
):
    _, session_factory = api_context
    engineer = user_factory(email="engineer@example.test", password="engineer-password")
    active = create_root(
        session_factory,
        user=engineer,
        path=tmp_path / "active",
        label="Active",
    )
    create_root(
        session_factory,
        user=engineer,
        path=tmp_path / "inactive",
        label="Inactive",
        is_active=False,
    )
    login(client, engineer.email, "engineer-password")

    response = client.get("/api/source-roots")

    assert response.status_code == 200
    assert [root["id"] for root in response.json()] == [active.id]
    assert response.json()[0]["path"] == str((tmp_path / "active").resolve())


def test_admin_sees_active_and_inactive_source_roots(
    client,
    user_factory,
    api_context,
    tmp_path,
):
    _, session_factory = api_context
    admin = user_factory(
        email="admin@example.test",
        password="admin-password",
        role="admin",
    )
    create_root(session_factory, user=admin, path=tmp_path / "active", label="Active")
    create_root(
        session_factory,
        user=admin,
        path=tmp_path / "inactive",
        label="Inactive",
        is_active=False,
    )
    login(client, admin.email, "admin-password")

    response = client.get("/api/source-roots")

    assert response.status_code == 200
    assert {root["label"]: root["is_active"] for root in response.json()} == {
        "Active": True,
        "Inactive": False,
    }


def test_admin_creates_normalized_source_root_and_rejects_duplicate(
    client,
    user_factory,
    tmp_path,
):
    admin = user_factory(
        email="admin@example.test",
        password="admin-password",
        role="admin",
    )
    source = tmp_path / "sources"
    nested = source / "nested"
    nested.mkdir(parents=True)
    login(client, admin.email, "admin-password")

    response = client.post(
        "/api/admin/source-roots",
        json={
            "path": str(nested / ".."),
            "label": "Incoming data",
            "description": "Approved imports",
        },
    )

    assert response.status_code == 201
    assert response.json()["path"] == str(source.resolve())
    duplicate = client.post(
        "/api/admin/source-roots",
        json={"path": str(source), "label": "Duplicate"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Source root already exists"


def test_source_root_creation_rejects_nonexistent_relative_and_symlink_paths(
    client,
    user_factory,
    tmp_path,
):
    admin = user_factory(
        email="admin@example.test",
        password="admin-password",
        role="admin",
    )
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked-root"
    link.symlink_to(target, target_is_directory=True)
    login(client, admin.email, "admin-password")

    for path in (str(tmp_path / "missing"), "relative/path", str(link)):
        response = client.post(
            "/api/admin/source-roots",
            json={"path": path, "label": "Invalid"},
        )
        assert response.status_code == 400


def test_data_engineer_cannot_manage_source_roots(client, user_factory, tmp_path):
    engineer = user_factory(email="engineer@example.test", password="engineer-password")
    source = tmp_path / "sources"
    source.mkdir()
    login(client, engineer.email, "engineer-password")

    response = client.post(
        "/api/admin/source-roots",
        json={"path": str(source), "label": "Sources"},
    )

    assert response.status_code == 403


def test_admin_updates_source_root_metadata_but_cannot_change_path(
    client,
    user_factory,
    api_context,
    tmp_path,
):
    _, session_factory = api_context
    admin = user_factory(
        email="admin@example.test",
        password="admin-password",
        role="admin",
    )
    root = create_root(session_factory, user=admin, path=tmp_path / "source", label="Old")
    login(client, admin.email, "admin-password")

    response = client.patch(
        f"/api/admin/source-roots/{root.id}",
        json={"label": "New", "description": "Updated", "is_active": False},
    )

    assert response.status_code == 200
    assert response.json()["label"] == "New"
    assert response.json()["is_active"] is False
    invalid = client.patch(
        f"/api/admin/source-roots/{root.id}",
        json={"path": str(tmp_path / "other")},
    )
    assert invalid.status_code == 422


def test_tree_returns_direct_supported_entries_with_relative_paths(
    client,
    user_factory,
    api_context,
    tmp_path,
):
    _, session_factory = api_context
    engineer = user_factory(email="engineer@example.test", password="engineer-password")
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "inside.jpg").write_bytes(b"not inspected during browsing")
    (source / "image.JPG").write_bytes(b"image")
    (source / "labels.json").write_text("{}", encoding="utf-8")
    (source / "export.ZIP").write_bytes(b"zip")
    (source / "notes.txt").write_text("ignored", encoding="utf-8")
    root = create_root(session_factory, user=engineer, path=source, label="Sources")
    login(client, engineer.email, "engineer-password")

    response = client.get(f"/api/source-roots/{root.id}/tree", params={"path": ""})

    assert response.status_code == 200
    assert response.json() == {
        "path": "",
        "entries": [
            {"name": "nested", "path": "nested", "type": "dir"},
            {"name": "export.ZIP", "path": "export.ZIP", "type": "file"},
            {"name": "image.JPG", "path": "image.JPG", "type": "file"},
            {"name": "labels.json", "path": "labels.json", "type": "file"},
        ],
    }

    nested = client.get(
        f"/api/source-roots/{root.id}/tree",
        params={"path": "nested"},
    )
    assert nested.status_code == 200
    assert nested.json()["entries"] == [
        {"name": "inside.jpg", "path": "nested/inside.jpg", "type": "file"}
    ]


def test_tree_rejects_traversal_symlink_and_inactive_root(
    client,
    user_factory,
    api_context,
    tmp_path,
):
    _, session_factory = api_context
    engineer = user_factory(email="engineer@example.test", password="engineer-password")
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (source / "escape").symlink_to(outside, target_is_directory=True)
    root = create_root(session_factory, user=engineer, path=source, label="Sources")
    inactive = create_root(
        session_factory,
        user=engineer,
        path=tmp_path / "inactive",
        label="Inactive",
        is_active=False,
    )
    login(client, engineer.email, "engineer-password")

    traversal = client.get(
        f"/api/source-roots/{root.id}/tree",
        params={"path": "../outside"},
    )
    symlink = client.get(
        f"/api/source-roots/{root.id}/tree",
        params={"path": "escape"},
    )
    hidden = client.get(f"/api/source-roots/{inactive.id}/tree")

    assert traversal.status_code == 400
    assert symlink.status_code == 400
    assert hidden.status_code == 404
