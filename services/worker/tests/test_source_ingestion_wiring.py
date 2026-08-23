"""Worker wiring and loop supervision for governed source ingestion dispatch.

Covers disabled-by-default construction, enabled composition (settings-owned
session factory + the validation-only observation runtime), the reusable
dispatch loop's drain/backoff/cancellation semantics under the ingestion
logger, dual-loop supervision beside the Temporal worker, and one SQLite
end-to-end proving the worker-built dispatcher completes requests with
truthful validation-only evidence and honest replay.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from axis_api.config import Settings
from axis_api.connector_source_ingestion import (
    ConnectorSourceIngestionSubmission,
    ObservationFreshnessIngestionRuntime,
    SourceIngestionOutboxDispatcher,
    record_connector_source_ingestion_request,
)
from axis_api.db import session_scope
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import axis_worker.runtime as runtime_module
from axis_worker.approval_outbox_loop import (
    run_dispatch_loop,
    run_source_ingestion_loop,
)
from axis_worker.runtime import (
    optional_source_ingestion_dispatcher,
    run_worker_with_optional_outbox,
)

# ---------------------------------------------------------------------------
# Scripted loop doubles


@dataclass(frozen=True)
class _Result:
    claimed: int


class _ScriptedDispatcher:
    def __init__(self, outcomes: list[_Result | Exception]) -> None:
        self._outcomes = iter(outcomes)
        self.calls = 0
        self.exhausted = asyncio.Event()

    async def run_once(self) -> _Result:
        self.calls += 1
        try:
            outcome = next(self._outcomes)
        except StopIteration:
            self.exhausted.set()
            return _Result(claimed=0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _ReturningWorker:
    async def run(self) -> None:
        await asyncio.sleep(0)


class _BlockingDispatcher:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    async def run_once(self) -> _Result:
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        return _Result(claimed=0)


# ---------------------------------------------------------------------------
# Wiring


def test_source_ingestion_dispatch_is_disabled_by_default() -> None:
    def fail_if_called(settings: Settings):
        raise AssertionError("disabled dispatcher must not allocate a DB pool")

    original = runtime_module.SourceIngestionOutboxDispatcher
    runtime_module.SourceIngestionOutboxDispatcher = fail_if_called
    try:
        assert optional_source_ingestion_dispatcher(Settings()) is None
    finally:
        runtime_module.SourceIngestionOutboxDispatcher = original


def test_enabled_setting_builds_dispatcher_with_validation_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    session_factory = object()

    class FakeDispatcher:
        def __init__(self, **kwargs) -> None:
            captured["dispatcher_kwargs"] = kwargs

    monkeypatch.setattr(
        runtime_module, "create_session_factory", lambda settings: session_factory
    )
    monkeypatch.setattr(runtime_module, "SourceIngestionOutboxDispatcher", FakeDispatcher)

    settings = Settings(AXIS_SOURCE_INGESTION_DISPATCH_ENABLED=True)
    dispatcher = optional_source_ingestion_dispatcher(settings)

    assert isinstance(dispatcher, FakeDispatcher)
    kwargs = captured["dispatcher_kwargs"]
    assert kwargs["settings"] is settings
    assert kwargs["session_factory"] is session_factory
    assert isinstance(kwargs["runtime"], ObservationFreshnessIngestionRuntime)


class _CountingTelemetry:
    """Telemetry double capturing counter additions for assertions."""

    def __init__(self) -> None:
        self.adds: list[tuple[int, dict]] = []
        self.source_ingestion_stage_counter = self

    def add(self, amount, attributes=None) -> None:
        self.adds.append((amount, dict(attributes or {})))


def test_instrumented_dispatcher_emits_outcome_counts_only() -> None:
    """Stage metrics carry outcome labels and counts — never payloads."""
    from axis_api.connector_source_ingestion import SourceIngestionRunResult

    from axis_worker.runtime import _InstrumentedIngestionDispatcher

    recorded: list[tuple[str, SourceIngestionRunResult]] = []

    class Inner:
        async def run_once(self):
            result = SourceIngestionRunResult(
                claimed=2, completed=1, retried=1, dead_lettered=0, fenced=0
            )
            recorded.append(("run", result))
            return result

    telemetry = _CountingTelemetry()
    result = asyncio.run(
        _InstrumentedIngestionDispatcher(Inner(), telemetry).run_once()
    )

    assert result.completed == 1 and result.retried == 1
    assert telemetry.adds == [
        (1, {"outcome": "completed"}),
        (1, {"outcome": "retried"}),
    ]


def test_optional_dispatcher_wraps_telemetry_when_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from axis_worker.runtime import (
        _InstrumentedIngestionDispatcher,
        optional_source_ingestion_dispatcher,
    )

    captured: dict[str, Any] = {}

    class FakeDispatcher:
        def __init__(self, **kwargs) -> None:
            captured["dispatcher_kwargs"] = kwargs

    monkeypatch.setattr(
        runtime_module, "create_session_factory", lambda settings: object()
    )
    monkeypatch.setattr(runtime_module, "SourceIngestionOutboxDispatcher", FakeDispatcher)
    settings = Settings(AXIS_SOURCE_INGESTION_DISPATCH_ENABLED=True)

    bare = optional_source_ingestion_dispatcher(settings, telemetry=None)
    assert isinstance(bare, FakeDispatcher)

    telemetry = _CountingTelemetry()
    wrapped = optional_source_ingestion_dispatcher(settings, telemetry=telemetry)
    assert isinstance(wrapped, _InstrumentedIngestionDispatcher)
    assert isinstance(wrapped._inner, FakeDispatcher)
    assert wrapped._telemetry is telemetry


def test_extraction_runtime_built_only_when_both_gates_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extraction composition is gated twice: dispatch AND extraction."""

    captured: dict[str, Any] = {}

    class FakeDispatcher(SourceIngestionOutboxDispatcher):
        def __init__(self, **kwargs) -> None:
            super().__init__(
                settings=kwargs["settings"],
                session_factory=object(),
                runtime=kwargs["runtime"],
                extraction_runtime=kwargs.get("extraction_runtime"),
            )
            captured["dispatcher"] = self
            captured["extraction_runtime"] = kwargs.get("extraction_runtime")

    class FakeStore:
        adapter_name = "fake"

        def put_json(self, key, payload):
            raise AssertionError("no payload should be written in this test")

    monkeypatch.setattr(
        runtime_module, "SourceIngestionOutboxDispatcher", FakeDispatcher
    )
    monkeypatch.setattr(
        runtime_module, "create_session_factory", lambda settings: object()
    )
    monkeypatch.setattr(
        runtime_module,
        "build_connector_export_object_store",
        lambda settings: FakeStore(),
    )

    # Dispatch on, extraction off → no extraction runtime, validate-only.
    dispatch_on = Settings(
        AXIS_SOURCE_INGESTION_DISPATCH_ENABLED=True,
        AXIS_SOURCE_INGESTION_EXTRACTION_ENABLED=False,
    )
    optional_source_ingestion_dispatcher(dispatch_on)
    assert captured["dispatcher"]._extraction_runtime is None

    # Both gates on → real bounded-extraction runtime present.
    both_on = Settings(
        AXIS_SOURCE_INGESTION_DISPATCH_ENABLED=True,
        AXIS_SOURCE_INGESTION_EXTRACTION_ENABLED=True,
    )
    optional_source_ingestion_dispatcher(both_on)
    from axis_api.connector_source_extraction import SelfHostedPostgresExtractionRuntime

    assert isinstance(captured["extraction_runtime"], SelfHostedPostgresExtractionRuntime)


