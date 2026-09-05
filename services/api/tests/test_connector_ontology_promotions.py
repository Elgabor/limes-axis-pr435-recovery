from copy import deepcopy
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_manifests import (
    ConnectorManifestCreateRequest,
    ConnectorManifestLifecycleRequest,
    record_demo_connector_manifest,
    transition_demo_connector_manifest_lifecycle,
)
from axis_api.connector_ontology_promotions import (
    ConnectorOntologyPromotionRequest,
    ConnectorOntologyPromotionValidationError,
    record_demo_connector_ontology_promotion,
)
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import (
    AuditEvent,
    Base,
    ConnectorOntologyPromotion,
    ConnectorOntologyProposal,
)
from axis_api.ontology.mutations import (
    OntologyMutationError,
    OntologyMutationRequest,
    OntologyMutationResult,
)
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorManualImportRequestCreate,
    ConnectorOntologyProposalCreate,
    ConnectorPromotionPolicyCreate,
    ConnectorPromotionPolicySetCreate,
    DemoReferenceRecordCreate,
)


class RecordingOntologyMutationRuntime:
    def __init__(self) -> None:
        self.requests: list[OntologyMutationRequest] = []

    def promote_connector_proposal(
        self,
        request: OntologyMutationRequest,
    ) -> OntologyMutationResult:
        self.requests.append(request)
        return OntologyMutationResult(
            status="type_db_mutation_applied",
            adapter="axis-test-typedb-adapter",
            mutation_ref=f"typedb://axis/{request.node_id}",
            typeql=request.typeql,
            payload=request.audit_payload,
        )


class FailingOntologyMutationRuntime:
    def promote_connector_proposal(
        self,
        request: OntologyMutationRequest,
    ) -> OntologyMutationResult:
        raise OntologyMutationError("synthetic_typedb_down")


class VerificationFailingOntologyMutationRuntime:
    def promote_connector_proposal(
        self,
        request: OntologyMutationRequest,
    ) -> OntologyMutationResult:
        raise OntologyMutationError(
            "verification_missing_node", status="type_db_mutation_failed"
        )


class DeferredRecordingOntologyMutationRuntime:
    """Mirrors the production deferred runtime: reports deferred, writes nothing."""

    def __init__(self) -> None:
        self.requests: list[OntologyMutationRequest] = []

    def promote_connector_proposal(
        self,
        request: OntologyMutationRequest,
    ) -> OntologyMutationResult:
        self.requests.append(request)
        return OntologyMutationResult(
            status="type_db_mutation_deferred",
            adapter="axis-deferred-ontology-adapter",
            mutation_ref=None,
            typeql=request.typeql,
            payload=request.audit_payload,
        )


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed_connector_registry_reference(factory)
    yield factory
    engine.dispose()


def connector_registry_payload() -> dict:
    migration = run_path("migrations/versions/0023_connector_registry_reference.py")
    return deepcopy(migration["CONNECTOR_REGISTRY_PAYLOAD"])


def seed_connector_registry_reference(
    factory: sessionmaker[Session],
    payload: dict | None = None,
) -> None:
    registry_payload = deepcopy(payload or connector_registry_payload())
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id="tenant_demo_manufacturing",
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=registry_payload,
            )
        )


def connector_manifest_request(
    connector_id: str = "file_csv_manufacturing_assets",
    payload: dict | None = None,
) -> ConnectorManifestCreateRequest:
    registry_payload = deepcopy(payload or connector_registry_payload())
    connector = next(
        item
        for item in registry_payload["connectors"]
        if item["manifest"]["connector_id"] == connector_id
    )
    return ConnectorManifestCreateRequest(
        tenant_id="tenant_demo_manufacturing",
        registered_by="platform-connector-owner-role",
        manifest=connector["manifest"],
        runtime_policy=connector["runtime_policy"],
        preview_sample=connector["preview_sample"],
        notes=["Manifest is registered without enabling live sync."],
    )


def seed_registered_connector_manifest(
    repository: AxisPersistenceRepository,
    connector_id: str = "file_csv_manufacturing_assets",
) -> None:
    record_demo_connector_manifest(repository, connector_manifest_request(connector_id))


def seed_active_connector_manifest(
    repository: AxisPersistenceRepository,
    connector_id: str = "file_csv_manufacturing_assets",
) -> None:
    seed_registered_connector_manifest(repository, connector_id)
    transition_demo_connector_manifest_lifecycle(
        repository,
        connector_id,
        ConnectorManifestLifecycleRequest(
            tenant_id="tenant_demo_manufacturing",
            transitioned_by="platform-connector-owner-role",
            target_status="active_preview",
            actor_scopes=["connectors:manifest:lifecycle"],
            transition_reason="Validated for tenant connector ontology promotion tests.",
            evidence_refs=["test://connector-ontology-promotion-active-manifest"],
        ),
    )


