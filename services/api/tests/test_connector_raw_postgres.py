"""Opt-in PostgreSQL transaction proof. Only a dedicated synthetic database is allowed."""

import os
from uuid import uuid4

import pytest
import test_connector_source_extraction as fixtures
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.skipif(
    os.environ.get("LIMES_ISOLATED_POSTGRES_PORT") is None,
    reason="Requires explicitly provisioned loopback PostgreSQL test container",
)


@pytest.fixture
def session_factory(monkeypatch):
    port = int(os.environ["LIMES_ISOLATED_POSTGRES_PORT"])
    url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/axis_connector_test"
    schema = "raw_proof_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    import psycopg

    connect = psycopg.connect
    engine = create_engine(
        url,
        creator=lambda: connect(
            f"postgresql://postgres@127.0.0.1:{port}/axis_connector_test",
            options=f"-csearch_path={schema}",
        ),
    )
    create_tables = fixtures.Base.metadata.create_all
    tables = [
        table
        for table in fixtures.Base.metadata.sorted_tables
        if (
            table.name.startswith("connector_source_")
            or table.name
            in {
                "tenants",
                "audit_events",
                "connector_credential_leases",
                "connector_egress_policies",
                "data_asset_resource_observations",
                "data_asset_stewardship_records",
            }
        )
    ]
    monkeypatch.setattr(
        fixtures.Base.metadata, "create_all", lambda bind: create_tables(bind, tables=tables)
    )
    monkeypatch.setattr(fixtures, "create_engine", lambda *args, **kwargs: engine)
    try:
        yield from fixtures.session_factory.__wrapped__()
    finally:
        engine.dispose()
        admin.dispose()


def _interrupted_worker(port, schema, root, when):
    """Executed in a separate process; abrupt exit deliberately skips cleanup."""
    import asyncio

    from sqlalchemy.orm import sessionmaker

    from axis_api.config import Settings

    Settings.model_config["env_file"] = None
    from axis_api.connector_source_ingestion import (
        ObservationFreshnessIngestionRuntime,
        SourceIngestionOutboxDispatcher,
    )
    from axis_api.object_storage import LocalObjectStore

    engine = create_engine(
        f"postgresql+psycopg://postgres@127.0.0.1:{int(port)}/axis_connector_test",
        connect_args={"options": f"-csearch_path={schema}"},
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    class InterruptibleStore(LocalObjectStore):
        def put_json(self, key, payload):
            result = super().put_json(key, payload)
            if when == "before":
                os._exit(71)
            return result

    runtime = fixtures.make_runtime(factory, store=InterruptibleStore(root))
    runtime._read_bounded = lambda *a, **k: fixtures.bounded_result([{"id": 1}])
    dispatcher = SourceIngestionOutboxDispatcher(
        settings=fixtures.both_gates(),
        session_factory=factory,
        runtime=ObservationFreshnessIngestionRuntime(),
        extraction_runtime=runtime,
    )
    dispatcher._finalize_success = lambda *a: os._exit(72)
    asyncio.run(dispatcher.run_once())
    os._exit(73)


@pytest.mark.parametrize("when", ["before", "after"])
def test_process_exit_before_and_after_batch_commit(session_factory, tmp_path, when):
    import asyncio
    import subprocess
    import sys
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    from axis_api.connector_source_ingestion import (
        ObservationFreshnessIngestionRuntime,
        SourceIngestionOutboxDispatcher,
    )
    from axis_api.db import session_scope
    from axis_api.object_storage import LocalObjectStore
    from axis_api.persistence import AxisPersistenceRepository

    fixtures.seed_extract_request(session_factory)
    with session_factory.kw["bind"].connect() as connection:
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    api = Path(__file__).resolve().parents[1]
    child = (
        "import sys; sys.path[:0] = sys.argv[1:3]; "
        'from axis_api.config import Settings; Settings.model_config["env_file"] = None; '
        "from test_connector_raw_postgres import _interrupted_worker; "
        "_interrupted_worker(*sys.argv[3:])"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            str(api / "src"),
            str(api / "tests"),
            os.environ["LIMES_ISOLATED_POSTGRES_PORT"],
            schema,
            str(tmp_path),
            when,
        ],
        env={k: v for k, v in os.environ.items() if not k.startswith("AXIS_")},
        timeout=30,
        capture_output=True,
        text=True,
    )
    assert result.returncode == (71 if when == "before" else 72), result.stderr
    with session_scope(session_factory) as session:
        repo = AxisPersistenceRepository(session)
        assert len(
            repo.get_connector_source_ingestion_request_batches(
                fixtures.TENANT_A, "ingreq_e2e_extract", limit=10
            )
        ) == int(when == "after")
        request = repo.get_connector_source_ingestion_request(
            fixtures.TENANT_A, "ingreq_e2e_extract"
        )
        request.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert len(list(tmp_path.rglob("*.json"))) == 1
    reads = []
    runtime = fixtures.make_runtime(session_factory, store=LocalObjectStore(tmp_path))

    def read(*args, **kwargs):
        reads.append(1)
        return fixtures.bounded_result([{"id": 2}])

    runtime._read_bounded = read
    dispatcher = SourceIngestionOutboxDispatcher(
        settings=fixtures.both_gates(),
        session_factory=session_factory,
        runtime=ObservationFreshnessIngestionRuntime(),
        extraction_runtime=runtime,
    )
    assert asyncio.run(dispatcher.run_once()).completed == 1
    assert len(reads) == int(when == "before")
    # Pre-commit crash leaves a discoverable orphan; committed content is reused.
    assert len(list(tmp_path.rglob("*.json"))) == (2 if when == "before" else 1)