def test_worker_supervises_and_cancels_both_outbox_loops() -> None:
    approval = _BlockingDispatcher()
    ingestion = _BlockingDispatcher()
    release = asyncio.Event()

    class _GatedWorker:
        async def run(self) -> None:
            await release.wait()

    async def scenario():
        task = asyncio.create_task(
            run_worker_with_optional_outbox(
                _GatedWorker(),
                dispatcher=approval,  # type: ignore[arg-type]
                dispatch_interval_seconds=60,
                ingestion_dispatcher=ingestion,  # type: ignore[arg-type]
                ingestion_dispatch_interval_seconds=60,
            )
        )
        await asyncio.sleep(0.01)
        assert not approval.cancelled.is_set()
        assert not ingestion.cancelled.is_set()
        release.set()
        await task

    asyncio.run(scenario())
    # Worker returned; both sibling loops were cancelled before control left.
    assert approval.cancelled.is_set()
    assert ingestion.cancelled.is_set()


def test_worker_runs_alone_when_no_dispatchers_are_enabled() -> None:
    class FailWorker:
        async def run(self) -> None:
            raise AssertionError("worker must still run without dispatchers")

    asyncio.run(
        run_worker_with_optional_outbox(
            _ReturningWorker(),
            dispatcher=None,
            dispatch_interval_seconds=60,
            ingestion_dispatcher=None,
            ingestion_dispatch_interval_seconds=60,
        )
    )


# ---------------------------------------------------------------------------
# Reusable loop semantics under the ingestion logger