def live_capable_registry_payload(
    connector_id: str = "file_csv_manufacturing_assets",
) -> dict:
    payload = connector_registry_payload()
    connector = next(
        item
        for item in payload["connectors"]
        if item["manifest"]["connector_id"] == connector_id
    )
    connector["manifest"]["sync_modes"] = [
        *connector["manifest"]["sync_modes"],
        "live_sync",
    ]
    connector["runtime_policy"]["allowed_operations"] = [
        *connector["runtime_policy"]["allowed_operations"],
        "live_query",
        "external_egress",
    ]
    connector["runtime_policy"]["blocked_operations"] = [
        "live_write",
        "credential_capture",
    ]
    connector["runtime_policy"]["egress_policy"] = "approved-live-sync-boundary"
    return payload


def seed_live_connector_manifest(
    repository: AxisPersistenceRepository,
    connector_id: str = "file_csv_manufacturing_assets",
) -> None:
    record_demo_connector_manifest(
        repository,
        connector_manifest_request(connector_id, live_capable_registry_payload(connector_id)),
    )
    transition_demo_connector_manifest_lifecycle(
        repository,
        connector_id,
        ConnectorManifestLifecycleRequest(
            tenant_id="tenant_demo_manufacturing",
            transitioned_by="platform-connector-owner-role",
            target_status="active_preview",
            actor_scopes=["connectors:manifest:lifecycle"],
            transition_reason="Validated for live-sync promotion tests.",
            evidence_refs=["test://connector-ontology-promotion-live-manifest"],
        ),
    )
    transition_demo_connector_manifest_lifecycle(
        repository,
        connector_id,
        ConnectorManifestLifecycleRequest(
            tenant_id="tenant_demo_manufacturing",
            transitioned_by="platform-connector-owner-role",
            target_status="active_live",
            actor_scopes=[
                "connectors:manifest:lifecycle",
                "connectors:manifest:enable_live",
            ],
            transition_reason="Governed live sync enabled for promotion tests.",
            evidence_refs=[
                "approval:connector-live-sync-enable",
                "policy:live-sync-boundary-reviewed",
                "credential:live-sync-readonly-lease-policy",
            ],
        ),
    )


def seed_promotable_connector_proposal(
    repository: AxisPersistenceRepository,
    *,
    manifest_status: str | None = "active_preview",
    mapping_profile: str = "manufacturing_asset_v1",
) -> None:
    if manifest_status == "active_preview":
        seed_active_connector_manifest(repository)
    elif manifest_status == "active_live":
        seed_live_connector_manifest(repository)
    elif manifest_status == "registered_preview_only":
        seed_registered_connector_manifest(repository)
    elif manifest_status is not None:
        raise ValueError(f"Unsupported test manifest_status: {manifest_status}")

    proposal_audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="connector-preview-service",
            event_type="connector.ontology_proposals.recorded",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "proposal_ids": ["proposal_asset_line_2_packaging"],
                "graph_mutation_status": "not_applied",
            },
        )
    )
    repository.create_connector_ontology_proposal(
        ConnectorOntologyProposalCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            proposal_id="proposal_asset_line_2_packaging",
            source_run_id="run_file_csv_assets_preview_20260622",
            source_file_name="manufacturing-assets-demo.csv",
            mapping_profile=mapping_profile,
            status="proposed_from_preview",
            write_mode="proposal_only",
            graph_mutation_status="not_applied",
            proposed_by="plant-operations-owner-role",
            node_id="asset_line_2_packaging",
            node_type="asset",
            ontology_type="manufacturing_asset",
            field_summary={
                "asset_name": "Line 2 Packaging",
                "domain": "Operations",
                "station": "Line 2",
                "risk_level": "high",
            },
            evidence_refs=["manufacturing-assets-demo.csv", "asset_line_2_packaging"],
            audit_event_id=proposal_audit_event.id,
            audit_event_type="connector.ontology_proposals.recorded",
            notes=["Proposal persisted for review; graph mutation is not applied."],
        )
    )
    manual_import_audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="plant-operations-owner-role",
            event_type="connector.manual_import.decision_recorded",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "import_id": "import_assets_manual_20260622",
                "decision": "approve",
                "proposal_ids": ["proposal_asset_line_2_packaging"],
                "workflow_signal": {"status": "manual_import_signal_requested"},
            },
        )
    )
    repository.create_connector_manual_import_request(
        ConnectorManualImportRequestCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            import_id="import_assets_manual_20260622",
            idempotency_key="manual-import-assets-20260622",
            status="approval_approved",
            import_mode="manual_import_request",
            requested_by="plant-operations-owner-role",
            owner_role="plant-operations-owner",
            risk_level="high",
            approval_id="appr_connector_import_assets_20260622",
            workflow_id="wf_connector_manual_import_review",
            proposal_ids=["proposal_asset_line_2_packaging"],
            import_summary={
                "proposal_count": "1",
                "mapping_profile": "manufacturing_asset_v1",
            },
            controls=[
                "approval_required",
                "workflow_signal_required",
                "idempotency_enforced",
            ],
            graph_mutation_status="not_applied",
            workflow_signal_status="manual_import_signal_requested",
            decision="approve",
            decision_actor_id="plant-operations-owner-role",
            decision_note="Approved import request; graph mutation remains gated.",
            workflow_signal={
                "workflow_id": "wf_connector_manual_import_review",
                "status": "manual_import_signal_requested",
                "adapter": "axis-test-workflow-adapter",
                "signal_name": "connector_manual_import_decided",
                "payload": {
                    "proposal_ids": ["proposal_asset_line_2_packaging"],
                    "graph_mutation_status": "not_applied",
                },
            },
            audit_event_id=manual_import_audit_event.id,
            audit_event_type="connector.manual_import.decision_recorded",
            notes=["Manual import request only; graph mutation is not applied."],
        )
    )


