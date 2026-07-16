from label_platform.cli import main
from label_platform.config import Settings
from label_platform.db.base import Base
from label_platform.db.models import User
from label_platform.db.session import create_engine_from_settings, create_session_factory
from label_platform.domain.enums import UserRole


def test_create_admin_command_creates_active_administrator(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("PLATFORM_DATABASE_URL", database_url)
    monkeypatch.setenv("PLATFORM_SESSION_SECRET", "test-secret-with-at-least-32-characters")
    passwords = iter(["admin-password", "admin-password"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    settings = Settings()
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)

    exit_code = main(
        [
            "create-admin",
            "--email",
            "Admin@Example.Test",
            "--name",
            "Administrator",
        ]
    )

    with create_session_factory(engine)() as session:
        user = session.query(User).one()
        assert user.email == "admin@example.test"
        assert user.role is UserRole.ADMIN
        assert user.is_active is True
    engine.dispose()
    assert exit_code == 0


def test_create_admin_command_rejects_password_mismatch(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'mismatch.db'}"
    monkeypatch.setenv("PLATFORM_DATABASE_URL", database_url)
    monkeypatch.setenv("PLATFORM_SESSION_SECRET", "test-secret-with-at-least-32-characters")
    passwords = iter(["admin-password", "different-password"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    settings = Settings()
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)

    exit_code = main(
        [
            "create-admin",
            "--email",
            "admin@example.test",
            "--name",
            "Administrator",
        ]
    )

    with create_session_factory(engine)() as session:
        assert session.query(User).count() == 0
    engine.dispose()
    assert exit_code == 2
