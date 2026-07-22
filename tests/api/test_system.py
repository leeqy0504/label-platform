def test_system_configuration_is_public(client):
    response = client.get("/api/admin/system-config")
    assert response.status_code == 200
    assert isinstance(response.json()["label_studio"]["api_key_configured"], bool)
    assert "token" not in response.text.lower()


def test_authentication_and_user_management_routes_are_removed(client):
    assert client.get("/api/auth/me").status_code == 404
    assert client.get("/api/admin/users").status_code == 404
