"""Durability contracts for bounded raw selections, using synthetic sources."""

from pathlib import Path

import pytest
from test_connector_extraction_boundaries import SourceDriver
from test_connector_source_extraction import (
    call_runtime,
    make_runtime,
    seed_binding_and_observation,
)
from test_connector_source_extraction import session_factory as _source_session_factory

from axis_api.object_storage import LocalObjectStore

session_factory = _source_session_factory


def test_changed_source_content_cannot_overwrite_a_previous_payload(
    session_factory,
    tmp_path: Path,
    monkeypatch,
):
    seed_binding_and_observation(session_factory)
    rows = [(1,)]
    monkeypatch.setattr("psycopg.connect", lambda *args, **kwargs: SourceDriver(rows, True))
    store = LocalObjectStore(tmp_path)
    runtime = make_runtime(session_factory, store=store)

    first = call_runtime(runtime, session_factory)
    original = (tmp_path / first.stored["storage_key"]).read_bytes()
    rows = [(2,)]
    second = call_runtime(runtime, session_factory)

    assert first.ok is True and second.ok is True
    assert first.stored["storage_key"] != second.stored["storage_key"]
    assert (tmp_path / first.stored["storage_key"]).read_bytes() == original


def test_local_store_does_not_publish_an_unflushed_replacement(tmp_path, monkeypatch):
    import pytest

    store = LocalObjectStore(tmp_path)
    store.put_json("synthetic/batch.json", {"rows": [1]})
    original = (tmp_path / "synthetic/batch.json").read_bytes()

    def flush_failed(*args):
        raise OSError("synthetic disk flush failure")

    monkeypatch.setattr("os.fsync", flush_failed)
    with pytest.raises(OSError):
        store.put_json("synthetic/batch.json", {"rows": [2]})

    assert (tmp_path / "synthetic/batch.json").read_bytes() == original


def test_source_read_runs_outside_axis_transaction(session_factory, tmp_path, monkeypatch):
    import asyncio

    from sqlalchemy import event
    from test_connector_source_extraction import both_gates, seed_extract_request

    from axis_api.connector_source_ingestion import (
        ObservationFreshnessIngestionRuntime,
        SourceIngestionOutboxDispatcher,
    )

    seed_extract_request(session_factory)
    active = set()

    def began(session, transaction, connection):
        active.add(id(session))

    def ended(session, transaction):
        if transaction.parent is None:
            active.discard(id(session))

    def connect(*args, **kwargs):
        assert not active, "source dial occurred inside an Axis transaction"
        return SourceDriver([(1,)], True)

    event.listen(session_factory.class_, "after_begin", began)
    event.listen(session_factory.class_, "after_transaction_end", ended)
    monkeypatch.setattr("psycopg.connect", connect)
    try:
        dispatcher = SourceIngestionOutboxDispatcher(
            settings=both_gates(),
            session_factory=session_factory,
            runtime=ObservationFreshnessIngestionRuntime(),
            extraction_runtime=make_runtime(session_factory, store=LocalObjectStore(tmp_path)),
        )
        result = asyncio.run(dispatcher.run_once())
        assert result.completed == 1
    finally:
        event.remove(session_factory.class_, "after_begin", began)
        event.remove(session_factory.class_, "after_transaction_end", ended)


@pytest.mark.parametrize("claim_change", ["token", "expiry"])
def test_lost_or_expired_claim_cannot_record_a_batch(
    session_factory,
    tmp_path,
    monkeypatch,
    claim_change,
):
    import asyncio
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from test_connector_source_extraction import TENANT_A, both_gates, seed_extract_request

    from axis_api.connector_source_ingestion import (
        ObservationFreshnessIngestionRuntime,
        SourceIngestionOutboxDispatcher,
    )
    from axis_api.db import session_scope
    from axis_api.persistence import AxisPersistenceRepository

    seed_extract_request(session_factory)

    def connect(*args, **kwargs):
        # Simulate another worker taking the claim, or expiry, during source I/O.
        with session_scope(session_factory) as session:
            request = AxisPersistenceRepository(session).get_connector_source_ingestion_request(
                TENANT_A,
                "ingreq_e2e_extract",
            )
            if claim_change == "token":
                request.claim_token = uuid4()
            else:
                request.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        return SourceDriver([(1,)], True)

    monkeypatch.setattr("psycopg.connect", connect)
    dispatcher = SourceIngestionOutboxDispatcher(
        settings=both_gates(),
        session_factory=session_factory,
        runtime=ObservationFreshnessIngestionRuntime(),
        extraction_runtime=make_runtime(session_factory, store=LocalObjectStore(tmp_path)),
    )
    result = asyncio.run(dispatcher.run_once())

    assert result.fenced == 1
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        assert (
            repository.get_connector_source_ingestion_request_batches(
                TENANT_A,
                "ingreq_e2e_extract",
                limit=10,
            )
            == []
        )
        assert (
            repository.list_audit_events(
                TENANT_A,
                event_type="connector.source.extraction.batch_recorded",
            )
            == []
        )


