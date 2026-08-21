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
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorPromotionPolicyCreate,
    ConnectorPromotionPolicyEnableRecord,
)


class ConnectorPromotionPolicyValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorPromotionPolicyPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ConnectorPromotionPolicyConflict(ValueError):
    def __init__(self, policy_id: str) -> None:
        super().__init__("Connector promotion policy already exists")
        self.policy_id = policy_id


class ConnectorPromotionPolicyNotFound(LookupError):
    pass


class ConnectorPromotionPolicyQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorPromotionPolicyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    policy_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    policy_version: str = Field(min_length=1, max_length=80)
    status: str = Field(default="draft", min_length=1, max_length=80)
    enforcement_mode: str = Field(default="advisory", min_length=1, max_length=80)
    created_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=lambda: [REQUIRED_PROMOTION_SCOPE])
    required_manual_import_status: str = Field(default="approval_approved", min_length=1)
    required_workflow_signal_status: str = Field(
        default="manual_import_signal_requested",
        min_length=1,
    )
    allowed_risk_levels: list[str] = Field(default_factory=lambda: ["high", "medium"])
    allowed_ontology_types: list[str] = Field(default_factory=lambda: ["manufacturing_asset"])
    review_window_hours: int = Field(default=24, ge=1, le=24 * 30)
    notes: list[str] = Field(default_factory=list)


class ConnectorPromotionPolicyEnableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    policy_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    enabled_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    approval_id: str = Field(min_length=1, max_length=180)
    approval_decision: str = Field(min_length=1, max_length=80)
    workflow_signal_status: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=600)


class ConnectorPromotionPolicyReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    policy_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    policy_version: str = Field(min_length=1, max_length=80)
    status: str = Field(default="draft", min_length=1, max_length=80)
    enforcement_mode: str = Field(default="advisory", min_length=1, max_length=80)
    updated_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=200)
    revises_policy_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    revision_approval_id: str = Field(min_length=1, max_length=180)
    revision_decision: str = Field(min_length=1, max_length=40)
    revision_workflow_signal_status: str = Field(min_length=1, max_length=120)
    required_scopes: list[str] = Field(default_factory=lambda: [REQUIRED_PROMOTION_SCOPE])
    required_manual_import_status: str = Field(default="approval_approved", min_length=1)
    required_workflow_signal_status: str = Field(
        default="manual_import_signal_requested",
        min_length=1,
    )
    allowed_risk_levels: list[str] = Field(default_factory=lambda: ["high", "medium"])
    allowed_ontology_types: list[str] = Field(default_factory=lambda: ["manufacturing_asset"])
    review_window_hours: int = Field(default=24, ge=1, le=24 * 30)
    notes: list[str] = Field(default_factory=list)


class ConnectorPromotionPolicyRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    status: str = Field(min_length=1)
    enforcement_mode: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    required_authoring_scope: str = Field(min_length=1)
    required_scopes: list[str] = Field(min_length=1)
    required_manual_import_status: str = Field(min_length=1)
    required_workflow_signal_status: str = Field(min_length=1)
    allowed_risk_levels: list[str] = Field(min_length=1)
    allowed_ontology_types: list[str] = Field(min_length=1)
    review_window_hours: int = Field(ge=1)
    permission_decision: PermissionDecision
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    revises_policy_id: str | None = None
    replaced_by_policy_id: str | None = None
    revision_idempotency_key: str | None = None
    revision_approval_id: str | None = None
    revision_decision: str | None = None
    revision_workflow_signal_status: str | None = None
    idempotent_replay: bool = False
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ManufacturingConnectorPromotionPolicyRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    policies: list[ConnectorPromotionPolicyRecord] = Field(default_factory=list)
    policy_notes: list[str] = Field(default_factory=list)


REQUIRED_AUTHORING_SCOPE = "connectors:promotion_policy:author"
REQUIRED_ENABLE_SCOPE = "connectors:promotion_policy:enable"
REQUIRED_REVISE_SCOPE = "connectors:promotion_policy:revise"
REQUIRED_PROMOTION_SCOPE = "connectors:ontology:promote"
AUDIT_EVENT_TYPE = "connector.promotion_policy.authored"
ENABLE_AUDIT_EVENT_TYPE = "connector.promotion_policy.enabled"
REVISED_AUDIT_EVENT_TYPE = "connector.promotion_policy.revised"
SUPPORTED_POLICY_STATUSES = {"draft", "enabled", "superseded"}
SUPPORTED_ENFORCEMENT_MODES = {"advisory", "required"}
SUPPORTED_ENABLE_WORKFLOW_SIGNAL_STATUS = "policy_enable_signal_recorded"
SUPPORTED_REVISION_WORKFLOW_SIGNAL_STATUS = "policy_revision_signal_recorded"


