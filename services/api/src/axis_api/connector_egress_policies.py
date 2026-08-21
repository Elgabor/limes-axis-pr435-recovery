import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from axis_api.audit import AuditEventCreate
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    find_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.persistence import AxisPersistenceRepository, ConnectorEgressPolicyCreate

READ_AUDIT_EVENT_TYPE = "connector.egress_policies_read"


class ConnectorEgressPolicyValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorEgressPolicyQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorEgressPolicyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="external_db_operational_mirror", min_length=1)
    policy_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=200)
    connection_profile_id: str = Field(min_length=1, max_length=180)
    egress_boundary: str = Field(min_length=1, max_length=120)
    policy_mode: str = Field(min_length=1, max_length=120)
    runtime_boundary: str = Field(default="axis-egress-policy-enforcer", min_length=1)
    private_endpoint_ref: str = Field(min_length=1, max_length=500)
    created_by: str = Field(min_length=1, max_length=160)
    policy_document: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ConnectorEgressPolicyRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    status: str = Field(min_length=1)
    connection_profile_id: str = Field(min_length=1)
    egress_boundary: str = Field(min_length=1)
    policy_mode: str = Field(min_length=1)
    runtime_boundary: str = Field(min_length=1)
    private_endpoint_ref: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    policy_document: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ConnectorEgressPolicyEvidenceInvariant(BaseModel):
    policy_id: str = Field(min_length=1)
    audit_event_id: str | None = None
    reason: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ManufacturingConnectorEgressPolicyRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    policies: list[ConnectorEgressPolicyRecord] = Field(default_factory=list)
    policy_evidence_invariants: list[
        ConnectorEgressPolicyEvidenceInvariant
    ] = Field(default_factory=list)
    policy_notes: list[str] = Field(default_factory=list)


RAW_NETWORK_OR_SECRET_MARKERS = (
    "api_key=",
    "client_secret=",
    "credential_value",
    "jdbc:",
    "literal-password",
    "mongodb://",
    "mssql://",
    "mysql://",
    "password=",
    "postgres://",
    "postgresql://",
    "redis://",
    "secret_value",
    "server=",
    "token=",
)
ENDPOINT_TARGET_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def build_connector_egress_policy_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorEgressPolicyQuery,
) -> ManufacturingConnectorEgressPolicyRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_connector_egress_policies(
        tenant_id=query.tenant_id,
        connector_id=query.connector_id,
        status=query.status,
        limit=query.limit,
    )
    policies = [_egress_policy_from_record(record) for record in records]
    policy_evidence_invariants = [
        invariant
        for record in records
        if (invariant := _policy_evidence_invariant(repository, record)) is not None
    ]
    active_count = sum(1 for policy in policies if policy.status == "active")
    return ManufacturingConnectorEgressPolicyRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.READY if policies else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Egress Policies",
                value=str(len(policies)),
                detail="Tenant-scoped connector egress policies persisted",
                status=OverviewStatus.READY if policies else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Active",
                value=str(active_count),
                detail="Policies available for preflight evaluation",
                status=OverviewStatus.READY if active_count else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Policy Evidence Invariants",
                value=str(len(policy_evidence_invariants)),
                detail="Egress policy audit ledger binding issues in this result set",
                status=(
                    OverviewStatus.WATCH
                    if policy_evidence_invariants
                    else OverviewStatus.READY
                ),
            ),
            OverviewMetric(
                label="External Query",
                value="Not Started",
                detail="Policies validate egress before live query execution",
                status=OverviewStatus.READY,
            ),
        ],
        policies=policies,
        policy_evidence_invariants=policy_evidence_invariants,
        policy_notes=[
            "Egress policies are tenant-scoped persisted records.",
            "The external DB preflight reads these records before considering secret retrieval.",
            "A policy record stores private endpoint references, never raw DSNs or credentials.",
        ],
    )


def read_connector_egress_policy_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorEgressPolicyQuery,
    *,
    actor_id: str,
) -> ManufacturingConnectorEgressPolicyRegistry:
    registry = build_connector_egress_policy_registry(repository, query)
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=query.tenant_id,
            actor_id=actor_id,
            event_type=READ_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": query.connector_id,
                "status": query.status,
                "limit": query.limit,
                "returned_policy_count": len(registry.policies),
                "policy_evidence_invariant_count": len(
                    registry.policy_evidence_invariants
                ),
                "policy_ids": [policy.policy_id for policy in registry.policies],
            },
        )
    )
    return registry


def record_demo_connector_egress_policy(
    repository: AxisPersistenceRepository,
    request: ConnectorEgressPolicyCreateRequest,
) -> ConnectorEgressPolicyRecord:
    _validate_egress_policy_request(request)
    existing = repository.get_connector_egress_policy(request.tenant_id, request.policy_id)
    if existing is not None:
        raise ConnectorEgressPolicyValidationError(
            "Connector egress policy already exists.",
            "egress_policy_already_exists",
        )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.created_by,
            event_type="connector.egress_policy.registered",
            payload={
                "connector_id": request.connector_id,
                "policy_id": request.policy_id,
                "connection_profile_id": request.connection_profile_id,
                "egress_boundary": request.egress_boundary,
                "policy_mode": request.policy_mode,
                "runtime_boundary": request.runtime_boundary,
                "private_endpoint_ref": request.private_endpoint_ref,
            },
        )
    )
    record = repository.create_connector_egress_policy(
        ConnectorEgressPolicyCreate(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            policy_id=request.policy_id,
            display_name=request.display_name,
            status="active",
            connection_profile_id=request.connection_profile_id,
            egress_boundary=request.egress_boundary,
            policy_mode=request.policy_mode,
            runtime_boundary=request.runtime_boundary,
            private_endpoint_ref=request.private_endpoint_ref,
            created_by=request.created_by,
            policy_document=request.policy_document,
            evidence_refs=[str(audit_event.id)],
            audit_event_id=audit_event.id,
            notes=request.notes,
        )
    )
    return _egress_policy_from_record(record)


