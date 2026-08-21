"""Canonical, systematic tenant-isolation matrix.

This module is the single authoritative place that exercises cross-tenant
access control across the whole API surface. Scattered per-surface cross-tenant
negative tests still live in their own files (``test_approval_decisions.py``,
``test_action_runs.py``, ``test_daily_plant_brief.py``, ``test_audit_queries.py``
and friends); this module intentionally overlaps them with one table-driven
matrix so a regression on any surface is caught in one predictable place.

The model under test
--------------------
Tenant A is the demo tenant (``tenant_demo_manufacturing``). Tenant B is a second
tenant provisioned the same way the platform-tenant tests provision tenants. Two
principals are constructed with *equivalent* (identical) scopes, one in each
tenant, so any difference in outcome is attributable purely to the tenant
boundary and never to a scope difference.

For each surface group the matrix asserts the applicable subset of:

* (a) tenant B reading tenant A's resource by id -> 403/404, never 200 + data;
* (b) tenant B listing -> tenant A's records are absent;
* (c) tenant B mutating tenant A's resource -> rejected;
* (d) a token-claim tenant that differs from the path/body tenant -> rejected.

Rejections must also leave tenant A's append-only audit ledger untouched, so the
enforced-rejection cases assert the tenant A (and tenant B) audit-event counts
are unchanged across the attempt.

Connector surface enforcement
-----------------------------
The connector read/list routes (credential handles, configurations, manifests,
runs, leases, egress policies, evidence invariants, ontology proposals,
promotion policies/sets, manual imports) and the manifest-create write were
originally captured here as strict-xfail isolation leaks (threat-model item
TM-001 "add tenant-scoped query checks everywhere"): they had no principal
binding and trusted the caller-supplied ``tenant_id``. They now bind the OIDC
principal and reject a tenant mismatch with the canonical 403
``tenant_mismatch`` shape, so the cases live in the enforced tables below as
hard assertions. The remaining connector write routes (configuration,
credential handle/rotation, credential lease create/renew/revoke, egress
policy, evidence snapshot create/export-request, ontology proposal, manual
import create, manifest lifecycle, and the csv/external-db previews that read
registry state from a body ``tenant_id``) are bound the same way and covered
by ``ENFORCED_WRITE_CASES``.

The demo reference registries (agents/actions/connectors/model-routing/overview)
share the same no-binding shape but serve public demo reference content, so they
are deliberately not treated as tenant-secret leaks here.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import AuditEvent, Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorConfigurationCreate,
    ConnectorCredentialHandleCreate,
    DemoReferenceRecordCreate,
    OidcBrowserSessionCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_beta_manufacturing"
BEARER = {"Authorization": "Bearer valid-token"}

ACTOR_A = "plant-operations-owner-role"
ACTOR_B = "beta-operations-owner-role"

# Both principals carry the same broad tenant-user scope set. None of these are
# the cross-tenant ``platform:tenant:*`` operator scopes: an ordinary tenant user
# in tenant B must never reach tenant A regardless of how many ordinary scopes it
# holds. Where a surface authorizes tenant before scope, the tenant boundary is
# what these tests pin down; the generous scope set removes "missing scope" as a
# confounding explanation for any 403.
EQUIVALENT_SCOPES = [
    "audit:read",
    "audit:legal_hold:write",
    "audit:retention:delete",
    "briefs:generate",
    "workflows:read",
    "quality:read",
    "maintenance:read",
    "supply:read",
    "approvals:supply:request",
    "approvals:supply:decide",
    "approvals:connectors:decide",
    "actions:result:record",
    "simulation:replay:persist",
    "platform:policy:read",
    "platform:policy:author",
    "platform:policy:revise",
    "connectors:manifest:lifecycle",
    "connectors:promotion_policy:author",
    "connectors:promotion_policy_set:activate",
    "connectors:ontology:promote",
    "connectors:sync_checkpoint:read",
    "connectors:sync_checkpoint:claim:read",
    "connectors:run:record",
    "sessions:admin",
]


class StaticIdentityVerifier:
    def __init__(self, principal: OidcPrincipal) -> None:
        self.principal = principal

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        assert authorization == "Bearer valid-token"
        return self.principal


def build_test_client(
    settings: Settings | None = None,
) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    app = create_app(settings or Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    return TestClient(app), factory


def as_principal(
    client: TestClient,
    *,
    tenant_id: str,
    actor_id: str,
    scopes: list[str] | None = None,
) -> None:
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id=actor_id,
            tenant_id=tenant_id,
            scopes=list(EQUIVALENT_SCOPES if scopes is None else scopes),
        )
    )


def as_tenant_b(client: TestClient, scopes: list[str] | None = None) -> None:
    as_principal(client, tenant_id=TENANT_B, actor_id=ACTOR_B, scopes=scopes)


def audit_count(factory: sessionmaker[Session], tenant_id: str) -> int:
    with factory() as session:
        return len(
            session.scalars(
                select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
            ).all()
        )


# --------------------------------------------------------------------------- #
# Seeding helpers (tenant A resources + tenant B provisioning)                 #
# --------------------------------------------------------------------------- #


def connector_registry_payload() -> dict:
    migration = run_path("migrations/versions/0023_connector_registry_reference.py")
    return deepcopy(migration["CONNECTOR_REGISTRY_PAYLOAD"])


def seed_connector_registry_reference(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=TENANT_A,
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=connector_registry_payload(),
            )
        )


def seed_tenant_a_credential_handle(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).create_connector_credential_handle(
            ConnectorCredentialHandleCreate(
                tenant_id=TENANT_A,
                connector_id="file_csv_manufacturing_assets",
                handle_id="cred_file_csv_readonly",
                display_name="File CSV readonly vault reference",
                status="active",
                secret_provider="external_vault",
                secret_ref="vault://axis/demo/connectors/file-csv-readonly",
                purpose="preview_import_readonly",
                rotation_interval_days=30,
                last_rotated_at=datetime(2026, 6, 1, tzinfo=UTC),
                next_rotation_due_at=datetime(2026, 7, 1, tzinfo=UTC),
                created_by=ACTOR_A,
            )
        )


def seed_tenant_a_configuration(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).create_connector_configuration(
            ConnectorConfigurationCreate(
                tenant_id=TENANT_A,
                connector_id="file_csv_manufacturing_assets",
                display_name="Manufacturing assets CSV intake",
                status="configured_preview_only",
                sync_mode="preview",
                runtime_boundary="axis-connector-sandbox",
                created_by=ACTOR_A,
                configuration_payload={"file_name_pattern": "*.csv"},
                credential_ref_ids=[],
                notes=["Preview-only tenant A configuration."],
            )
        )


def seed_tenant_a_audit_events(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        if repository.get_tenant(TENANT_A) is None:
            repository.create_tenant(
                TenantCreate(
                    tenant_id=TENANT_A,
                    display_name="Ravenna Works",
                    description="Plant Operations Cockpit",
                    created_by="test",
                )
            )
        repository.append_audit_event(
            AuditEventCreate(
                tenant_id=TENANT_A,
                actor_id="agent_supply_risk",
                event_type="action.proposal.created",
                payload={
                    "action_id": "request_supplier_expedite",
                    "workflow_id": "wf_supplier_delay_review",
                    "approval_id": "appr_expedite_supplier_batch",
                    "status": "approval_required",
                },
            )
        )
        repository.append_audit_event(
            AuditEventCreate(
                tenant_id=TENANT_A,
                actor_id=ACTOR_A,
                event_type="approval.decision.recorded",
                payload={"approval_id": "appr_expedite_supplier_batch", "decision": "approve"},
            )
        )


def seed_tenant_a_session(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).create_oidc_browser_session(
            OidcBrowserSessionCreate(
                session_id_hash="a" * 64,
                tenant_id=TENANT_A,
                actor_id=ACTOR_A,
                scopes=["audit:read"],
                expires_at=datetime(2030, 1, 1, tzinfo=UTC),
            )
        )


def provision_tenant(client: TestClient, tenant_id: str, admin_actor: str, key: str) -> None:
    response = client.post(
        "/platform/tenants",
        json={
            "tenant_id": tenant_id,
            "display_name": f"{tenant_id} display",
            "description": "Tenant provisioned for isolation tests.",
            "requested_by": "axis-platform-operator-role",
            "actor_scopes": [
                "platform:tenant:operator",
                "platform:tenant:provision",
                "platform:tenant:read",
            ],
            "idempotency_key": key,
            "bootstrap_admin": {
                "actor_id": admin_actor,
                "display_name": f"{tenant_id} admin",
                "scopes": ["audit:read"],
            },
        },
    )
    assert response.status_code == 201, response.text


def provision_tenant_b(client: TestClient) -> None:
    response = client.post(
        "/platform/tenants",
        json={
            "tenant_id": TENANT_B,
            "display_name": "Beta Manufacturing",
            "description": "Second tenant provisioned for isolation tests.",
            "requested_by": "axis-platform-operator-role",
            "actor_scopes": [
                "platform:tenant:operator",
                "platform:tenant:provision",
                "platform:tenant:read",
            ],
            "idempotency_key": "idem_provision_beta_isolation_v1",
            "bootstrap_admin": {
                "actor_id": ACTOR_B,
                "display_name": "Beta operations owner",
                "scopes": ["audit:read"],
            },
        },
    )
    assert response.status_code == 201, response.text


# --------------------------------------------------------------------------- #
# (c)/(d) Enforced write isolation: tenant B mutating tenant A -> rejected.    #
#                                                                              #
# Every route below binds the request through the OIDC principal and rejects a #
# tenant mismatch before touching persistence, so no tenant-A seeding is       #
# required to prove the mutation is refused. Bodies carry tenant A (or the     #
# implicit demo tenant), the principal is tenant B: the outcome must be a 403  #
# tenant mismatch and both ledgers must stay empty.                            #
# --------------------------------------------------------------------------- #


def _replay_output_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "workflow_id": "wf_supplier_delay_review",
        "simulation_output_id": "replay_output_supplier_delay_review_20260622",
        "idempotency_key": "idem_replay_output_supplier_delay_review_20260622",
        "requested_by": ACTOR_A,
        "actor_scopes": ["simulation:replay:persist"],
        "reason": "Persist replay output for governance review.",
        "retention_window_days": 30,
        "notes": ["Governed replay output."],
    }


def _daily_brief_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "brief_date": "2026-06-21",
        "requested_by": ACTOR_A,
        "actor_scopes": ["briefs:generate", "audit:read", "workflows:read"],
    }


def _risk_scenario_body(scope: str) -> dict:
    return {
        "tenant_id": TENANT_A,
        "requested_by": ACTOR_A,
        "actor_scopes": [scope, "audit:read", "workflows:read"],
    }


def _connector_run_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "file_csv_manufacturing_assets",
        "run_id": "run_file_csv_assets_preview_20260622",
        "execution_mode": "preview",
        "requested_by": ACTOR_A,
        "credential_handle_ids": ["cred_file_csv_readonly"],
        "input_summary": {"file_name": "assets.csv", "record_count": "2"},
        "result_summary": {"accepted_record_count": "2", "rejected_record_count": "0"},
        "notes": ["Run record only."],
    }


def _action_run_body() -> dict:
    return {
        "actor_id": "agent_supply_risk",
        "actor_scopes": ["supply:read", "approvals:supply:request"],
        "idempotency_key": "tenant_demo_manufacturing:request_supplier_expedite:iso",
        "payload": {
            "supplier_batch_id": "asset_motors_batch",
            "target_arrival": "2026-06-22T08:00:00+02:00",
            "reason": "Line 2 packaging risk",
            "cost_ceiling_eur": "1200",
        },
    }


def _agent_run_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "actor_id": "plant-operations-owner",
        "actor_scopes": [],
        "idempotency_key": "agent-run-isolation",
        "mode": "propose",
    }


def _action_outcome_body() -> dict:
    return {
        "actor_id": "workflow-runtime",
        "actor_scopes": ["actions:result:record"],
        "idempotency_key": "supplier-expedite-outcome-iso",
        "status": "dry_run_completed",
        "result_summary": "Supplier expedite dry-run package generated.",
        "evidence_refs": ["audit_supplier_expedite_preview"],
        "metrics": {"external_mutations": 0, "records_written": 0},
    }


def _approval_decision_body() -> dict:
    return {"decision": "approve", "actor_id": ACTOR_A}


def _manual_import_decision_body() -> dict:
    return {
        "decision": "approve",
        "actor_id": ACTOR_A,
        "actor_scopes": ["approvals:connectors:decide"],
        "note": "Approved.",
    }


def _ontology_promotion_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "promotion_id": "promote_asset_line_2_packaging_20260622",
        "idempotency_key": "promote-asset-line-2-packaging-20260622",
        "proposal_id": "proposal_asset_line_2_packaging",
        "manual_import_id": "import_assets_manual_20260622",
        "actor_id": ACTOR_A,
        "actor_scopes": ["connectors:ontology:promote"],
        "note": "Promote approved proposal.",
    }


def _promotion_policy_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "file_csv_manufacturing_assets",
        "policy_id": "policy_connector_asset_promotion_v1",
        "policy_version": "2026-06-22",
        "status": "draft",
        "enforcement_mode": "advisory",
        "created_by": "platform-governance-owner-role",
        "actor_scopes": ["connectors:promotion_policy:author"],
        "required_scopes": ["connectors:ontology:promote"],
        "required_manual_import_status": "approval_approved",
        "required_workflow_signal_status": "manual_import_signal_requested",
        "allowed_risk_levels": ["high", "medium"],
        "allowed_ontology_types": ["manufacturing_asset"],
        "review_window_hours": 24,
        "notes": ["Policy draft."],
    }


def _promotion_policy_set_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "file_csv_manufacturing_assets",
        "policy_set_id": "policy_set_connector_asset_required_20260622",
        "policy_set_version": "2026-06-22.1",
        "status": "active",
        "activated_by": "platform-governance-owner-role",
        "actor_scopes": ["connectors:promotion_policy_set:activate"],
        "policy_ids": ["policy_connector_asset_required_scope"],
        "activation_reason": "Activate required policy set.",
        "notes": ["Active set."],
    }


def _audit_legal_hold_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "hold_id": "hold-api-quality-proposals",
        "actor_id": "legal-ops-controller",
        "actor_scopes": ["audit:legal_hold:write"],
        "reason": "Regulatory review hold.",
        "event_type": "action.proposal.created",
        "approved_by": "legal-reviewer-role",
    }


def _audit_retention_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "actor_id": "audit-retention-operator",
        "actor_scopes": ["audit:retention:delete"],
        "retention_days": 30,
        "dry_run": True,
    }


def _connector_manifest_body() -> dict:
    connector = connector_registry_payload()["connectors"][0]
    return {
        "tenant_id": TENANT_A,
        "registered_by": "platform-connector-owner-role",
        "manifest": connector["manifest"],
        "runtime_policy": connector["runtime_policy"],
        "preview_sample": connector["preview_sample"],
        "notes": ["Cross-tenant write attempt from tenant B."],
    }


def _connector_manifest_validation_body() -> dict:
    body = _connector_manifest_body()
    return {
        "tenant_id": body.pop("tenant_id"),
        "registered_by": body.pop("registered_by"),
        "manifests": [body],
    }


def _connector_manifest_lifecycle_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "transitioned_by": "platform-connector-owner-role",
        "target_status": "certified",
        "actor_scopes": ["connectors:manifest:lifecycle"],
        "transition_reason": "Cross-tenant lifecycle attempt from tenant B.",
    }


def _connector_configuration_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "file_csv_manufacturing_assets",
        "display_name": "Manufacturing assets CSV intake",
        "sync_mode": "preview",
        "created_by": ACTOR_A,
    }


def _connector_credential_handle_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "file_csv_manufacturing_assets",
        "handle_id": "cred_file_csv_readonly",
        "display_name": "File CSV readonly vault reference",
        "secret_provider": "external_vault",
        "secret_ref": "vault://axis/demo/connectors/file-csv-readonly",
        "purpose": "preview_import_readonly",
        "created_by": ACTOR_A,
    }


def _connector_credential_rotation_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "rotated_by": ACTOR_A,
        "evidence_ref": "audit_credential_rotation_iso",
    }


def _connector_credential_lease_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "file_csv_manufacturing_assets",
        "handle_id": "cred_file_csv_readonly",
        "lease_id": "lease_file_csv_iso_20260710",
        "requested_by": ACTOR_A,
        "lease_purpose": "preview_import_readonly",
    }


def _connector_credential_lease_renew_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "renewed_by": ACTOR_A,
        "renewal_reason": "Extend preview import window.",
        "evidence_ref": "audit_credential_lease_renewal_iso",
    }


def _connector_credential_lease_revoke_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "revoked_by": ACTOR_A,
        "revocation_reason": "Revoke preview import lease.",
        "evidence_ref": "audit_credential_lease_revocation_iso",
    }


def _connector_egress_policy_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "external_db_operational_mirror",
        "policy_id": "policy_egress_ops_mirror_iso_v1",
        "display_name": "Operational mirror egress policy",
        "connection_profile_id": "profile_postgres_ops_readonly",
        "egress_boundary": "private_endpoint_only",
        "policy_mode": "enforce",
        "private_endpoint_ref": "vpce://axis/demo/postgres-ops-readonly",
        "created_by": ACTOR_A,
    }


def _connector_evidence_snapshot_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "snapshot_id": "snapshot_evidence_iso_20260710",
        "requested_by": ACTOR_A,
        "idempotency_key": "idem_snapshot_evidence_iso_20260710",
        "reason": "Cross-tenant snapshot attempt from tenant B.",
    }


def _connector_evidence_snapshot_export_request_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "export_request_id": "export_req_evidence_iso_20260710",
        "idempotency_key": "idem_export_req_evidence_iso_20260710",
        "requested_by": ACTOR_A,
        "owner_role": "plant-operations-owner-role",
        "risk_level": "medium",
        "approval_id": "appr_evidence_export_iso",
        "workflow_id": "wf_evidence_export_iso",
    }


def _connector_ontology_proposal_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "file_csv_manufacturing_assets",
        "source_file_name": "assets.csv",
        "proposed_by": ACTOR_A,
        "proposed_entities": [
            {
                "proposal_id": "proposal_asset_line_2_packaging",
                "node_id": "asset_line_2_packaging",
                "node_type": "Asset",
                "ontology_type": "manufacturing_asset",
            }
        ],
    }


def _connector_manual_import_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "file_csv_manufacturing_assets",
        "import_id": "import_assets_iso_20260710",
        "idempotency_key": "idem_import_assets_iso_20260710",
        "requested_by": ACTOR_A,
        "owner_role": "plant-operations-owner-role",
        "risk_level": "medium",
        "approval_id": "appr_manual_import_iso",
        "workflow_id": "wf_manual_import_iso",
        "proposal_ids": ["proposal_asset_line_2_packaging"],
    }


def _connector_csv_preview_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": "file_csv_manufacturing_assets",
        "file_name": "assets.csv",
        "csv_content": "asset_id,asset_name\nasset_1,Line 1 packer\n",
    }


def _connector_external_db_preview_body() -> dict:
    return {"tenant_id": TENANT_A}


def _platform_policy_body() -> dict:
    return {
        "tenant_id": TENANT_A,
        "policy_id": "policy_platform_high_risk_gate_v1",
        "policy_version": "2026-07-05",
        "display_name": "High risk action gate",
        "description": "Gate governed action execution on declared risk conditions.",
        "scope": "action_execution",
        "effect": "require_approval",
        "conditions": {"action_domains": ["Operations"], "risk_levels": ["low"]},
        "created_by": "platform-governance-owner-role",
        "actor_scopes": ["platform:policy:author"],
        "notes": ["Platform policy."],
    }


# id, method, path, body-factory
ENFORCED_WRITE_CASES: list[tuple[str, str, str, Callable[[], dict]]] = [
    ("replay_output", "post", "/demo/manufacturing/simulation/replay/outputs", _replay_output_body),
    ("daily_brief", "post", "/demo/manufacturing/operations/daily-brief", _daily_brief_body),
    (
        "risk_quality",
        "post",
        "/demo/manufacturing/operations/risk-scenarios/quality",
        lambda: _risk_scenario_body("quality:read"),
    ),
    (
        "risk_maintenance",
        "post",
        "/demo/manufacturing/operations/risk-scenarios/maintenance",
        lambda: _risk_scenario_body("maintenance:read"),
    ),
    (
        "risk_supplier_delay",
        "post",
        "/demo/manufacturing/operations/risk-scenarios/supplier-delay",
        lambda: _risk_scenario_body("supply:read"),
    ),
    ("connector_run", "post", "/demo/manufacturing/connectors/runs", _connector_run_body),
    (
        "connector_manifest_create",
        "post",
        "/demo/manufacturing/connectors/manifests",
        _connector_manifest_body,
    ),
    (
        "connector_manifest_validation",
        "post",
        "/operations/connectors/manifests/validation",
        _connector_manifest_validation_body,
    ),
    (
        "action_run",
        "post",
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        _action_run_body,
    ),
    (
        "agent_run",
        "post",
        "/demo/manufacturing/agents/agent_daily_brief/runs",
        _agent_run_body,
    ),
    (
        "action_outcome",
        "post",
        "/demo/manufacturing/actions/runs/00000000-0000-0000-0000-000000000000/outcome",
        _action_outcome_body,
    ),
    (
        "approval_decision",
        "post",
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        _approval_decision_body,
    ),
    (
        "manual_import_decision",
        "post",
        "/demo/manufacturing/connectors/manual-imports/import_assets_manual_20260622/decision",
        _manual_import_decision_body,
    ),
    (
        "ontology_promotion",
        "post",
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        _ontology_promotion_body,
    ),
    (
        "promotion_policy",
        "post",
        "/demo/manufacturing/connectors/promotion-policies",
        _promotion_policy_body,
    ),
    (
        "promotion_policy_set",
        "post",
        "/demo/manufacturing/connectors/promotion-policy-sets",
        _promotion_policy_set_body,
    ),
    (
        "connector_manifest_lifecycle",
        "post",
        "/demo/manufacturing/connectors/manifests/file_csv_manufacturing_assets/lifecycle",
        _connector_manifest_lifecycle_body,
    ),
    (
        "connector_configuration_create",
        "post",
        "/demo/manufacturing/connectors/configurations",
        _connector_configuration_body,
    ),
    (
        "connector_credential_handle_create",
        "post",
        "/demo/manufacturing/connectors/credential-handles",
        _connector_credential_handle_body,
    ),
    (
        "connector_credential_rotation",
        "post",
        "/demo/manufacturing/connectors/credential-handles/cred_file_csv_readonly/rotations",
        _connector_credential_rotation_body,
    ),
    (
        "connector_credential_lease_create",
        "post",
        "/demo/manufacturing/connectors/credential-leases",
        _connector_credential_lease_body,
    ),
    (
        "connector_credential_lease_renew",
        "post",
        "/demo/manufacturing/connectors/credential-leases/lease_file_csv_iso_20260710/renew",
        _connector_credential_lease_renew_body,
    ),
    (
        "connector_credential_lease_revoke",
        "post",
        "/demo/manufacturing/connectors/credential-leases/lease_file_csv_iso_20260710/revoke",
        _connector_credential_lease_revoke_body,
    ),
    (
        "connector_egress_policy_create",
        "post",
        "/demo/manufacturing/connectors/egress-policies",
        _connector_egress_policy_body,
    ),
    (
        "connector_evidence_snapshot",
        "post",
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        _connector_evidence_snapshot_body,
    ),
    (
        "connector_evidence_snapshot_export_request",
        "post",
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        _connector_evidence_snapshot_export_request_body,
    ),
    (
        "connector_ontology_proposal_create",
        "post",
        "/demo/manufacturing/connectors/ontology-proposals",
        _connector_ontology_proposal_body,
    ),
    (
        "connector_manual_import_create",
        "post",
        "/demo/manufacturing/connectors/manual-imports",
        _connector_manual_import_body,
    ),
    (
        "connector_csv_preview",
        "post",
        "/demo/manufacturing/connectors/file-csv/preview",
        _connector_csv_preview_body,
    ),
    (
        "connector_external_db_preview",
        "post",
        "/demo/manufacturing/connectors/external-db/preview",
        _connector_external_db_preview_body,
    ),
    (
        "audit_legal_hold",
        "post",
        "/demo/manufacturing/audit/legal-holds",
        _audit_legal_hold_body,
    ),
    (
        "audit_retention_delete",
        "post",
        "/demo/manufacturing/audit/retention/delete",
        _audit_retention_body,
    ),
    ("platform_policy", "post", "/platform/policies", _platform_policy_body),
]


@pytest.mark.parametrize(
    ("case_id", "method", "path", "body_factory"),
    ENFORCED_WRITE_CASES,
    ids=[case[0] for case in ENFORCED_WRITE_CASES],
)
def test_tenant_b_cannot_mutate_tenant_a_resource(
    case_id: str,
    method: str,
    path: str,
    body_factory: Callable[[], dict],
) -> None:
    client, factory = build_test_client()
    as_tenant_b(client)

    before_a = audit_count(factory, TENANT_A)
    before_b = audit_count(factory, TENANT_B)

    response = getattr(client, method)(path, json=body_factory(), headers=BEARER)

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["reason"] == "tenant_mismatch"
    # The rejected mutation must not append anything to either ledger.
    assert audit_count(factory, TENANT_A) == before_a
    assert audit_count(factory, TENANT_B) == before_b


# --------------------------------------------------------------------------- #
# (a)/(b) Enforced read isolation: tenant B reading tenant A -> 403.           #
#                                                                              #
# These GET routes bind the caller principal and reject a query ``tenant_id``  #
# that differs from the principal's tenant before returning any record.        #
# --------------------------------------------------------------------------- #

ENFORCED_READ_PATHS: list[tuple[str, str]] = [
    ("agent_runs", "/demo/manufacturing/agents/agent_daily_brief/runs"),
    (
        "agent_run_detail",
        "/demo/manufacturing/agents/agent_daily_brief/runs/00000000-0000-0000-0000-000000000000",
    ),
    ("audit_events", "/demo/manufacturing/audit/events"),
    ("audit_export", "/demo/manufacturing/audit/export"),
    ("audit_legal_holds", "/demo/manufacturing/audit/legal-holds"),
    ("action_runs", "/operations/actions/runs"),
    ("replay_simulation", "/demo/manufacturing/simulation/replay"),
    ("connector_manifests", "/demo/manufacturing/connectors/manifests"),
    ("connector_configurations", "/demo/manufacturing/connectors/configurations"),
    ("connector_credential_handles", "/demo/manufacturing/connectors/credential-handles"),
    ("connector_credential_leases", "/demo/manufacturing/connectors/credential-leases"),
    ("connector_egress_policies", "/demo/manufacturing/connectors/egress-policies"),
    ("connector_evidence_invariants", "/demo/manufacturing/connectors/evidence-invariants"),
    (
        "connector_evidence_snapshots",
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
    ),
    ("connector_runs", "/demo/manufacturing/connectors/runs"),
    ("connector_ontology_proposals", "/demo/manufacturing/connectors/ontology-proposals"),
    ("connector_promotion_policies", "/demo/manufacturing/connectors/promotion-policies"),
    ("connector_promotion_policy_sets", "/demo/manufacturing/connectors/promotion-policy-sets"),
    ("connector_manual_imports", "/demo/manufacturing/connectors/manual-imports"),
    ("sync_checkpoints", "/demo/manufacturing/connectors/runs/checkpoints"),
    ("sync_checkpoint_claims", "/demo/manufacturing/connectors/runs/checkpoints/claims"),
    ("platform_policies", "/platform/policies"),
    ("platform_policy_detail", "/platform/policies/policy_platform_high_risk_gate_v1"),
]


@pytest.mark.parametrize(
    ("case_id", "path"),
    ENFORCED_READ_PATHS,
    ids=[case[0] for case in ENFORCED_READ_PATHS],
)
def test_tenant_b_cannot_read_tenant_a_scope(case_id: str, path: str) -> None:
    client, factory = build_test_client()
    seed_tenant_a_audit_events(factory)
    as_tenant_b(client)

    before_a = audit_count(factory, TENANT_A)

    response = client.get(path, params={"tenant_id": TENANT_A}, headers=BEARER)

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["reason"] == "tenant_mismatch"
    # A denied read is a pure query and must not mutate tenant A's ledger.
    assert audit_count(factory, TENANT_A) == before_a


def test_tenant_a_audit_events_are_readable_by_tenant_a_only() -> None:
    """Positive control: the same query succeeds for tenant A and returns data."""
    client, factory = build_test_client()
    seed_tenant_a_audit_events(factory)
    as_principal(client, tenant_id=TENANT_A, actor_id=ACTOR_A)

    ok = client.get(
        "/demo/manufacturing/audit/events",
        params={"tenant_id": TENANT_A},
        headers=BEARER,
    )
    assert ok.status_code == 200
    assert ok.json()["events"], "tenant A must be able to read its own audit events"


# --------------------------------------------------------------------------- #
# Platform-tenant surface: cross-tenant admin is scope-gated, not tenant-gated.#
#                                                                              #
# The platform-tenant/quota/usage reads are a deliberate cross-tenant operator #
# surface: an operator authenticates under its own tenant and reads any        #
# tenant. Isolation here is enforced by the dedicated ``platform:tenant:*``    #
# operator scopes -- an ordinary tenant-B principal (equivalent non-operator   #
# scopes) must be refused for missing scope, never handed tenant A's record.   #
# --------------------------------------------------------------------------- #

PLATFORM_OPERATOR_READ_PATHS: list[tuple[str, str]] = [
    ("tenant_detail", f"/platform/tenants/{TENANT_A}"),
    ("tenant_quotas", f"/platform/tenants/{TENANT_A}/quotas"),
    ("tenant_usage", f"/platform/tenants/{TENANT_A}/usage"),
    ("tenant_registry", "/platform/tenants"),
]


@pytest.mark.parametrize(
    ("case_id", "path"),
    PLATFORM_OPERATOR_READ_PATHS,
    ids=[case[0] for case in PLATFORM_OPERATOR_READ_PATHS],
)
def test_tenant_b_without_operator_scope_cannot_read_platform_tenant(
    case_id: str, path: str
) -> None:
    client, _factory = build_test_client()
    as_tenant_b(client)

    response = client.get(path, headers=BEARER)

    assert response.status_code == 403, response.text
    # Never a 200 that would hand back tenant A's platform record.
    assert response.status_code != 200


def test_tenant_b_cannot_update_tenant_a_quota_without_operator_scope() -> None:
    client, factory = build_test_client()
    provision_tenant(client, TENANT_A, "demo-bootstrap-admin-role", "idem_provision_demo_iso_v1")
    as_tenant_b(client)
    before_a = audit_count(factory, TENANT_A)

    response = client.put(
        f"/platform/tenants/{TENANT_A}/quotas",
        json={
            "requested_by": ACTOR_B,
            "actor_scopes": EQUIVALENT_SCOPES,
            "quotas": {"api_requests_per_window": 5},
        },
        headers=BEARER,
    )

    assert response.status_code == 403, response.text
    assert audit_count(factory, TENANT_A) == before_a


# --------------------------------------------------------------------------- #
# Identity sessions: the surface derives tenant scope from the principal, so a #
# tenant-B caller can only ever see or revoke tenant-B sessions.               #
# --------------------------------------------------------------------------- #


def test_tenant_b_session_listing_excludes_tenant_a_sessions() -> None:
    client, factory = build_test_client()
    seed_tenant_a_session(factory)
    as_tenant_b(client)

    response = client.get("/identity/sessions", headers=BEARER)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tenant_id"] == TENANT_B
    assert body["sessions"] == []
    assert ACTOR_A not in str(body)


def test_tenant_b_cannot_revoke_tenant_a_session() -> None:
    client, factory = build_test_client()
    seed_tenant_a_session(factory)
    as_tenant_b(client)

    # Look up tenant A's session row id, then attempt to revoke it as tenant B.
    with factory() as session:
        from axis_api.models import OidcBrowserSession

        row = session.scalars(
            select(OidcBrowserSession).where(OidcBrowserSession.tenant_id == TENANT_A)
        ).one()
        session_ref = str(row.id)

    response = client.post(
        f"/identity/sessions/{session_ref}/revoke", headers=BEARER
    )

    # Scoped to the caller's tenant, so tenant A's session simply "does not exist".
    assert response.status_code == 404, response.text


# --------------------------------------------------------------------------- #
# Connector surface positive controls.                                         #
#                                                                              #
# The connector read routes were the TM-001 isolation leaks (strict xfails)    #
# before principal binding was added; the negative cases now live in the       #
# enforced tables above. These controls prove the binding does not over-block: #
# a tenant-A principal still reads tenant A's own connector records, and a     #
# tenant-B read denial leaks nothing about tenant A's data.                    #
# --------------------------------------------------------------------------- #


def test_tenant_a_reads_its_own_credential_handles() -> None:
    client, factory = build_test_client()
    seed_connector_registry_reference(factory)
    seed_tenant_a_credential_handle(factory)
    as_principal(client, tenant_id=TENANT_A, actor_id=ACTOR_A)

    response = client.get(
        "/demo/manufacturing/connectors/credential-handles",
        params={"tenant_id": TENANT_A},
        headers=BEARER,
    )

    assert response.status_code == 200, response.text
    assert response.json()["handles"], "tenant A must read its own credential handles"


def test_tenant_b_credential_handle_denial_reveals_no_tenant_a_data() -> None:
    client, factory = build_test_client()
    seed_connector_registry_reference(factory)
    seed_tenant_a_credential_handle(factory)
    as_tenant_b(client)

    response = client.get(
        "/demo/manufacturing/connectors/credential-handles",
        params={"tenant_id": TENANT_A},
        headers=BEARER,
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["reason"] == "tenant_mismatch"
    assert "vault://" not in response.text, "denial must not leak secret refs"


def test_tenant_a_reads_its_own_configurations() -> None:
    client, factory = build_test_client()
    seed_connector_registry_reference(factory)
    seed_tenant_a_configuration(factory)
    as_principal(client, tenant_id=TENANT_A, actor_id=ACTOR_A)

    response = client.get(
        "/demo/manufacturing/connectors/configurations",
        params={"tenant_id": TENANT_A},
        headers=BEARER,
    )

    assert response.status_code == 200, response.text
    assert response.json()["configurations"], (
        "tenant A must read its own connector configurations"
    )


def test_tenant_a_creates_its_own_configuration() -> None:
    """Positive write control: the binding must not block a same-tenant write."""
    client, factory = build_test_client()
    seed_connector_registry_reference(factory)
    as_principal(client, tenant_id=TENANT_A, actor_id=ACTOR_A)

    manifest_body = _connector_manifest_body()
    manifest_body["registered_by"] = ACTOR_A
    manifest = client.post(
        "/demo/manufacturing/connectors/manifests",
        json=manifest_body,
        headers=BEARER,
    )
    assert manifest.status_code == 201, manifest.text

    lifecycle_body = _connector_manifest_lifecycle_body()
    lifecycle_body["transitioned_by"] = ACTOR_A
    lifecycle_body["target_status"] = "active_preview"
    lifecycle = client.post(
        "/demo/manufacturing/connectors/manifests/file_csv_manufacturing_assets/lifecycle",
        json=lifecycle_body,
        headers=BEARER,
    )
    assert lifecycle.status_code == 200, lifecycle.text

    response = client.post(
        "/demo/manufacturing/connectors/configurations",
        json=_connector_configuration_body(),
        headers=BEARER,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tenant_id"] == TENANT_A
    assert body["created_by"] == ACTOR_A


# --------------------------------------------------------------------------- #
# Sanity: tenant B provisioning is symmetric with existing tenant provisioning.#
# --------------------------------------------------------------------------- #


def test_second_tenant_provisions_like_the_demo_tenant() -> None:
    client, factory = build_test_client()
    provision_tenant_b(client)

    with factory() as session:
        from axis_api.models import Tenant

        assert session.get(Tenant, TENANT_B) is not None