def seed_required_promotion_policy(
    repository: AxisPersistenceRepository,
    *,
    policy_id: str = "policy_connector_asset_promotion_v1",
    allowed_risk_levels: list[str] | None = None,
    allowed_ontology_types: list[str] | None = None,
    status: str = "enabled",
    enforcement_mode: str = "required",
) -> None:
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="platform-governance-owner-role",
            event_type="connector.promotion_policy.authored",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "policy_id": policy_id,
                "status": status,
                "enforcement_mode": enforcement_mode,
                "required_scopes": ["connectors:ontology:promote"],
            },
        )
    )
    repository.create_connector_promotion_policy(
        ConnectorPromotionPolicyCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            policy_id=policy_id,
            policy_version="2026-06-22",
            status=status,
            enforcement_mode=enforcement_mode,
            created_by="platform-governance-owner-role",
            required_scopes=["connectors:ontology:promote"],
            required_manual_import_status="approval_approved",
            required_workflow_signal_status="manual_import_signal_requested",
            allowed_risk_levels=allowed_risk_levels or ["high", "medium"],
            allowed_ontology_types=allowed_ontology_types or ["manufacturing_asset"],
            review_window_hours=24,
            permission_decision={"allowed": True, "reason": "allowed"},
            audit_event_id=audit_event.id,
            audit_event_type="connector.promotion_policy.authored",
            notes=["Required policy for connector ontology promotion."],
        )
    )


def seed_active_promotion_policy_set(
    repository: AxisPersistenceRepository,
    policy_ids: list[str],
) -> None:
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="platform-governance-owner-role",
            event_type="connector.promotion_policy_set.activated",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "policy_set_id": "policy_set_connector_asset_required_20260622",
                "policy_set_version": "2026-06-22.1",
                "policy_ids": policy_ids,
            },
        )
    )
    repository.create_connector_promotion_policy_set(
        ConnectorPromotionPolicySetCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            policy_set_id="policy_set_connector_asset_required_20260622",
            policy_set_version="2026-06-22.1",
            status="active",
            activated_by="platform-governance-owner-role",
            policy_ids=policy_ids,
            permission_decision={"allowed": True, "reason": "allowed"},
            audit_event_id=audit_event.id,
            audit_event_type="connector.promotion_policy_set.activated",
            activation_reason="Activate versioned required policy set for asset promotions.",
            notes=["Active policy set for connector ontology promotion."],
        )
    )


def promotion_payload() -> dict:
    return {
        "tenant_id": "tenant_demo_manufacturing",
        "promotion_id": "promote_asset_line_2_packaging_20260622",
        "idempotency_key": "promote-asset-line-2-packaging-20260622",
        "proposal_id": "proposal_asset_line_2_packaging",
        "manual_import_id": "import_assets_manual_20260622",
        "actor_id": "plant-operations-owner-role",
        "actor_scopes": ["connectors:ontology:promote"],
        "note": "Promote approved proposal into TypeDB asset graph.",
    }


