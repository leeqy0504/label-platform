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
    "users",
}


def test_initial_migration_round_trip(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert CORE_TABLES <= set(inspect(engine).get_table_names())

    command.downgrade(config, "base")
    assert not (CORE_TABLES & set(inspect(engine).get_table_names()))

    command.upgrade(config, "head")
    assert CORE_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()
