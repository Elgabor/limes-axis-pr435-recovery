from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import AuditEvent, Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    DemoReferenceRecordCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_other_plant"
ASSET_A = "source:file_csv_manufacturing_assets:default"
RESOURCE = "assets.csv"


def reference_registry_payload() -> dict:
    return {
        "tenant_id": TENANT_A,
        "plant_name": "Ravenna Works",
        "scenario": "Data Contract Fixture",
        "registry_status": "ready",
        "metrics": [
            {
                "label": "Persisted Connector Registry",
                "value": "1",
                "detail": "Loaded from demo_reference_records.",
                "status": "ready",
            }
        ],
        "connectors": [
            {
                "connector_status": "ready",
                "manifest": {
                    "connector_id": "file_csv_manufacturing_assets",
                    "display_name": "Manufacturing assets CSV",
                    "connector_type": "file_csv",
                    "version": "2026-08-21",
                    "source_type": "file",
                    "sync_modes": ["preview"],
                    "runtime_boundary": "axis-connector-sandbox",
                    "required_permissions": ["connectors:read"],
                    "credential_requirements": {
                        "storage": "none",
                        "required_secret_refs": [],
                        "notes": [],
                    },
                    "schema_fields": [
                        {
                            "source_column": "asset_id",
                            "target_field": "node_id",
                            "ontology_target": "manufacturing_asset",
                            "data_type": "string",
                            "required": True,
                            "description": "Asset identifier.",
                        },
                        {
                            "source_column": "station",
                            "target_field": "station",
                            "ontology_target": "manufacturing_station",
                            "data_type": "string",
                            "required": False,
                            "description": "Station.",
                        },
                    ],
                    "mapping_notes": [],
                },
                "runtime_policy": {
                    "allowed_operations": ["schema_validate", "metadata_preview"],
                    "blocked_operations": ["live_sync"],
                    "egress_policy": "no-external-egress",
                    "max_file_size_mb": 5,
                    "row_limit": 500,
                    "payload_policy": "metadata-only",
                },
            }
        ],
        "connector_notes": [],
    }


class StaticIdentityVerifier:
    def __init__(self, principal: OidcPrincipal) -> None:
        self.principal = principal

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        assert authorization == "Bearer valid-token"
        return self.principal


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
        repository.create_tenant(
            TenantCreate(
                tenant_id=TENANT_A,
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
        repository.create_tenant(
            TenantCreate(
                tenant_id=TENANT_B,
                display_name="Other Plant",
                description="Second tenant",
                created_by="test",
            )
        )
        repository.upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=TENANT_A,
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-08-21",
                payload=reference_registry_payload(),
            )
        )
    yield factory
    engine.dispose()


def build_client(session_factory: sessionmaker) -> TestClient:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    return TestClient(app)


def contract_payload(
    *,
    fingerprint: str | None = None,
    warn_hours: int | None = None,
    fail_hours: int | None = None,
    expected_revision: int | None = None,
    idempotency_key: str = "contract-idem-001",
) -> dict:
    payload = {
        "expected_resource_name": RESOURCE,
        "idempotency_key": idempotency_key,
    }
    if fingerprint is not None:
        payload["expected_schema_fingerprint"] = fingerprint
    if warn_hours is not None:
        payload["freshness_warn_hours"] = warn_hours
    if fail_hours is not None:
        payload["freshness_fail_hours"] = fail_hours
    if expected_revision is not None:
        payload["expected_revision"] = expected_revision
    return payload


def run_ready_preview(client: TestClient, csv_content: str) -> dict:
    response = client.post(
        "/operations/connectors/file-csv/preview",
        json={
            "tenant_id": TENANT_A,
            "connector_id": "file_csv_manufacturing_assets",
            "file_name": RESOURCE,
            "csv_content": csv_content,
        },
    )
    assert response.status_code == 200
    return response.json()


def audit_count(factory: sessionmaker, event_type: str) -> int:
    with session_scope(factory) as session:
        return len(
            session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == event_type)
            ).all()
        )


def evaluation(
    client: TestClient,
) -> tuple[str, list[dict]]:
    response = client.get(
        f"/data/assets/{ASSET_A}/contract/evaluation",
        params={"tenant_id": TENANT_A},
    )
    assert response.status_code == 200
    body = response.json()
    return body["status"], body["checks"]


def check_by_kind(checks: list[dict], kind: str) -> dict:
    return next(check for check in checks if check["kind"] == kind)