@pytest.mark.asyncio
async def test_ingestion_loop_drains_then_waits_and_cancels_cleanly(caplog) -> None:
    dispatcher = _ScriptedDispatcher([_Result(claimed=2), _Result(claimed=1)])
    with caplog.at_level(logging.INFO, logger="axis_worker.source_ingestion_loop"):
        task = asyncio.create_task(
            run_source_ingestion_loop(dispatcher, interval_seconds=60)
        )
        await asyncio.wait_for(dispatcher.exhausted.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert dispatcher.calls == 3


@pytest.mark.asyncio
async def test_ingestion_loop_logs_failures_under_its_own_name(caplog) -> None:
    dispatcher = _ScriptedDispatcher([RuntimeError("pg unavailable")])
    with caplog.at_level(logging.ERROR, logger="axis_worker.source_ingestion_loop"):
        task = asyncio.create_task(
            run_source_ingestion_loop(dispatcher, interval_seconds=0.001)
        )
        await asyncio.wait_for(dispatcher.exhausted.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert "dispatch failed; retrying" in caplog.text
    assert any(record.name == "axis_worker.source_ingestion_loop" for record in caplog.records)


@pytest.mark.asyncio
async def test_generic_loop_rejects_non_positive_interval() -> None:
    dispatcher = _ScriptedDispatcher([])
    with pytest.raises(ValueError, match="greater than zero"):
        await run_dispatch_loop(dispatcher, interval_seconds=0, logger=logging.getLogger("t"))
    assert dispatcher.calls == 0


# ---------------------------------------------------------------------------
# End-to-end through the worker-built dispatcher (validation-only truth)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from axis_api.models import Base

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def test_worker_built_dispatcher_completes_with_truthful_evidence_and_replays(
    monkeypatch: pytest.MonkeyPatch, session_factory
) -> None:
    captured: dict[str, Any] = {}

    class CapturingDispatcher(SourceIngestionOutboxDispatcher):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            captured["dispatcher"] = self

    monkeypatch.setattr(
        runtime_module, "SourceIngestionOutboxDispatcher", CapturingDispatcher
    )
    monkeypatch.setattr(
        runtime_module, "create_session_factory", lambda settings: session_factory
    )
    settings = Settings(AXIS_SOURCE_INGESTION_DISPATCH_ENABLED=True)
    dispatcher = optional_source_ingestion_dispatcher(settings)
    assert dispatcher is captured["dispatcher"]

    # Seed one pending request directly; its selections point at evidence the
    # deterministic runtime can actually validate.
    now = datetime.now(UTC)
    with session_scope(session_factory) as session:
        repository = _seeded_repository(session)
        view = record_connector_source_ingestion_request(
            repository,
            submission=ConnectorSourceIngestionSubmission(
                tenant_id="tenant_demo_manufacturing",
                connector_id="external_db_operational_mirror",
                request_id="ingest_worker_e2e",
                requested_by="axis-operator",
                reason="Worker lane end-to-end probe.",
                selections=[{"binding_id": "binding_worker_e2e"}],
                actor_scopes=["connectors:source:ingest"],
            ),
            principal_scopes=["connectors:source:ingest"],
            max_selections=20,
            now=now,
        )
        assert view.outcome == "created"

    result = asyncio.run(dispatcher.run_once())
    assert result.claimed == 1 and result.completed == 1

    with session_scope(session_factory) as session:
        row = session.scalars(
            select(_request_model()).where(
                _request_model().request_id == "ingest_worker_e2e"
            )
        ).first()
        assert row is not None
        assert row.status == "completed"
        evidence = dict(row.evidence)
        assert evidence["source_dial_performed"] is False
        assert evidence["extraction_performed"] is False

    # Nothing left to claim; the same ask replays instead of duplicating.
    idle = asyncio.run(dispatcher.run_once())
    assert idle.claimed == 0
    with session_scope(session_factory) as session:
        from axis_api.persistence import AxisPersistenceRepository

        replay = record_connector_source_ingestion_request(
            AxisPersistenceRepository(session),
            submission=ConnectorSourceIngestionSubmission(
                tenant_id="tenant_demo_manufacturing",
                connector_id="external_db_operational_mirror",
                request_id="ingest_worker_e2e",
                requested_by="axis-operator",
                reason="Worker lane end-to-end probe.",
                selections=[{"binding_id": "binding_worker_e2e"}],
                actor_scopes=["connectors:source:ingest"],
            ),
            principal_scopes=["connectors:source:ingest"],
            max_selections=20,
            now=now + timedelta(seconds=30),
        )
        assert replay.outcome == "replayed"


def _seeded_repository(session):
    """Seed tenant, binding, and observation rows; return the repository."""

    from uuid import uuid4

    from axis_api.models import ConnectorSourceBinding, Tenant
    from axis_api.persistence import (
        AxisPersistenceRepository,
        DataResourceObservationCreate,
    )

    session.add(
        Tenant(
            id="tenant_demo_manufacturing",
            name="Ravenna Works",
            description="Plant Operations Cockpit",
            created_by="test",
        )
    )
    session.add(
        ConnectorSourceBinding(
            audit_event_id=uuid4(),
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            asset_id="source:external_db_operational_mirror:default",
            binding_id="binding_worker_e2e",
            connection_profile_id="profile_postgres_discovery_readonly",
            resource_name="operations.production_orders",
            schema_fingerprint="a" * 64,
            credential_lease_id="lease_seed",
            egress_policy_id="egress_seed",
            status="active",
            ingestion_status="pending_ingestion",
            activated_by="axis-operator",
            activation_reason="Seeded by worker e2e.",
            audit_event_type="connector.source.bindings.activated",
        )
    )
    repository = AxisPersistenceRepository(session)
    repository.create_data_resource_observation(
        DataResourceObservationCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            asset_id="source:external_db_operational_mirror:default",
            resource_name="operations.production_orders",
            schema_fingerprint="a" * 64,
            drift_state="added",
            observed_by="worker-e2e-lane",
            source_kind="postgres_discovery",
        )
    )
    return repository


def _request_model():
    from axis_api.models import ConnectorSourceIngestionRequest

    return ConnectorSourceIngestionRequest
