def test_admin_manages_users_roots_connectors_and_audit_log(
    client,
    user_factory,
    tmp_path,
):
    admin = user_factory(
        email="admin@example.test",
        password="admin-password",
        role="admin",
        name="Administrator",
    )
    login = client.post(
        "/api/auth/login",
        json={"email": admin.email, "password": "admin-password"},
    )
    assert login.status_code == 200

    system = client.get("/api/admin/system-config")
    assert system.status_code == 200
    assert system.json()["label_studio"]["api_key_configured"] is False
    assert "token" not in system.text.lower()

    created = client.post(
        "/api/admin/users",
        json={
            "email": "reviewer@example.test",
            "name": "Reviewer",
            "password": "review-password",
            "role": "reviewer",
        },
    )
    assert created.status_code == 201
    updated = client.patch(
        f"/api/admin/users/{created.json()['id']}",
        json={"is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False

    root_path = tmp_path / "admin-source"
    root_path.mkdir()
    root = client.post(
        "/api/admin/source-roots",
        json={"path": str(root_path), "label": "Admin source", "description": ""},
    )
    assert root.status_code == 201
    disabled = client.patch(
        f"/api/admin/source-roots/{root.json()['id']}",
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    audit = client.get("/api/admin/audit-events")
    assert audit.status_code == 200
    actions = {event["action"] for event in audit.json()["data"]}
    assert {"user.created", "user.updated", "source_root.created", "source_root.updated"} <= actions
