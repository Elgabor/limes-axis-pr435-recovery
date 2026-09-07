"""Full migration chain and P4 data-preservation proof in a dedicated test database."""

import os
from uuid import uuid4

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.skipif(
    os.environ.get("LIMES_ISOLATED_POSTGRES_PORT") is None,
    reason="Requires the dedicated synthetic loopback PostgreSQL container",
)


def test_schema_migration_preserves_legacy_bindings_and_refuses_lossy_downgrade():
    port = int(os.environ["LIMES_ISOLATED_POSTGRES_PORT"])
    database = "schema_proof_" + uuid4().hex
    admin = create_engine(
        f"postgresql+psycopg://postgres@127.0.0.1:{port}/axis_connector_test",
        isolation_level="AUTOCOMMIT",
    )
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {database}"))
        url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/{database}"
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        upgrade(config, "0064_connector_source_batch_exports")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO connector_source_bindings
                (id, tenant_id, connector_id, asset_id, binding_id, connection_profile_id,
                resource_name, schema_fingerprint, credential_lease_id, egress_policy_id,
                status, ingestion_status, activated_by, activation_reason, audit_event_id,
                audit_event_type, activated_at)
                VALUES (:id, 'synthetic_tenant', 'synthetic_connector', 'synthetic_asset',
                'legacy_binding', 'synthetic_profile', 'synthetic.orders', :fingerprint,
                'synthetic_lease', 'synthetic_policy', 'active', 'pending_ingestion',
                'test', 'migration proof', :audit, 'connector.source.bindings.activated', now())
                """),
                {"id": uuid4(), "fingerprint": "a" * 64, "audit": uuid4()},
            )
        upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT binding_id, schema_fingerprint, schema_fingerprint_version, status "
                    "FROM connector_source_bindings"
                )
            ).one()
            assert tuple(row) == ("legacy_binding", "a" * 64, "column_names_v1", "active")
        downgrade(config, "0064_connector_source_batch_exports")
        upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text("UPDATE connector_source_bindings SET status='superseded'"))
        with pytest.raises(RuntimeError, match="superseded binding history"):
            downgrade(config, "0064_connector_source_batch_exports")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT status FROM connector_source_bindings")
                ).scalar_one()
                == "superseded"
            )
    finally:
        if engine is not None:
            engine.dispose()
        admin.dispose()
