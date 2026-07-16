from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from label_platform.api.app import create_app
from label_platform.config import Settings
from label_platform.db.base import Base
from label_platform.db.models import AllowedRoot, User
from label_platform.db.session import create_engine_from_settings, create_session_factory
from label_platform.domain.enums import UserRole


@pytest.fixture
def db_session(tmp_path) -> Iterator[Session]:
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        managed_data_root=tmp_path / "managed",
        session_secret="test-secret-with-at-least-32-characters",
    )
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)
    session = create_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def user(db_session: Session) -> User:
    account = User(
        email="engineer@example.test",
        name="Dataset Engineer",
        password_hash="test-password-hash",
        role=UserRole.DATA_ENGINEER,
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture
def allowed_root(db_session: Session, user: User, tmp_path) -> AllowedRoot:
    root_path = tmp_path / "sources"
    root_path.mkdir()
    root = AllowedRoot(
        path=str(root_path),
        label="Test sources",
        created_by_id=user.id,
    )
    db_session.add(root)
    db_session.commit()
    return root


@pytest.fixture
def api_context(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}",
        managed_data_root=tmp_path / "managed",
        session_secret="test-secret-with-at-least-32-characters",
        environment="test",
    )
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    try:
        yield settings, session_factory
    finally:
        engine.dispose()


@pytest.fixture
def client(api_context) -> Iterator[TestClient]:
    settings, session_factory = api_context
    app = create_app(settings)
    app.state.session_factory = session_factory
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_factory(api_context) -> Callable[..., User]:
    _, session_factory = api_context
    password_hash = PasswordHash.recommended()

    def create_user(
        *,
        email: str,
        password: str,
        role: str = "data_engineer",
        is_active: bool = True,
        name: str = "Test User",
    ) -> User:
        with session_factory() as session:
            account = User(
                email=email,
                name=name,
                password_hash=password_hash.hash(password),
                role=UserRole(role),
                is_active=is_active,
            )
            session.add(account)
            session.commit()
            session.refresh(account)
            session.expunge(account)
            return account

    return create_user


@pytest.fixture
def authenticated_client(client: TestClient, user_factory) -> TestClient:
    user_factory(email="engineer@example.test", password="correct-horse")
    response = client.post(
        "/api/auth/login",
        json={"email": "engineer@example.test", "password": "correct-horse"},
    )
    assert response.status_code == 200
    return client
