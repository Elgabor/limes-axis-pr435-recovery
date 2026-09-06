import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


@pytest.fixture
def migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/0065_data_asset_observation_tenant_asset_index.py"
    )
    spec = importlib.util.spec_from_file_location("observation_index_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("direction,statement", [
    ("upgrade", "CREATE INDEX CONCURRENTLY"),
    ("downgrade", "DROP INDEX CONCURRENTLY"),
])
def test_postgres_index_ddl_runs_outside_a_transaction(
    migration, monkeypatch, direction, statement,
) -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    with context.begin_transaction():
        getattr(migration, direction)()
    sql = output.getvalue()
    assert statement in sql
    before, after = sql.split(statement, 1)
    assert before.rstrip().endswith("COMMIT;")
    assert "BEGIN;" in after


def test_index_upgrade_and_downgrade_preserve_observations(migration, monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite://")
    try:
        with engine.connect() as connection:
            connection.execute(text(
                "CREATE TABLE data_asset_resource_observations "
                "(id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, asset_id TEXT NOT NULL)"
            ))
            connection.execute(text(
                "INSERT INTO data_asset_resource_observations VALUES (1, 'tenant-a', 'asset-a')"
            ))
            connection.commit()
            context = MigrationContext.configure(connection)
            monkeypatch.setattr(migration, "op", Operations(context))
            with context.begin_transaction():
                migration.upgrade()
            indexes = inspect(connection).get_indexes(migration.TABLE_NAME)
            assert any(
                item["name"] == migration.INDEX_NAME
                and item["column_names"] == ["tenant_id", "asset_id"]
                for item in indexes
            )
            connection.commit()
            with context.begin_transaction():
                migration.downgrade()
            assert not inspect(connection).get_indexes(migration.TABLE_NAME)
            assert connection.execute(text(
                "SELECT id, tenant_id, asset_id FROM data_asset_resource_observations"
            )).all() == [(1, "tenant-a", "asset-a")]
    finally:
        engine.dispose()
