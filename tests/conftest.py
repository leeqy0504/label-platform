from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from label_platform.api.app import create_app
from label_platform.config import Settings
from label_platform.db.base import Base
from label_platform.db.models import AllowedRoot
from label_platform.db.session import create_engine_from_settings, create_session_factory

pytest_plugins = ["tests.integration.fixtures"]



@pytest.fixture
def image_factory() -> Callable[..., Path]:
    def create_image(
        path: Path,
        *,
        size: tuple[int, int] = (32, 24),
        image_format: str | None = None,
        orientation: int | None = None,
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", size, color=(120, 80, 40))
        exif = Image.Exif()
        if orientation is not None:
            exif[274] = orientation
        image.save(path, format=image_format, exif=exif)
        return path

    return create_image


@pytest.fixture
def db_session(tmp_path) -> Iterator[Session]:
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        managed_data_root=tmp_path / "managed",
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
def allowed_root(db_session: Session, tmp_path) -> AllowedRoot:
    root_path = tmp_path / "sources"
    root_path.mkdir()
    root = AllowedRoot(
        path=str(root_path),
        label="Test sources",
    )
    db_session.add(root)
    db_session.commit()
    return root


@pytest.fixture
def api_context(tmp_path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}",
        managed_data_root=tmp_path / "managed",
        label_studio_export_root=tmp_path / "labelstudio-exports",
        unitrain_export_root=tmp_path / "unitrain-exports",
        unitrain_mount_root=tmp_path / "unitrain-exports",
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
