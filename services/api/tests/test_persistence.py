from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from axis_api.audit import AuditEventCreate
from axis_api.models import (
    ActionRun,
    ApprovalRecord,
    AuditEvent,
    AuditLegalHold,
    Base,
    ConnectorConfiguration,
    ConnectorCredentialHandle,
    ConnectorCredentialRotation,
    ConnectorManifestRecord,
    ConnectorManualImportRequest,
    ConnectorOntologyPromotion,
    ConnectorOntologyProposal,
    ConnectorPromotionPolicy,
    ConnectorRun,
    ConnectorSyncCheckpoint,
    DemoReferenceRecord,
)
from axis_api.persistence import (
    ActionRunCreate,
    ActionRunResultRecord,
    ApprovalDecisionRecord,
    ApprovalRecordCreate,
    AxisPersistenceRepository,
    ConnectorConfigurationCreate,
    ConnectorCredentialHandleCreate,
    ConnectorCredentialRotationCreate,
    ConnectorManifestCreate,
    ConnectorManualImportDecisionRecord,
    ConnectorManualImportRequestCreate,
    ConnectorOntologyPromotionCreate,
    ConnectorOntologyPromotionResultRecord,
    ConnectorOntologyProposalCreate,
    ConnectorPromotionPolicyCreate,
    ConnectorRunCreate,
    ConnectorSyncCheckpointClaimCreate,
    ConnectorSyncCheckpointCreate,
    DemoReferenceRecordCreate,
    PersistenceRecordNotFound,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def test_persistence_metadata_exposes_foundation_tables() -> None:
    assert {
        "audit_events",
        "audit_legal_holds",
        "approval_records",
        "action_runs",
        "connector_configurations",
        "connector_manifests",
        "connector_credential_handles",
        "connector_credential_rotations",
        "connector_runs",
        "connector_sync_checkpoints",
        "connector_ontology_proposals",
        "connector_ontology_promotions",
        "connector_promotion_policies",
        "connector_manual_import_requests",
        "demo_reference_records",
    }.issubset(Base.metadata.tables.keys())
    assert ApprovalRecord.__table__.c.tenant_id.index is True
    assert ActionRun.__table__.c.idempotency_key.index is True
    assert AuditEvent.__table__.c.event_type.index is True
    assert AuditLegalHold.__table__.c.hold_id.index is True
    assert AuditLegalHold.__table__.c.status.index is True
    assert ConnectorConfiguration.__table__.c.connector_id.index is True
    assert ConnectorManifestRecord.__table__.c.connector_id.index is True
    assert ConnectorCredentialHandle.__table__.c.handle_id.index is True
    assert ConnectorCredentialRotation.__table__.c.handle_id.index is True
    assert ConnectorRun.__table__.c.run_id.index is True
    assert ConnectorSyncCheckpoint.__table__.c.checkpoint_id.index is True
    assert ConnectorSyncCheckpoint.__table__.c.run_id.index is True
    assert ConnectorSyncCheckpoint.__table__.c.status.index is True
    assert ConnectorOntologyProposal.__table__.c.proposal_id.index is True
    assert ConnectorOntologyProposal.__table__.c.promotion_id.index is True
    assert ConnectorOntologyProposal.__table__.c.policy_id.index is True
    assert ConnectorOntologyProposal.__table__.c.promoted_by.index is True
    assert ConnectorOntologyPromotion.__table__.c.promotion_id.index is True
    assert ConnectorOntologyPromotion.__table__.c.idempotency_key.index is True
    assert ConnectorOntologyPromotion.__table__.c.policy_id.index is True
    assert ConnectorPromotionPolicy.__table__.c.policy_id.index is True
    assert ConnectorPromotionPolicy.__table__.c.status.index is True
    assert ConnectorPromotionPolicy.__table__.c.created_by.index is True
    assert ConnectorManualImportRequest.__table__.c.import_id.index is True
    assert ConnectorManualImportRequest.__table__.c.idempotency_key.index is True
    assert ConnectorManualImportRequest.__table__.c.decision.index is True
    assert ConnectorManualImportRequest.__table__.c.decision_actor_id.index is True
    assert DemoReferenceRecord.__table__.c.tenant_id.index is True
    assert DemoReferenceRecord.__table__.c.surface.index is True
    assert DemoReferenceRecord.__table__.c.status.index is True


def test_repository_persists_demo_reference_records_by_surface(session: Session) -> None:
    repository = AxisPersistenceRepository(session)
    created = repository.upsert_demo_reference_record(
        DemoReferenceRecordCreate(
            tenant_id="tenant_demo_manufacturing",
            surface="overview",
            reference_id="manufacturing-overview",
            status="active",
            source="bootstrap",
            version="2026-06-22",
            payload={
                "tenant_id": "tenant_demo_manufacturing",
                "plant_name": "Persisted Plant",
                "scenario": "Persisted Overview",
                "as_of": "2026-06-22T10:00:00+02:00",
                "metrics": [
                    {
                        "label": "Persisted Metric",
                        "value": "1",
                        "detail": "Loaded from the repository.",
                        "status": "ready",
                    }
                ],
                "risk_signals": [
                    {
                        "title": "Persisted risk",
                        "domain": "Operations",
                        "severity": "watch",
                        "owner_role": "operations-owner",
                        "evidence": "Persisted risk evidence.",
                        "related_asset": "asset_persisted",
                    }
                ],
                "workflows": [
                    {
                        "workflow_id": "wf_persisted",
                        "name": "Persisted Workflow",
                        "state": "ready",
                        "owner_role": "operations-owner",
                        "blocker": None,
                        "eta": "Today",
                    }
                ],
                "approvals": [
                    {
                        "approval_id": "appr_persisted",
                        "action": "Persisted approval",
                        "risk_level": "low",
                        "requested_by": "axis-bootstrap",
                        "owner_role": "operations-owner",
                        "due": "Today",
                    }
                ],
                "agents": [
                    {
                        "agent_id": "agent_persisted",
                        "name": "Persisted Agent",
                        "autonomy_level": "L1",
                        "status": "ready",
                        "proposals_pending": 0,
                        "model_policy": "local-only",
                    }
                ],
                "audit_events": [
                    {
                        "event": "overview.loaded",
                        "actor": "axis-bootstrap",
                        "scope": "overview",
                        "result": "persisted",
                    }
                ],
            },
        )
    )

    loaded = repository.get_demo_reference_record(
        tenant_id="tenant_demo_manufacturing",
        surface="overview",
        reference_id="manufacturing-overview",
    )

    assert loaded is not None
    assert loaded.id == created.id
    assert loaded.payload["plant_name"] == "Persisted Plant"
    assert loaded.source == "bootstrap"

    inactive_payload = dict(loaded.payload)
    inactive_payload["plant_name"] = "Inactive Persisted Plant"
    inactive = repository.upsert_demo_reference_record(
        DemoReferenceRecordCreate(
            tenant_id="tenant_demo_manufacturing",
            surface="overview",
            reference_id="manufacturing-overview",
            status="inactive",
            source="bootstrap",
            version="2026-06-23",
            payload=inactive_payload,
        )
    )

    assert inactive.id == created.id
    assert (
        repository.get_demo_reference_record(
            tenant_id="tenant_demo_manufacturing",
            surface="overview",
            reference_id="manufacturing-overview",
        )
        is None
    )

    reactivated_payload = dict(inactive.payload)
    reactivated_payload["plant_name"] = "Reactivated Persisted Plant"
    reactivated = repository.upsert_demo_reference_record(
        DemoReferenceRecordCreate(
            tenant_id="tenant_demo_manufacturing",
            surface="overview",
            reference_id="manufacturing-overview",
            status="active",
            source="bootstrap",
            version="2026-06-24",
            payload=reactivated_payload,
        )
    )
    loaded = repository.get_demo_reference_record(
        tenant_id="tenant_demo_manufacturing",
        surface="overview",
        reference_id="manufacturing-overview",
    )

    assert reactivated.id == created.id
    assert loaded is not None
    assert loaded.payload["plant_name"] == "Reactivated Persisted Plant"
    assert loaded.version == "2026-06-24"


def test_repository_appends_audit_events_without_cross_tenant_leakage(session: Session) -> None:
    repository = AxisPersistenceRepository(session)
    first = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="axis-test",
            event_type="approval.created",
            payload={"approval_id": "appr_1"},
        )
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_other",
            actor_id="axis-test",
            event_type="approval.created",
            payload={"approval_id": "appr_other"},
        )
    )

    events = repository.list_audit_events("tenant_demo_manufacturing")

    assert len(events) == 1
    assert events[0].id == first.id
    assert events[0].payload == {"approval_id": "appr_1"}


