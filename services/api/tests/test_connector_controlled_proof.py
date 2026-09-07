"""P5: synthetic PostgreSQL source -> discovery -> selection -> durable raw output.

Opt-in loopback container only. Roles, databases and datasets are created for this
proof; no configured credentials, shared schemas, graph service or remote data.
"""

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from uuid import uuid4

import psycopg
import pytest
import test_connector_source_extraction as f
from psycopg import sql
from test_connector_raw_postgres import session_factory as _postgres_factory

from axis_api.connector_execution import postgres_endpoint_target_sha256
from axis_api.connector_postgres_discovery import (
    ConnectorSourceDiscoveryRequest,
    SelfHostedPostgresDiscoveryRuntime,
    postgres_discovery_profile_from_settings,
    record_connector_source_discovery,
)
from axis_api.connector_source_activation import (
    ConnectorSourceActivationRequest,
    record_connector_source_activation,
)
from axis_api.connector_source_ingestion import (
    ConnectorSourceIngestionSubmission,
    ObservationFreshnessIngestionRuntime,
    SourceIngestionOutboxDispatcher,
    record_connector_source_ingestion_request,
)
from axis_api.db import session_scope
from axis_api.object_storage import LocalObjectStore
from axis_api.persistence import AxisPersistenceRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("LIMES_ISOLATED_POSTGRES_PORT") is None,
    reason="Requires the explicitly authorized dedicated PostgreSQL container",
)


@pytest.fixture
def session_factory(monkeypatch):
    yield from _postgres_factory.__wrapped__(monkeypatch)


@dataclass
class Source:
    connection: psycopg.Connection
    read_dsn: str
    reader: str


@pytest.fixture
def source():
    port = int(os.environ["LIMES_ISOLATED_POSTGRES_PORT"])
    suffix = uuid4().hex
    database, reader = "source_proof_" + suffix, "source_reader_" + suffix
    with psycopg.connect(
        f"postgresql://postgres@127.0.0.1:{port}/axis_connector_test", autocommit=True
    ) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(reader)))
    with psycopg.connect(
        f"postgresql://postgres@127.0.0.1:{port}/{database}", autocommit=True
    ) as connection:
        connection.execute("CREATE SCHEMA operations")
        connection.execute(
            "CREATE TABLE operations.production_orders "
            "(order_id text PRIMARY KEY, amount numeric(10,2), note text)"
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO operations.production_orders VALUES (%s,%s,%s)",
                [(f"L{i}", i * 10, f"RAW_CANARY_{i}") for i in range(1, 6)],
            )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA operations TO {}").format(sql.Identifier(reader))
        )
        connection.execute(
            sql.SQL("GRANT SELECT ON operations.production_orders TO {}").format(
                sql.Identifier(reader)
            )
        )
        yield Source(connection, f"postgresql://{reader}@127.0.0.1:{port}/{database}", reader)


