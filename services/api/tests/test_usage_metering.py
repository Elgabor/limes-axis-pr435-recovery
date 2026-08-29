import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Cross-module reuse of the OIDC authorization-code harness for the
# session-created choke point (drives a real callback end to end).
from test_oidc_authorization_code_session import (  # noqa: E402
    _app_with_static_oidc,
    _start_oidc_login,
)
from test_oidc_authorization_code_session import (
    _settings as _oidc_settings,
)

from axis_api.config import Settings
from axis_api.connector_execution import ConnectorSyncExecutionResult
from axis_api.connector_runs import (
    SYNC_BATCH_CHECKPOINT_TYPE,
    SYNC_BATCH_COMMITTED_STATUS,
    _live_sync_resume_records_seed,
    _record_connector_sync_rows_usage,
)
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app, oidc_principal
from axis_api.models import Base, TenantUsageEvent, TenantUsageRecord
from axis_api.persistence import (
    AxisPersistenceRepository,
    TenantCreate,
    TenantUsageAdd,
    TenantUsageEventAppend,
    TenantUsageIdempotencyConflict,
)
from axis_api.usage_metering import (
    DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
    TenantUsageMetric,
    UsageEventProjector,
    build_tenant_usage_summary,
    record_tenant_usage_event,
    usage_period_start,
)

TENANT_ID = "tenant_acme_manufacturing"
OTHER_TENANT_ID = "tenant_globex_manufacturing"
OPERATOR_ACTOR = "axis-platform-operator-role"
USAGE_SCOPES = ["platform:tenant:operator", "platform:tenant:usage"]


def _adapt_sqlite_datetime(value: datetime) -> str:
    return value.isoformat(" ")


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _metering_settings(**overrides) -> Settings:
    values: dict = {
        "postgres_dsn": "sqlite+pysqlite://",
        "usage_metering_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def _build_client(settings: Settings | None = None) -> tuple[TestClient, sessionmaker[Session]]:
    factory = _factory()
    app = create_app(settings or _metering_settings())
    app.state.session_factory = factory
    return TestClient(app), factory


def _provision_tenant(factory: sessionmaker[Session], tenant_id: str = TENANT_ID) -> None:
    with factory() as session:
        AxisPersistenceRepository(session).create_tenant(
            TenantCreate(
                tenant_id=tenant_id,
                display_name=tenant_id,
                created_by=OPERATOR_ACTOR,
            )
        )
        session.commit()


def _seed_usage(
    factory: sessionmaker[Session],
    tenant_id: str,
    metric: str,
    quantity: int,
    occurred_at: datetime,
) -> None:
    with factory() as session:
        record_tenant_usage_event(
            AxisPersistenceRepository(session),
            tenant_id,
            metric,
            quantity,
            source_type="test_seed",
            source_id=f"{tenant_id}:{metric}:{occurred_at.isoformat()}:{quantity}",
            occurred_at=occurred_at,
        )
        session.commit()


def _usage_rows(factory: sessionmaker[Session], tenant_id: str) -> list[TenantUsageRecord]:
    with factory() as session:
        return list(
            session.scalars(
                select(TenantUsageRecord)
                .where(TenantUsageRecord.tenant_id == tenant_id)
                .order_by(
                    TenantUsageRecord.metric_key.asc(),
                    TenantUsageRecord.period_start.asc(),
                )
            )
        )


def _usage_events(factory: sessionmaker[Session], tenant_id: str) -> list[TenantUsageEvent]:
    with factory() as session:
        return list(
            session.scalars(
                select(TenantUsageEvent)
                .where(TenantUsageEvent.tenant_id == tenant_id)
                .order_by(TenantUsageEvent.recorded_at.asc(), TenantUsageEvent.id.asc())
            )
        )


# --------------------------------------------------------------------------- #
# Period bucketing                                                            #
# --------------------------------------------------------------------------- #


def test_usage_period_start_floors_to_utc_day_by_default() -> None:
    moment = datetime(2026, 7, 10, 13, 45, 12, tzinfo=UTC)
    assert usage_period_start(moment) == datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)


def test_usage_period_start_aligns_to_configurable_window() -> None:
    moment = datetime(2026, 7, 10, 13, 45, 12, tzinfo=UTC)
    # Hourly buckets align to the top of the hour.
    assert usage_period_start(moment, 3600) == datetime(2026, 7, 10, 13, 0, 0, tzinfo=UTC)


def test_usage_period_start_treats_naive_datetime_as_utc() -> None:
    naive = datetime(2026, 7, 10, 23, 59, 59)
    assert usage_period_start(naive) == datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Persistence upsert-add                                                       #
# --------------------------------------------------------------------------- #