def test_repository_records_approval_decisions(session: Session) -> None:
    repository = AxisPersistenceRepository(session)
    approval = repository.create_approval_record(
        ApprovalRecordCreate(
            tenant_id="tenant_demo_manufacturing",
            approval_id="appr_expedite_supplier_batch",
            workflow_id="wf_supplier_delay_review",
            action_id="request_supplier_expedite",
            requested_by="agent_supply_risk",
            owner_role="plant-operations-owner",
            risk_level="high",
            payload={"required_permission": "approvals:supply:decide"},
        )
    )

    decided = repository.record_approval_decision(
        ApprovalDecisionRecord(
            tenant_id="tenant_demo_manufacturing",
            approval_id="appr_expedite_supplier_batch",
            decision="approved",
            decision_actor_id="plant-operations-owner-role",
            decision_note="Approved inside synthetic test scope.",
        )
    )

    assert decided.id == approval.id
    assert decided.status == "approved"
    assert decided.decision == "approved"
    assert decided.decision_actor_id == "plant-operations-owner-role"
    assert decided.decided_at is not None
    assert repository.list_approval_records("tenant_demo_manufacturing", status="approved") == [
        decided
    ]


def test_repository_raises_for_missing_approval_decision(session: Session) -> None:
    repository = AxisPersistenceRepository(session)

    with pytest.raises(PersistenceRecordNotFound, match="Approval record not found"):
        repository.record_approval_decision(
            ApprovalDecisionRecord(
                tenant_id="tenant_demo_manufacturing",
                approval_id="missing",
                decision="approved",
                decision_actor_id="plant-operations-owner-role",
            )
        )


