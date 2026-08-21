from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from axis_api.audit import AuditEventCreate
from axis_api.connector_reference import require_persisted_manufacturing_connector_registry
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    find_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.persistence import AxisPersistenceRepository, ConnectorOntologyProposalCreate


class ConnectorOntologyProposalValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorOntologyProposalQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorOntologyProposalEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    node_id: str = Field(min_length=1, max_length=180)
    node_type: str = Field(min_length=1, max_length=80)
    ontology_type: str = Field(min_length=1, max_length=160)
    field_summary: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class ConnectorOntologyProposalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    source_run_id: str | None = Field(default=None, min_length=1, max_length=180)
    source_file_name: str = Field(min_length=1, max_length=240)
    mapping_profile: str = Field(default="manufacturing_asset_v1", min_length=1, max_length=160)
    write_mode: str = Field(default="proposal_only", min_length=1, max_length=80)
    proposed_by: str = Field(min_length=1, max_length=160)
    proposed_entities: list[ConnectorOntologyProposalEntity] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorOntologyProposalRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    source_run_id: str | None = None
    source_file_name: str = Field(min_length=1)
    mapping_profile: str = Field(min_length=1)
    status: str = Field(min_length=1)
    write_mode: str = Field(min_length=1)
    graph_mutation_status: str = Field(min_length=1)
    proposed_by: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    ontology_type: str = Field(min_length=1)
    field_summary: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    promotion_id: str | None = None
    policy_id: str | None = None
    policy_set_id: str | None = None
    policy_ids: list[str] | None = None
    policy_decision: dict | None = None
    promoted_by: str | None = None
    promoted_at: datetime | None = None
    ontology_mutation: dict | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ManufacturingConnectorOntologyProposalRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    proposals: list[ConnectorOntologyProposalRecord] = Field(default_factory=list)
    proposal_notes: list[str] = Field(default_factory=list)


AUDIT_EVENT_TYPE = "connector.ontology_proposals.recorded"
ALLOWED_WRITE_MODES = {"proposal_only"}
RAW_PAYLOAD_FIELD_NAMES = {
    "api_key",
    "client_secret",
    "credential_value",
    "csv_content",
    "password",
    "raw_file_content",
    "raw_payload",
    "secret",
    "secret_ref",
    "token",
}


def build_connector_ontology_proposal_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorOntologyProposalQuery,
) -> ManufacturingConnectorOntologyProposalRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_connector_ontology_proposals(
        tenant_id=query.tenant_id,
        connector_id=query.connector_id,
        status=query.status,
        limit=query.limit,
    )
    proposals = [_proposal_from_record(record) for record in records]
    pending_review = sum(1 for proposal in proposals if proposal.status == "proposed_from_preview")
    graph_mutations = sum(
        1
        for proposal in proposals
        if proposal.graph_mutation_status == "type_db_mutation_applied"
    )
    return ManufacturingConnectorOntologyProposalRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.READY if proposals else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Ontology Proposals",
                value=str(len(proposals)),
                detail="Connector preview proposals persisted for review",
                status=OverviewStatus.READY if proposals else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Pending Review",
                value=str(pending_review),
                detail="Proposals waiting for approval or import workflow",
                status=OverviewStatus.WATCH if pending_review else OverviewStatus.READY,
            ),
            OverviewMetric(
                label="Graph Mutations",
                value=str(graph_mutations),
                detail="Connector proposals promoted through controlled graph mutation",
                status=OverviewStatus.READY
                if graph_mutations <= len(proposals)
                else OverviewStatus.ACTION_REQUIRED,
            ),
        ],
        proposals=proposals,
        proposal_notes=[
            "Connector ontology proposals are persisted before any graph mutation.",
            "Graph mutation is applied only by the controlled promotion endpoint.",
            "Raw CSV content, payloads and credential material are never stored.",
            "Promotion to ontology graph requires approval, workflow evidence and audit writes.",
        ],
    )