def _validate_egress_policy_request(request: ConnectorEgressPolicyCreateRequest) -> None:
    serialized = request.model_dump_json().lower()
    if any(marker in serialized for marker in RAW_NETWORK_OR_SECRET_MARKERS):
        raise ConnectorEgressPolicyValidationError(
            "Connector egress policy must not contain raw DSNs or credential material.",
            "raw_network_or_secret_material",
        )
    endpoint_target_sha256 = str(
        request.policy_document.get("approved_endpoint_target_sha256", "")
    )
    if endpoint_target_sha256 and not ENDPOINT_TARGET_SHA256_PATTERN.fullmatch(
        endpoint_target_sha256
    ):
        raise ConnectorEgressPolicyValidationError(
            "Connector egress policy endpoint binding must be a SHA-256 hex digest.",
            "invalid_endpoint_target_sha256",
        )
    if request.egress_boundary != "approved_private_endpoint":
        raise ConnectorEgressPolicyValidationError(
            "Connector egress policy must use an approved private endpoint boundary.",
            "unsupported_egress_boundary",
        )
    if request.policy_mode != "approved_private_endpoint":
        raise ConnectorEgressPolicyValidationError(
            "Connector egress policy mode must be approved_private_endpoint.",
            "unsupported_policy_mode",
        )


def _egress_policy_from_record(record) -> ConnectorEgressPolicyRecord:
    return ConnectorEgressPolicyRecord(
        tenant_id=record.tenant_id,
        connector_id=record.connector_id,
        policy_id=record.policy_id,
        display_name=record.display_name,
        status=record.status,
        connection_profile_id=record.connection_profile_id,
        egress_boundary=record.egress_boundary,
        policy_mode=record.policy_mode,
        runtime_boundary=record.runtime_boundary,
        private_endpoint_ref=record.private_endpoint_ref,
        created_by=record.created_by,
        policy_document=record.policy_document,
        evidence_refs=record.evidence_refs,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        notes=record.notes,
        created_at=record.created_at,
    )


def _policy_evidence_invariant(
    repository: AxisPersistenceRepository,
    record,
) -> ConnectorEgressPolicyEvidenceInvariant | None:
    audit_event_id = str(record.audit_event_id) if record.audit_event_id else None
    if record.audit_event_id is None:
        return ConnectorEgressPolicyEvidenceInvariant(
            policy_id=record.policy_id,
            audit_event_id=None,
            reason="egress_policy_audit_event_missing",
            detail="Egress policy must reference an append-only audit event.",
        )
    if str(record.audit_event_id) not in (record.evidence_refs or []):
        return ConnectorEgressPolicyEvidenceInvariant(
            policy_id=record.policy_id,
            audit_event_id=audit_event_id,
            reason="egress_policy_audit_event_ref_missing",
            detail="Egress policy evidence_refs must include its audit event id.",
        )
    audit_event = repository.get_audit_event(record.tenant_id, record.audit_event_id)
    if audit_event is None:
        return ConnectorEgressPolicyEvidenceInvariant(
            policy_id=record.policy_id,
            audit_event_id=audit_event_id,
            reason="egress_policy_audit_event_not_found",
            detail="Egress policy audit event id must resolve in the tenant ledger.",
        )
    if audit_event.event_type != record.audit_event_type:
        return ConnectorEgressPolicyEvidenceInvariant(
            policy_id=record.policy_id,
            audit_event_id=audit_event_id,
            reason="egress_policy_audit_event_type_mismatch",
            detail="Egress policy audit event type must match the policy record.",
        )
    if (
        audit_event.payload.get("connector_id") != record.connector_id
        or audit_event.payload.get("policy_id") != record.policy_id
        or audit_event.payload.get("connection_profile_id")
        != record.connection_profile_id
    ):
        return ConnectorEgressPolicyEvidenceInvariant(
            policy_id=record.policy_id,
            audit_event_id=audit_event_id,
            reason="egress_policy_audit_event_payload_mismatch",
            detail=(
                "Egress policy audit event payload must match connector_id, "
                "policy_id and connection_profile_id."
            ),
        )
    if not _policy_evidence_payload_is_public_safe(audit_event.payload):
        return ConnectorEgressPolicyEvidenceInvariant(
            policy_id=record.policy_id,
            audit_event_id=audit_event_id,
            reason="egress_policy_audit_payload_unsafe",
            detail=(
                "Egress policy audit event payload must not report external "
                "query or credential material access."
            ),
        )
    return None


def _policy_evidence_payload_is_public_safe(payload: dict) -> bool:
    if str(payload.get("external_query_started", "false")).lower() != "false":
        return False
    return str(payload.get("credential_material_returned", "false")).lower() == "false"