def test_repository_records_action_runs_and_results(session: Session) -> None:
    repository = AxisPersistenceRepository(session)
    action_run = repository.create_action_run(
        ActionRunCreate(
            tenant_id="tenant_demo_manufacturing",
            action_id="request_supplier_expedite",
            idempotency_key="tenant_demo_manufacturing:request_supplier_expedite:appr_1",
            execution_mode="approval_gated_dry_run",
            requested_by="agent_supply_risk",
            approval_id="appr_expedite_supplier_batch",
            workflow_id="wf_supplier_delay_review",
            payload={"supplier_batch_id": "batch_motors_773"},
        )
    )

    found = repository.get_action_run_by_idempotency_key(
        "tenant_demo_manufacturing",
        "request_supplier_expedite",
        "tenant_demo_manufacturing:request_supplier_expedite:appr_1",
    )
    completed = repository.record_action_run_result(
        ActionRunResultRecord(
            tenant_id="tenant_demo_manufacturing",
            action_run_id=action_run.id,
            status="completed",
            result_payload={"dry_run": "recorded"},
        )
    )

    assert found == action_run
    assert completed.status == "completed"
    assert completed.result_payload == {"dry_run": "recorded"}
    assert repository.list_action_runs("tenant_demo_manufacturing", status="completed") == [
        completed
    ]


def test_action_run_idempotency_is_unique_per_tenant_action(session: Session) -> None:
    repository = AxisPersistenceRepository(session)
    payload = ActionRunCreate(
        tenant_id="tenant_demo_manufacturing",
        action_id="request_supplier_expedite",
        idempotency_key="duplicate-key",
        execution_mode="approval_gated_dry_run",
        requested_by="agent_supply_risk",
    )

    repository.create_action_run(payload)

    with pytest.raises(IntegrityError):
        repository.create_action_run(payload)


def test_repository_records_connector_configurations_tenant_scoped(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    created = repository.create_connector_configuration(
        ConnectorConfigurationCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            display_name="Manufacturing assets CSV intake",
            status="configured_preview_only",
            sync_mode="preview",
            runtime_boundary="axis-connector-sandbox",
            created_by="plant-operations-owner-role",
            configuration_payload={
                "file_name_pattern": "*.csv",
                "mapping_profile": "manufacturing_asset_v1",
            },
            credential_ref_ids=[],
            notes=["Preview-only tenant configuration."],
        )
    )
    repository.create_connector_configuration(
        ConnectorConfigurationCreate(
            tenant_id="tenant_other",
            connector_id="file_csv_manufacturing_assets",
            display_name="Other tenant CSV intake",
            status="configured_preview_only",
            sync_mode="preview",
            runtime_boundary="axis-connector-sandbox",
            created_by="other-owner-role",
            configuration_payload={"file_name_pattern": "*.csv"},
            credential_ref_ids=[],
            notes=[],
        )
    )

    records = repository.list_connector_configurations("tenant_demo_manufacturing")

    assert records == [created]
    assert records[0].configuration_payload == {
        "file_name_pattern": "*.csv",
        "mapping_profile": "manufacturing_asset_v1",
    }
    assert records[0].credential_ref_ids == []
    assert records[0].status == "configured_preview_only"


def test_repository_records_connector_manifests_tenant_scoped(session: Session) -> None:
    repository = AxisPersistenceRepository(session)
    created = repository.create_connector_manifest(
        ConnectorManifestCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_shift_orders",
            revision_number=1,
            display_name="Shift orders database mirror",
            connector_type="external_db",
            source_type="database",
            version="2026-06-22",
            status="registered_preview_only",
            runtime_boundary="axis-connector-sandbox",
            registered_by="platform-connector-owner-role",
            manifest_payload={"connector_id": "external_db_shift_orders"},
            runtime_policy={"blocked_operations": ["live_query"]},
            preview_sample={"record_count": 1},
            audit_event_id=None,
            audit_event_type="connector.manifest.registered",
            notes=["Manifest is public-safe."],
        )
    )
    repository.create_connector_manifest(
        ConnectorManifestCreate(
            tenant_id="tenant_other",
            connector_id="external_db_shift_orders",
            revision_number=1,
            display_name="Other tenant database mirror",
            connector_type="external_db",
            source_type="database",
            version="2026-06-22",
            status="registered_preview_only",
            runtime_boundary="axis-connector-sandbox",
            registered_by="other-owner-role",
            manifest_payload={"connector_id": "external_db_shift_orders"},
            runtime_policy={},
            preview_sample={},
            audit_event_id=None,
            audit_event_type="connector.manifest.registered",
            notes=[],
        )
    )

    records = repository.list_connector_manifests("tenant_demo_manufacturing")

    assert records == [created]
    assert records[0].connector_id == "external_db_shift_orders"
    assert records[0].manifest_payload == {"connector_id": "external_db_shift_orders"}
    assert records[0].runtime_policy == {"blocked_operations": ["live_query"]}
    assert records[0].status == "registered_preview_only"