def build_connector_promotion_policy_registry(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> ManufacturingConnectorPromotionPolicyRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, tenant_id)
    records = repository.list_connector_promotion_policies(
        tenant_id=tenant_id,
        connector_id=connector_id,
        status=status,
        limit=limit,
    )
    policies = [_policy_from_record(record) for record in records]
    draft_count = sum(1 for policy in policies if policy.status == "draft")
    required_count = sum(
        1
        for policy in policies
        if policy.status == "enabled" and policy.enforcement_mode == "required"
    )
    return ManufacturingConnectorPromotionPolicyRegistry(
        tenant_id=tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.READY if policies else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Promotion Policies",
                value=str(len(policies)),
                detail="Connector promotion policies",
                status=OverviewStatus.READY if policies else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Draft Policies",
                value=str(draft_count),
                detail="Policies authored but not yet enforced",
                status=OverviewStatus.WATCH if draft_count else OverviewStatus.READY,
            ),
            OverviewMetric(
                label="Required Gates",
                value=str(required_count),
                detail="Enabled policies marked required for promotion",
                status=OverviewStatus.READY if required_count else OverviewStatus.WATCH,
            ),
        ],
        policies=policies,
        policy_notes=[
            "Promotion policies are authored as governance metadata before required enforcement.",
            "Policies declare the scopes, import status and workflow signal "
            "required for promotion.",
            "Policy authoring never executes connector sync or TypeDB mutations.",
            "Draft revisions are append-only and idempotent; enabled policies stay immutable.",
        ],
    )


def record_demo_connector_promotion_policy(
    repository: AxisPersistenceRepository,
    request: ConnectorPromotionPolicyCreateRequest,
) -> ConnectorPromotionPolicyRecord:
    _manifest_for_connector(repository, request.tenant_id, request.connector_id)
    _validate_policy_status(request.status)
    _validate_enforcement_mode(request.enforcement_mode)
    _validate_required_scopes(request.required_scopes)
    existing = repository.get_connector_promotion_policy(
        request.tenant_id,
        request.policy_id,
    )
    if existing is not None:
        raise ConnectorPromotionPolicyConflict(existing.policy_id)

    permission_decision = _evaluate_authoring_permission(request)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.created_by,
            event_type=AUDIT_EVENT_TYPE,
            payload={
                "connector_id": request.connector_id,
                "policy_id": request.policy_id,
                "policy_version": request.policy_version,
                "status": request.status,
                "enforcement_mode": request.enforcement_mode,
                "required_authoring_scope": REQUIRED_AUTHORING_SCOPE,
                "required_scopes": request.required_scopes,
                "required_manual_import_status": request.required_manual_import_status,
                "required_workflow_signal_status": request.required_workflow_signal_status,
                "allowed_risk_levels": request.allowed_risk_levels,
                "allowed_ontology_types": request.allowed_ontology_types,
                "review_window_hours": request.review_window_hours,
                "permission_decision": permission_decision.model_dump(),
            },
        )
    )
    policy = repository.create_connector_promotion_policy(
        ConnectorPromotionPolicyCreate(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            policy_id=request.policy_id,
            policy_version=request.policy_version,
            status=request.status,
            enforcement_mode=request.enforcement_mode,
            created_by=request.created_by,
            required_authoring_scope=REQUIRED_AUTHORING_SCOPE,
            required_scopes=request.required_scopes,
            required_manual_import_status=request.required_manual_import_status,
            required_workflow_signal_status=request.required_workflow_signal_status,
            allowed_risk_levels=request.allowed_risk_levels,
            allowed_ontology_types=request.allowed_ontology_types,
            review_window_hours=request.review_window_hours,
            permission_decision=permission_decision.model_dump(),
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            notes=request.notes,
        )
    )
    return _policy_from_record(policy)


def enable_demo_connector_promotion_policy(
    repository: AxisPersistenceRepository,
    request: ConnectorPromotionPolicyEnableRequest,
) -> ConnectorPromotionPolicyRecord:
    policy = repository.get_connector_promotion_policy(request.tenant_id, request.policy_id)
    if policy is None:
        raise ConnectorPromotionPolicyNotFound()
    _manifest_for_connector(repository, request.tenant_id, policy.connector_id)
    _validate_enable_request(request)
    permission_decision = _evaluate_enable_permission(request, policy.connector_id)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.enabled_by,
            event_type=ENABLE_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": policy.connector_id,
                "policy_id": policy.policy_id,
                "policy_version": policy.policy_version,
                "previous_status": policy.status,
                "previous_enforcement_mode": policy.enforcement_mode,
                "status": "enabled",
                "enforcement_mode": "required",
                "approval_id": request.approval_id,
                "approval_decision": request.approval_decision,
                "workflow_signal_status": request.workflow_signal_status,
                "required_enable_scope": REQUIRED_ENABLE_SCOPE,
                "permission_decision": permission_decision.model_dump(),
                "note_recorded": str(request.note is not None).lower(),
            },
        )
    )
    enabled_policy = repository.enable_connector_promotion_policy(
        ConnectorPromotionPolicyEnableRecord(
            tenant_id=request.tenant_id,
            policy_id=request.policy_id,
            status="enabled",
            enforcement_mode="required",
            permission_decision=permission_decision.model_dump(),
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            note=request.note,
        )
    )
    return _policy_from_record(enabled_policy)


