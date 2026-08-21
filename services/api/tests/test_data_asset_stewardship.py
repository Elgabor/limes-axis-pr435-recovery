from datetime import datetime

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


def reference_registry_payload() -> dict:
    return {
        "tenant_id": TENANT_A,
        "plant_name": "Ravenna Works",
        "scenario": "Stewardship Fixture",
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
                        }
                    ],
                    "mapping_notes": [],
                },
                "runtime_policy": {
                    "allowed_operations": ["schema_validate"],
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


def stewardship_payload(
    *,
    expected_revision: int | None = None,
    idempotency_key: str = "idem-001",
    classification: str = "internal",
) -> dict:
    payload = {
        "owner": "plant-data-team",
        "classification": classification,
        "residency": "eu-central",
        "retention": "retain_7_years",
        "notes": ["Declared during onboarding."],
        "idempotency_key": idempotency_key,
    }
    if expected_revision is not None:
        payload["expected_revision"] = expected_revision
    return payload


def audit_count(factory: sessionmaker, event_type: str) -> int:
    with session_scope(factory) as session:
        return len(
            session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == event_type)
            ).all()
        )


def test_stewardship_view_is_null_before_declaration(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.get(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == TENANT_A
    assert body["asset_id"] == ASSET_A
    assert body["stewardship"] is None


def test_first_declaration_creates_revision_one_and_audit_event(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    stewardship = body["stewardship"]
    assert stewardship["owner"] == "plant-data-team"
    assert stewardship["classification"] == "internal"
    assert stewardship["revision_number"] == 1
    assert stewardship["declared_by"] == "public-demo-steward"
    assert audit_count(session_factory, "data.stewardship.declared") == 1


def test_update_appends_revision_and_marks_previous_replaced(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(),
    )

    response = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(
            expected_revision=1,
            idempotency_key="idem-002",
            classification="confidential",
        ),
    )

    assert response.status_code == 200
    assert response.json()["stewardship"]["revision_number"] == 2
    with session_scope(session_factory) as session:
        records = list(
            session.scalars(
                select(_stewardship_model()).where(
                    _stewardship_model().tenant_id == TENANT_A
                )
            )
        )
    assert len(records) == 2
    replaced = [record for record in records if record.replaced_by_revision_number]
    assert len(replaced) == 1
    assert replaced[0].replaced_by_revision_number == 2
    assert audit_count(session_factory, "data.stewardship.updated") == 1


def _stewardship_model():
    from axis_api.models import DataAssetStewardshipRecord

    return DataAssetStewardshipRecord


def test_stale_expected_revision_returns_structured_conflict(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(),
    )

    stale = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(
            expected_revision=5,
            idempotency_key="idem-stale",
            classification="restricted",
        ),
    )
    missing = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(idempotency_key="idem-missing"),
    )

    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "CONFLICT"
    assert detail["reason"] == "expected_revision_mismatch"
    assert detail["current_revision"] == 1
    assert missing.status_code == 409
    assert missing.json()["detail"]["reason"] == "expected_revision_mismatch"


def test_idempotent_replay_returns_existing_record_without_new_row(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    first = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(),
    )

    replay = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(expected_revision=None),
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["stewardship"]["revision_number"] == 1


def test_idempotency_key_with_changed_payload_conflicts(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(),
    )

    replay = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(classification="restricted"),
    )

    assert replay.status_code == 409
    assert replay.json()["detail"]["reason"] == "revision_idempotency_conflict"


def test_unknown_asset_fails_closed_and_cross_tenant_is_rejected(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    unknown = client.get(
        "/data/assets/source:not_a_real_asset:default/stewardship",
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
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert cross_tenant.status_code == 403
    assert cross_tenant.json()["detail"]["reason"] == "tenant_mismatch"


def test_catalog_governance_becomes_declared_after_stewardship(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    before = client.get("/data/assets", params={"tenant_id": TENANT_A})
    assert before.json()["assets"][0]["governance"] == "partial"

    declared = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(),
    )
    assert declared.status_code == 201

    after = client.get("/data/assets", params={"tenant_id": TENANT_A})
    asset = after.json()["assets"][0]
    assert asset["governance"] == "declared"
    assert asset["stewardship"]["owner"] == "plant-data-team"
    assert asset["stewardship"]["classification"] == "internal"
    assert asset["stewardship"]["revision_number"] == 1
    assert set(asset["stewardship"].keys()) == {
        "owner",
        "classification",
        "residency",
        "retention",
        "revision_number",
    }


def test_principal_actor_overrides_declared_body_actor(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="actor-enterprise",
            tenant_id=TENANT_A,
            scopes=["connectors:read"],
        )
    )

    response = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        headers={"Authorization": "Bearer valid-token"},
        json={
            **stewardship_payload(),
            "declared_by": "spoofed-actor",
        },
    )

    assert response.status_code == 201
    assert response.json()["stewardship"]["declared_by"] == "actor-enterprise"


def test_declared_at_reflects_persisted_timestamp(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.put(
        f"/data/assets/{ASSET_A}/stewardship",
        params={"tenant_id": TENANT_A},
        json=stewardship_payload(),
    )

    declared_at = response.json()["stewardship"]["declared_at"]
    assert datetime.fromisoformat(declared_at).tzinfo is not None or "T" in declared_at