def record_demo_connector_ontology_proposals(
    repository: AxisPersistenceRepository,
    request: ConnectorOntologyProposalCreateRequest,
) -> ManufacturingConnectorOntologyProposalRegistry:
    _validate_write_mode(request.write_mode)
    for entity in request.proposed_entities:
        _validate_redacted_summary(entity.field_summary)
    manifest = _active_preview_manifest_for_connector(
        repository,
        request.tenant_id,
        request.connector_id,
    )

    proposal_ids = [entity.proposal_id for entity in request.proposed_entities]
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.proposed_by,
            event_type=AUDIT_EVENT_TYPE,
            payload={
                "connector_id": request.connector_id,
                "proposal_ids": proposal_ids,
                "proposal_count": len(proposal_ids),
                "source_run_id": request.source_run_id,
                "source_file_name": request.source_file_name,
                "mapping_profile": request.mapping_profile,
                "write_mode": request.write_mode,
                "graph_mutation_status": "not_applied",
                "runtime_boundary": manifest.runtime_boundary,
            },
        )
    )

    for entity in request.proposed_entities:
        repository.create_connector_ontology_proposal(
            ConnectorOntologyProposalCreate(
                tenant_id=request.tenant_id,
                connector_id=request.connector_id,
                proposal_id=entity.proposal_id,
                source_run_id=request.source_run_id,
                source_file_name=request.source_file_name,
                mapping_profile=request.mapping_profile,
                status="proposed_from_preview",
                write_mode=request.write_mode,
                graph_mutation_status="not_applied",
                proposed_by=request.proposed_by,
                node_id=entity.node_id,
                node_type=entity.node_type,
                ontology_type=entity.ontology_type,
                field_summary=entity.field_summary,
                evidence_refs=entity.evidence_refs,
                audit_event_id=audit_event.id,
                audit_event_type=AUDIT_EVENT_TYPE,
                notes=request.notes,
            )
        )

    return build_connector_ontology_proposal_registry(
        repository,
        ConnectorOntologyProposalQuery(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
        ),
    )


def _proposal_from_record(record) -> ConnectorOntologyProposalRecord:
    return ConnectorOntologyProposalRecord(
        tenant_id=record.tenant_id,
        connector_id=record.connector_id,
        proposal_id=record.proposal_id,
        source_run_id=record.source_run_id,
        source_file_name=record.source_file_name,
        mapping_profile=record.mapping_profile,
        status=record.status,
        write_mode=record.write_mode,
        graph_mutation_status=record.graph_mutation_status,
        proposed_by=record.proposed_by,
        node_id=record.node_id,
        node_type=record.node_type,
        ontology_type=record.ontology_type,
        field_summary=record.field_summary,
        evidence_refs=record.evidence_refs,
        promotion_id=record.promotion_id,
        policy_id=record.policy_id,
        policy_decision=record.policy_decision,
        promoted_by=record.promoted_by,
        promoted_at=record.promoted_at,
        ontology_mutation=record.ontology_mutation,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        notes=record.notes,
        created_at=record.created_at,
    )


def _manifest_for_connector(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str,
):
    registry = require_persisted_manufacturing_connector_registry(
        repository, tenant_id=tenant_id
    )
    for connector in registry.connectors:
        if connector.manifest.connector_id == connector_id:
            return connector.manifest
    raise ConnectorOntologyProposalValidationError(
        f"Unsupported connector_id: {connector_id}",
        "unsupported_connector_id",
    )


def _active_preview_manifest_for_connector(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str,
):
    _manifest_for_connector(repository, tenant_id, connector_id)
    manifest = repository.get_connector_manifest(tenant_id, connector_id)
    if manifest is None:
        raise ConnectorOntologyProposalValidationError(
            "Connector manifest must be registered before ontology proposal creation.",
            "connector_manifest_not_found",
        )
    if manifest.status != "active_preview":
        raise ConnectorOntologyProposalValidationError(
            "Connector manifest must be active_preview before ontology proposal creation.",
            "connector_manifest_not_active_preview",
        )
    return manifest


def _validate_write_mode(write_mode: str) -> None:
    if write_mode in ALLOWED_WRITE_MODES:
        return
    raise ConnectorOntologyProposalValidationError(
        "Connector ontology proposals can only be recorded as proposal_only.",
        "unsupported_write_mode",
    )


def _validate_redacted_summary(summary: dict[str, str]) -> None:
    for key in summary:
        if key.lower() in RAW_PAYLOAD_FIELD_NAMES:
            raise ConnectorOntologyProposalValidationError(
                "Connector ontology proposals cannot include raw payload or credential fields.",
                "raw_payload_field",
            )