def revise_demo_connector_promotion_policy(
    repository: AxisPersistenceRepository,
    request: ConnectorPromotionPolicyReviseRequest,
) -> ConnectorPromotionPolicyRecord:
    _manifest_for_connector(repository, request.tenant_id, request.connector_id)
    _validate_policy_revision_request(request)
    existing_replay = repository.get_connector_promotion_policy_by_revision_idempotency_key(
        request.tenant_id,
        request.idempotency_key,
    )
    if existing_replay is not None:
        return _policy_from_record(existing_replay, idempotent_replay=True)

    existing_policy = repository.get_connector_promotion_policy(
        request.tenant_id,
        request.policy_id,
    )
    if existing_policy is not None:
        raise ConnectorPromotionPolicyConflict(existing_policy.policy_id)

    target_policy = repository.get_connector_promotion_policy(
        request.tenant_id,
        request.revises_policy_id,
    )
    if target_policy is None:
        raise ConnectorPromotionPolicyNotFound()
    if target_policy.connector_id != request.connector_id:
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policy revision target belongs to another connector.",
            "policy_revision_connector_mismatch",
        )
    if target_policy.status != "draft":
        raise ConnectorPromotionPolicyValidationError(
            "Only draft connector promotion policies can be revised append-only.",
            "policy_revision_target_not_draft",
        )
    if target_policy.replaced_by_policy_id is not None:
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policy revision target is already superseded.",
            "policy_revision_target_already_revised",
        )

    permission_decision = _evaluate_revision_permission(request)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.updated_by,
            event_type=REVISED_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": request.connector_id,
                "previous_policy_id": target_policy.policy_id,
                "previous_policy_version": target_policy.policy_version,
                "policy_id": request.policy_id,
                "policy_version": request.policy_version,
                "status": request.status,
                "enforcement_mode": request.enforcement_mode,
                "revision_approval_id": request.revision_approval_id,
                "revision_decision": request.revision_decision,
                "revision_workflow_signal_status": request.revision_workflow_signal_status,
                "idempotency_key": request.idempotency_key,
                "required_revision_scope": REQUIRED_REVISE_SCOPE,
                "required_scopes": request.required_scopes,
                "required_manual_import_status": request.required_manual_import_status,
                "required_workflow_signal_status": request.required_workflow_signal_status,
                "allowed_risk_levels": request.allowed_risk_levels,
                "allowed_ontology_types": request.allowed_ontology_types,
                "review_window_hours": request.review_window_hours,
                "permission_decision": permission_decision.model_dump(),
            },
        )
    )
    revised_policy = repository.revise_connector_promotion_policy(
        target_policy,
        ConnectorPromotionPolicyCreate(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            policy_id=request.policy_id,
            policy_version=request.policy_version,
            status=request.status,
            enforcement_mode=request.enforcement_mode,
            created_by=request.updated_by,
            required_authoring_scope=REQUIRED_REVISE_SCOPE,
            required_scopes=request.required_scopes,
            required_manual_import_status=request.required_manual_import_status,
            required_workflow_signal_status=request.required_workflow_signal_status,
            allowed_risk_levels=request.allowed_risk_levels,
            allowed_ontology_types=request.allowed_ontology_types,
            review_window_hours=request.review_window_hours,
            permission_decision=permission_decision.model_dump(),
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            revises_policy_id=request.revises_policy_id,
            revision_idempotency_key=request.idempotency_key,
            revision_approval_id=request.revision_approval_id,
            revision_decision=request.revision_decision,
            revision_workflow_signal_status=request.revision_workflow_signal_status,
            notes=request.notes,
        ),
    )
    return _policy_from_record(revised_policy)