def promotion_payload_with_policy() -> dict:
    payload = promotion_payload()
    payload["policy_id"] = "policy_connector_asset_promotion_v1"
    return payload


def test_record_connector_ontology_promotion_applies_mutation_and_updates_records(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        result = record_demo_connector_ontology_promotion(
            repository,
            ConnectorOntologyPromotionRequest(**promotion_payload()),
            ontology_runtime,
        )

    with session_factory() as session:
        promotion = session.scalars(select(ConnectorOntologyPromotion)).one()
        proposal = session.scalars(select(ConnectorOntologyProposal)).one()
        audit_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.ontology_promotion.applied"
            )
        ).one()

    assert result.status == "promoted_to_graph"
    assert result.graph_mutation_status == "type_db_mutation_applied"
    assert result.permission_decision.model_dump() == {"allowed": True, "reason": "allowed"}
    assert result.ontology_mutation.status == "type_db_mutation_applied"
    assert result.ontology_mutation.payload["node_id"] == "asset_line_2_packaging"
    assert result.ontology_mutation.payload["field_summary_keys"] == [
        "asset_name",
        "domain",
        "risk_level",
        "station",
    ]
    assert result.proposal.status == "promoted_to_graph"
    assert result.proposal.graph_mutation_status == "type_db_mutation_applied"
    assert result.proposal.promotion_id == "promote_asset_line_2_packaging_20260622"
    assert promotion.idempotency_key == "promote-asset-line-2-packaging-20260622"
    assert promotion.status == "promoted_to_graph"
    assert promotion.graph_mutation_status == "type_db_mutation_applied"
    assert proposal.status == "promoted_to_graph"
    assert proposal.graph_mutation_status == "type_db_mutation_applied"
    assert proposal.promotion_id == "promote_asset_line_2_packaging_20260622"
    assert proposal.ontology_mutation["status"] == "type_db_mutation_applied"
    assert audit_event.payload["promotion_id"] == "promote_asset_line_2_packaging_20260622"
    assert audit_event.payload["manual_import_id"] == "import_assets_manual_20260622"
    assert audit_event.payload["graph_mutation_status"] == "type_db_mutation_applied"
    assert ontology_runtime.requests[0].typeql.startswith("put $asset isa axis_asset")
    assert "axis_asset" in ontology_runtime.requests[0].typeql
    assert "asset_line_2_packaging" in ontology_runtime.requests[0].typeql
    assert "csv_content" not in str(audit_event.payload).lower()


def test_record_connector_ontology_promotion_enforces_required_policy_and_persists_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        seed_required_promotion_policy(repository)
        result = record_demo_connector_ontology_promotion(
            repository,
            ConnectorOntologyPromotionRequest(**promotion_payload_with_policy()),
            ontology_runtime,
        )

    with session_factory() as session:
        promotion = session.scalars(select(ConnectorOntologyPromotion)).one()
        proposal = session.scalars(select(ConnectorOntologyProposal)).one()
        audit_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.ontology_promotion.applied"
            )
        ).one()

    assert result.policy_decision is not None
    assert result.policy_decision.status == "policy_enforced"
    assert result.policy_decision.allowed is True
    assert result.policy_decision.policy_id == "policy_connector_asset_promotion_v1"
    assert result.policy_decision.policy_version == "2026-06-22"
    assert result.policy_decision.enforcement_mode == "required"
    assert result.policy_decision.reason == "policy_constraints_satisfied"
    assert result.policy_decision.matched_constraints["risk_level"] == "high"
    assert result.policy_decision.matched_constraints["ontology_type"] == "manufacturing_asset"
    assert promotion.policy_id == "policy_connector_asset_promotion_v1"
    assert promotion.policy_decision["status"] == "policy_enforced"
    assert proposal.policy_id == "policy_connector_asset_promotion_v1"
    assert proposal.policy_decision["reason"] == "policy_constraints_satisfied"
    assert audit_event.payload["policy_id"] == "policy_connector_asset_promotion_v1"
    assert audit_event.payload["policy_decision"]["status"] == "policy_enforced"
    matched_constraints = audit_event.payload["policy_decision"]["matched_constraints"]
    assert matched_constraints["workflow_signal_status"] == "manual_import_signal_requested"