def test_first_batch_visible_to_independent_connection_before_next_read(session_factory, tmp_path):
    import asyncio

    from axis_api.connector_source_ingestion import (
        ObservationFreshnessIngestionRuntime,
        SourceIngestionOutboxDispatcher,
    )
    from axis_api.object_storage import LocalObjectStore

    fixtures.seed_two_bindings_with_request(session_factory)
    engine = session_factory.kw["bind"]
    observed = []
    # Keep this separate physical connection open throughout dispatch.
    with engine.connect() as observer:
        runtime = fixtures.make_runtime(session_factory, store=LocalObjectStore(tmp_path))

        def read(*args, **kwargs):
            observed.append(
                observer.execute(
                    text("SELECT count(*) FROM connector_source_extraction_batches")
                ).scalar_one()
            )
            observer.commit()
            return fixtures.bounded_result([{"id": 1}])

        runtime._read_bounded = read
        dispatcher = SourceIngestionOutboxDispatcher(
            settings=fixtures.both_gates(),
            session_factory=session_factory,
            runtime=ObservationFreshnessIngestionRuntime(),
            extraction_runtime=runtime,
        )
        assert asyncio.run(dispatcher.run_once()).completed == 1
    assert observed == [0, 1]


@pytest.mark.parametrize("corrupt", [False, True])
def test_postgres_committed_replay(session_factory, tmp_path, monkeypatch, corrupt):
    import test_connector_raw_durability as contracts

    contracts.test_committed_batch_replay_verifies_storage_without_reading_source(
        session_factory,
        tmp_path,
        monkeypatch,
        corrupt,
    )


@pytest.mark.parametrize("claim_change", ["token", "expiry"])
def test_postgres_claim_fencing(session_factory, tmp_path, monkeypatch, claim_change):
    import test_connector_raw_durability as contracts

    contracts.test_lost_or_expired_claim_cannot_record_a_batch(
        session_factory,
        tmp_path,
        monkeypatch,
        claim_change,
    )


def test_postgres_source_outside_transaction(session_factory, tmp_path, monkeypatch):
    import test_connector_raw_durability as contracts

    contracts.test_source_read_runs_outside_axis_transaction(session_factory, tmp_path, monkeypatch)
