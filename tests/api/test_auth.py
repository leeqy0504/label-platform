from fastapi.testclient import TestClient


def login(client: TestClient, email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_sets_http_only_session_cookie(client, user_factory):
    user_factory(email="engineer@example.test", password="correct-horse")

    response = login(client, "engineer@example.test", "correct-horse")

    assert response.status_code == 200
    assert response.json()["role"] == "data_engineer"
    cookie = response.headers["set-cookie"]
    assert "platform_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie


def test_login_rejects_wrong_password(client, user_factory):
    user_factory(email="engineer@example.test", password="correct-horse")

    response = login(client, "engineer@example.test", "wrong-password")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_current_user_rejects_inactive_account(client, user_factory):
    user_factory(
        email="inactive@example.test",
        password="correct-horse",
        is_active=False,
    )

    response = login(client, "inactive@example.test", "correct-horse")

    assert response.status_code == 401


def test_logout_clears_session(authenticated_client):
    response = authenticated_client.post("/api/auth/logout")

    assert response.status_code == 204
    assert "platform_session=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert authenticated_client.get("/api/auth/me").status_code == 401


def test_current_user_rejects_invalid_cookie(client):
    client.cookies.set("platform_session", "not-a-signed-session")

    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_data_engineer_cannot_call_admin_probe(authenticated_client):
    response = authenticated_client.get("/api/auth/admin-probe")
    assert response.status_code == 403


def test_admin_can_call_admin_probe(client, user_factory):
    user_factory(
        email="admin@example.test",
        password="admin-password",
        role="admin",
    )
    assert login(client, "admin@example.test", "admin-password").status_code == 200

    response = client.get("/api/auth/admin-probe")

    assert response.status_code == 200
    assert response.json() == {"admin": True}


def test_current_user_rejects_expired_cookie(client, user_factory, api_context):
    settings, _ = api_context
    user_factory(email="engineer@example.test", password="correct-horse")
    assert login(client, "engineer@example.test", "correct-horse").status_code == 200
    settings.session_max_age_seconds = -1

    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_current_user_rejects_deleted_account(client, user_factory, api_context):
    _, session_factory = api_context
    user = user_factory(email="engineer@example.test", password="correct-horse")
    assert login(client, "engineer@example.test", "correct-horse").status_code == 200
    with session_factory() as session:
        session.delete(session.get(type(user), user.id))
        session.commit()

    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_admin_creates_normalized_user_without_exposing_hash(client, user_factory):
    user_factory(
        email="admin@example.test",
        password="admin-password",
        role="admin",
        name="Administrator",
    )
    assert login(client, "admin@example.test", "admin-password").status_code == 200

    response = client.post(
        "/api/admin/users",
        json={
            "email": "  Engineer@Example.Test ",
            "name": "Dataset Engineer",
            "password": "initial-password",
            "role": "data_engineer",
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == "engineer@example.test"
    assert "password_hash" not in response.json()


def test_admin_lists_users_without_exposing_hash(client, user_factory):
    user_factory(
        email="admin@example.test",
        password="admin-password",
        role="admin",
        name="Administrator",
    )
    user_factory(
        email="reviewer@example.test",
        password="review-password",
        role="reviewer",
        name="Reviewer",
    )
    assert login(client, "admin@example.test", "admin-password").status_code == 200

    response = client.get("/api/admin/users")

    assert response.status_code == 200
    assert [user["email"] for user in response.json()] == [
        "admin@example.test",
        "reviewer@example.test",
    ]
    assert all("password_hash" not in user for user in response.json())


def test_admin_cannot_deactivate_last_active_admin(client, user_factory):
    admin = user_factory(
        email="admin@example.test",
        password="admin-password",
        role="admin",
        name="Administrator",
    )
    assert login(client, "admin@example.test", "admin-password").status_code == 200

    response = client.patch(f"/api/admin/users/{admin.id}", json={"is_active": False})

    assert response.status_code == 409
    assert response.json()["detail"] == "At least one active administrator is required"