def test_record_connector_ontology_promotion_auto_selects_required_policy(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        seed_required_promotion_policy(repository)
        result = record_demo_connector_ontology_promotion(
            repository,
            ConnectorOntologyPromotionRequest(**promotion_payload()),
            ontology_runtime,
        )

    with session_factory() as session:
        promotion = session.scalars(select(ConnectorOntologyPromotion)).one()
        proposal = session.scalars(select(ConnectorOntologyProposal)).one()
        audit_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.ontology_promotion.applied"
            )
        ).one()

    assert result.policy_id == "policy_connector_asset_promotion_v1"
    assert result.policy_decision is not None
    assert result.policy_decision.status == "policy_enforced"
    assert result.policy_decision.reason == "policy_constraints_satisfied"
    assert result.policy_decision.matched_constraints["selection_mode"] == "auto_required"
    assert promotion.policy_id == "policy_connector_asset_promotion_v1"
    assert promotion.policy_decision["matched_constraints"]["selection_mode"] == "auto_required"
    assert proposal.policy_id == "policy_connector_asset_promotion_v1"
    assert audit_event.payload["policy_id"] == "policy_connector_asset_promotion_v1"
    assert audit_event.payload["policy_decision"]["status"] == "policy_enforced"


def test_record_connector_ontology_promotion_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(
            repository,
            manifest_status="registered_preview_only",
        )
        with pytest.raises(ConnectorOntologyPromotionValidationError) as exc_info:
            record_demo_connector_ontology_promotion(
                repository,
                ConnectorOntologyPromotionRequest(**promotion_payload()),
                ontology_runtime,
            )

    assert exc_info.value.reason == "connector_manifest_not_active_preview"
    assert ontology_runtime.requests == []