@pytest.mark.parametrize("corrupt", [False, True])
def test_committed_batch_replay_verifies_storage_without_reading_source(
    session_factory,
    tmp_path,
    monkeypatch,
    corrupt,
):
    import asyncio
    from datetime import UTC, datetime, timedelta

    from test_connector_source_extraction import TENANT_A, both_gates, seed_extract_request

    from axis_api.connector_source_ingestion import (
        ObservationFreshnessIngestionRuntime,
        SourceIngestionOutboxDispatcher,
    )
    from axis_api.db import session_scope
    from axis_api.persistence import AxisPersistenceRepository

    seed_extract_request(session_factory)
    dials = []

    def connect(*args, **kwargs):
        dials.append(1)
        return SourceDriver([(1,)], True)

    monkeypatch.setattr("psycopg.connect", connect)
    dispatcher = SourceIngestionOutboxDispatcher(
        settings=both_gates(),
        session_factory=session_factory,
        runtime=ObservationFreshnessIngestionRuntime(),
        extraction_runtime=make_runtime(session_factory, store=LocalObjectStore(tmp_path)),
    )

    class Crash(BaseException):
        pass

    finalize = dispatcher._finalize_success
    monkeypatch.setattr(
        dispatcher, "_finalize_success", lambda *args: (_ for _ in ()).throw(Crash())
    )
    with pytest.raises(Crash):
        asyncio.run(dispatcher.run_once())
    with session_scope(session_factory) as session:
        repo = AxisPersistenceRepository(session)
        batches = repo.get_connector_source_ingestion_request_batches(
            TENANT_A, "ingreq_e2e_extract", limit=10
        )
        assert len(batches) == 1
        if corrupt:
            (tmp_path / batches[0].storage_key).write_text("tampered synthetic data")
        request = repo.get_connector_source_ingestion_request(TENANT_A, "ingreq_e2e_extract")
        request.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(dispatcher, "_finalize_success", finalize)
    result = asyncio.run(dispatcher.run_once())
    assert len(dials) == 1
    assert result.dead_lettered == int(corrupt)
    assert result.completed == int(not corrupt)
    with session_scope(session_factory) as session:
        repo = AxisPersistenceRepository(session)
        assert (
            len(
                repo.get_connector_source_ingestion_request_batches(
                    TENANT_A, "ingreq_e2e_extract", limit=10
                )
            )
            == 1
        )
        assert (
            len(
                repo.list_audit_events(
                    TENANT_A, event_type="connector.source.extraction.batch_recorded"
                )
            )
            == 1
        )


def test_local_store_flushes_new_directory_entries(tmp_path, monkeypatch):
    import os
    import stat

    flushed = set()
    original = os.fsync

    def fsync(fd):
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            flushed.add(info.st_ino)
        original(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    LocalObjectStore(tmp_path).put_json("request/binding/batch/payload.json", {"rows": []})
    assert {
        p.stat().st_ino
        for p in [
            tmp_path,
            tmp_path / "request",
            tmp_path / "request/binding",
            tmp_path / "request/binding/batch",
        ]
    } <= flushed


def test_storage_metadata_must_match_raw_payload(session_factory, tmp_path, monkeypatch):
    seed_binding_and_observation(session_factory)
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: SourceDriver([(1,)], True))

    class IncorrectStore(LocalObjectStore):
        def put_json(self, key, payload):
            return super().put_json(key, payload).model_copy(update={"checksum_sha256": "0" * 64})

    outcome = call_runtime(
        make_runtime(session_factory, store=IncorrectStore(tmp_path)), session_factory
    )
    assert not outcome.ok and outcome.reason == "object_store_integrity_mismatch"
    assert outcome.extraction_performed and outcome.source_dial_performed


def test_reused_requeue_key_starts_a_distinct_generation(session_factory):
    from datetime import UTC, datetime, timedelta

    from test_connector_source_extraction import TENANT_A, both_gates, seed_extract_request

    from axis_api.connector_source_ingestion import (
        ObservationFreshnessIngestionRuntime,
        SourceIngestionOutboxDispatcher,
    )
    from axis_api.db import session_scope
    from axis_api.persistence import AxisPersistenceRepository

    seed_extract_request(session_factory)
    dispatcher = SourceIngestionOutboxDispatcher(
        settings=both_gates(),
        session_factory=session_factory,
        runtime=ObservationFreshnessIngestionRuntime(),
    )
    generations = [dispatcher._claim()[0].generation]
    for seconds_ago in [2, 1]:
        with session_scope(session_factory) as session:
            repo = AxisPersistenceRepository(session)
            request = repo.get_connector_source_ingestion_request(TENANT_A, "ingreq_e2e_extract")
            request.status = "failed"
            request.dead_lettered_at = datetime.now(UTC) - timedelta(seconds=3)
            session.flush()
            assert (
                repo.requeue_connector_source_ingestion_request(
                    tenant_id=TENANT_A,
                    request_id="ingreq_e2e_extract",
                    requeued_by="operator",
                    requeue_reason="synthetic retry",
                    idempotency_key="same_requeue_key",
                    now=datetime.now(UTC) - timedelta(seconds=seconds_ago),
                )
                == "requeued"
            )
        generations.append(dispatcher._claim()[0].generation)
    assert len(set(generations)) == 3
