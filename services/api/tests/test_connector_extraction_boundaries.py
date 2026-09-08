"""Tests at the real extraction and dispatch boundaries; no source network."""

from types import SimpleNamespace

import pytest
from test_connector_source_extraction import (
    both_gates,
    call_runtime,
    make_runtime,
    seed_binding_and_observation,
)
from test_connector_source_extraction import (
    session_factory as _source_session_factory,
)

session_factory = _source_session_factory


class SourceDriver:
    def __init__(self, rows, primary_key):
        self.rows = rows
        self.primary_key = primary_key
        self.pending = []
        self.statements = []
        self.description = [SimpleNamespace(name="id")]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self

    def execute(self, query, params=None):
        statement = query if isinstance(query, str) else query.as_string()
        self.statements.append(statement)
        if "pg_catalog.pg_attribute" in statement:
            self.pending = [("id", "integer", True, self.primary_key, "", "")]
        elif "information_schema.table_constraints" in statement:
            self.pending = [("id",)] if self.primary_key else []
        elif statement.startswith("SELECT"):
            candidates = self.rows
            if "WHERE" in statement:
                candidates = [row for row in candidates if row[0] > params[0]]
            limit = 1 if statement.startswith("SELECT 1") else params[-1]
            self.pending = candidates[:limit]

    def fetchall(self):
        result, self.pending = self.pending, []
        return result

    def fetchmany(self, size):
        result, self.pending = self.pending[:size], self.pending[size:]
        return result

    def fetchone(self):
        return self.pending[0] if self.pending else None


@pytest.mark.parametrize("primary_key", [False, True])
@pytest.mark.parametrize(("row_count", "truncated"), [(0, False), (2, False), (3, True)])
def test_real_extraction_reader_handles_empty_exact_and_capped_sources(
    session_factory,
    monkeypatch,
    primary_key,
    row_count,
    truncated,
):
    seed_binding_and_observation(session_factory)
    driver = SourceDriver([(i,) for i in range(row_count)], primary_key)
    monkeypatch.setattr("psycopg.connect", lambda *args, **kwargs: driver)
    settings = both_gates(
        source_ingestion_extraction_max_rows=2,
        source_ingestion_extraction_page_size=2,
    )

    outcome = call_runtime(make_runtime(session_factory, settings), session_factory)

    assert outcome.ok is True
    assert outcome.row_count == min(row_count, 2)
    assert outcome.truncated is truncated
    assert outcome.limit_reason == ("row_limit" if truncated else None)
    assert outcome.cursor_watermark == (
        {"id": min(row_count, 2) - 1} if primary_key and row_count else None
    )
    assert outcome.ordering_mode == ("primary_key" if primary_key else "none")
    assert driver.statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert driver.statements[1].startswith("SET LOCAL statement_timeout = ")


@pytest.mark.parametrize(
    "revocation",
    [
        "expired",
        "inactive",
        "foreign_connector",
        "permission_denied",
        "missing_broker_ref",
        "binding_resource",
        "binding_connector",
        "policy_connector",
        "policy_revoked",
    ],
)
def test_current_access_is_revalidated_before_extraction(session_factory, monkeypatch, revocation):
    from datetime import UTC, datetime, timedelta

    from test_connector_source_extraction import LEASE_ID, POLICY_ID, TENANT_A

    from axis_api.db import session_scope
    from axis_api.persistence import AxisPersistenceRepository

    seed_binding_and_observation(session_factory)
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        lease = repository.get_connector_credential_lease(TENANT_A, LEASE_ID)
        binding = repository.get_connector_source_binding(TENANT_A, "binding_extract_001")
        policy = repository.get_connector_egress_policy(TENANT_A, POLICY_ID)
        if revocation == "expired":
            lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif revocation == "inactive":
            lease.status = "revoked"
        elif revocation == "foreign_connector":
            lease.connector_id = "other_connector"
        elif revocation == "permission_denied":
            lease.permission_decision = {"allowed": False}
        elif revocation == "missing_broker_ref":
            lease.lease_result = {**lease.lease_result, "provider_lease_ref": ""}
        elif revocation == "binding_resource":
            binding.resource_name = "operations.other"
        elif revocation == "binding_connector":
            binding.connector_id = "other_connector"
        elif revocation == "policy_connector":
            policy.connector_id = "other_connector"
        else:
            policy.status = "revoked"

    def forbidden(*args, **kwargs):
        pytest.fail("revoked or mismatched access reached source dial")

    monkeypatch.setattr("psycopg.connect", forbidden)
    outcome = call_runtime(make_runtime(session_factory), session_factory)

    assert outcome.ok is False
    assert outcome.source_dial_performed is False
    assert outcome.extraction_performed is False
    assert outcome.payload_envelope is None