def test_add_tenant_usage_upsert_add_accumulates_same_bucket() -> None:
    factory = _factory()
    moment = datetime(2026, 7, 10, 8, 0, 0, tzinfo=UTC)
    period = usage_period_start(moment)
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        for _ in range(3):
            repository.add_tenant_usage(
                TenantUsageAdd(
                    tenant_id=TENANT_ID,
                    metric_key=TenantUsageMetric.API_REQUEST.value,
                    period_start=period,
                    period_window_seconds=DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
                    quantity=2,
                    first_occurred_at=moment,
                    last_occurred_at=moment,
                )
            )
        session.commit()

    rows = _usage_rows(factory, TENANT_ID)
    assert len(rows) == 1
    assert rows[0].quantity == 6
    # SQLite drops tzinfo on readback; compare the wall-clock instant.
    stored = rows[0].period_start
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=UTC)
    assert stored == period


def test_add_tenant_usage_composes_across_independent_sessions() -> None:
    # Two separate sessions (two flushers / replicas) targeting one bucket sum.
    factory = _factory()
    moment = datetime(2026, 7, 10, 8, 0, 0, tzinfo=UTC)
    period = usage_period_start(moment)
    for delta in (3, 4):
        with factory() as session:
            AxisPersistenceRepository(session).add_tenant_usage(
                TenantUsageAdd(
                    tenant_id=TENANT_ID,
                    metric_key=TenantUsageMetric.SESSION_CREATED.value,
                    period_start=period,
                    period_window_seconds=DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
                    quantity=delta,
                    first_occurred_at=moment,
                    last_occurred_at=moment,
                )
            )
            session.commit()

    rows = _usage_rows(factory, TENANT_ID)
    assert len(rows) == 1
    assert rows[0].quantity == 7


def test_usage_event_replay_is_idempotent_and_preserves_dimensions() -> None:
    factory = _factory()
    moment = datetime(2026, 7, 10, 8, tzinfo=UTC)
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        first = record_tenant_usage_event(
            repository,
            TENANT_ID,
            TenantUsageMetric.MODEL_INVOCATIONS,
            1,
            source_type="model_invocation",
            source_id="invocation-1",
            occurred_at=moment,
            dimensions={"provider_id": "provider-a"},
        )
        replay = record_tenant_usage_event(
            repository,
            TENANT_ID,
            TenantUsageMetric.MODEL_INVOCATIONS,
            1,
            source_type="model_invocation",
            source_id="invocation-1",
            occurred_at=moment,
            dimensions={"provider_id": "provider-a"},
        )
        session.commit()

    assert first is True
    assert replay is False
    assert len(_usage_events(factory, TENANT_ID)) == 1
    assert _usage_events(factory, TENANT_ID)[0].dimensions == {
        "provider_id": "provider-a"
    }
    rows = _usage_rows(factory, TENANT_ID)
    assert rows[0].quantity == 1
    assert rows[0].dimensions == {}


def test_usage_event_replay_rejects_a_different_billing_payload() -> None:
    factory = _factory()
    moment = datetime(2026, 7, 10, 8, tzinfo=UTC)
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        record_tenant_usage_event(
            repository,
            TENANT_ID,
            TenantUsageMetric.CONNECTOR_SYNC_ROWS,
            10,
            source_type="connector_sync_execution",
            source_id="run-1:execution-1",
            occurred_at=moment,
        )
        with pytest.raises(TenantUsageIdempotencyConflict):
            record_tenant_usage_event(
                repository,
                TENANT_ID,
                TenantUsageMetric.CONNECTOR_SYNC_ROWS,
                11,
                source_type="connector_sync_execution",
                source_id="run-1:execution-1",
                occurred_at=moment,
            )
        session.commit()

    assert len(_usage_events(factory, TENANT_ID)) == 1
    assert _usage_rows(factory, TENANT_ID)[0].quantity == 10


def test_usage_event_and_rollup_rollback_together() -> None:
    factory = _factory()
    with factory() as session:
        record_tenant_usage_event(
            AxisPersistenceRepository(session),
            TENANT_ID,
            TenantUsageMetric.SESSION_CREATED,
            1,
            source_type="oidc_browser_session",
            source_id="session-1",
            occurred_at=datetime(2026, 7, 10, 8, tzinfo=UTC),
        )
        session.rollback()

    assert _usage_events(factory, TENANT_ID) == []
    assert _usage_rows(factory, TENANT_ID) == []


def test_usage_windows_do_not_collide_at_the_same_period_start() -> None:
    factory = _factory()
    midnight = datetime(2026, 7, 10, tzinfo=UTC)
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        for window_seconds, quantity in ((86_400, 3), (3_600, 5)):
            record_tenant_usage_event(
                repository,
                TENANT_ID,
                TenantUsageMetric.API_REQUEST,
                quantity,
                source_type="test_window",
                source_id=str(window_seconds),
                window_seconds=window_seconds,
                occurred_at=midnight,
            )
        session.commit()

    rows = _usage_rows(factory, TENANT_ID)
    assert {(row.period_window_seconds, row.quantity) for row in rows} == {
        (86_400, 3),
        (3_600, 5),
    }
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        daily = repository.aggregate_tenant_usage(
            TENANT_ID,
            period_window_seconds=86_400,
        )
        hourly = repository.aggregate_tenant_usage(
            TENANT_ID,
            period_window_seconds=3_600,
        )
    assert [row.quantity for row in daily] == [3]
    assert [row.quantity for row in hourly] == [5]