def test_repository_records_connector_credential_handles_and_rotations(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    created = repository.create_connector_credential_handle(
        ConnectorCredentialHandleCreate(
            tenant_id="tenant_demo_manufacturing",
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
            created_by="plant-operations-owner-role",
            labels={"environment": "demo"},
            notes=["Metadata-only handle; no raw credential value is stored."],
        )
    )
    repository.create_connector_credential_handle(
        ConnectorCredentialHandleCreate(
            tenant_id="tenant_other",
            connector_id="file_csv_manufacturing_assets",
            handle_id="cred_other",
            display_name="Other tenant handle",
            status="active",
            secret_provider="external_vault",
            secret_ref="vault://axis/demo/connectors/other",
            purpose="preview_import_readonly",
            rotation_interval_days=30,
            last_rotated_at=datetime(2026, 6, 1, tzinfo=UTC),
            next_rotation_due_at=datetime(2026, 7, 1, tzinfo=UTC),
            created_by="other-owner-role",
        )
    )

    rotation = repository.record_connector_credential_rotation(
        ConnectorCredentialRotationCreate(
            tenant_id="tenant_demo_manufacturing",
            handle_id="cred_file_csv_readonly",
            rotated_by="security-operations-role",
            rotated_at=datetime(2026, 6, 22, tzinfo=UTC),
            evidence_ref="change-window-2026-06-22",
            status="rotated",
            notes=["Reference rotated in external vault; Axis stored metadata only."],
        )
    )

    handles = repository.list_connector_credential_handles("tenant_demo_manufacturing")
    rotations = repository.list_connector_credential_rotations(
        "tenant_demo_manufacturing",
        "cred_file_csv_readonly",
    )

    assert handles == [created]
    assert handles[0].secret_ref == "vault://axis/demo/connectors/file-csv-readonly"
    assert handles[0].rotation_interval_days == 30
    assert handles[0].labels == {"environment": "demo"}
    assert rotations == [rotation]
    assert rotations[0].evidence_ref == "change-window-2026-06-22"


def test_repository_records_connector_runs_tenant_scoped(session: Session) -> None:
    repository = AxisPersistenceRepository(session)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="connector-runtime-adapter",
            event_type="connector.run.recorded",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "run_id": "run_file_csv_assets_preview_20260622",
                "execution_mode": "preview",
            },
        )
    )
    created = repository.create_connector_run(
        ConnectorRunCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            run_id="run_file_csv_assets_preview_20260622",
            status="recorded_preview_only",
            execution_mode="preview",
            runtime_boundary="axis-connector-sandbox",
            requested_by="plant-operations-owner-role",
            credential_handle_ids=["cred_file_csv_readonly"],
            input_summary={"file_name": "manufacturing-assets-demo.csv", "record_count": "2"},
            result_summary={"accepted_record_count": "2", "rejected_record_count": "0"},
            audit_event_id=audit_event.id,
            notes=["Run record only; no connector execution occurred."],
        )
    )
    repository.create_connector_run(
        ConnectorRunCreate(
            tenant_id="tenant_other",
            connector_id="file_csv_manufacturing_assets",
            run_id="run_other",
            status="recorded_preview_only",
            execution_mode="preview",
            runtime_boundary="axis-connector-sandbox",
            requested_by="other-owner-role",
            input_summary={"file_name": "other.csv"},
            result_summary={},
            audit_event_id=audit_event.id,
        )
    )

    records = repository.list_connector_runs("tenant_demo_manufacturing")

    assert records == [created]
    assert records[0].run_id == "run_file_csv_assets_preview_20260622"
    assert records[0].audit_event_id == audit_event.id
    assert records[0].credential_handle_ids == ["cred_file_csv_readonly"]
    assert records[0].input_summary == {
        "file_name": "manufacturing-assets-demo.csv",
        "record_count": "2",
    }


def test_repository_records_connector_sync_checkpoints_tenant_scoped(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="axis-sync-worker-role",
            event_type="connector.run.sync_checkpoint.recorded",
            payload={
                "connector_id": "external_db_operational_mirror",
                "run_id": "run_external_db_orders_scheduled_20260625",
                "checkpoint_id": "chk_external_db_orders_20260625_1400_0001",
            },
        )
    )

    created = repository.create_connector_sync_checkpoint(
        ConnectorSyncCheckpointCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            run_id="run_external_db_orders_scheduled_20260625",
            checkpoint_id="chk_external_db_orders_20260625_1400_0001",
            checkpoint_type="sync_execution",
            status="checkpoint_recorded",
            sequence=1,
            runtime_boundary="axis-connector-sandbox",
            adapter="axis-postgres-external-db-sync-executor",
            cursor={
                "cursor_type": "watermark",
                "watermark_column": "updated_at",
                "last_seen_value": "2026-06-25T12:00:00Z",
            },
            result_summary={
                "records_read": "2",
                "records_accepted": "2",
                "external_query_started": "false",
                "credential_material_returned": "false",
            },
            evidence_refs=[str(audit_event.id)],
            audit_event_id=audit_event.id,
            audit_event_type="connector.run.sync_checkpoint.recorded",
            notes=["Checkpoint evidence only; no secret material stored."],
        )
    )
    repository.create_connector_sync_checkpoint(
        ConnectorSyncCheckpointCreate(
            tenant_id="tenant_other",
            connector_id="external_db_operational_mirror",
            run_id="run_external_db_orders_other",
            checkpoint_id="chk_other",
            checkpoint_type="sync_execution",
            status="checkpoint_recorded",
            sequence=1,
            runtime_boundary="axis-connector-sandbox",
            adapter="axis-postgres-external-db-sync-executor",
            cursor={"cursor_type": "watermark"},
            result_summary={},
            evidence_refs=[],
            audit_event_id=audit_event.id,
        )
    )

    records = repository.list_connector_sync_checkpoints(
        "tenant_demo_manufacturing",
        run_id="run_external_db_orders_scheduled_20260625",
    )

    assert records == [created]
    assert records[0].checkpoint_id == "chk_external_db_orders_20260625_1400_0001"
    assert records[0].cursor["last_seen_value"] == "2026-06-25T12:00:00Z"
    assert records[0].result_summary["credential_material_returned"] == "false"
    assert records[0].audit_event_id == audit_event.id
    assert "secret" not in str(records[0].cursor).lower()

    with pytest.raises(IntegrityError):
        repository.create_connector_sync_checkpoint(
            ConnectorSyncCheckpointCreate(
                tenant_id="tenant_demo_manufacturing",
                connector_id="external_db_operational_mirror",
                run_id="run_external_db_orders_scheduled_20260625",
                checkpoint_id="chk_external_db_orders_20260625_1400_0001",
                checkpoint_type="sync_execution",
                status="checkpoint_recorded",
                sequence=2,
                runtime_boundary="axis-connector-sandbox",
                adapter="axis-postgres-external-db-sync-executor",
                cursor={"cursor_type": "watermark"},
                result_summary={},
                evidence_refs=[],
                audit_event_id=audit_event.id,
            )
        )


