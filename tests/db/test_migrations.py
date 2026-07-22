from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


CORE_TABLES = {
    "allowed_roots",
    "audit_events",
    "background_jobs",
    "dataset_items",
    "dataset_sources",
    "dataset_versions",
    "datasets",
    "review_sessions",
    "review_task_bindings",
    "training_runs",
}


def test_initial_migration_round_trip(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert CORE_TABLES <= set(inspect(engine).get_table_names())
    assert "category_counts" in {
        column["name"] for column in inspect(engine).get_columns("dataset_versions")
    }
    assert "annotation_count" in {
        column["name"] for column in inspect(engine).get_columns("dataset_items")
    }
    for table, column in (
        ("allowed_roots", "created_by_id"),
        ("datasets", "created_by_id"),
        ("dataset_versions", "created_by_id"),
        ("background_jobs", "created_by_id"),
        ("audit_events", "actor_user_id"),
        ("audit_events", "ip_address"),
        ("review_sessions", "created_by_id"),
        ("training_runs", "created_by_id"),
    ):
        assert column not in {item["name"] for item in inspect(engine).get_columns(table)}

    command.downgrade(config, "base")
    assert not (CORE_TABLES & set(inspect(engine).get_table_names()))

    command.upgrade(config, "head")
    assert CORE_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_upgrade_from_authenticated_schema_preserves_business_rows(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(database_url)
    identity_columns = {
        "allowed_roots": "created_by_id",
        "datasets": "created_by_id",
        "dataset_versions": "created_by_id",
        "background_jobs": "created_by_id",
        "audit_events": "actor_user_id",
        "review_sessions": "created_by_id",
        "training_runs": "created_by_id",
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "id VARCHAR(36) PRIMARY KEY, email VARCHAR(320) NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO users (id, email) VALUES ('user-1', 'legacy@example.test')")
        )
        for table_name, identity_column in identity_columns.items():
            extra_column = ", ip_address VARCHAR(45)" if table_name == "audit_events" else ""
            connection.execute(
                text(
                    f"CREATE TABLE {table_name} ("
                    f"id VARCHAR(36) PRIMARY KEY, payload VARCHAR(100) NOT NULL, "
                    f"{identity_column} VARCHAR(36){extra_column})"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {table_name} "
                    f"(id, payload, {identity_column}) "
                    f"VALUES ('{table_name}-1', 'keep-me', 'user-1')"
                )
            )
        connection.execute(
            text("CREATE INDEX ix_audit_events_actor_user_id ON audit_events (actor_user_id)")
        )

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.stamp(config, "0004_training_runs")
    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "users" not in inspector.get_table_names()
    with engine.connect() as connection:
        for table_name, identity_column in identity_columns.items():
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            assert identity_column not in columns
            assert connection.scalar(text(f"SELECT payload FROM {table_name}")) == "keep-me"
        assert "ip_address" not in {
            column["name"] for column in inspector.get_columns("audit_events")
        }
    engine.dispose()
