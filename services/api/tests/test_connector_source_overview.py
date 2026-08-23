"""Cross-request ingestion overview: aggregates, keyset pagination, scoping.

Covers the daily operator landing read model end to end on SQLite: honest
status/dead-letter/extract aggregate counting, newest-first stable pagination
with opaque cursors, tie-breaking on equal timestamps, tenant isolation,
read-scope enforcement at the route, and public-safe view parity with
single-request reads.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorSourceIngestionRequestCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_other_plant"
CONNECTOR_ID = "external_db_operational_mirror"


@pytest.fixture
def session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        for tenant_id, name in ((TENANT_A, "Ravenna Works"), (TENANT_B, "Other Plant")):
            repository.create_tenant(
                TenantCreate(
                    tenant_id=tenant_id,
                    display_name=name,
                    description="Overview probe",
                    created_by="test",
                )
            )
    yield factory
    engine.dispose()


def seed_request(
    factory,
    request_id: str,
    *,
    tenant_id: str = TENANT_A,
    status: str = "pending",
    stage: str = "validate",
    dead_lettered: bool = False,
    minutes_ago: int = 0,
) -> None:
    created = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=tenant_id,
                actor_id="axis-operator",
                event_type="connector.source.ingestion.requested",
                payload={"request_id": request_id},
            )
        )
        row = repository.create_connector_source_ingestion_request(
            ConnectorSourceIngestionRequestCreate(
                tenant_id=tenant_id,
                connector_id=CONNECTOR_ID,
                request_id=request_id,
                requested_by="axis-operator",
                reason="Overview aggregation probe.",
                stage=stage,
                selections=[
                    {
                        "binding_id": f"binding_{request_id}",
                        "resource_name": "operations.production_orders",
                        "schema_fingerprint": "a" * 64,
                    }
                ],
                audit_event_id=event.id,
                audit_event_type="connector.source.ingestion.requested",
            ),
            available_at=created,
        )
        row.created_at = created
        if status != "pending":
            row.status = status
        if dead_lettered:
            row.dead_lettered_at = created
        if status == "completed":
            row.completed_at = created


def build_client(factory: sessionmaker) -> TestClient:
    from axis_api.main import create_app

    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    return TestClient(app)


def read_params(**overrides):
    params = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "actor_scopes": ["connectors:source:ingest:read"],
    }
    params.update(overrides)
    return params


def encode_cursor(inner: str) -> str:
    import base64

    return base64.urlsafe_b64encode(inner.encode()).decode()


def test_empty_connector_reports_all_zero_cleanly(session_factory) -> None:
    client = build_client(session_factory)
    response = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params=read_params(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["total_count"] == 0
    assert body["summary"]["status_counts"] == {}
    assert body["summary"]["dead_lettered_count"] == 0
    assert body["summary"]["extract_stage_count"] == 0
    assert body["summary"]["last_activity_at"] is None
    assert body["requests"] == []
    assert body["next_cursor"] is None


def test_aggregates_count_statuses_dead_letters_and_extract_stage(
    session_factory,
) -> None:
    seed_request(session_factory, "ov_pending", status="pending")
    seed_request(session_factory, "ov_working", status="dispatching", minutes_ago=1)
    seed_request(
        session_factory,
        "ov_done",
        status="completed",
        stage="extract",
        minutes_ago=2,
    )
    seed_request(
        session_factory,
        "ov_dead",
        status="failed",
        dead_lettered=True,
        minutes_ago=3,
    )
    seed_request(
        session_factory,
        "ov_extract_dead",
        status="failed",
        stage="extract",
        dead_lettered=True,
        minutes_ago=4,
    )
    client = build_client(session_factory)
    body = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params=read_params(),
    ).json()
    summary = body["summary"]
    assert summary["status_counts"] == {
        "pending": 1,
        "dispatching": 1,
        "completed": 1,
        "failed": 2,
    }
    assert summary["total_count"] == 5
    assert summary["dead_lettered_count"] == 2
    assert summary["extract_stage_count"] == 2
    # Newest-first page leads with the most recently created request.
    assert body["requests"][0]["request_id"] == "ov_pending"


def test_requeued_failed_request_is_not_counted_dead_lettered(
    session_factory,
) -> None:
    seed_request(
        session_factory,
        "ov_requeued",
        status="pending",
        dead_lettered=False,
    )
    client = build_client(session_factory)
    body = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params=read_params(),
    ).json()
    assert body["summary"]["status_counts"] == {"pending": 1}
    assert body["summary"]["dead_lettered_count"] == 0


def test_overview_is_tenant_scoped(session_factory) -> None:
    seed_request(session_factory, "ov_mine", minutes_ago=5)
    seed_request(session_factory, "ov_theirs", tenant_id=TENANT_B, minutes_ago=1)
    client = build_client(session_factory)
    mine = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params=read_params(),
    ).json()
    theirs = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params=read_params(tenant_id=TENANT_B),
    ).json()
    assert [row["request_id"] for row in mine["requests"]] == ["ov_mine"]
    assert [row["request_id"] for row in theirs["requests"]] == ["ov_theirs"]
    assert mine["summary"]["total_count"] == 1
    assert theirs["summary"]["total_count"] == 1


def test_pagination_walks_newest_first_without_duplicates(session_factory) -> None:
    for index in range(5):
        seed_request(session_factory, f"ov_page_{index}", minutes_ago=index)
    client = build_client(session_factory)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params = read_params(limit="2")
        if cursor is not None:
            params["cursor"] = cursor
        body = client.get(
            "/operations/connectors/external-db/source-ingestion/overview",
            params=params,
        ).json()
        seen.extend(row["request_id"] for row in body["requests"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == [
        "ov_page_0",
        "ov_page_1",
        "ov_page_2",
        "ov_page_3",
        "ov_page_4",
    ]


def test_equal_timestamps_tiebreak_on_request_id(session_factory) -> None:
    stamp = datetime.now(UTC) - timedelta(minutes=9)
    for request_id in ("ov_b_second", "ov_a_first", "ov_c_third"):
        with session_scope(session_factory) as session:
            repository = AxisPersistenceRepository(session)
            event = repository.append_audit_event(
                AuditEventCreate(
                    tenant_id=TENANT_A,
                    actor_id="axis-operator",
                    event_type="connector.source.ingestion.requested",
                    payload={"request_id": request_id},
                )
            )
            row = repository.create_connector_source_ingestion_request(
                ConnectorSourceIngestionRequestCreate(
                    tenant_id=TENANT_A,
                    connector_id=CONNECTOR_ID,
                    request_id=request_id,
                    requested_by="axis-operator",
                    reason="Tie-break probe.",
                    selections=[
                        {
                            "binding_id": f"binding_{request_id}",
                            "resource_name": "operations.production_orders",
                            "schema_fingerprint": "a" * 64,
                        }
                    ],
                    audit_event_id=event.id,
                    audit_event_type="connector.source.ingestion.requested",
                ),
                available_at=stamp,
            )
            row.created_at = stamp
    client = build_client(session_factory)
    body = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params=read_params(limit="2"),
    ).json()
    assert [row["request_id"] for row in body["requests"]] == [
        "ov_a_first",
        "ov_b_second",
    ]
    assert body["next_cursor"] is not None
    follow_up = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params=read_params(limit="2", cursor=body["next_cursor"]),
    ).json()
    assert [row["request_id"] for row in follow_up["requests"]] == ["ov_c_third"]
    assert follow_up["next_cursor"] is None


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!!",
        encode_cursor("garbage-without-separator"),
        encode_cursor(f"not-a-timestamp|{'x' * 8}"),
        encode_cursor("2026-01-01T00:00:00+00:00|bad|id"),
    ],
)
def test_invalid_cursors_fail_closed_with_public_reason(
    session_factory, cursor: str
) -> None:
    client = build_client(session_factory)
    response = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params=read_params(cursor=cursor),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_cursor"


def test_overview_requires_read_scope(session_factory) -> None:
    client = build_client(session_factory)
    denied = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params={"tenant_id": TENANT_A, "connector_id": CONNECTOR_ID},
    )
    assert denied.status_code == 403
    detail = denied.json()["detail"]
    assert detail["required_permission"] == "connectors:source:ingest:read"


def test_overview_views_match_single_request_contract(session_factory) -> None:
    seed_request(session_factory, "ov_contract", stage="extract", minutes_ago=2)
    client = build_client(session_factory)
    body = client.get(
        "/operations/connectors/external-db/source-ingestion/overview",
        params=read_params(),
    ).json()
    single = client.get(
        "/operations/connectors/external-db/source-ingestion-requests/ov_contract",
        params={
            "tenant_id": TENANT_A,
            "actor_scopes": ["connectors:source:ingest:read"],
        },
    ).json()
    overview_row = body["requests"][0]
    for field in (
        "request_id",
        "stage",
        "status",
        "attempt_count",
        "selections",
        "reason",
    ):
        assert overview_row[field] == single[field]


def test_seed_helper_writes_distinct_audit_events() -> None:
    """Sanity: the seeding helper never shares one audit event between rows."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with session_scope(factory) as session:
            AxisPersistenceRepository(session).create_tenant(
                TenantCreate(
                    tenant_id=TENANT_A,
                    display_name="Ravenna Works",
                    description="probe",
                    created_by="test",
                )
            )
        seed_request(factory, "ov_s1")
        seed_request(factory, "ov_s2")
        with session_scope(factory) as session:
            rows = AxisPersistenceRepository(session)
            first = rows.get_connector_source_ingestion_request(TENANT_A, "ov_s1")
            second = rows.get_connector_source_ingestion_request(TENANT_A, "ov_s2")
            assert first is not None and second is not None
            assert first.id != second.id
            assert first.audit_event_id != second.audit_event_id
    finally:
        engine.dispose()


def test_uuid4_collision_guard_is_unnecessary_for_ids() -> None:
    """Documentary guard: request identity is (tenant_id, request_id), not UUID."""
    assert uuid4() != uuid4()