def test_repository_records_connector_ontology_proposals_tenant_scoped(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="connector-preview-service",
            event_type="connector.ontology_proposals.recorded",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "proposal_ids": ["proposal_asset_line_2_packaging"],
                "write_mode": "proposal_only",
            },
        )
    )
    created = repository.create_connector_ontology_proposal(
        ConnectorOntologyProposalCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            proposal_id="proposal_asset_line_2_packaging",
            source_run_id="run_file_csv_assets_preview_20260622",
            source_file_name="manufacturing-assets-demo.csv",
            mapping_profile="manufacturing_asset_v1",
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
            audit_event_id=audit_event.id,
            notes=["Proposal persisted for review; graph mutation is not applied."],
        )
    )
    repository.create_connector_ontology_proposal(
        ConnectorOntologyProposalCreate(
            tenant_id="tenant_other",
            connector_id="file_csv_manufacturing_assets",
            proposal_id="proposal_other",
            source_file_name="other.csv",
            mapping_profile="manufacturing_asset_v1",
            proposed_by="other-owner-role",
            node_id="asset_other",
            node_type="asset",
            ontology_type="manufacturing_asset",
            field_summary={"asset_name": "Other"},
            evidence_refs=["other.csv", "asset_other"],
            audit_event_id=audit_event.id,
        )
    )

    records = repository.list_connector_ontology_proposals("tenant_demo_manufacturing")

    assert records == [created]
    assert records[0].proposal_id == "proposal_asset_line_2_packaging"
    assert records[0].source_run_id == "run_file_csv_assets_preview_20260622"
    assert records[0].write_mode == "proposal_only"
    assert records[0].graph_mutation_status == "not_applied"
    assert records[0].audit_event_id == audit_event.id
    assert records[0].field_summary == {
        "asset_name": "Line 2 Packaging",
        "domain": "Operations",
        "station": "Line 2",
        "risk_level": "high",
    }
    assert records[0].promotion_id is None
    assert records[0].ontology_mutation is None


def test_repository_records_connector_ontology_promotion_and_updates_proposal(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    proposal = repository.create_connector_ontology_proposal(
        ConnectorOntologyProposalCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            proposal_id="proposal_asset_line_2_packaging",
            source_run_id="run_file_csv_assets_preview_20260622",
            source_file_name="manufacturing-assets-demo.csv",
            mapping_profile="manufacturing_asset_v1",
            proposed_by="plant-operations-owner-role",
            node_id="asset_line_2_packaging",
            node_type="asset",
            ontology_type="manufacturing_asset",
            field_summary={"asset_name": "Line 2 Packaging"},
            evidence_refs=["manufacturing-assets-demo.csv"],
        )
    )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="plant-operations-owner-role",
            event_type="connector.ontology_promotion.applied",
            payload={
                "proposal_id": "proposal_asset_line_2_packaging",
                "graph_mutation_status": "type_db_mutation_applied",
            },
        )
    )
    promotion = repository.create_connector_ontology_promotion(
        ConnectorOntologyPromotionCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            promotion_id="promote_asset_line_2_packaging_20260622",
            idempotency_key="promote-asset-line-2-packaging-20260622",
            proposal_id="proposal_asset_line_2_packaging",
            manual_import_id="import_assets_manual_20260622",
            status="promoted_to_graph",
            promotion_mode="approved_manual_import",
            requested_by="plant-operations-owner-role",
            graph_mutation_status="type_db_mutation_applied",
            ontology_mutation={
                "status": "type_db_mutation_applied",
                "mutation_ref": "typedb://axis/asset_line_2_packaging",
            },
            permission_decision={"allowed": True, "reason": "allowed"},
            policy_id="policy_connector_asset_promotion_v1",
            policy_decision={
                "status": "policy_enforced",
                "allowed": True,
                "policy_id": "policy_connector_asset_promotion_v1",
                "policy_version": "2026-06-22",
                "enforcement_mode": "required",
                "reason": "policy_constraints_satisfied",
                "required_scopes": ["connectors:ontology:promote"],
                "matched_constraints": {
                    "risk_level": "high",
                    "ontology_type": "manufacturing_asset",
                },
            },
            audit_event_id=audit_event.id,
            audit_event_type="connector.ontology_promotion.applied",
            notes=["Promoted in persistence test."],
        )
    )
    updated_proposal = repository.record_connector_ontology_proposal_promotion(
        ConnectorOntologyPromotionResultRecord(
            tenant_id="tenant_demo_manufacturing",
            proposal_id="proposal_asset_line_2_packaging",
            status="promoted_to_graph",
            graph_mutation_status="type_db_mutation_applied",
            promotion_id="promote_asset_line_2_packaging_20260622",
            promoted_by="plant-operations-owner-role",
            ontology_mutation={
                "status": "type_db_mutation_applied",
                "mutation_ref": "typedb://axis/asset_line_2_packaging",
            },
            policy_id="policy_connector_asset_promotion_v1",
            policy_decision={
                "status": "policy_enforced",
                "allowed": True,
                "policy_id": "policy_connector_asset_promotion_v1",
                "policy_version": "2026-06-22",
                "enforcement_mode": "required",
                "reason": "policy_constraints_satisfied",
                "required_scopes": ["connectors:ontology:promote"],
                "matched_constraints": {
                    "risk_level": "high",
                    "ontology_type": "manufacturing_asset",
                },
            },
            audit_event_id=audit_event.id,
            audit_event_type="connector.ontology_promotion.applied",
        )
    )
    found_promotion = repository.get_connector_ontology_promotion_by_idempotency_key(
        "tenant_demo_manufacturing",
        "promote-asset-line-2-packaging-20260622",
    )
    found_proposal = repository.get_connector_ontology_proposal(
        "tenant_demo_manufacturing",
        "proposal_asset_line_2_packaging",
    )

    assert found_promotion == promotion
    assert found_proposal == updated_proposal
    assert updated_proposal.id == proposal.id
    assert updated_proposal.status == "promoted_to_graph"
    assert updated_proposal.graph_mutation_status == "type_db_mutation_applied"
    assert updated_proposal.promotion_id == "promote_asset_line_2_packaging_20260622"
    assert updated_proposal.promoted_by == "plant-operations-owner-role"
    assert updated_proposal.promoted_at is not None
    assert updated_proposal.ontology_mutation["status"] == "type_db_mutation_applied"
    assert updated_proposal.policy_id == "policy_connector_asset_promotion_v1"
    assert updated_proposal.policy_decision["status"] == "policy_enforced"
    assert updated_proposal.policy_decision["matched_constraints"]["risk_level"] == "high"
    assert promotion.policy_id == "policy_connector_asset_promotion_v1"
    assert promotion.policy_decision["reason"] == "policy_constraints_satisfied"
    assert promotion.audit_event_id == audit_event.id


