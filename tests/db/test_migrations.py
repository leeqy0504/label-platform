from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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
    "users",
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

    command.downgrade(config, "base")
    assert not (CORE_TABLES & set(inspect(engine).get_table_names()))

    command.upgrade(config, "head")
    assert CORE_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()