class Pilot:
    def __init__(self, factory, source, root, max_rows=10):
        self.factory, self.source, self.root = factory, source, root
        self.settings = f.both_gates(
            external_db_live_query_dsn=source.read_dsn,
            external_db_live_query_private_endpoint_ref=f"private-endpoint://{f.TENANT_A}/persisted-operations-postgres-readonly",
            external_db_runtime_egress_enforcement_enabled=True,
            source_ingestion_extraction_page_size=2,
            source_ingestion_extraction_max_rows=max_rows,
        )
        with session_scope(factory) as session:
            policy = AxisPersistenceRepository(session).get_connector_egress_policy(
                f.TENANT_A, f.POLICY_ID
            )
            policy.policy_document = {
                "approved_endpoint_target_sha256": postgres_endpoint_target_sha256(source.read_dsn)
            }
        self.runtime = f.make_runtime(factory, self.settings, LocalObjectStore(root))

    def discover_and_activate(self, binding_id="pilot_binding_1", predecessor=None):
        discovery_runtime = SelfHostedPostgresDiscoveryRuntime(
            profile=postgres_discovery_profile_from_settings(self.settings),
            runtime_egress_enforcement_enabled=True,
        )
        with session_scope(self.factory) as session:
            repo = AxisPersistenceRepository(session)
            result = record_connector_source_discovery(
                repo,
                runtime=discovery_runtime,
                request=ConnectorSourceDiscoveryRequest(
                    tenant_id=f.TENANT_A,
                    connector_id=f.CONNECTOR_ID,
                    discovery_id="pilot_discovery",
                    requested_by="synthetic_operator",
                    connection_profile_id=f.PROFILE_ID,
                    schema_name="operations",
                    credential_lease_id=f.LEASE_ID,
                    egress_policy_id=f.POLICY_ID,
                ),
                principal_scopes=["connectors:source:discover"],
            )
            assert result.result.status == "discovery_completed", result.result.block_reason
            table = result.result.tables[0]
            assert table.schema_fingerprint_version == "postgres_schema_v2"
            assert not table.columns_truncated
            record_connector_source_activation(
                repo,
                request=ConnectorSourceActivationRequest(
                    tenant_id=f.TENANT_A,
                    connector_id=f.CONNECTOR_ID,
                    activation_id="pilot_activation",
                    requested_by="synthetic_operator",
                    connection_profile_id=f.PROFILE_ID,
                    credential_lease_id=f.LEASE_ID,
                    egress_policy_id=f.POLICY_ID,
                    activation_reason="Review synthetic source schema",
                    selections=[
                        {
                            "binding_id": binding_id,
                            "resource_name": f.RESOURCE,
                            "expected_schema_fingerprint": table.column_fingerprint,
                            "expected_schema_fingerprint_version": table.schema_fingerprint_version,
                            "supersedes_binding_id": predecessor,
                        }
                    ],
                ),
                principal_scopes=["connectors:source:activate"],
                max_selections=10,
            )
        return binding_id

    def submit(self, request_id, binding="pilot_binding_1", stage="extract"):
        with session_scope(self.factory) as session:
            return record_connector_source_ingestion_request(
                AxisPersistenceRepository(session),
                submission=ConnectorSourceIngestionSubmission(
                    tenant_id=f.TENANT_A,
                    connector_id=f.CONNECTOR_ID,
                    request_id=request_id,
                    requested_by="synthetic_operator",
                    reason="Controlled source proof",
                    stage=stage,
                    selections=[{"binding_id": binding}],
                ),
                principal_scopes=["connectors:source:ingest"],
                max_selections=10,
                settings=self.settings,
            )

    def run(self):
        dispatcher = SourceIngestionOutboxDispatcher(
            settings=self.settings,
            session_factory=self.factory,
            runtime=ObservationFreshnessIngestionRuntime(),
            extraction_runtime=self.runtime,
        )
        return asyncio.run(dispatcher.run_once())

    def payload(self, request_id):
        with session_scope(self.factory) as session:
            repo = AxisPersistenceRepository(session)
            batches = repo.get_connector_source_ingestion_request_batches(
                f.TENANT_A, request_id, limit=10
            )
            assert len(batches) == 1
            batch = batches[0]
            data = (self.root / batch.storage_key).read_bytes()
            assert hashlib.sha256(data).hexdigest() == batch.digest_sha256
            request = repo.get_connector_source_ingestion_request(f.TENANT_A, request_id)
            assert "RAW_CANARY" not in json.dumps(request.evidence)
            for event in repo.list_audit_events(f.TENANT_A):
                assert "RAW_CANARY" not in json.dumps(event.payload)
            return batch, json.loads(data)


@pytest.mark.parametrize("max_rows", [3, 10])
def test_real_readonly_source_paging_caps_replay_and_new_snapshot(
    session_factory, source, tmp_path, max_rows
):
    pilot = Pilot(session_factory, source, tmp_path, max_rows)
    pilot.discover_and_activate()
    pilot.submit("pilot_first")
    assert pilot.run().completed == 1
    batch, payload = pilot.payload("pilot_first")
    assert payload["row_count"] == min(max_rows, 5)
    assert payload["ordering_mode"] == "primary_key"
    assert payload["truncated"] == (max_rows == 3)
    assert payload["limit_reason"] == ("row_limit" if max_rows == 3 else None)
    first_bytes = (tmp_path / batch.storage_key).read_bytes()
    assert pilot.submit("pilot_first").outcome == "replayed"
    assert pilot.run().claimed == 0
    source.connection.execute(
        "UPDATE operations.production_orders SET amount=200 WHERE order_id='L2'"
    )
    source.connection.execute(
        "INSERT INTO operations.production_orders VALUES ('L6',60,'RAW_CANARY_6')"
    )
    pilot.submit("pilot_second")
    assert pilot.run().completed == 1
    new_batch, updated = pilot.payload("pilot_second")
    assert updated["row_count"] == min(max_rows, 6)
    assert str(updated["rows"][1]["amount"]) == "200.00"
    assert new_batch.storage_key != batch.storage_key
    assert (tmp_path / batch.storage_key).read_bytes() == first_bytes
    with psycopg.connect(source.read_dsn) as read_connection:
        assert read_connection.execute(
            "SELECT has_table_privilege(current_user, 'operations.production_orders', 'INSERT')"
        ).fetchone() == (False,)