def test_repository_records_connector_promotion_policy_authoring(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="platform-governance-owner-role",
            event_type="connector.promotion_policy.authored",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "policy_id": "policy_connector_asset_promotion_v1",
                "required_scopes": ["connectors:ontology:promote"],
            },
        )
    )

    policy = repository.create_connector_promotion_policy(
        ConnectorPromotionPolicyCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            policy_id="policy_connector_asset_promotion_v1",
            policy_version="2026-06-22",
            status="draft",
            enforcement_mode="advisory",
            created_by="platform-governance-owner-role",
            required_scopes=["connectors:ontology:promote"],
            required_manual_import_status="approval_approved",
            required_workflow_signal_status="manual_import_signal_requested",
            allowed_risk_levels=["high", "medium"],
            allowed_ontology_types=["manufacturing_asset"],
            review_window_hours=24,
            audit_event_id=audit_event.id,
            audit_event_type="connector.promotion_policy.authored",
            notes=["Policy draft for connector proposal promotion review."],
        )
    )

    found_policy = repository.get_connector_promotion_policy(
        "tenant_demo_manufacturing",
        "policy_connector_asset_promotion_v1",
    )
    policies = repository.list_connector_promotion_policies(
        "tenant_demo_manufacturing",
        connector_id="file_csv_manufacturing_assets",
    )

    assert found_policy == policy
    assert policies == [policy]
    assert policy.audit_event_id == audit_event.id
    assert policy.required_scopes == ["connectors:ontology:promote"]
    assert policy.required_manual_import_status == "approval_approved"
    assert policy.required_workflow_signal_status == "manual_import_signal_requested"
    assert policy.allowed_ontology_types == ["manufacturing_asset"]


def test_repository_adopts_connector_promotion_policy_revision(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    current = repository.create_connector_promotion_policy(
        ConnectorPromotionPolicyCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            policy_id="policy_connector_asset_promotion_v1",
            policy_version="2026-06-22.1",
            status="enabled",
            enforcement_mode="required",
            created_by="platform-governance-owner-role",
            required_scopes=["connectors:ontology:promote"],
            required_manual_import_status="approval_approved",
            required_workflow_signal_status="manual_import_signal_requested",
            allowed_risk_levels=["high", "medium"],
            allowed_ontology_types=["manufacturing_asset"],
            review_window_hours=24,
            audit_event_type="connector.promotion_policy.enabled",
            notes=["Required policy enabled for connector ontology promotion."],
        )
    )
    revised = repository.create_connector_promotion_policy(
        ConnectorPromotionPolicyCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            policy_id="policy_connector_asset_promotion_v2",
            policy_version="2026-06-22.2",
            status="draft",
            enforcement_mode="advisory",
            created_by="platform-governance-owner-role",
            required_scopes=["connectors:ontology:promote"],
            required_manual_import_status="approval_approved",
            required_workflow_signal_status="manual_import_signal_requested",
            allowed_risk_levels=["medium"],
            allowed_ontology_types=["manufacturing_asset"],
            review_window_hours=24,
            audit_event_type="connector.promotion_policy.revised",
            revises_policy_id="policy_connector_asset_promotion_v1",
            revision_idempotency_key="idem_policy_revision_asset_promotion_v2",
            revision_approval_id="approval_policy_revision_asset_promotion_v2",
            revision_decision="approve",
            revision_workflow_signal_status="policy_revision_signal_recorded",
            notes=["Approved revision candidate awaiting adoption."],
        )
    )
    adoption_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="platform-governance-owner-role",
            event_type="connector.promotion_policy.revision_adopted",
            payload={
                "current_policy_id": current.policy_id,
                "revised_policy_id": revised.policy_id,
            },
        )
    )

    adopted = repository.adopt_connector_promotion_policy_revision(
        current,
        revised,
        audit_event_id=adoption_event.id,
        audit_event_type=adoption_event.event_type,
        note="Adopted during policy-set replacement.",
    )

    assert adopted == revised
    assert current.status == "superseded"
    assert current.replaced_by_policy_id == "policy_connector_asset_promotion_v2"
    assert revised.status == "enabled"
    assert revised.enforcement_mode == "required"
    assert revised.audit_event_id == adoption_event.id
    assert revised.audit_event_type == "connector.promotion_policy.revision_adopted"
    assert "Adopted during policy-set replacement." in revised.notes