def test_usage_rollup_keeps_true_first_and_last_event_times() -> None:
    factory = _factory()
    earlier = datetime(2026, 7, 10, 8, tzinfo=UTC)
    later = datetime(2026, 7, 10, 18, tzinfo=UTC)
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        for source_id, occurred_at in (("later", later), ("earlier", earlier)):
            record_tenant_usage_event(
                repository,
                TENANT_ID,
                TenantUsageMetric.API_REQUEST,
                1,
                source_type="out_of_order_test",
                source_id=source_id,
                occurred_at=occurred_at,
            )
        session.commit()

    row = _usage_rows(factory, TENANT_ID)[0]
    first = row.first_recorded_at.replace(tzinfo=UTC)
    last = row.last_recorded_at.replace(tzinfo=UTC)
    assert first == earlier
    assert last == later


# --------------------------------------------------------------------------- #
# Deferred event projection                                                    #
# --------------------------------------------------------------------------- #


def test_deferred_usage_event_projects_exactly_once() -> None:
    factory = _factory()
    moment = datetime(2026, 7, 10, 8, 0, 0, tzinfo=UTC)
    with factory() as session:
        AxisPersistenceRepository(session).append_tenant_usage_event(
            TenantUsageEventAppend(
                tenant_id=TENANT_ID,
                metric_key=TenantUsageMetric.API_REQUEST,
                source_type="api_request_admission",
                source_id="admission-1",
                period_start=usage_period_start(moment),
                period_window_seconds=DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
                quantity=1,
                occurred_at=moment,
            ),
            project_immediately=False,
        )
        session.commit()

    assert _usage_rows(factory, TENANT_ID) == []
    assert _usage_events(factory, TENANT_ID)[0].projected_at is None

    projector = UsageEventProjector(
        failure_threshold=3,
        max_backlog_age_seconds=60,
    )
    first = projector.project_available(factory, batch_size=10, max_batches=2)
    second = projector.project_available(factory, batch_size=10, max_batches=2)

    assert first.events_projected == 1
    assert first.quantity_projected == 1
    assert second.events_projected == 0
    assert _usage_rows(factory, TENANT_ID)[0].quantity == 1
    assert _usage_events(factory, TENANT_ID)[0].projected_at is not None
    assert projector.health()["healthy"] is True


def test_projector_groups_events_and_preserves_time_extremes() -> None:
    factory = _factory()
    earlier = datetime(2026, 7, 10, 8, tzinfo=UTC)
    later = datetime(2026, 7, 10, 18, tzinfo=UTC)
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        for source_id, occurred_at, quantity in (
            ("later", later, 3),
            ("earlier", earlier, 2),
        ):
            repository.append_tenant_usage_event(
                TenantUsageEventAppend(
                    tenant_id=TENANT_ID,
                    metric_key=TenantUsageMetric.API_REQUEST,
                    source_type="api_request_admission",
                    source_id=source_id,
                    period_start=usage_period_start(occurred_at),
                    period_window_seconds=DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
                    quantity=quantity,
                    occurred_at=occurred_at,
                ),
                project_immediately=False,
            )
        session.commit()

    projector = UsageEventProjector(
        failure_threshold=3,
        max_backlog_age_seconds=60,
    )
    result = projector.project_available(factory, batch_size=10, max_batches=1)

    assert result.events_projected == 2
    assert result.quantity_projected == 5
    row = _usage_rows(factory, TENANT_ID)[0]
    assert row.quantity == 5
    assert row.first_recorded_at.replace(tzinfo=UTC) == earlier
    assert row.last_recorded_at.replace(tzinfo=UTC) == later