def test_record_connector_ontology_promotion_promotes_live_sync_proposal_on_active_live(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(
            repository,
            manifest_status="active_live",
            mapping_profile="connector_live_sync_v1",
        )
        result = record_demo_connector_ontology_promotion(
            repository,
            ConnectorOntologyPromotionRequest(**promotion_payload()),
            ontology_runtime,
        )

    assert result.status == "promoted_to_graph"
    assert result.graph_mutation_status == "type_db_mutation_applied"
    assert result.proposal.mapping_profile == "connector_live_sync_v1"
    assert result.proposal.status == "promoted_to_graph"
    assert len(ontology_runtime.requests) == 1


def test_promotion_on_active_live_manifest_still_requires_manual_import_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(
            repository,
            manifest_status="active_live",
            mapping_profile="connector_live_sync_v1",
        )
        payload = promotion_payload()
        payload["manual_import_id"] = "import_missing_evidence"
        with pytest.raises(ConnectorOntologyPromotionValidationError) as exc_info:
            record_demo_connector_ontology_promotion(
                repository,
                ConnectorOntologyPromotionRequest(**payload),
                ontology_runtime,
            )

    assert exc_info.value.reason == "manual_import_not_found"
    assert ontology_runtime.requests == []


def test_promotion_on_active_live_manifest_still_enforces_required_policy(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(
            repository,
            manifest_status="active_live",
            mapping_profile="connector_live_sync_v1",
        )
        seed_required_promotion_policy(repository, allowed_risk_levels=["low"])
        with pytest.raises(ConnectorOntologyPromotionValidationError) as exc_info:
            record_demo_connector_ontology_promotion(
                repository,
                ConnectorOntologyPromotionRequest(**promotion_payload()),
                ontology_runtime,
            )

    assert exc_info.value.reason == "promotion_policy_rejected"
    assert ontology_runtime.requests == []


def test_connector_ontology_promotion_endpoint_applies_mutation(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.ontology_mutation_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        seed_promotable_connector_proposal(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "promoted_to_graph"
    assert body["graph_mutation_status"] == "type_db_mutation_applied"
    assert body["proposal"]["status"] == "promoted_to_graph"
    assert body["proposal"]["promotion_id"] == "promote_asset_line_2_packaging_20260622"
    assert body["ontology_mutation"]["status"] == "type_db_mutation_applied"
    assert body["audit_event_type"] == "connector.ontology_promotion.applied"


def test_connector_ontology_promotion_endpoint_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.ontology_mutation_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(
            repository,
            manifest_status="registered_preview_only",
        )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "connector_manifest_not_active_preview"
    assert app.state.ontology_mutation_runtime.requests == []


def test_connector_ontology_promotion_endpoint_rejects_missing_permission(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_promotable_connector_proposal(AxisPersistenceRepository(session))
    client = TestClient(app)
    payload = promotion_payload()
    payload["actor_scopes"] = []

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=payload,
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "missing_required_scope"


def test_connector_ontology_promotion_endpoint_requires_approved_manual_import(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        manual_import = repository.get_connector_manual_import_request(
            "tenant_demo_manufacturing",
            "import_assets_manual_20260622",
        )
        manual_import.status = "approval_required"
        manual_import.decision = None
        manual_import.workflow_signal = None
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "manual_import_not_approved"


def test_connector_ontology_promotion_endpoint_rejects_missing_policy(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_promotable_connector_proposal(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload_with_policy(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "promotion_policy_not_found"


def test_connector_ontology_promotion_endpoint_rejects_policy_risk_mismatch(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        seed_required_promotion_policy(repository, allowed_risk_levels=["low"])
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload_with_policy(),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["reason"] == "promotion_policy_rejected"
    assert detail["audit_event_type"] == "connector.ontology_promotion.rejected"
    with session_factory() as session:
        assert list(session.scalars(select(ConnectorOntologyPromotion))) == []
        rejection_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.ontology_promotion.rejected"
            )
        ).one()

    assert detail["audit_event_id"] == str(rejection_event.id)
    assert rejection_event.actor_id == "plant-operations-owner-role"
    assert rejection_event.payload["promotion_id"] == "promote_asset_line_2_packaging_20260622"
    assert rejection_event.payload["proposal_id"] == "proposal_asset_line_2_packaging"
    assert rejection_event.payload["manual_import_id"] == "import_assets_manual_20260622"
    assert rejection_event.payload["policy_id"] == "policy_connector_asset_promotion_v1"
    assert rejection_event.payload["policy_set_id"] is None
    assert rejection_event.payload["policy_ids"] == ["policy_connector_asset_promotion_v1"]
    assert rejection_event.payload["status"] == "promotion_rejected"
    assert rejection_event.payload["graph_mutation_status"] == "not_applied"
    assert rejection_event.payload["rejection_reason"] == "promotion_policy_rejected"
    assert rejection_event.payload["policy_decision"]["status"] == "policy_rejected"
    assert rejection_event.payload["policy_decision"]["allowed"] is False
    assert rejection_event.payload["policy_decision"]["policy_results"][0]["violations"] == [
        "risk_level_not_allowed"
    ]


def test_connector_ontology_promotion_endpoint_auto_selects_required_policy_and_rejects_mismatch(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        seed_required_promotion_policy(repository, allowed_risk_levels=["low"])
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["reason"] == "promotion_policy_rejected"
    assert detail["audit_event_type"] == "connector.ontology_promotion.rejected"
    with session_factory() as session:
        assert list(session.scalars(select(ConnectorOntologyPromotion))) == []
        rejection_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.ontology_promotion.rejected"
            )
        ).one()

    assert detail["audit_event_id"] == str(rejection_event.id)
    assert rejection_event.payload["policy_id"] == "policy_connector_asset_promotion_v1"
    assert rejection_event.payload["policy_set_id"] is None
    assert rejection_event.payload["policy_ids"] == ["policy_connector_asset_promotion_v1"]
    assert rejection_event.payload["policy_decision"]["status"] == "policy_rejected"
    assert rejection_event.payload["policy_decision"]["matched_constraints"]["selection_mode"] == (
        "auto_required"
    )
    assert rejection_event.payload["policy_decision"]["policy_results"][0]["violations"] == [
        "risk_level_not_allowed"
    ]


def test_connector_ontology_promotion_rejects_ambiguous_required_policy_selection(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        seed_required_promotion_policy(repository, policy_id="policy_connector_asset_required_a")
        seed_required_promotion_policy(repository, policy_id="policy_connector_asset_required_b")
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "promotion_policy_selection_ambiguous"
    with session_factory() as session:
        assert list(session.scalars(select(ConnectorOntologyPromotion))) == []


def test_connector_ontology_promotion_enforces_active_policy_set_for_multiple_required_policies(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        policy_ids = [
            "policy_connector_asset_required_scope",
            "policy_connector_asset_required_risk",
        ]
        for policy_id in policy_ids:
            seed_required_promotion_policy(repository, policy_id=policy_id)
        seed_active_promotion_policy_set(repository, policy_ids)
        result = record_demo_connector_ontology_promotion(
            repository,
            ConnectorOntologyPromotionRequest(**promotion_payload()),
            ontology_runtime,
        )

    with session_factory() as session:
        promotion = session.scalars(select(ConnectorOntologyPromotion)).one()
        proposal = session.scalars(select(ConnectorOntologyProposal)).one()
        audit_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.ontology_promotion.applied"
            )
        ).one()

    assert result.policy_set_id == "policy_set_connector_asset_required_20260622"
    assert result.policy_ids == [
        "policy_connector_asset_required_scope",
        "policy_connector_asset_required_risk",
    ]
    assert result.policy_decision is not None
    assert result.policy_decision.status == "policy_set_enforced"
    assert result.policy_decision.policy_set_id == "policy_set_connector_asset_required_20260622"
    assert result.policy_decision.policy_ids == result.policy_ids
    assert result.policy_decision.matched_constraints["selection_mode"] == "active_policy_set"
    assert promotion.policy_set_id == "policy_set_connector_asset_required_20260622"
    assert promotion.policy_ids == result.policy_ids
    assert proposal.policy_set_id == "policy_set_connector_asset_required_20260622"
    assert audit_event.payload["policy_set_id"] == "policy_set_connector_asset_required_20260622"
    assert audit_event.payload["policy_ids"] == result.policy_ids
    assert audit_event.payload["policy_decision"]["status"] == "policy_set_enforced"
    assert len(audit_event.payload["policy_decision"]["policy_results"]) == 2


def test_connector_ontology_promotion_rejects_active_policy_set_violation(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        seed_required_promotion_policy(
            repository,
            policy_id="policy_connector_asset_required_scope",
        )
        seed_required_promotion_policy(
            repository,
            policy_id="policy_connector_asset_required_risk",
            allowed_risk_levels=["low"],
        )
        seed_active_promotion_policy_set(
            repository,
            [
                "policy_connector_asset_required_scope",
                "policy_connector_asset_required_risk",
            ],
        )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["reason"] == "promotion_policy_rejected"
    assert detail["audit_event_type"] == "connector.ontology_promotion.rejected"
    with session_factory() as session:
        assert list(session.scalars(select(ConnectorOntologyPromotion))) == []
        rejection_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.ontology_promotion.rejected"
            )
        ).one()

    assert detail["audit_event_id"] == str(rejection_event.id)
    assert rejection_event.payload["policy_set_id"] == (
        "policy_set_connector_asset_required_20260622"
    )
    assert rejection_event.payload["policy_ids"] == [
        "policy_connector_asset_required_scope",
        "policy_connector_asset_required_risk",
    ]
    assert rejection_event.payload["policy_decision"]["status"] == "policy_set_rejected"
    assert rejection_event.payload["policy_decision"]["policy_results"][1]["policy_id"] == (
        "policy_connector_asset_required_risk"
    )
    assert rejection_event.payload["policy_decision"]["policy_results"][1]["allowed"] is False
    assert rejection_event.payload["policy_decision"]["policy_results"][1]["violations"] == [
        "risk_level_not_allowed"
    ]


def test_connector_ontology_promotion_rejects_explicit_policy_when_policy_set_active(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        policy_ids = [
            "policy_connector_asset_required_scope",
            "policy_connector_asset_required_risk",
        ]
        for policy_id in policy_ids:
            seed_required_promotion_policy(repository, policy_id=policy_id)
        seed_active_promotion_policy_set(repository, policy_ids)
    client = TestClient(app)
    explicit_payload = promotion_payload()
    explicit_payload["policy_id"] = "policy_connector_asset_required_scope"

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=explicit_payload,
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["reason"] == "promotion_policy_set_required"
    assert detail["audit_event_type"] == "connector.ontology_promotion.rejected"
    with session_factory() as session:
        assert list(session.scalars(select(ConnectorOntologyPromotion))) == []
        rejection_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.ontology_promotion.rejected"
            )
        ).one()

    assert detail["audit_event_id"] == str(rejection_event.id)
    assert rejection_event.payload["policy_id"] == "policy_connector_asset_required_scope"
    assert rejection_event.payload["policy_set_id"] == (
        "policy_set_connector_asset_required_20260622"
    )
    assert rejection_event.payload["policy_ids"] == [
        "policy_connector_asset_required_scope",
        "policy_connector_asset_required_risk",
    ]
    assert rejection_event.payload["rejection_reason"] == "promotion_policy_set_required"
    assert rejection_event.payload["policy_decision"]["status"] == "policy_set_rejected"
    assert rejection_event.payload["policy_decision"]["reason"] == "policy_set_required"


def test_connector_ontology_promotion_rejects_explicit_policy_after_policy_set_replay(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.ontology_mutation_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        policy_ids = [
            "policy_connector_asset_required_scope",
            "policy_connector_asset_required_risk",
        ]
        for policy_id in policy_ids:
            seed_required_promotion_policy(repository, policy_id=policy_id)
        seed_active_promotion_policy_set(repository, policy_ids)
    client = TestClient(app)
    explicit_payload = promotion_payload()
    explicit_payload["policy_id"] = "policy_connector_asset_required_scope"

    first_response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )
    second_response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=explicit_payload,
    )

    assert first_response.status_code == 201
    assert first_response.json()["policy_set_id"] == "policy_set_connector_asset_required_20260622"
    assert second_response.status_code == 409
    assert second_response.json()["detail"]["reason"] == "idempotency_conflict"


def test_connector_ontology_promotion_endpoint_records_runtime_unavailable(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.ontology_mutation_runtime = FailingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        seed_promotable_connector_proposal(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "promotion_failed"
    assert body["graph_mutation_status"] == "type_db_mutation_unavailable"
    assert body["ontology_mutation"]["payload"]["reason"] == "synthetic_typedb_down"
    assert body["proposal"]["status"] == "proposed_from_preview"
    assert body["proposal"]["graph_mutation_status"] == "not_applied"


def test_connector_ontology_promotion_records_verification_failure(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.ontology_mutation_runtime = VerificationFailingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        seed_promotable_connector_proposal(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "promotion_failed"
    assert body["graph_mutation_status"] == "type_db_mutation_failed"
    assert body["ontology_mutation"]["payload"]["reason"] == "verification_missing_node"
    # Fail-closed: the proposal is NOT marked promoted and stays retry-safe.
    assert body["proposal"]["status"] == "proposed_from_preview"
    assert body["proposal"]["graph_mutation_status"] == "not_applied"
    assert body["audit_event_type"] == "connector.ontology_promotion.failed"


def test_connector_ontology_promotion_deferred_runtime_writes_nothing(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_runtime = DeferredRecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        result = record_demo_connector_ontology_promotion(
            repository,
            ConnectorOntologyPromotionRequest(**promotion_payload()),
            ontology_runtime,
        )

    with session_factory() as session:
        promotion = session.scalars(select(ConnectorOntologyPromotion)).one()
        proposal = session.scalars(select(ConnectorOntologyProposal)).one()

    assert result.status == "promotion_deferred"
    assert result.graph_mutation_status == "type_db_mutation_deferred"
    assert promotion.status == "promotion_deferred"
    # Proposal is untouched, so it remains promotable once mutations are enabled.
    assert proposal.status == "proposed_from_preview"
    assert proposal.graph_mutation_status == "not_applied"
    assert proposal.promotion_id is None


def test_connector_ontology_promotion_is_idempotent_for_same_payload(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.ontology_mutation_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        seed_promotable_connector_proposal(AxisPersistenceRepository(session))
    client = TestClient(app)

    first_response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )
    second_response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["idempotent_replay"] is True
    assert second_response.json()["audit_event_id"] == first_response.json()["audit_event_id"]


def test_connector_ontology_promotion_replays_auto_selected_policy(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.ontology_mutation_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        seed_required_promotion_policy(repository)
    client = TestClient(app)

    first_response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )
    second_response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["idempotent_replay"] is True
    assert second_response.json()["policy_id"] == "policy_connector_asset_promotion_v1"
    assert second_response.json()["policy_decision"]["status"] == "policy_enforced"
    assert second_response.json()["audit_event_id"] == first_response.json()["audit_event_id"]


def test_connector_ontology_promotion_rejects_omitted_policy_after_explicit_policy(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.ontology_mutation_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_promotable_connector_proposal(repository)
        seed_required_promotion_policy(repository)
    client = TestClient(app)

    first_response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload_with_policy(),
    )
    second_response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json()["detail"]["reason"] == "idempotency_conflict"


def test_connector_ontology_promotion_rejects_idempotency_conflict(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.ontology_mutation_runtime = RecordingOntologyMutationRuntime()
    with session_scope(session_factory) as session:
        seed_promotable_connector_proposal(AxisPersistenceRepository(session))
    client = TestClient(app)
    conflicting_payload = promotion_payload()
    conflicting_payload["proposal_id"] = "proposal_other"

    assert client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=promotion_payload(),
    ).status_code == 201

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals/promotions",
        json=conflicting_payload,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "idempotency_conflict"
    assert response.json()["detail"]["promotion_id"] == "promote_asset_line_2_packaging_20260622"


def test_openapi_exposes_connector_ontology_promotion_endpoint(openapi_schema: dict) -> None:
    paths = openapi_schema["paths"]
    assert "/demo/manufacturing/connectors/ontology-proposals/promotions" in paths