def test_repository_records_connector_manual_import_requests_tenant_scoped_and_idempotent(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="plant-operations-owner-role",
            event_type="connector.manual_import.requested",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "import_id": "import_assets_manual_20260622",
                "idempotency_key": "manual-import-assets-20260622",
                "proposal_ids": ["proposal_asset_line_2_packaging"],
                "graph_mutation_status": "not_applied",
            },
        )
    )
    created = repository.create_connector_manual_import_request(
        ConnectorManualImportRequestCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            import_id="import_assets_manual_20260622",
            idempotency_key="manual-import-assets-20260622",
            status="approval_required",
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
            workflow_signal_status="pending_approval_decision",
            audit_event_id=audit_event.id,
            audit_event_type="connector.manual_import.requested",
            notes=["Manual import request only; graph mutation is not applied."],
        )
    )
    repository.create_connector_manual_import_request(
        ConnectorManualImportRequestCreate(
            tenant_id="tenant_other",
            connector_id="file_csv_manufacturing_assets",
            import_id="import_other",
            idempotency_key="manual-import-other",
            status="approval_required",
            import_mode="manual_import_request",
            requested_by="other-owner-role",
            owner_role="other-owner",
            risk_level="medium",
            approval_id="appr_other",
            workflow_id="wf_other",
            proposal_ids=["proposal_other"],
            import_summary={"proposal_count": "1"},
            audit_event_id=audit_event.id,
        )
    )

    records = repository.list_connector_manual_import_requests("tenant_demo_manufacturing")
    found = repository.get_connector_manual_import_request_by_idempotency_key(
        "tenant_demo_manufacturing",
        "manual-import-assets-20260622",
    )

    assert records == [created]
    assert found == created
    assert records[0].import_id == "import_assets_manual_20260622"
    assert records[0].status == "approval_required"
    assert records[0].import_mode == "manual_import_request"
    assert records[0].approval_id == "appr_connector_import_assets_20260622"
    assert records[0].workflow_id == "wf_connector_manual_import_review"
    assert records[0].proposal_ids == ["proposal_asset_line_2_packaging"]
    assert records[0].graph_mutation_status == "not_applied"
    assert records[0].workflow_signal_status == "pending_approval_decision"
    assert records[0].audit_event_id == audit_event.id
    assert records[0].decision is None
    assert records[0].workflow_signal is None


def test_connector_manual_import_idempotency_is_unique_per_tenant(session: Session) -> None:
    repository = AxisPersistenceRepository(session)
    payload = ConnectorManualImportRequestCreate(
        tenant_id="tenant_demo_manufacturing",
        connector_id="file_csv_manufacturing_assets",
        import_id="import_assets_manual_20260622",
        idempotency_key="manual-import-assets-20260622",
        requested_by="plant-operations-owner-role",
        owner_role="plant-operations-owner",
        risk_level="high",
        approval_id="appr_connector_import_assets_20260622",
        workflow_id="wf_connector_manual_import_review",
        proposal_ids=["proposal_asset_line_2_packaging"],
    )

    repository.create_connector_manual_import_request(payload)

    with pytest.raises(IntegrityError):
        repository.create_connector_manual_import_request(payload)


def test_repository_records_connector_manual_import_decision_and_signal(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    created = repository.create_connector_manual_import_request(
        ConnectorManualImportRequestCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            import_id="import_assets_manual_20260622",
            idempotency_key="manual-import-assets-20260622",
            requested_by="plant-operations-owner-role",
            owner_role="plant-operations-owner",
            risk_level="high",
            approval_id="appr_connector_import_assets_20260622",
            workflow_id="wf_connector_manual_import_review",
            proposal_ids=["proposal_asset_line_2_packaging"],
        )
    )

    updated = repository.record_connector_manual_import_decision(
        ConnectorManualImportDecisionRecord(
            tenant_id="tenant_demo_manufacturing",
            import_id="import_assets_manual_20260622",
            status="approval_approved",
            decision="approve",
            decision_actor_id="plant-operations-owner-role",
            decision_note="Approved in persistence test.",
            workflow_signal_status="manual_import_signal_requested",
            workflow_signal={
                "workflow_id": "wf_connector_manual_import_review",
                "status": "manual_import_signal_requested",
                "signal_name": "connector_manual_import_decided",
            },
        )
    )
    found = repository.get_connector_manual_import_request(
        "tenant_demo_manufacturing",
        "import_assets_manual_20260622",
    )

    assert found == updated
    assert updated.id == created.id
    assert updated.status == "approval_approved"
    assert updated.decision == "approve"
    assert updated.decision_actor_id == "plant-operations-owner-role"
    assert updated.decision_note == "Approved in persistence test."
    assert updated.decided_at is not None
    assert updated.workflow_signal_status == "manual_import_signal_requested"
    assert updated.workflow_signal["signal_name"] == "connector_manual_import_decided"