@pytest.mark.parametrize("change", ["type", "name", "key"])
def test_real_drift_requires_reviewed_successor(session_factory, source, tmp_path, change):
    pilot = Pilot(session_factory, source, tmp_path)
    pilot.discover_and_activate()
    pilot.submit("pilot_stale")
    source.connection.execute(
        {
            "type": (
                "ALTER TABLE operations.production_orders ALTER COLUMN amount TYPE numeric(12,2)"
            ),
            "name": "ALTER TABLE operations.production_orders RENAME COLUMN note TO source_note",
            "key": (
                "ALTER TABLE operations.production_orders DROP CONSTRAINT production_orders_pkey"
            ),
        }[change]
    )
    assert pilot.run().dead_lettered == 1
    with session_scope(session_factory) as session:
        request = AxisPersistenceRepository(session).get_connector_source_ingestion_request(
            f.TENANT_A, "pilot_stale"
        )
        assert request.last_error == "source_schema_drift"
        assert request.evidence["source_dial_performed"] is True
        assert request.evidence["extraction_performed"] is False
    assert list(tmp_path.rglob("*.json")) == []
    pilot.discover_and_activate("pilot_binding_2", "pilot_binding_1")
    pilot.submit("pilot_reviewed", "pilot_binding_2")
    assert pilot.run().completed == 1
    _, payload = pilot.payload("pilot_reviewed")
    assert payload["row_count"] == 5
    if change == "key":
        assert payload["ordering_mode"] == "none"
        assert payload["cursor_watermark"] is None


@pytest.mark.parametrize("gate", ["axis_revoked", "source_denied", "validate_only"])
def test_real_gate_and_validation_facts(session_factory, source, tmp_path, gate):
    from datetime import UTC, datetime, timedelta

    pilot = Pilot(session_factory, source, tmp_path)
    pilot.discover_and_activate()
    pilot.submit("pilot_gate", stage="validate" if gate == "validate_only" else "extract")
    if gate == "axis_revoked":
        with session_scope(session_factory) as session:
            lease = AxisPersistenceRepository(session).get_connector_credential_lease(
                f.TENANT_A, f.LEASE_ID
            )
            lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    if gate == "source_denied":
        source.connection.execute(
            sql.SQL("REVOKE SELECT ON operations.production_orders FROM {}").format(
                sql.Identifier(source.reader)
            )
        )
    result = pilot.run()
    assert result.completed == int(gate == "validate_only")
    assert result.dead_lettered == int(gate != "validate_only")
    with session_scope(session_factory) as session:
        request = AxisPersistenceRepository(session).get_connector_source_ingestion_request(
            f.TENANT_A, "pilot_gate"
        )
        assert request.evidence["source_dial_performed"] == (gate == "source_denied")
        assert request.evidence["extraction_performed"] is False
    assert list(tmp_path.rglob("*.json")) == []


def test_repeatable_read_keeps_pages_consistent_during_source_changes(
    session_factory,
    source,
    tmp_path,
    monkeypatch,
):
    pilot = Pilot(session_factory, source, tmp_path)
    pilot.discover_and_activate()
    pilot.submit("pilot_concurrent")
    pages = []
    original_connect = psycopg.connect

    class ObservePages(psycopg.Cursor):
        def fetchmany(self, size=0):
            rows = super().fetchmany(size)
            pages.append(len(rows))
            if len(pages) == 1:
                source.connection.execute(
                    "UPDATE operations.production_orders SET amount=999 WHERE order_id='L3'"
                )
                source.connection.execute(
                    "INSERT INTO operations.production_orders VALUES ('L6',60,'RAW_CANARY_6')"
                )
            return rows

    def connect(dsn="", **kwargs):
        if dsn == source.read_dsn:
            kwargs["cursor_factory"] = ObservePages
        return original_connect(dsn, **kwargs)

    monkeypatch.setattr(psycopg, "connect", connect)
    assert pilot.run().completed == 1
    _, payload = pilot.payload("pilot_concurrent")
    assert pages == [2, 2, 1]
    assert payload["row_count"] == 5
    assert str(payload["rows"][2]["amount"]) == "30.00"
    assert source.connection.execute(
        "SELECT count(*) FROM operations.production_orders"
    ).fetchone() == (6,)


def test_real_source_timeout_retries_without_advancing_output(session_factory, source, tmp_path):
    from datetime import UTC, datetime

    pilot = Pilot(session_factory, source, tmp_path)
    pilot.discover_and_activate()
    pilot.submit("pilot_timeout")
    pilot.runtime._profile = pilot.runtime._profile.model_copy(
        update={"statement_timeout_seconds": 1}
    )
    # Hold a synthetic DDL lock on this test table; reader's timeout must be safe.
    with source.connection.transaction():
        source.connection.execute(
            "LOCK TABLE operations.production_orders IN ACCESS EXCLUSIVE MODE"
        )
        assert pilot.run().retried == 1
    with session_scope(session_factory) as session:
        request = AxisPersistenceRepository(session).get_connector_source_ingestion_request(
            f.TENANT_A, "pilot_timeout"
        )
        assert request.last_error == "source_timeout"
        assert request.evidence["source_dial_performed"] is True
        assert request.evidence["extraction_performed"] is False
        request.available_at = datetime.now(UTC)
    assert list(tmp_path.rglob("*.json")) == []
    assert pilot.run().completed == 1
    _, payload = pilot.payload("pilot_timeout")
    assert payload["row_count"] == 5
