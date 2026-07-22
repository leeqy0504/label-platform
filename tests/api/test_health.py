from fastapi.testclient import TestClient

from label_platform.api.app import create_app
from label_platform.config import Settings


def test_health_reports_service_ready(tmp_path):
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/15",
        managed_data_root=tmp_path / "managed",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "label-platform-api"}