def test_projector_failure_rolls_back_claim_and_rollup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    moment = datetime(2026, 7, 10, 8, tzinfo=UTC)
    with factory() as session:
        AxisPersistenceRepository(session).append_tenant_usage_event(
            TenantUsageEventAppend(
                tenant_id=TENANT_ID,
                metric_key=TenantUsageMetric.API_REQUEST,
                source_type="api_request_admission",
                source_id="admission-rollback",
                period_start=usage_period_start(moment),
                period_window_seconds=DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
                quantity=1,
                occurred_at=moment,
            ),
            project_immediately=False,
        )
        session.commit()

    def fail_rollup(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated rollup failure")

    monkeypatch.setattr(AxisPersistenceRepository, "add_tenant_usage", fail_rollup)
    projector = UsageEventProjector(
        failure_threshold=3,
        max_backlog_age_seconds=60,
    )

    with pytest.raises(RuntimeError, match="simulated rollup failure"):
        projector.project_available(factory, batch_size=10, max_batches=1)

    assert _usage_rows(factory, TENANT_ID) == []
    assert _usage_events(factory, TENANT_ID)[0].projected_at is None
    assert projector.health()["consecutive_failures"] == 1


def test_projector_health_fails_when_heartbeat_is_stale() -> None:
    factory = _factory()
    projector = UsageEventProjector(
        failure_threshold=3,
        max_backlog_age_seconds=1,
    )
    projector.project_available(factory, batch_size=10, max_batches=1)
    assert projector.health()["healthy"] is True

    with projector._lock:
        projector._last_success_at = datetime.now(UTC) - timedelta(seconds=2)

    health = projector.health()
    assert health["healthy"] is False
    assert float(health["heartbeat_age_seconds"] or 0) >= 1


def test_projector_shutdown_wait_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from threading import Event
    from time import monotonic

    app = create_app(
        _metering_settings(usage_metering_shutdown_timeout_seconds=0.1)
    )
    started = Event()
    release = Event()

    def blocked_projection(*_args, **_kwargs) -> None:
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(
        app.state.usage_event_projector,
        "project_available",
        blocked_projection,
    )
    began = monotonic()
    try:
        with TestClient(app):
            assert started.wait(timeout=1)
    finally:
        release.set()

    assert monotonic() - began < 1


# --------------------------------------------------------------------------- #
# Choke point: connector sync rows                                             #
# --------------------------------------------------------------------------- #


def test_connector_sync_rows_recorded_with_real_row_count() -> None:
    factory = _factory()
    result = ConnectorSyncExecutionResult(
        adapter="file_csv",
        status="succeeded",
        sync_ref="sync_ref_1",
        external_sync_started=True,
        idempotency_key="idem_1",
        result_summary={"records_read": "17", "records_accepted": "17"},
    )
    with factory() as session:
        _record_connector_sync_rows_usage(
            AxisPersistenceRepository(session),
            TENANT_ID,
            result,
            DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
            source_id="run-1:execution-1",
            occurred_at=datetime(2026, 7, 10, 8, tzinfo=UTC),
        )
        session.commit()

    rows = _usage_rows(factory, TENANT_ID)
    assert len(rows) == 1
    assert rows[0].metric_key == TenantUsageMetric.CONNECTOR_SYNC_ROWS.value
    assert rows[0].quantity == 17


def test_connector_sync_rows_zero_is_not_recorded() -> None:
    factory = _factory()
    result = ConnectorSyncExecutionResult(
        adapter="file_csv",
        status="succeeded",
        sync_ref="sync_ref_1",
        external_sync_started=False,
        idempotency_key="idem_1",
        result_summary={"records_read": "0"},
    )
    with factory() as session:
        _record_connector_sync_rows_usage(
            AxisPersistenceRepository(session),
            TENANT_ID,
            result,
            DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
            source_id="run-1:execution-1",
            occurred_at=datetime(2026, 7, 10, 8, tzinfo=UTC),
        )
        session.commit()
    assert _usage_rows(factory, TENANT_ID) == []


def _sync_result(records_read: int, status: str = "sync_execution_completed"):
    return ConnectorSyncExecutionResult(
        adapter="file_csv",
        status=status,
        sync_ref="sync_ref_1",
        external_sync_started=True,
        idempotency_key="idem_1",
        result_summary={"records_read": str(records_read)},
    )


def test_connector_sync_rows_meters_delta_on_resume() -> None:
    # A resumed run reports the run-CUMULATIVE records_read; metering must
    # subtract the resume seed so only this attempt's increment is billed.
    factory = _factory()
    with factory() as session:
        _record_connector_sync_rows_usage(
            AxisPersistenceRepository(session),
            TENANT_ID,
            _sync_result(250),
            DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
            resume_records_seed=100,
            source_id="run-1:execution-2",
            occurred_at=datetime(2026, 7, 10, 9, tzinfo=UTC),
        )
        session.commit()
    rows = _usage_rows(factory, TENANT_ID)
    assert len(rows) == 1
    assert rows[0].quantity == 150


def test_connector_sync_failed_then_retry_resume_does_not_double_count() -> None:
    # Attempt A reads 100 rows and fails (metered on the failed outcome); Attempt
    # B resumes from the committed checkpoint (seed 100), reads 150 more and
    # completes with cumulative records_read=250. The ledger must total the true
    # 250 rows read, not 350.
    factory = _factory()
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        # Attempt A: fresh (seed 0), fails after reading 100.
        _record_connector_sync_rows_usage(
            repository,
            TENANT_ID,
            _sync_result(100, status="sync_execution_failed"),
            DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
            resume_records_seed=0,
            source_id="run-1:execution-a",
            occurred_at=datetime(2026, 7, 10, 8, tzinfo=UTC),
        )
        # Attempt B: resumes from seed 100, completes at cumulative 250.
        _record_connector_sync_rows_usage(
            repository,
            TENANT_ID,
            _sync_result(250),
            DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
            resume_records_seed=100,
            source_id="run-1:execution-b",
            occurred_at=datetime(2026, 7, 10, 9, tzinfo=UTC),
        )
        session.commit()

    rows = _usage_rows(factory, TENANT_ID)
    assert len(rows) == 1
    assert rows[0].metric_key == TenantUsageMetric.CONNECTOR_SYNC_ROWS.value
    assert rows[0].quantity == 250


class _RunStub:
    def __init__(self, tenant_id: str, run_id: str, connector_id: str) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.connector_id = connector_id


def test_live_sync_resume_records_seed_reads_committed_checkpoint() -> None:
    from axis_api.persistence import ConnectorSyncCheckpointCreate

    factory = _factory()
    run = _RunStub(TENANT_ID, "run_live_1", "connector_file_csv")
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        # No checkpoint yet: a fresh run seeds zero.
        assert _live_sync_resume_records_seed(repository, run) == 0
        repository.create_connector_sync_checkpoint(
            ConnectorSyncCheckpointCreate(
                tenant_id=TENANT_ID,
                connector_id="connector_file_csv",
                run_id="run_live_1",
                checkpoint_id="chk_batch_1",
                checkpoint_type=SYNC_BATCH_CHECKPOINT_TYPE,
                status=SYNC_BATCH_COMMITTED_STATUS,
                sequence=1,
                runtime_boundary="axis_self_hosted_runtime",
                adapter="file_csv",
                cursor={"next_offset": "100", "total_records_read": "100"},
            )
        )
        session.commit()
        assert _live_sync_resume_records_seed(repository, run) == 100


# --------------------------------------------------------------------------- #
# Choke point: api_request via the rate-limit middleware                       #
# --------------------------------------------------------------------------- #


class _StaticVerifier:
    def __init__(self, principal: OidcPrincipal) -> None:
        self.principal = principal

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        assert authorization == "Bearer valid-token"
        return self.principal


def _set_bearer_principal(client: TestClient, tenant_id: str = TENANT_ID) -> None:
    client.app.state.identity_verifier = _StaticVerifier(
        OidcPrincipal(
            actor_id="acme-console-user-role",
            tenant_id=tenant_id,
            scopes=["audit:read"],
        )
    )


def test_api_request_metered_for_verified_bearer_on_non_rate_limited_path() -> None:
    settings = _metering_settings(api_rate_limit_paths=["/deployment/readiness"])
    client, factory = _build_client(settings)
    _set_bearer_principal(client)

    response = client.get(
        "/identity/session",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 200

    events = _usage_events(factory, TENANT_ID)
    assert len(events) == 1
    assert events[0].source_type == "api_request_admission"
    assert events[0].projected_at is None
    assert events[0].dimensions["method"] == "GET"
    client.app.state.usage_event_projector.project_available(
        factory,
        batch_size=10,
        max_batches=1,
    )
    rows = _usage_rows(factory, TENANT_ID)
    assert len(rows) == 1
    assert rows[0].metric_key == TenantUsageMetric.API_REQUEST.value
    assert rows[0].quantity == 1


def test_api_request_admission_is_committed_before_handler_and_survives_500() -> None:
    client, factory = _build_client()
    _set_bearer_principal(client)
    observed: dict[str, int] = {}

    @client.app.get("/test/usage-handler-failure")
    def failing_handler(
        _principal: Annotated[OidcPrincipal | None, Depends(oidc_principal)],
    ) -> None:
        observed["event_count"] = len(_usage_events(factory, TENANT_ID))
        raise RuntimeError("simulated handler failure")

    response = TestClient(client.app, raise_server_exceptions=False).get(
        "/test/usage-handler-failure",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 500
    assert observed == {"event_count": 1}
    assert len(_usage_events(factory, TENANT_ID)) == 1


def test_api_request_rejected_by_auth_is_not_metered() -> None:
    client, factory = _build_client(_metering_settings(oidc_auth_required=True))

    # A protected route still rejects anonymous callers with 401...
    rejected = client.get(f"/operations/approvals?tenant_id={TENANT_ID}")
    assert rejected.status_code == 401

    # ...while the deliberately public session report answers without any
    # principal attached. Neither response may record tenant usage.
    report = client.get("/identity/session")
    assert report.status_code == 200
    assert report.json()["authenticated"] is False

    assert _usage_events(factory, TENANT_ID) == []


def test_api_request_fails_closed_when_tenant_state_cannot_be_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = _build_client()
    _set_bearer_principal(client)

    def fail_snapshot(*_args, **_kwargs) -> None:
        raise SQLAlchemyError("simulated tenant-state outage")

    monkeypatch.setattr(client.app.state.tenant_state_cache, "snapshot", fail_snapshot)

    response = client.get(
        "/identity/session",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "tenant_state_unavailable"
    assert _usage_events(factory, TENANT_ID) == []


def test_api_request_rejected_by_rate_limit_is_not_metered() -> None:
    client, factory = _build_client(
        _metering_settings(
            api_rate_limit_enabled=True,
            api_rate_limit_requests=1,
            api_rate_limit_paths=["/identity/session"],
        )
    )
    _set_bearer_principal(client)
    headers = {"Authorization": "Bearer valid-token"}

    assert client.get("/identity/session", headers=headers).status_code == 200
    rejected = client.get("/identity/session", headers=headers)

    assert rejected.status_code == 429
    assert len(_usage_events(factory, TENANT_ID)) == 1


@pytest.mark.parametrize(
    ("failure_mode", "expected_status", "handler_called"),
    [
        ("closed", 503, False),
        ("open", 200, True),
    ],
)
def test_usage_admission_failure_mode_controls_handler_execution(
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    expected_status: int,
    handler_called: bool,
) -> None:
    client, factory = _build_client(
        _metering_settings(usage_metering_failure_mode=failure_mode)
    )
    _set_bearer_principal(client)
    called = False

    def fail_admission(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated metering database outage")

    monkeypatch.setattr(
        client.app.state.request_usage_admission_recorder,
        "record",
        fail_admission,
    )

    @client.app.get("/test/usage-admission-failure")
    def handler(
        _principal: Annotated[OidcPrincipal | None, Depends(oidc_principal)],
    ) -> dict[str, bool]:
        nonlocal called
        called = True
        return {"ok": True}

    response = client.get(
        "/test/usage-admission-failure",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == expected_status
    assert called is handler_called
    assert _usage_events(factory, TENANT_ID) == []


def test_api_request_not_metered_without_verified_principal() -> None:
    settings = _metering_settings()
    client, factory = _build_client(settings)

    assert client.get("/deployment/readiness").status_code == 200

    assert _usage_events(factory, TENANT_ID) == []


def test_api_request_not_metered_when_disabled() -> None:
    settings = _metering_settings(usage_metering_enabled=False)
    client, factory = _build_client(settings)
    _set_bearer_principal(client)

    assert (
        client.get(
            "/identity/session",
            headers={"Authorization": "Bearer valid-token"},
        ).status_code
        == 200
    )

    assert _usage_events(factory, TENANT_ID) == []
    assert _usage_rows(factory, TENANT_ID) == []


# --------------------------------------------------------------------------- #
# Choke point: session_created via the OIDC callback                           #
# --------------------------------------------------------------------------- #


def test_session_created_metered_on_oidc_callback() -> None:
    settings = _oidc_settings(
        oidc_session_cookie_secure=False,
        usage_metering_enabled=True,
    )
    client, factory, _token_requests, id_token_context = _app_with_static_oidc(
        settings,
        token_secret="axis-test-secret",
    )
    state = _start_oidc_login(client, id_token_context, return_to="/settings")

    callback = client.get(f"/identity/oidc/callback?code=valid-code&state={state}")
    assert callback.status_code == 307

    rows = _usage_rows(factory, "tenant_demo_manufacturing")
    assert len(rows) == 1
    assert rows[0].metric_key == TenantUsageMetric.SESSION_CREATED.value
    assert rows[0].quantity == 1


def test_api_request_metering_has_persisted_cookie_parity() -> None:
    settings = _oidc_settings(
        oidc_session_cookie_secure=False,
        usage_metering_enabled=True,
    )
    client, factory, _token_requests, id_token_context = _app_with_static_oidc(
        settings,
        token_secret="axis-test-secret",
    )
    state = _start_oidc_login(client, id_token_context, return_to="/settings")
    assert client.get(
        f"/identity/oidc/callback?code=valid-code&state={state}"
    ).status_code == 307

    response = client.get("/identity/session")

    assert response.status_code == 200
    request_events = [
        event
        for event in _usage_events(factory, "tenant_demo_manufacturing")
        if event.metric_key == TenantUsageMetric.API_REQUEST.value
    ]
    assert len(request_events) == 1
    assert request_events[0].dimensions["session_source"] == "secure_cookie"


def test_session_created_not_metered_when_disabled() -> None:
    settings = _oidc_settings(oidc_session_cookie_secure=False)
    client, factory, _token_requests, id_token_context = _app_with_static_oidc(
        settings,
        token_secret="axis-test-secret",
    )
    state = _start_oidc_login(client, id_token_context, return_to="/settings")

    assert client.get(f"/identity/oidc/callback?code=valid-code&state={state}").status_code == 307
    assert _usage_rows(factory, "tenant_demo_manufacturing") == []


# --------------------------------------------------------------------------- #
# Read API                                                                     #
# --------------------------------------------------------------------------- #


def test_usage_read_returns_aggregated_totals_and_breakdown() -> None:
    client, factory = _build_client()
    _provision_tenant(factory)
    now = datetime.now(UTC)
    today = now.replace(hour=6, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    _seed_usage(factory, TENANT_ID, TenantUsageMetric.API_REQUEST.value, 10, today)
    _seed_usage(factory, TENANT_ID, TenantUsageMetric.API_REQUEST.value, 5, yesterday)
    _seed_usage(factory, TENANT_ID, TenantUsageMetric.SESSION_CREATED.value, 2, today)

    response = client.get(f"/platform/tenants/{TENANT_ID}/usage?last_days=7")
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == TENANT_ID
    totals = {row["metric_key"]: row["quantity"] for row in body["metric_totals"]}
    assert totals == {"api_request": 15, "session_created": 2}
    # Breakdown: api_request spans two periods, session_created one.
    api_points = [p for p in body["periods"] if p["metric_key"] == "api_request"]
    assert len(api_points) == 2
    assert sum(p["quantity"] for p in api_points) == 15


def test_usage_read_period_filtering_excludes_out_of_window() -> None:
    client, factory = _build_client()
    _provision_tenant(factory)
    now = datetime.now(UTC)
    recent = now.replace(hour=6, minute=0, second=0, microsecond=0)
    old = recent - timedelta(days=40)
    _seed_usage(factory, TENANT_ID, TenantUsageMetric.API_REQUEST.value, 9, recent)
    _seed_usage(factory, TENANT_ID, TenantUsageMetric.API_REQUEST.value, 99, old)

    response = client.get(f"/platform/tenants/{TENANT_ID}/usage?last_days=7")
    assert response.status_code == 200
    totals = {row["metric_key"]: row["quantity"] for row in response.json()["metric_totals"]}
    assert totals == {"api_request": 9}


def test_usage_read_empty_when_no_usage() -> None:
    client, factory = _build_client()
    _provision_tenant(factory)

    response = client.get(f"/platform/tenants/{TENANT_ID}/usage")
    assert response.status_code == 200
    body = response.json()
    assert body["metric_totals"] == []
    assert body["periods"] == []


def test_usage_read_isolates_tenants() -> None:
    client, factory = _build_client()
    _provision_tenant(factory, TENANT_ID)
    _provision_tenant(factory, OTHER_TENANT_ID)
    now = datetime.now(UTC).replace(hour=6, minute=0, second=0, microsecond=0)
    _seed_usage(factory, TENANT_ID, TenantUsageMetric.API_REQUEST.value, 3, now)
    _seed_usage(factory, OTHER_TENANT_ID, TenantUsageMetric.API_REQUEST.value, 100, now)

    response = client.get(f"/platform/tenants/{TENANT_ID}/usage")
    totals = {row["metric_key"]: row["quantity"] for row in response.json()["metric_totals"]}
    assert totals == {"api_request": 3}


def test_usage_read_missing_tenant_returns_404() -> None:
    client, _factory = _build_client()
    response = client.get("/platform/tenants/tenant_absent/usage")
    assert response.status_code == 404


def test_usage_read_rejects_invalid_window() -> None:
    client, factory = _build_client()
    _provision_tenant(factory)
    response = client.get(
        f"/platform/tenants/{TENANT_ID}/usage",
        params={"from": "2999-01-01T00:00:00Z", "to": "2000-01-01T00:00:00Z"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_usage_window"


def test_usage_read_naive_future_from_yields_422_not_500() -> None:
    # A naive `from` (no tz) with `to` omitted compares against an aware now();
    # normalization must yield a clean 422, not a TypeError-driven 500.
    client, factory = _build_client()
    _provision_tenant(factory)
    response = client.get(
        f"/platform/tenants/{TENANT_ID}/usage",
        params={"from": "2999-01-01T00:00:00"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_usage_window"


def test_usage_read_requires_operator_and_usage_scopes_when_authenticated() -> None:
    client, factory = _build_client()
    _provision_tenant(factory)
    bearer = {"Authorization": "Bearer valid-token"}

    # Missing the operator scope: denied.
    client.app.state.identity_verifier = _StaticVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=["platform:tenant:usage"],
        )
    )
    denied = client.get(f"/platform/tenants/{TENANT_ID}/usage", headers=bearer)
    assert denied.status_code == 403
    assert denied.json()["detail"]["required_permission"] == "platform:tenant:operator"

    # Missing the usage scope: denied.
    client.app.state.identity_verifier = _StaticVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=["platform:tenant:operator", "platform:tenant:read"],
        )
    )
    denied_usage = client.get(f"/platform/tenants/{TENANT_ID}/usage", headers=bearer)
    assert denied_usage.status_code == 403
    assert denied_usage.json()["detail"]["required_permission"] == "platform:tenant:usage"

    # Operator + usage: allowed cross-tenant (operator reads any tenant).
    client.app.state.identity_verifier = _StaticVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=USAGE_SCOPES,
        )
    )
    allowed = client.get(f"/platform/tenants/{TENANT_ID}/usage", headers=bearer)
    assert allowed.status_code == 200


# --------------------------------------------------------------------------- #
# build_tenant_usage_summary service + migration                              #
# --------------------------------------------------------------------------- #


def test_build_tenant_usage_summary_raises_for_missing_tenant() -> None:
    from axis_api.platform_tenants import TenantNotFound

    factory = _factory()
    with factory() as session:
        repository = AxisPersistenceRepository(session)
        raised = False
        try:
            build_tenant_usage_summary(
                repository,
                "tenant_absent",
                window_start=datetime.now(UTC) - timedelta(days=1),
                window_end=datetime.now(UTC),
            )
        except TenantNotFound:
            raised = True
        assert raised


def test_migration_0049_identifier_and_down_revision() -> None:
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0049_tenant_usage_records.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0049", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "0049_tenant_usage_records"
    assert migration.down_revision == "0048_session_device_metadata"


def test_tenant_usage_records_schema_has_unique_bucket_constraint() -> None:
    table = TenantUsageRecord.__table__
    assert table.name == "tenant_usage_records"
    unique_columns = {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert (
        "metric_key",
        "period_start",
        "period_window_seconds",
        "tenant_id",
    ) in unique_columns


def test_migration_0052_identifier_and_down_revision() -> None:
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0052_tenant_usage_event_journal.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0052", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "0052_tenant_usage_event_journal"
    assert migration.down_revision == "0051_agent_runs"


def test_migration_0053_identifier_and_down_revision() -> None:
    import importlib.util
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0053_usage_event_projection.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0053", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "0053_usage_event_projection"
    assert migration.down_revision == "0052_tenant_usage_event_journal"


def test_migration_0053_backfills_legacy_events_and_guards_downgrade(tmp_path) -> None:
    from pathlib import Path

    from alembic.command import downgrade, stamp, upgrade
    from alembic.config import Config
    from sqlalchemy import text

    # Raw SQL text has no SQLAlchemy type processor, so make the Python 3.12
    # DB-API conversion explicit instead of relying on sqlite3's deprecated default.
    sqlite3.register_adapter(datetime, _adapt_sqlite_datetime)
    database_path = tmp_path / "usage-projection.sqlite"
    database_url = f"sqlite+pysqlite:///{database_path}"
    engine = create_engine(database_url)
    old_schema = """
        CREATE TABLE tenant_usage_events (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(80) NOT NULL,
            metric_key VARCHAR(80) NOT NULL,
            source_type VARCHAR(80) NOT NULL,
            source_id VARCHAR(200) NOT NULL,
            period_start DATETIME NOT NULL,
            period_window_seconds INTEGER NOT NULL,
            quantity BIGINT NOT NULL,
            dimensions JSON NOT NULL,
            occurred_at DATETIME NOT NULL,
            recorded_at DATETIME NOT NULL
        )
    """
    with engine.begin() as connection:
        connection.execute(text(old_schema))

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    stamp(config, "0052_tenant_usage_event_journal")
    moment = datetime(2026, 7, 10, 8, tzinfo=UTC)
    insert_event = text(
        "INSERT INTO tenant_usage_events "
        "(id, tenant_id, metric_key, source_type, source_id, period_start, "
        "period_window_seconds, quantity, dimensions, occurred_at, recorded_at) "
        "VALUES (:id, :tenant_id, 'api_request', :source_type, :source_id, "
        ":moment, 86400, 1, '{}', :moment, :moment)"
    )
    with engine.begin() as connection:
        connection.execute(
            insert_event,
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "tenant_id": TENANT_ID,
                "source_type": "legacy_synchronous",
                "source_id": "legacy-1",
                "moment": moment,
            },
        )

    upgrade(config, "0053_usage_event_projection")
    with engine.begin() as connection:
        projected_at, recorded_at = connection.execute(
            text("SELECT projected_at, recorded_at FROM tenant_usage_events")
        ).one()
        assert projected_at == recorded_at
        connection.execute(
            insert_event,
            {
                "id": "00000000-0000-0000-0000-000000000002",
                "tenant_id": TENANT_ID,
                "source_type": "api_request_admission",
                "source_id": "pending-1",
                "moment": moment,
            },
        )
        connection.execute(
            text(
                "UPDATE tenant_usage_events SET projected_at = NULL "
                "WHERE source_id = 'pending-1'"
            )
        )

    with pytest.raises(RuntimeError, match="awaiting projection"):
        downgrade(config, "0052_tenant_usage_event_journal")

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE tenant_usage_events SET projected_at = recorded_at "
                "WHERE projected_at IS NULL"
            )
        )
    downgrade(config, "0052_tenant_usage_event_journal")


def test_tenant_usage_event_schema_has_source_identity_constraint() -> None:
    table = TenantUsageEvent.__table__
    assert table.name == "tenant_usage_events"
    unique_columns = {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("metric_key", "source_id", "source_type", "tenant_id") in unique_columns
    assert "projected_at" in table.columns
    assert "ix_tenant_usage_events_unprojected" in {
        index.name for index in table.indexes
    }