@pytest.mark.parametrize(
    "flag", ["source_ingestion_dispatch_enabled", "source_ingestion_extraction_enabled"]
)
def test_runtime_requires_both_deployment_gates(session_factory, monkeypatch, flag):
    seed_binding_and_observation(session_factory)

    def forbidden(*args, **kwargs):
        pytest.fail("disabled runtime reached source dial")

    monkeypatch.setattr("psycopg.connect", forbidden)
    settings = both_gates()
    setattr(settings, flag, False)
    outcome = call_runtime(make_runtime(session_factory, settings), session_factory)

    assert outcome.ok is False
    assert outcome.reason == "extraction_disabled"
    assert outcome.source_dial_performed is False


@pytest.mark.parametrize(
    ("failure_stage", "error_name", "reason", "retryable", "extracted"),
    [
        ("connect", "OperationalError", "source_unreachable", True, False),
        ("connect", "InvalidAuthorizationSpecification", "auth_denied", False, False),
        ("read", "QueryCanceled", "source_timeout", True, False),
        ("read", "InsufficientPrivilege", "permission_denied", False, False),
        ("second_page", "OperationalError", "source_unreachable", True, True),
    ],
)
def test_read_failures_preserve_phase_and_retry_evidence(
    session_factory,
    monkeypatch,
    failure_stage,
    error_name,
    reason,
    retryable,
    extracted,
):
    import psycopg

    seed_binding_and_observation(session_factory)
    error_type = getattr(psycopg, error_name, None) or getattr(psycopg.errors, error_name)
    driver = SourceDriver([(0,), (1,), (2,)], primary_key=True)
    original_execute = driver.execute
    reads = 0

    def execute(query, params=None):
        nonlocal reads
        statement = query if isinstance(query, str) else query.as_string()
        if statement.startswith("SELECT *"):
            reads += 1
            if failure_stage == "read" or (failure_stage == "second_page" and reads == 2):
                raise error_type("synthetic private driver detail")
        return original_execute(query, params)

    driver.execute = execute

    def connect(*args, **kwargs):
        if failure_stage == "connect":
            raise error_type("synthetic private driver detail")
        return driver

    monkeypatch.setattr("psycopg.connect", connect)
    settings = both_gates(source_ingestion_extraction_page_size=2)
    outcome = call_runtime(make_runtime(session_factory, settings), session_factory)

    assert outcome.ok is False
    assert outcome.reason == reason
    assert outcome.retryable is retryable
    assert outcome.source_dial_performed is True
    assert outcome.extraction_performed is extracted
    assert outcome.payload_envelope is None
    assert "synthetic private driver detail" not in outcome.model_dump_json()


@pytest.mark.parametrize(
    ("scenario", "expected_status", "dial", "extracted"),
    [
        ("expired", "failed", False, False),
        ("unreachable", "pending", True, False),
        ("unreachable_exhausted", "failed", True, False),
        ("success", "completed", True, True),
        ("storage_failure", "pending", True, True),
    ],
)
def test_dispatcher_records_real_access_facts_and_retry_policy(
    session_factory,
    monkeypatch,
    scenario,
    expected_status,
    dial,
    extracted,
):
    import asyncio
    from datetime import UTC, datetime, timedelta

    import psycopg
    from test_connector_source_extraction import LEASE_ID, TENANT_A, seed_extract_request

    from axis_api.connector_source_ingestion import (
        INGESTION_COMPLETED_EVENT,
        ObservationFreshnessIngestionRuntime,
        SourceIngestionOutboxDispatcher,
    )
    from axis_api.db import session_scope
    from axis_api.persistence import AxisPersistenceRepository

    seed_extract_request(session_factory)
    if scenario == "expired":
        with session_scope(session_factory) as session:
            lease = AxisPersistenceRepository(session).get_connector_credential_lease(
                TENANT_A, LEASE_ID
            )
            lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    def connect(*args, **kwargs):
        if scenario == "expired":
            pytest.fail("dispatcher reached source with expired lease")
        if scenario.startswith("unreachable"):
            raise psycopg.OperationalError("synthetic unavailable")
        return SourceDriver([(1,)], primary_key=True)

    monkeypatch.setattr("psycopg.connect", connect)

    class UnavailableStore:
        def put_json(self, key, payload):
            raise OSError("synthetic private storage detail")

    store = UnavailableStore() if scenario == "storage_failure" else None
    dispatcher = SourceIngestionOutboxDispatcher(
        settings=both_gates(source_ingestion_max_attempts=1)
        if scenario == "unreachable_exhausted"
        else both_gates(),
        session_factory=session_factory,
        runtime=ObservationFreshnessIngestionRuntime(),
        extraction_runtime=make_runtime(session_factory, store=store),
        random_uniform=lambda low, high: low,
    )
    result = asyncio.run(dispatcher.run_once())

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        request = repository.get_connector_source_ingestion_request(TENANT_A, "ingreq_e2e_extract")
        assert request.status == expected_status
        assert request.evidence["source_dial_performed"] is dial
        assert request.evidence["extraction_performed"] is extracted
        if scenario == "unreachable":
            assert result.retried == 1
            assert request.last_error == "source_unreachable"
        if scenario == "success":
            events = repository.list_audit_events(TENANT_A, event_type=INGESTION_COMPLETED_EVENT)
            assert events[0].payload["source_dial_performed"] == "true"
            assert events[0].payload["extraction_performed"] == "true"
