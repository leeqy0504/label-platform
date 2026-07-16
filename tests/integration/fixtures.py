from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from label_platform.api.app import create_app
from label_platform.auth.passwords import hash_password
from label_platform.config import Settings
from label_platform.db.base import Base
from label_platform.db.models import AllowedRoot, User
from label_platform.db.session import create_session_factory
from label_platform.domain.enums import UserRole


@dataclass(frozen=True)
class IntegrationContext:
    client: TestClient
    redis: Redis
    source_root: Path
    managed_root: Path
    root_id: str

    def run_queued_jobs(self) -> None:
        SimpleWorker(
            [Queue("dataset-operations", connection=self.redis)],
            connection=self.redis,
        ).work(burst=True, with_scheduler=False)


@pytest.fixture(scope="session")
def integration_database_url() -> str:
    return os.getenv(
        "PLATFORM_INTEGRATION_DATABASE_URL",
        "postgresql+psycopg://platform:platform-dev-password@127.0.0.1:5432/platform",
    )


@pytest.fixture(scope="session")
def integration_redis_url() -> str:
    return os.getenv("PLATFORM_INTEGRATION_REDIS_URL", "redis://127.0.0.1:6379/15")


@pytest.fixture(scope="session")
def integration_engine(integration_database_url: str) -> Iterator[Engine]:
    engine = create_engine(integration_database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:
        engine.dispose()
        pytest.fail(f"PostgreSQL integration database is unavailable: {exc}")

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", integration_database_url)
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def integration_context(
    integration_engine: Engine,
    integration_redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[IntegrationContext]:
    session_factory = create_session_factory(integration_engine)
    _clear_platform_database(session_factory)

    redis = Redis.from_url(integration_redis_url)
    try:
        redis.ping()
    except Exception as exc:
        pytest.fail(f"Redis integration service is unavailable: {exc}")
    redis.flushdb()

    source_root = tmp_path / "sources"
    source_root.mkdir()
    managed_root = tmp_path / "managed"
    settings = Settings(
        database_url=integration_engine.url.render_as_string(hide_password=False),
        redis_url=integration_redis_url,
        managed_data_root=managed_root,
        session_secret="integration-secret-with-at-least-32-characters",
        environment="test",
    )
    monkeypatch.setenv("PLATFORM_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("PLATFORM_REDIS_URL", settings.redis_url)
    monkeypatch.setenv("PLATFORM_MANAGED_DATA_ROOT", str(settings.managed_data_root))
    monkeypatch.setenv("PLATFORM_SESSION_SECRET", settings.session_secret)
    monkeypatch.setenv("PLATFORM_ENVIRONMENT", settings.environment)

    root_id = _seed_account_and_root(session_factory, source_root)
    app = create_app(settings)
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "engineer@example.test", "password": "correct-horse"},
        )
        assert login.status_code == 200
        yield IntegrationContext(
            client=client,
            redis=redis,
            source_root=source_root,
            managed_root=managed_root,
            root_id=root_id,
        )

    redis.flushdb()
    _clear_platform_database(session_factory)


def _seed_account_and_root(session_factory: sessionmaker[Session], source_root: Path) -> str:
    with session_factory() as session, session.begin():
        user = User(
            email="engineer@example.test",
            name="Dataset Engineer",
            password_hash=hash_password("correct-horse"),
            role=UserRole.DATA_ENGINEER,
        )
        session.add(user)
        session.flush()
        root = AllowedRoot(
            path=str(source_root),
            label="Integration sources",
            created_by_id=user.id,
        )
        session.add(root)
        session.flush()
        return root.id


def _clear_platform_database(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session, session.begin():
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
