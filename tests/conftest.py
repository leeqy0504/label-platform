from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

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