def _live_sync_proposal_create(
    proposal_id: str = "prop_run_live_sync_r0",
    *,
    node_id: str = "asset_live_0",
    audit_event_id=None,
) -> ConnectorOntologyProposalCreate:
    return ConnectorOntologyProposalCreate(
        tenant_id="tenant_demo_manufacturing",
        connector_id="file_csv_manufacturing_assets",
        proposal_id=proposal_id,
        source_run_id="run_live_sync",
        source_file_name="dropzone-assets.csv",
        mapping_profile="connector_live_sync_v1",
        status="proposed_from_preview",
        write_mode="proposal_only",
        graph_mutation_status="not_applied",
        proposed_by="axis-sync-worker-role",
        node_id=node_id,
        node_type="asset",
        ontology_type="manufacturing_asset",
        field_summary={"asset_name": "Asset 0"},
        evidence_refs=["dropzone-assets.csv", node_id],
        audit_event_id=audit_event_id,
    )


def test_create_connector_ontology_proposal_if_absent_is_idempotent(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)

    first, created_first = repository.create_connector_ontology_proposal_if_absent(
        _live_sync_proposal_create()
    )
    second, created_second = repository.create_connector_ontology_proposal_if_absent(
        _live_sync_proposal_create(node_id="asset_live_0_dup")
    )

    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    # The conflicting insert is ignored, so the original row is preserved.
    assert second.node_id == "asset_live_0"

    records = repository.list_connector_ontology_proposals("tenant_demo_manufacturing")
    assert len(records) == 1
    assert records[0].proposal_id == "prop_run_live_sync_r0"


def test_create_connector_ontology_proposal_plain_add_raises_on_duplicate(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    repository.create_connector_ontology_proposal(_live_sync_proposal_create())

    with pytest.raises(IntegrityError):
        repository.create_connector_ontology_proposal(_live_sync_proposal_create())


def test_single_active_checkpoint_claim_index_rejects_second_claim(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    checkpoint_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="axis-sync-worker-role",
            event_type="connector.run.sync_execution_preflight_passed",
            payload={
                "connector_id": "external_db_operational_mirror",
                "run_id": "run_claim_index",
                "checkpoint_id": "chk_run_claim_index_batch_1",
            },
        )
    )
    repository.create_connector_sync_checkpoint(
        ConnectorSyncCheckpointCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            run_id="run_claim_index",
            checkpoint_id="chk_run_claim_index_batch_1",
            checkpoint_type="sync_batch",
            status="sync_batch_committed",
            sequence=1,
            runtime_boundary="axis-connector-sandbox",
            adapter="axis-postgres-external-db-live-sync-executor",
            cursor={"next_offset": "2"},
            result_summary={"external_query_started": "true"},
            evidence_refs=[str(checkpoint_event.id)],
            audit_event_id=checkpoint_event.id,
            audit_event_type="connector.run.sync_batch_committed",
            notes=["Batch checkpoint for claim index test."],
        )
    )

    def claim_row(claim_id: str, idempotency_key: str) -> ConnectorSyncCheckpointClaimCreate:
        return ConnectorSyncCheckpointClaimCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            run_id="run_claim_index",
            checkpoint_id="chk_run_claim_index_batch_1",
            claim_id=claim_id,
            status="claimed",
            claimed_by="axis-sync-worker-role",
            idempotency_key=idempotency_key,
            lease_duration_seconds=900,
            lease_expires_at=datetime(2030, 1, 1, tzinfo=UTC),
            claim_result={
                "external_sync_started": False,
                "secret_material_returned": False,
                "worker_claim_only": True,
            },
            audit_event_id=checkpoint_event.id,
            audit_event_type="connector.run.sync_checkpoint_claimed",
            notes=["Claim for single-active index test."],
        )

    repository.create_connector_sync_checkpoint_claim(claim_row("claim_a", "idem_a"))

    with pytest.raises(IntegrityError):
        repository.create_connector_sync_checkpoint_claim(claim_row("claim_b", "idem_b"))


def test_get_latest_connector_sync_checkpoint_orders_by_sequence(
    session: Session,
) -> None:
    repository = AxisPersistenceRepository(session)
    for sequence in (1, 3, 2):
        repository.create_connector_sync_checkpoint(
            ConnectorSyncCheckpointCreate(
                tenant_id="tenant_demo_manufacturing",
                connector_id="external_db_operational_mirror",
                run_id="run_latest_checkpoint",
                checkpoint_id=f"chk_run_latest_checkpoint_batch_{sequence}",
                checkpoint_type="sync_batch",
                status="sync_batch_committed",
                sequence=sequence,
                runtime_boundary="axis-connector-sandbox",
                adapter="axis-postgres-external-db-live-sync-executor",
                cursor={"next_offset": str(sequence * 2)},
                result_summary={"external_query_started": "true"},
                evidence_refs=[],
                audit_event_type="connector.run.sync_batch_committed",
                notes=["Batch checkpoint for latest lookup test."],
            )
        )

    latest = repository.get_latest_connector_sync_checkpoint(
        "tenant_demo_manufacturing",
        run_id="run_latest_checkpoint",
        checkpoint_type="sync_batch",
        status="sync_batch_committed",
    )

    assert latest is not None
    assert latest.sequence == 3
    assert latest.checkpoint_id == "chk_run_latest_checkpoint_batch_3"
    assert repository.count_connector_sync_checkpoints(
        "tenant_demo_manufacturing",
        run_id="run_latest_checkpoint",
    ) == 3
