"""
Real-Postgres migration rehearsal for the lifecycle-event projection.

Proven here against the local Docker Postgres (gated behind
``AXIS_RUN_INTEGRATION=1``, like every integration lane):

- the full revision chain applies cleanly to a fresh database;
- upgrading a database that already holds pre-0061 connector manifests from
  ``0060_data_asset_contracts`` to head creates the projection without
  touching existing records, and those legacy manifests then read an honestly
  empty transition history through the normal detail path;
- the first post-upgrade governed transition projects exactly one row.

Every run uses throwaway databases created for the test and dropped in
``finally``; the developer's ``axis`` database is never migrated or deleted
here.
"""

import os
from uuid import uuid4

import pytest
from alembic.command import upgrade
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from axis_api.config import Settings
from axis_api.connector_manifests import (
    ConnectorManifestLifecycleRequest,
    get_connector_manifest_detail,
    record_demo_connector_manifest,
    transition_demo_connector_manifest_lifecycle,
)
from axis_api.db import session_scope
from axis_api.persistence import AxisPersistenceRepository


def _manifest_request_builder():
    """Load the shared manifest fixture builder from the unit-test module.

    Integration lanes collect under ``tests/integration`` without package
    imports, so the builder is loaded by path — the same pattern the unit
    suite uses to load migration modules.
    """
    import importlib.util
    from pathlib import Path

    module_path = Path(__file__).resolve().parents[1] / "test_connector_manifests.py"
    spec = importlib.util.spec_from_file_location(
        "axis_connector_manifest_fixtures",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.external_db_manifest_request


external_db_manifest_request = _manifest_request_builder()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AXIS_RUN_INTEGRATION") != "1",
        reason="set AXIS_RUN_INTEGRATION=1 with the local Docker runtime running",
    ),
]


def _server_dsn(database_dsn: str, database_name: str) -> str:
    """The DSN's own server pointed at ``database_name``."""
    scheme, rest = database_dsn.split("://", 1)
    server = rest.rsplit("/", 1)[0]
    return f"{scheme}://{server}/{database_name}"


def _maintenance_dsn(database_dsn: str) -> str:
    return _server_dsn(database_dsn, "postgres")


def _database_config(base_dsn: str, database_name: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        _server_dsn(base_dsn, database_name),
    )
    return config


def test_fresh_database_migrates_cleanly_to_head() -> None:
    settings = Settings()
    admin_engine = create_engine(
        _maintenance_dsn(settings.postgres_dsn),
        isolation_level="AUTOCOMMIT",
    )
    database_name = f"axis_migration_chain_{uuid4().hex}"
    engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        config = _database_config(settings.postgres_dsn, database_name)
        upgrade(config, "head")

        engine = create_engine(_server_dsn(settings.postgres_dsn, database_name))
        with engine.connect() as connection:
            applied_head = connection.execute(
                text("SELECT version_num FROM alembic_version"),
            ).scalar_one()
        expected_head = ScriptDirectory.from_config(config).get_current_head()
        assert applied_head == expected_head
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def test_upgrade_from_previous_revision_keeps_pre_projection_history_honest() -> None:
    settings = Settings()
    admin_engine = create_engine(
        _maintenance_dsn(settings.postgres_dsn),
        isolation_level="AUTOCOMMIT",
    )
    database_name = f"axis_migration_legacy_{uuid4().hex}"
    database_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        config = _database_config(settings.postgres_dsn, database_name)
        upgrade(config, "0060_data_asset_contracts")

        # Seed the exact shape a pre-0061 deployment has: persisted manifest
        # revisions and audit events, no lifecycle projection table at all.
        database_engine = create_engine(
            _server_dsn(settings.postgres_dsn, database_name),
        )
        factory = sessionmaker(
            bind=database_engine,
            autoflush=False,
            expire_on_commit=False,
        )
        with session_scope(factory) as session:
            record_demo_connector_manifest(
                AxisPersistenceRepository(session),
                external_db_manifest_request(),
            )

        upgrade(config, "head")

        with session_scope(factory) as session:
            repository = AxisPersistenceRepository(session)
            detail = get_connector_manifest_detail(
                repository,
                "tenant_demo_manufacturing",
                "external_db_shift_orders",
            )
            assert detail.current_revision.status == "registered_preview_only"
            assert detail.transitions == []

            transitioned = transition_demo_connector_manifest_lifecycle(
                repository,
                "external_db_shift_orders",
                ConnectorManifestLifecycleRequest(
                    tenant_id="tenant_demo_manufacturing",
                    transitioned_by="platform-connector-owner-role",
                    target_status="active_preview",
                    actor_scopes=["connectors:manifest:lifecycle"],
                    transition_reason="Post-upgrade governed activation.",
                    evidence_refs=["approval:migration-rehearsal"],
                ),
            )
            assert transitioned.status == "active_preview"

            upgraded_detail = get_connector_manifest_detail(
                repository,
                "tenant_demo_manufacturing",
                "external_db_shift_orders",
            )
        assert [transition.target_status for transition in upgraded_detail.transitions] == [
            "active_preview"
        ]
        assert len(upgraded_detail.transitions) == 1
    finally:
        if database_engine is not None:
            database_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()