def test_evaluation_is_unknown_without_contract(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    status, checks = evaluation(client)

    assert status == "unknown"
    assert checks == []


def test_contract_view_is_null_before_declaration(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.get(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
    )

    assert response.status_code == 200
    assert response.json()["contract"] is None


def test_first_declaration_creates_revision_and_audit_event(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=12, fail_hours=48),
    )

    assert response.status_code == 201
    contract = response.json()["contract"]
    assert contract["expected_resource_name"] == RESOURCE
    assert contract["revision_number"] == 1
    assert audit_count(session_factory, "data.contract.declared") == 1


def test_update_appends_revision_marks_previous_replaced(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=12),
    )

    response = client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=24, expected_revision=1, idempotency_key="c2"),
    )

    assert response.status_code == 200
    assert response.json()["contract"]["revision_number"] == 2
    from axis_api.models import DataAssetContractRecord

    with session_scope(session_factory) as session:
        records = list(session.scalars(select(DataAssetContractRecord)).all())
    assert len(records) == 2
    assert any(record.replaced_by_revision_number == 2 for record in records)
    assert audit_count(session_factory, "data.contract.updated") == 1


def test_stale_revision_conflicts_with_current_revision(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=12),
    )

    stale = client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=24, expected_revision=5, idempotency_key="s"),
    )
    missing = client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(idempotency_key="m"),
    )

    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["reason"] == "expected_revision_mismatch"
    assert detail["current_revision"] == 1
    assert missing.status_code == 409


def test_replayed_key_converges_changed_key_conflicts(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    first = client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=12),
    )

    replay = client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=12),
    )
    changed = client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=99),
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["contract"]["revision_number"] == 1
    assert changed.status_code == 409
    assert changed.json()["detail"]["reason"] == "revision_idempotency_conflict"


def test_passing_evaluation_on_fresh_matching_observation(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    observed = run_ready_preview(client, "asset_id,station\nA-1,line-1\n")
    fingerprint = observed["observed_schema"]["fingerprint"]
    client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(fingerprint=fingerprint, warn_hours=12, fail_hours=48),
    )

    status, checks = evaluation(client)

    assert status == "pass"
    assert {check["state"] for check in checks} == {"pass"}
    kinds = {check["kind"] for check in checks}
    assert kinds == {"presence", "schema", "freshness"}


def test_schema_mismatch_fails_evaluation(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    run_ready_preview(client, "asset_id,station\nA-1,line-1\n")
    client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(fingerprint="f" * 64),
    )

    status, checks = evaluation(client)

    schema_check = check_by_kind(checks, "schema")
    assert status == "fail"
    assert schema_check["state"] == "fail"


def test_stale_observation_warns_then_fails_past_threshold(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    run_ready_preview(client, "asset_id,station\nA-1,line-1\n")
    client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=1, fail_hours=48),
    )

    recent_time = datetime.now(UTC) + timedelta(hours=2)
    app_state = client.app.state
    with session_scope(app_state.session_factory) as session:
        from axis_api.models import DataAssetResourceObservation

        record = session.scalars(select(DataAssetResourceObservation)).first()
        record.last_seen_at = datetime.now(UTC) - timedelta(hours=2)
        session.flush()
    warn_status, warn_checks = evaluation(client)
    # Freeze-free deterministic check: backdate far beyond the threshold.
    with session_scope(app_state.session_factory) as session:
        from axis_api.models import DataAssetResourceObservation

        record = session.scalars(select(DataAssetResourceObservation)).first()
        record.last_seen_at = datetime.now(UTC) - timedelta(hours=72)
        session.flush()
    fail_status, fail_checks = evaluation(client)

    assert check_by_kind(warn_checks, "freshness")["state"] == "warn"
    assert warn_status == "warn"
    assert check_by_kind(fail_checks, "freshness")["state"] == "fail"
    assert fail_status == "fail"
    del recent_time


def test_never_observed_resource_fails_presence(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    client.put(
        f"/data/assets/{ASSET_A}/contract",
        params={"tenant_id": TENANT_A},
        json=contract_payload(warn_hours=12, fail_hours=48),
    )

    status, checks = evaluation(client)

    presence = check_by_kind(checks, "presence")
    assert status == "fail"
    assert presence["state"] == "fail"
    assert "never been observed" in presence["detail"]


def test_unknown_asset_fails_closed_and_cross_tenant_rejected(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    unknown = client.get(
        "/data/assets/source:not_a_real_asset:default/contract",
        params={"tenant_id": TENANT_A},
    )

    assert unknown.status_code == 404
    assert unknown.json()["detail"]["surface"] == "data"

    authenticated = build_client(session_factory)
    authenticated.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="actor-b",
            tenant_id=TENANT_B,
            scopes=["connectors:read"],
        )
    )
    cross_tenant = authenticated.get(
        f"/data/assets/{ASSET_A}/contract/evaluation",
        params={"tenant_id": TENANT_A},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert cross_tenant.status_code == 403
    assert cross_tenant.json()["detail"]["reason"] == "tenant_mismatch"
