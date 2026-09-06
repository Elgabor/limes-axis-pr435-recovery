"""HTTP parity, payload bounds and failure isolation for the console projection."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from test_connector_run_oidc_binding import StaticIdentityVerifier
from test_connectors import connector_registry_payload, seed_connector_registry_reference

from axis_api import connector_workspace
from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_manifests import (
    ConnectorManifestCreateRequest,
    record_demo_connector_manifest,
)
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorEgressPolicyCreate,
    ConnectorOntologyProposalCreate,
    ConnectorRunCreate,
    TenantCreate,
)

TENANT = "tenant_demo_manufacturing"
CONNECTOR = "file_csv_manufacturing_assets"
PREFIX = "/operations/connectors"
HEADERS = {"Authorization": "Bearer valid-token"}


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        for tenant in (TENANT, "other"):
            repository.create_tenant(
                TenantCreate(tenant_id=tenant, display_name=tenant, created_by="fixture")
            )
    seed_connector_registry_reference(factory)
    yield factory
    engine.dispose()


def client_for(factory, *, scopes=()):
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            oidc_auth_required=True,
            workflow_signals_enabled=False,
            api_rate_limit_enabled=False,
        )
    )
    app.state.session_factory = factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="verified-reader",
            tenant_id=TENANT,
            scopes=list(scopes),
        )
    )
    return TestClient(app)


def read(client, suffix="/workspace", **params):
    return client.get(PREFIX + suffix, params={"tenant_id": TENANT, **params}, headers=HEADERS)


def test_summary_projects_every_list_field_and_counters_from_authorized_sources(factory):
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        template = connector_registry_payload()["connectors"][0]
        record_demo_connector_manifest(
            repository,
            ConnectorManifestCreateRequest(
                registered_by="fixture",
                manifest=template["manifest"],
                runtime_policy=template["runtime_policy"],
                preview_sample=template["preview_sample"],
            ),
        )
        for i in range(105):
            repository.create_connector_run(
                ConnectorRunCreate(
                    tenant_id=TENANT,
                    connector_id=CONNECTOR,
                    run_id=f"run_{i}",
                    requested_by="fixture",
                    status="sync_execution_completed",
                    result_summary={"records_read": str(i)},
                )
            )
        proposal = repository.create_connector_ontology_proposal(
            ConnectorOntologyProposalCreate(
                tenant_id=TENANT,
                connector_id=CONNECTOR,
                proposal_id="promoted",
                proposed_by="fixture",
                source_file_name="sample.csv",
                mapping_profile="fixture",
                node_id="a",
                node_type="asset",
                ontology_type="asset",
            )
        )
        proposal.promoted_at = datetime.now(UTC)
        repository.create_connector_ontology_proposal(
            ConnectorOntologyProposalCreate(
                tenant_id=TENANT,
                connector_id=CONNECTOR,
                proposal_id="pending",
                proposed_by="fixture",
                source_file_name="sample.csv",
                mapping_profile="fixture",
                node_id="b",
                node_type="asset",
                ontology_type="asset",
            )
        )
        repository.create_connector_egress_policy(
            ConnectorEgressPolicyCreate(
                tenant_id=TENANT,
                connector_id=CONNECTOR,
                policy_id="policy",
                display_name="Policy",
                connection_profile_id="profile",
                egress_boundary="private",
                policy_mode="allowlist",
                private_endpoint_ref="endpoint-reference-must-not-enter-summary",
                created_by="fixture",
            )
        )
    # No read scopes are required by the contributing legacy reads. The new
    # projection uses the same authenticated tenant binding, field by field.
    client = client_for(factory)
    legacy = read(client, "").json()
    response = read(client, actor_id="untrusted-query-actor")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    for key in ("tenant_id", "plant_name", "scenario", "provenance", "registry_status"):
        assert body[key] == legacy[key]
    for item, full in zip(body["connectors"], legacy["connectors"], strict=True):
        assert item == {
            "manifest": {
                key: full["manifest"][key]
                for key in ("connector_id", "display_name", "connector_type")
            },
            "connector_status": full["connector_status"],
            "registry_origin": full["registry_origin"],
            "persisted_manifest": (
                {"status": full["persisted_manifest"]["status"]}
                if full["persisted_manifest"]
                else None
            ),
            "preview_sample": (
                {"record_count": full["preview_sample"]["record_count"]}
                if full["preview_sample"]
                else None
            ),
            "last_successful_sync": full["last_successful_sync"],
        }
    counts = body["counts"]
    assert counts["runs"] == len(read(client, "/runs").json()["runs"]) == 100
    assert (
        counts["pending_proposals"]
        == sum(
            proposal["promoted_at"] is None
            for proposal in read(client, "/ontology-proposals").json()["proposals"]
        )
        == 1
    )
    assert (
        counts["egress_policies"] == len(read(client, "/egress-policies").json()["policies"]) == 1
    )
    assert (
        counts["evidence_issues"]
        == len(read(client, "/evidence-invariants").json()["invariants"])
        == 1
    )
    assert counts["source_limit"] == 100
    for forbidden in (
        "schema_fields",
        "sample_rows",
        "required_secret_refs",
        "policy_document",
        "endpoint-reference-must-not-enter-summary",
        "registered_by",
    ):
        assert forbidden not in response.text
    with session_scope(factory) as session:
        audit = AxisPersistenceRepository(session).list_audit_events(
            TENANT, actor_id="verified-reader"
        )
        assert {event.event_type for event in audit} == {
            "connector.workspace_read",
            "connector.egress_policies_read",
            "connector.evidence_invariants_read",
        }
        assert not AxisPersistenceRepository(session).list_audit_events(
            TENANT, actor_id="untrusted-query-actor"
        )


@pytest.mark.parametrize(
    "suffix",
    [
        "/workspace",
        "/workspace/detail",
        "",
        "/runs",
        "/ontology-proposals",
        "/egress-policies",
        "/evidence-invariants",
        "/credential-handles",
        "/credential-leases",
    ],
)
def test_authorization_parity_rejects_missing_identity_and_foreign_tenant(factory, suffix):
    client = client_for(factory)
    params = {"tenant_id": TENANT, "connector_id": CONNECTOR}
    assert client.get(PREFIX + suffix, params=params).status_code == 401
    foreign = read(client, suffix, tenant_id="other", connector_id=CONNECTOR)
    assert foreign.status_code == 403
    assert foreign.json()["detail"]["reason"] == "tenant_mismatch"
    with session_scope(factory) as session:
        assert AxisPersistenceRepository(session).list_audit_events(TENANT) == []
        assert AxisPersistenceRepository(session).list_audit_events("other") == []


def test_pagination_and_detail_find_connectors_outside_first_page(factory):
    payload = connector_registry_payload()
    for i in range(60):
        connector = deepcopy(payload["connectors"][0])
        connector["manifest"]["connector_id"] = f"connector_{i}"
        payload["connectors"].append(connector)
    seed_connector_registry_reference(factory, payload)
    client = client_for(factory)
    first = read(client).json()
    assert first["total_connectors"] == 62
    assert len(first["connectors"]) == 25
    assert first["next_offset"] == 25
    second = read(client, offset=25).json()
    last = read(client, offset=50).json()
    ids = [
        item["manifest"]["connector_id"]
        for page in (first, second, last)
        for item in page["connectors"]
    ]
    assert ids == [item["manifest"]["connector_id"] for item in payload["connectors"]]
    assert last["next_offset"] is None
    detail = read(client, "/workspace/detail", connector_id="connector_59")
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "private, no-store"
    assert detail.json()["connector"] == read(client, "").json()["connectors"][-1]
    assert read(client, "/workspace/detail", connector_id="missing").status_code == 404
    assert read(client, offset=100).json()["connectors"] == []


@pytest.mark.parametrize(
    "params", [{"limit": 51}, {"limit": 0}, {"offset": -1}, {"offset": 1_000_001}]
)
def test_invalid_page_bounds_are_rejected(factory, params):
    assert read(client_for(factory), **params).status_code == 422


def test_page_byte_budget_fails_closed_without_truncating_identifiers(factory):
    payload = connector_registry_payload()
    payload["connectors"] = [deepcopy(payload["connectors"][0]) for _ in range(50)]
    for i, connector in enumerate(payload["connectors"]):
        connector["manifest"]["connector_id"] = f"large_{i}"
        connector["manifest"]["display_name"] = "🌍" * 512
    seed_connector_registry_reference(factory, payload)
    response = read(client_for(factory), limit=50)
    assert response.status_code == 422
    assert "large_0" not in response.text


def test_failed_counter_keeps_other_counts_and_audits(factory, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ValueError("Invalid run source")

    monkeypatch.setattr(connector_workspace, "build_connector_run_registry", unavailable)
    response = read(client_for(factory))
    assert response.status_code == 200
    assert response.json()["counts"] == {
        "runs": None,
        "pending_proposals": 0,
        "egress_policies": 0,
        "evidence_issues": 0,
        "source_limit": 100,
    }
    assert len(response.json()["connectors"]) == 2
    with session_scope(factory) as session:
        assert len(AxisPersistenceRepository(session).list_audit_events(TENANT)) == 3


def test_summary_is_fresh_after_mutation(factory):
    client = client_for(factory)
    before = read(client).json()
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).create_connector_run(
            ConnectorRunCreate(
                tenant_id=TENANT, connector_id=CONNECTOR, run_id="new_run", requested_by="fixture"
            )
        )
    after = read(client).json()
    assert before["counts"]["runs"] == 0
    assert after["counts"]["runs"] == 1
    assert after["generated_at"] != before["generated_at"]


def test_counter_failure_rolls_back_its_partial_audit_before_other_reads(factory, monkeypatch):
    def unavailable(repository, query, *, actor_id):
        repository.append_audit_event(
            AuditEventCreate(
                tenant_id=query.tenant_id,
                actor_id=actor_id,
                event_type="partial.counter.read",
                payload={},
            )
        )
        raise ValueError("Counter conversion failed after audit append")

    monkeypatch.setattr(connector_workspace, "read_connector_egress_policy_registry", unavailable)
    response = read(client_for(factory))
    assert response.status_code == 200
    assert response.json()["counts"]["egress_policies"] is None
    assert response.json()["counts"]["evidence_issues"] == 0
    with session_scope(factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(TENANT)
        assert {event.event_type for event in events} == {
            "connector.workspace_read",
            "connector.evidence_invariants_read",
        }


def test_summary_read_audits_remain_owned_by_the_callers_transaction(factory):
    with pytest.raises(RuntimeError, match="caller cancelled"), session_scope(factory) as session:
        connector_workspace.read_connector_workspace_summary(
            AxisPersistenceRepository(session), tenant_id=TENANT, actor_id="verified-reader"
        )
        raise RuntimeError("caller cancelled")
    with session_scope(factory) as session:
        assert AxisPersistenceRepository(session).list_audit_events(TENANT) == []
