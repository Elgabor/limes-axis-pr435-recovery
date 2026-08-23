"""One governed action, end to end: request → approval → follow-through.

This journey drives the real HTTP surface the way an operator and an external
executor would:

1. A supply-risk agent requests a high-risk action; Axis gates it on approval.
2. The approval appears in the tenant inbox while the run waits.
3. Follow-through is impossible before a human decides (422), and deciding
   without the required scope is denied (403).
4. The owner approves; replay is idempotent; a conflicting second decision is
   refused (409); the delivery outbox reports where the decision stands.
5. The executor outcome is recorded as *reported evidence* — dry-run only,
   ``external_mutation_started`` stays false — never as work Axis executed.
6. The audit ledger carries the whole chain with cross-references, scoped per
   tenant, so every hop deep-links to the same approval id.

Rerunnable by construction: ids are fixed demo-scenario references and every
mutation is either idempotent or expected-conflict, so the lane can replay
against a fresh database or an already-seeded one without special casing.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    DemoReferenceRecordCreate,
)
from axis_api.workflow_runtime import WorkflowSignalRequest, WorkflowSignalResult

MIGRATIONS_DIR = Path("migrations/versions")

DEMO_TENANT = "tenant_demo_manufacturing"
OTHER_TENANT = "tenant_other_operations"
APPROVAL_ID = "appr_expedite_supplier_batch"
WORKFLOW_ID = "wf_supplier_delay_review"


def _migration_payload(filename: str, constant: str) -> dict:
    migration = run_path(str(MIGRATIONS_DIR / filename))
    return deepcopy(migration[constant])


def _action_registry_payload() -> dict:
    return _migration_payload("0025_action_registry_reference.py", "ACTION_REGISTRY_PAYLOAD")


def _ontology_payload() -> dict:
    return _migration_payload("0030_ontology_reference.py", "ONTOLOGY_PAYLOAD")


def _approval_inbox_payload() -> dict:
    return _migration_payload("0027_approval_inbox_reference.py", "APPROVAL_INBOX_PAYLOAD")


class RecordingWorkflowRuntime:
    def __init__(self) -> None:
        self.requests: list[WorkflowSignalRequest] = []

    async def signal_approval_decision(
        self,
        request: WorkflowSignalRequest,
    ) -> WorkflowSignalResult:
        self.requests.append(request)
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="approval_signaled",
            adapter="axis-test-workflow-adapter",
            signal_name=request.signal_name,
            payload={
                "approval_id": request.approval_id,
                "approved": request.approved,
                "decision": request.decision.value,
            },
        )

    async def signal_action_run(self, request) -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="action_signal_requested",
            adapter="axis-test-workflow-adapter",
            signal_name=request.signal_name,
            payload={"action_run_id": str(request.action_run_id)},
        )


class TokenSwitchedIdentityVerifier:
    """Maps one test bearer token to one principal, like a real IdP would."""

    def __init__(self, principals: dict[str, OidcPrincipal]) -> None:
        self.principals = principals

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        if not authorization or not authorization.startswith("Bearer "):
            from axis_api.identity import OidcAuthenticationError

            raise OidcAuthenticationError("missing_authorization")
        token = authorization.partition(" ")[2]
        principal = self.principals.get(token)
        if principal is None:
            from axis_api.identity import OidcAuthenticationError

            raise OidcAuthenticationError("invalid_token")
        return principal


AGENT_TOKEN = "journey-agent-token"
OWNER_TOKEN = "journey-owner-token"
LIMITED_OWNER_TOKEN = "journey-owner-without-decide-scope"
OUTSIDER_TOKEN = "journey-other-tenant-token"


def _principals() -> dict[str, OidcPrincipal]:
    return {
        AGENT_TOKEN: OidcPrincipal(
            actor_id="agent_supply_risk",
            tenant_id=DEMO_TENANT,
            scopes=["supply:read", "approvals:supply:request"],
        ),
        OWNER_TOKEN: OidcPrincipal(
            actor_id="plant-operations-owner-role",
            tenant_id=DEMO_TENANT,
            scopes=["approvals:supply:decide", "audit:read", "actions:result:record"],
        ),
        LIMITED_OWNER_TOKEN: OidcPrincipal(
            actor_id="quality-owner-role",
            tenant_id=DEMO_TENANT,
            scopes=["approvals:quality:decide"],
        ),
        OUTSIDER_TOKEN: OidcPrincipal(
            actor_id="other-operations-owner-role",
            tenant_id=OTHER_TENANT,
            scopes=["approvals:supply:decide", "actions:result:record", "audit:read"],
        ),
    }


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    registry_payload = _action_registry_payload()
    registry_payload["tenant_id"] = DEMO_TENANT
    inbox_payload = _approval_inbox_payload()
    inbox_payload["tenant_id"] = DEMO_TENANT
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=DEMO_TENANT,
                surface="actions",
                reference_id="manufacturing-action-registry",
                status="active",
                source="bootstrap",
                version=registry_payload["schema_version"],
                payload=registry_payload,
            )
        )
        repository.upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=DEMO_TENANT,
                surface="approvals",
                reference_id="manufacturing-approval-inbox",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=inbox_payload,
            )
        )
        repository.upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=DEMO_TENANT,
                surface="ontology",
                reference_id="manufacturing-ontology",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=_ontology_payload(),
            )
        )
    yield factory
    engine.dispose()


def _client(session_factory: sessionmaker[Session]) -> TestClient:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            oidc_auth_required=True,
            # The journey asserts the decision-delivery seam, so the outbox
            # enqueue must be on (production turns it on explicitly too).
            approval_decision_outbox_enabled=True,
        )
    )
    app.state.session_factory = session_factory
    app.state.workflow_runtime = RecordingWorkflowRuntime()
    app.state.identity_verifier = TokenSwitchedIdentityVerifier(_principals())
    return TestClient(app)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request_action_run(client: TestClient) -> dict:
    response = client.post(
        f"/operations/actions/request_supplier_expedite/runs?tenant_id={DEMO_TENANT}",
        headers=_auth(AGENT_TOKEN),
        json={
            "actor_id": "agent_supply_risk",
            "actor_scopes": ["supply:read", "approvals:supply:request"],
            "idempotency_key": "journey:supplier-expedite:request-1",
            "payload": {
                "supplier_batch_id": "asset_motors_batch",
                "target_arrival": "2026-06-22T08:00:00+02:00",
                "reason": "Line 2 packaging risk",
                "cost_ceiling_eur": "1200",
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_request_to_decision_to_outcome_chain_stays_cross_referenced(
    session_factory: sessionmaker[Session],
) -> None:
    client = _client(session_factory)

    # 1. Governed request lands in the queue as approval-gated work.
    run = _request_action_run(client)
    assert run["status"] == "approval_required"
    assert run["approval_required"] is True
    assert run["approval_id"] == APPROVAL_ID
    action_run_id = run["action_run_id"]

    # 2. The inbox shows the linked approval as still pending.
    inbox = client.get(f"/operations/approvals?tenant_id={DEMO_TENANT}", headers=_auth(AGENT_TOKEN))
    assert inbox.status_code == 200
    linked = [item for item in inbox.json()["approvals"] if item["approval_id"] == APPROVAL_ID]
    assert len(linked) == 1
    assert linked[0]["status"] == "pending"

    # 3. No executor may follow through before a human decides.
    premature = client.post(
        f"/operations/actions/runs/{action_run_id}/outcome?tenant_id={DEMO_TENANT}",
        headers=_auth(OWNER_TOKEN),
        json={
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["actions:result:record"],
            "idempotency_key": "journey:supplier-expedite:outcome-1",
            "status": "dry_run_completed",
            "result_summary": "Premature outcome attempt.",
            "evidence_refs": ["audit_premature_attempt"],
        },
    )
    assert premature.status_code == 422
    assert "approval_required_before_outcome" in premature.json()["detail"]["issues"]

    # 4. Deciding requires the exact decide scope.
    unauthorized = client.post(
        f"/operations/approvals/{APPROVAL_ID}/decision?tenant_id={DEMO_TENANT}",
        headers=_auth(LIMITED_OWNER_TOKEN),
        json={
            "decision": "approve",
            "actor_id": "quality-owner-role",
            "actor_scopes": ["approvals:quality:decide"],
        },
    )
    assert unauthorized.status_code == 403
    assert unauthorized.json()["detail"]["required_permission"] == "approvals:supply:decide"

    # 5. The owner approves; the decision is persisted once and replayed exactly.
    decision_body = {
        "decision": "approve",
        "actor_id": "plant-operations-owner-role",
        "actor_scopes": ["approvals:supply:decide"],
        "note": "Expedite approved within cost ceiling.",
    }
    decided = client.post(
        f"/operations/approvals/{APPROVAL_ID}/decision?tenant_id={DEMO_TENANT}",
        headers=_auth(OWNER_TOKEN),
        json=decision_body,
    )
    assert decided.status_code == 201, decided.text
    assert decided.json()["idempotent_replay"] is False

    replay = client.post(
        f"/operations/approvals/{APPROVAL_ID}/decision?tenant_id={DEMO_TENANT}",
        headers=_auth(OWNER_TOKEN),
        json=decision_body,
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True

    conflict = client.post(
        f"/operations/approvals/{APPROVAL_ID}/decision?tenant_id={DEMO_TENANT}",
        headers=_auth(OWNER_TOKEN),
        json={**decision_body, "decision": "reject"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "approval_decision_conflict"

    # 6. The delivery outbox represents follow-through honestly: recorded, not
    # yet delivered anywhere unless a dispatcher actually ran.
    delivery = client.get(
        f"/operations/approvals/{APPROVAL_ID}/decision-delivery?tenant_id={DEMO_TENANT}",
        headers=_auth(OWNER_TOKEN),
    )
    assert delivery.status_code == 200
    delivery_body = delivery.json()
    assert delivery_body["workflow_id"] == WORKFLOW_ID
    assert delivery_body["status"] in {"pending", "delivered"}
    assert delivery_body["attempt_count"] >= 0

    # 7. The gate transition is visible on the run itself.
    runs = client.get(
        f"/operations/actions/runs?tenant_id={DEMO_TENANT}", headers=_auth(OWNER_TOKEN)
    )
    assert runs.status_code == 200
    journey_runs = [item for item in runs.json()["runs"] if item["action_run_id"] == action_run_id]
    assert len(journey_runs) == 1
    assert journey_runs[0]["status"] == "approved_for_execution"

    # 8. Executor follow-through is recorded as reported dry-run evidence only.
    outcome = client.post(
        f"/operations/actions/runs/{action_run_id}/outcome?tenant_id={DEMO_TENANT}",
        headers=_auth(OWNER_TOKEN),
        json={
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["actions:result:record"],
            "idempotency_key": "journey:supplier-expedite:outcome-1",
            "status": "dry_run_completed",
            "result_summary": "Executor reported the dry-run package for the approved expedite.",
            "evidence_refs": ["audit_supplier_expedite_preview"],
            "metrics": {"external_mutations": 0},
            "external_mutation_started": False,
        },
    )
    assert outcome.status_code == 201, outcome.text
    outcome_body = outcome.json()
    assert outcome_body["status"] == "dry_run_completed"
    assert outcome_body["idempotent_replay"] is False
    assert outcome_body["approval_id"] == APPROVAL_ID

    outcome_replay = client.post(
        f"/operations/actions/runs/{action_run_id}/outcome?tenant_id={DEMO_TENANT}",
        headers=_auth(OWNER_TOKEN),
        json={
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["actions:result:record"],
            "idempotency_key": "journey:supplier-expedite:outcome-1",
            "status": "dry_run_completed",
            "result_summary": "Executor reported the dry-run package for the approved expedite.",
            "evidence_refs": ["audit_supplier_expedite_preview"],
            "metrics": {"external_mutations": 0},
            "external_mutation_started": False,
        },
    )
    assert outcome_replay.status_code == 200
    assert outcome_replay.json()["idempotent_replay"] is True

    # 9. The audit chain is scoped to the bound workflow and every hop
    # deep-links to the same approval id. Persisted events are served by the
    # scope-gated /audit/events lane, not the static reference explorer.
    audit = client.get(
        f"/operations/audit/events?tenant_id={DEMO_TENANT}&scope={WORKFLOW_ID}",
        headers=_auth(OWNER_TOKEN),
    )
    assert audit.status_code == 200
    events = audit.json()["events"]
    event_types = [event["event_type"] for event in events]
    assert "action.proposal.created" in event_types
    assert "approval.decision.recorded" in event_types
    assert "action.run.outcome.recorded" in event_types
    for event in events:
        assert event["related_workflow_id"] == WORKFLOW_ID
        assert event["related_approval_id"] == APPROVAL_ID


def test_follow_through_never_claims_external_mutation_axis_did_not_start(
    session_factory: sessionmaker[Session],
) -> None:
    client = _client(session_factory)
    run = _request_action_run(client)
    action_run_id = run["action_run_id"]

    decided = client.post(
        f"/operations/approvals/{APPROVAL_ID}/decision?tenant_id={DEMO_TENANT}",
        headers=_auth(OWNER_TOKEN),
        json={
            "decision": "approve",
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["approvals:supply:decide"],
        },
    )
    assert decided.status_code == 201

    claimed = client.post(
        f"/operations/actions/runs/{action_run_id}/outcome?tenant_id={DEMO_TENANT}",
        headers=_auth(OWNER_TOKEN),
        json={
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["actions:result:record"],
            "idempotency_key": "journey:claimed-mutation:1",
            "status": "dry_run_completed",
            "result_summary": "Outcome claiming an external mutation happened.",
            "evidence_refs": ["audit_claimed_mutation"],
            "external_mutation_started": True,
        },
    )

    assert claimed.status_code == 422
    assert "external_mutation_not_enabled" in claimed.json()["detail"]["issues"]
    with session_factory() as session:
        from sqlalchemy import select

        from axis_api.models import AuditEvent

        outcomes = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == "action.run.outcome.recorded")
            )
        )
        assert outcomes == []


def test_outsider_tenant_cannot_touch_any_hop_of_the_chain(
    session_factory: sessionmaker[Session],
) -> None:
    client = _client(session_factory)
    run = _request_action_run(client)
    action_run_id = run["action_run_id"]

    inbox = client.get(
        f"/operations/approvals?tenant_id={DEMO_TENANT}", headers=_auth(OUTSIDER_TOKEN)
    )
    assert inbox.status_code == 403

    outsider_decision = client.post(
        f"/operations/approvals/{APPROVAL_ID}/decision?tenant_id={DEMO_TENANT}",
        headers=_auth(OUTSIDER_TOKEN),
        json={
            "decision": "approve",
            "actor_id": "other-operations-owner-role",
            "actor_scopes": ["approvals:supply:decide"],
        },
    )
    assert outsider_decision.status_code == 403

    outsider_delivery = client.get(
        f"/operations/approvals/{APPROVAL_ID}/decision-delivery?tenant_id={DEMO_TENANT}",
        headers=_auth(OUTSIDER_TOKEN),
    )
    assert outsider_delivery.status_code in {403, 404}

    outsider_audit = client.get(
        f"/operations/audit/events?tenant_id={DEMO_TENANT}&scope={WORKFLOW_ID}",
        headers=_auth(OUTSIDER_TOKEN),
    )
    assert outsider_audit.status_code == 403

    outsider_outcome = client.post(
        f"/operations/actions/runs/{action_run_id}/outcome?tenant_id={DEMO_TENANT}",
        headers=_auth(OUTSIDER_TOKEN),
        json={
            "actor_id": "other-operations-owner-role",
            "actor_scopes": ["actions:result:record"],
            "idempotency_key": "journey:outsider-outcome:1",
            "status": "dry_run_completed",
            "result_summary": "Cross-tenant outcome attempt.",
            "evidence_refs": ["audit_outsider_attempt"],
        },
    )
    assert outsider_outcome.status_code == 403