def _evaluate_authoring_permission(
    request: ConnectorPromotionPolicyCreateRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.created_by,
            actor_scopes=request.actor_scopes,
            required_scopes=[REQUIRED_AUTHORING_SCOPE],
            attributes={
                "connector_id": request.connector_id,
                "policy_id": request.policy_id,
                "enforcement_mode": request.enforcement_mode,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorPromotionPolicyPermissionDenied(REQUIRED_AUTHORING_SCOPE, decision)
    return decision


def _evaluate_enable_permission(
    request: ConnectorPromotionPolicyEnableRequest,
    connector_id: str,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.enabled_by,
            actor_scopes=request.actor_scopes,
            required_scopes=[REQUIRED_ENABLE_SCOPE],
            attributes={
                "connector_id": connector_id,
                "policy_id": request.policy_id,
                "approval_id": request.approval_id,
                "workflow_signal_status": request.workflow_signal_status,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorPromotionPolicyPermissionDenied(REQUIRED_ENABLE_SCOPE, decision)
    return decision


def _evaluate_revision_permission(
    request: ConnectorPromotionPolicyReviseRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.updated_by,
            actor_scopes=request.actor_scopes,
            required_scopes=[REQUIRED_REVISE_SCOPE],
            attributes={
                "connector_id": request.connector_id,
                "policy_id": request.policy_id,
                "revises_policy_id": request.revises_policy_id,
                "idempotency_key": request.idempotency_key,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorPromotionPolicyPermissionDenied(REQUIRED_REVISE_SCOPE, decision)
    return decision


def _validate_enable_request(request: ConnectorPromotionPolicyEnableRequest) -> None:
    if request.approval_decision != "approve":
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policy enablement requires an approved decision.",
            "policy_enable_not_approved",
        )
    if request.workflow_signal_status != SUPPORTED_ENABLE_WORKFLOW_SIGNAL_STATUS:
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policy enablement requires workflow signal evidence.",
            "policy_enable_signal_missing",
        )


def _validate_policy_revision_request(request: ConnectorPromotionPolicyReviseRequest) -> None:
    if request.status != "draft":
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policy revisions must create draft policies.",
            "policy_revision_status_not_draft",
        )
    if request.enforcement_mode != "advisory":
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policy revisions must remain advisory until enablement.",
            "policy_revision_enforcement_not_advisory",
        )
    if request.revision_decision != "approve":
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policy revision requires an approved decision.",
            "policy_revision_not_approved",
        )
    if request.revision_workflow_signal_status != SUPPORTED_REVISION_WORKFLOW_SIGNAL_STATUS:
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policy revision requires workflow signal evidence.",
            "policy_revision_signal_missing",
        )
    _validate_required_scopes(request.required_scopes)


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
    raise ConnectorPromotionPolicyValidationError(
        f"Unsupported connector_id: {connector_id}",
        "unsupported_connector_id",
    )


def _validate_policy_status(status: str) -> None:
    if status == "draft":
        return
    if status == "enabled":
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policies must be enabled through the approval workflow.",
            "policy_enable_requires_workflow",
        )
    if status == "superseded":
        raise ConnectorPromotionPolicyValidationError(
            "Connector promotion policies must be superseded through the revision workflow.",
            "policy_supersede_requires_revision",
        )
    raise ConnectorPromotionPolicyValidationError(
        "Connector promotion policy status must be draft or enabled.",
        "unsupported_policy_status",
    )


def _validate_enforcement_mode(enforcement_mode: str) -> None:
    if enforcement_mode in SUPPORTED_ENFORCEMENT_MODES:
        return
    raise ConnectorPromotionPolicyValidationError(
        "Connector promotion policy enforcement mode must be advisory or required.",
        "unsupported_enforcement_mode",
    )


def _validate_required_scopes(required_scopes: list[str]) -> None:
    if REQUIRED_PROMOTION_SCOPE in required_scopes:
        return
    raise ConnectorPromotionPolicyValidationError(
        "Connector promotion policies must require the ontology promotion scope.",
        "missing_promotion_scope",
    )


def _policy_from_record(record, idempotent_replay: bool = False) -> ConnectorPromotionPolicyRecord:
    return ConnectorPromotionPolicyRecord(
        tenant_id=record.tenant_id,
        connector_id=record.connector_id,
        policy_id=record.policy_id,
        policy_version=record.policy_version,
        status=record.status,
        enforcement_mode=record.enforcement_mode,
        created_by=record.created_by,
        required_authoring_scope=record.required_authoring_scope,
        required_scopes=record.required_scopes,
        required_manual_import_status=record.required_manual_import_status,
        required_workflow_signal_status=record.required_workflow_signal_status,
        allowed_risk_levels=record.allowed_risk_levels,
        allowed_ontology_types=record.allowed_ontology_types,
        review_window_hours=record.review_window_hours,
        permission_decision=PermissionDecision.model_validate(record.permission_decision),
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        revises_policy_id=record.revises_policy_id,
        replaced_by_policy_id=record.replaced_by_policy_id,
        revision_idempotency_key=record.revision_idempotency_key,
        revision_approval_id=record.revision_approval_id,
        revision_decision=record.revision_decision,
        revision_workflow_signal_status=record.revision_workflow_signal_status,
        idempotent_replay=idempotent_replay,
        notes=record.notes,
        created_at=record.created_at,
    )
