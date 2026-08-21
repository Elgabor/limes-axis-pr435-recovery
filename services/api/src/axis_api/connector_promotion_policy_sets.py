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
from axis_api.persistence import AxisPersistenceRepository, ConnectorPromotionPolicySetCreate


class ConnectorPromotionPolicySetValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorPromotionPolicySetPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ConnectorPromotionPolicySetConflict(ValueError):
    def __init__(self, policy_set_id: str, reason: str) -> None:
        super().__init__("Connector promotion policy set already exists or conflicts")
        self.policy_set_id = policy_set_id
        self.reason = reason


class ConnectorPromotionPolicySetQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorPromotionPolicyRevisionAdoption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_policy_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    revised_policy_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    revision_idempotency_key: str = Field(min_length=1, max_length=200)
    adoption_approval_id: str | None = Field(default=None, min_length=1, max_length=180)
    adoption_decision: str | None = Field(default=None, min_length=1, max_length=40)
    adoption_workflow_signal_status: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )


class ConnectorPromotionPolicyRevisionAdoptionRecord(
    ConnectorPromotionPolicyRevisionAdoption
):
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None


class ConnectorPromotionPolicySetActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    policy_set_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    policy_set_version: str = Field(min_length=1, max_length=80)
    status: str = Field(default="active", min_length=1, max_length=80)
    activated_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(min_length=1, max_length=20)
    activation_reason: str = Field(min_length=1, max_length=600)
    replaces_policy_set_id: str | None = Field(default=None, min_length=1, max_length=180)
    replacement_approval_id: str | None = Field(default=None, min_length=1, max_length=180)
    replacement_decision: str | None = Field(default=None, min_length=1, max_length=40)
    replacement_workflow_signal_status: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )
    rollback_to_policy_set_id: str | None = Field(default=None, min_length=1, max_length=180)
    rollback_approval_id: str | None = Field(default=None, min_length=1, max_length=180)
    rollback_decision: str | None = Field(default=None, min_length=1, max_length=40)
    rollback_workflow_signal_status: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )
    policy_revision_adoptions: list[ConnectorPromotionPolicyRevisionAdoption] = Field(
        default_factory=list,
        max_length=20,
    )
    notes: list[str] = Field(default_factory=list)


class ConnectorPromotionPolicySetRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    policy_set_id: str = Field(min_length=1)
    policy_set_version: str = Field(min_length=1)
    status: str = Field(min_length=1)
    activated_by: str = Field(min_length=1)
    activation_scope: str = Field(min_length=1)
    policy_ids: list[str] = Field(min_length=1)
    permission_decision: PermissionDecision
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    activation_reason: str = Field(min_length=1)
    replaces_policy_set_id: str | None = None
    replaced_by_policy_set_id: str | None = None
    replacement_approval_id: str | None = None
    replacement_decision: str | None = None
    replacement_workflow_signal_status: str | None = None
    replaced_at: datetime | None = None
    rollback_to_policy_set_id: str | None = None
    rollback_approval_id: str | None = None
    rollback_decision: str | None = None
    rollback_workflow_signal_status: str | None = None
    policy_revision_adoptions: list[ConnectorPromotionPolicyRevisionAdoptionRecord] = (
        Field(default_factory=list)
    )
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ManufacturingConnectorPromotionPolicySetRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    policy_sets: list[ConnectorPromotionPolicySetRecord] = Field(default_factory=list)
    policy_set_notes: list[str] = Field(default_factory=list)


REQUIRED_POLICY_SET_ACTIVATION_SCOPE = "connectors:promotion_policy_set:activate"
POLICY_SET_AUDIT_EVENT_TYPE = "connector.promotion_policy_set.activated"
POLICY_SET_REPLACED_AUDIT_EVENT_TYPE = "connector.promotion_policy_set.replaced"
POLICY_SET_ROLLED_BACK_AUDIT_EVENT_TYPE = "connector.promotion_policy_set.rolled_back"
POLICY_REVISION_ADOPTED_AUDIT_EVENT_TYPE = "connector.promotion_policy.revision_adopted"
REQUIRED_POLICY_SET_REPLACEMENT_SIGNAL = "policy_set_replacement_signal_recorded"
REQUIRED_POLICY_SET_ROLLBACK_SIGNAL = "policy_set_rollback_signal_recorded"
REQUIRED_POLICY_REVISION_SIGNAL = "policy_revision_signal_recorded"
REQUIRED_POLICY_REVISION_ADOPTION_SIGNAL = "policy_revision_adoption_signal_recorded"
SUPPORTED_POLICY_SET_STATUSES = {"active"}


def build_connector_promotion_policy_set_registry(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> ManufacturingConnectorPromotionPolicySetRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, tenant_id)
    records = repository.list_connector_promotion_policy_sets(
        tenant_id=tenant_id,
        connector_id=connector_id,
        status=status,
        limit=limit,
    )
    policy_sets = [_policy_set_from_record(record) for record in records]
    active_count = sum(1 for policy_set in policy_sets if policy_set.status == "active")
    policy_count = sum(len(policy_set.policy_ids) for policy_set in policy_sets)
    return ManufacturingConnectorPromotionPolicySetRegistry(
        tenant_id=tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.READY if policy_sets else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Policy Sets",
                value=str(len(policy_sets)),
                detail="Versioned connector promotion policy sets",
                status=OverviewStatus.READY if policy_sets else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Active Sets",
                value=str(active_count),
                detail="Policy sets selected for automatic required gates",
                status=OverviewStatus.READY if active_count else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Set Policies",
                value=str(policy_count),
                detail="Required policy references inside versioned sets",
                status=OverviewStatus.READY if policy_count else OverviewStatus.WATCH,
            ),
        ],
        policy_sets=policy_sets,
        policy_set_notes=[
            "Policy sets resolve multi-policy required gates without implicit selection.",
            "Activation requires each referenced policy to be enabled and required.",
            "Active set replacement and rollback require approval and workflow signal evidence.",
        ],
    )


def record_demo_connector_promotion_policy_set(
    repository: AxisPersistenceRepository,
    request: ConnectorPromotionPolicySetActivateRequest,
) -> ConnectorPromotionPolicySetRecord:
    _manifest_for_connector(repository, request.tenant_id, request.connector_id)
    _validate_policy_set_status(request.status)
    _validate_policy_ids_unique(request.policy_ids)
    existing = repository.get_connector_promotion_policy_set(
        request.tenant_id,
        request.policy_set_id,
    )
    if existing is not None:
        raise ConnectorPromotionPolicySetConflict(
            existing.policy_set_id,
            "policy_set_already_exists",
        )
    active_sets = repository.list_active_connector_promotion_policy_sets(
        request.tenant_id,
        request.connector_id,
    )
    rollback_requested = _rollback_requested(request)
    if rollback_requested and request.rollback_to_policy_set_id is None:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set rollback requires a target policy set.",
            "policy_set_rollback_target_required",
        )
    if rollback_requested and request.replaces_policy_set_id is None:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set rollback requires the active set target.",
            "policy_set_rollback_active_target_required",
        )
    active_policy_set = _active_policy_set_for_replacement(active_sets, request)
    if active_sets and active_policy_set is None:
        raise ConnectorPromotionPolicySetConflict(
            active_sets[0].policy_set_id,
            "policy_set_active_exists",
        )
    if not active_sets and request.replaces_policy_set_id is not None:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set replacement target is not active.",
            "policy_set_replacement_target_not_found",
        )
    rollback_target = None
    if rollback_requested:
        if active_policy_set is None:
            raise ConnectorPromotionPolicySetValidationError(
                "Connector promotion policy set rollback target is not active.",
                "policy_set_rollback_active_target_not_found",
            )
        rollback_target = _rollback_policy_set_for_request(repository, request)
        _validate_rollback_evidence(request)
    elif active_policy_set is not None:
        _validate_replacement_evidence(request)
    permission_decision = _evaluate_activation_permission(request)
    policy_revision_adoptions = _apply_policy_revision_adoptions(
        repository,
        request,
        active_policy_set,
        rollback_target,
        permission_decision,
    )
    policies = _validate_referenced_policies(repository, request)
    if rollback_target is not None and rollback_target.policy_ids != request.policy_ids:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set rollback must restore the target policy ids.",
            "policy_set_rollback_policy_mismatch",
        )
    audit_event_type = _audit_event_type_for_request(active_policy_set, rollback_target)
    policy_revision_adoption_payload = [
        adoption.model_dump(mode="json") for adoption in policy_revision_adoptions
    ]
    audit_payload = {
        "connector_id": request.connector_id,
        "policy_set_id": request.policy_set_id,
        "policy_set_version": request.policy_set_version,
        "status": request.status,
        "policy_ids": request.policy_ids,
        "policy_versions": [policy.policy_version for policy in policies],
        "policy_revision_adoptions": policy_revision_adoption_payload,
        "activation_scope": REQUIRED_POLICY_SET_ACTIVATION_SCOPE,
        "permission_decision": permission_decision.model_dump(),
        "activation_reason": request.activation_reason,
    }
    if active_policy_set is not None:
        audit_payload.update(
            {
                "previous_policy_set_id": active_policy_set.policy_set_id,
                "previous_policy_set_version": active_policy_set.policy_set_version,
                "previous_status": active_policy_set.status,
            }
        )
    if rollback_target is not None:
        audit_payload.update(
            {
                "rollback_to_policy_set_id": rollback_target.policy_set_id,
                "rollback_to_policy_set_version": rollback_target.policy_set_version,
                "rollback_approval_id": request.rollback_approval_id,
                "rollback_decision": request.rollback_decision,
                "rollback_workflow_signal_status": request.rollback_workflow_signal_status,
            }
        )
    elif active_policy_set is not None:
        audit_payload.update(
            {
                "replacement_approval_id": request.replacement_approval_id,
                "replacement_decision": request.replacement_decision,
                "replacement_workflow_signal_status": request.replacement_workflow_signal_status,
            }
        )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.activated_by,
            event_type=audit_event_type,
            payload=audit_payload,
        )
    )
    create_record = ConnectorPromotionPolicySetCreate(
        tenant_id=request.tenant_id,
        connector_id=request.connector_id,
        policy_set_id=request.policy_set_id,
        policy_set_version=request.policy_set_version,
        status=request.status,
        activated_by=request.activated_by,
        activation_scope=REQUIRED_POLICY_SET_ACTIVATION_SCOPE,
        policy_ids=request.policy_ids,
        permission_decision=permission_decision.model_dump(),
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        activation_reason=request.activation_reason,
        replaces_policy_set_id=request.replaces_policy_set_id,
        replacement_approval_id=request.replacement_approval_id,
        replacement_decision=request.replacement_decision,
        replacement_workflow_signal_status=request.replacement_workflow_signal_status,
        rollback_to_policy_set_id=request.rollback_to_policy_set_id,
        rollback_approval_id=request.rollback_approval_id,
        rollback_decision=request.rollback_decision,
        rollback_workflow_signal_status=request.rollback_workflow_signal_status,
        policy_revision_adoptions=policy_revision_adoption_payload,
        notes=request.notes,
    )
    if active_policy_set is None:
        policy_set = repository.create_connector_promotion_policy_set(create_record)
    else:
        policy_set = repository.replace_connector_promotion_policy_set(
            active_policy_set,
            create_record,
        )
    return _policy_set_from_record(policy_set)


def _apply_policy_revision_adoptions(
    repository: AxisPersistenceRepository,
    request: ConnectorPromotionPolicySetActivateRequest,
    active_policy_set,
    rollback_target,
    permission_decision: PermissionDecision,
) -> list[ConnectorPromotionPolicyRevisionAdoptionRecord]:
    if not request.policy_revision_adoptions:
        return []
    if active_policy_set is None:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy revision adoption requires active-set replacement.",
            "policy_revision_adoption_requires_replacement",
        )
    if rollback_target is not None:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy revision adoption is not supported during rollback.",
            "policy_revision_adoption_not_supported_for_rollback",
        )

    _validate_policy_revision_adoption_uniqueness(request.policy_revision_adoptions)
    active_policy_ids = set(active_policy_set.policy_ids)
    requested_policy_ids = set(request.policy_ids)
    adoption_records: list[ConnectorPromotionPolicyRevisionAdoptionRecord] = []

    for adoption in request.policy_revision_adoptions:
        _validate_policy_revision_adoption_evidence(adoption)
        if adoption.current_policy_id == adoption.revised_policy_id:
            raise ConnectorPromotionPolicySetValidationError(
                "Connector promotion policy revision adoption cannot self-reference.",
                "policy_revision_adoption_self_reference",
            )
        if adoption.current_policy_id not in active_policy_ids:
            raise ConnectorPromotionPolicySetValidationError(
                "Connector promotion policy revision adoption must replace an active-set policy.",
                "policy_revision_adoption_current_policy_not_active",
            )
        if adoption.revised_policy_id not in requested_policy_ids:
            raise ConnectorPromotionPolicySetValidationError(
                "Policy revision adoption must include the revised policy in the set.",
                "policy_revision_adoption_revised_policy_not_requested",
            )

        current_policy = repository.get_connector_promotion_policy(
            request.tenant_id,
            adoption.current_policy_id,
        )
        if current_policy is None:
            raise ConnectorPromotionPolicySetValidationError(
                "Policy revision adoption references an unknown current policy.",
                "policy_revision_adoption_current_policy_not_found",
            )
        revised_policy = repository.get_connector_promotion_policy(
            request.tenant_id,
            adoption.revised_policy_id,
        )
        if revised_policy is None:
            raise ConnectorPromotionPolicySetValidationError(
                "Policy revision adoption references an unknown revised policy.",
                "policy_revision_adoption_revised_policy_not_found",
            )
        if (
            current_policy.connector_id != request.connector_id
            or revised_policy.connector_id != request.connector_id
        ):
            raise ConnectorPromotionPolicySetValidationError(
                "Connector promotion policy revision adoption cannot cross connector boundaries.",
                "policy_revision_adoption_connector_mismatch",
            )
        if current_policy.status != "enabled" or current_policy.enforcement_mode != "required":
            raise ConnectorPromotionPolicySetValidationError(
                "Policy revision adoption current policy must be enabled required.",
                "policy_revision_adoption_current_policy_not_enabled_required",
            )
        if revised_policy.status != "draft" or revised_policy.enforcement_mode != "advisory":
            raise ConnectorPromotionPolicySetValidationError(
                "Policy revision adoption revised policy must be draft advisory.",
                "policy_revision_adoption_revised_policy_not_draft_advisory",
            )
        if revised_policy.revises_policy_id != current_policy.policy_id:
            raise ConnectorPromotionPolicySetValidationError(
                "Policy revision adoption lineage does not match the current policy.",
                "policy_revision_adoption_lineage_mismatch",
            )
        if revised_policy.revision_idempotency_key != adoption.revision_idempotency_key:
            raise ConnectorPromotionPolicySetValidationError(
                "Policy revision adoption idempotency does not match the revised policy.",
                "policy_revision_adoption_idempotency_mismatch",
            )
        if revised_policy.revision_decision != "approve":
            raise ConnectorPromotionPolicySetValidationError(
                "Connector promotion policy revision adoption requires an approved revised policy.",
                "policy_revision_adoption_revision_not_approved",
            )
        if revised_policy.revision_workflow_signal_status != REQUIRED_POLICY_REVISION_SIGNAL:
            raise ConnectorPromotionPolicySetValidationError(
                "Policy revision adoption requires revised-policy workflow evidence.",
                "policy_revision_adoption_revision_signal_required",
            )

        audit_payload = {
            "connector_id": request.connector_id,
            "policy_set_id": request.policy_set_id,
            "policy_set_version": request.policy_set_version,
            "current_policy_id": current_policy.policy_id,
            "current_policy_version": current_policy.policy_version,
            "revised_policy_id": revised_policy.policy_id,
            "revised_policy_version": revised_policy.policy_version,
            "revision_idempotency_key": adoption.revision_idempotency_key,
            "revision_approval_id": revised_policy.revision_approval_id,
            "revision_decision": revised_policy.revision_decision,
            "revision_workflow_signal_status": revised_policy.revision_workflow_signal_status,
            "adoption_approval_id": adoption.adoption_approval_id,
            "adoption_decision": adoption.adoption_decision,
            "adoption_workflow_signal_status": adoption.adoption_workflow_signal_status,
            "activation_scope": REQUIRED_POLICY_SET_ACTIVATION_SCOPE,
            "permission_decision": permission_decision.model_dump(),
        }
        audit_event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=request.tenant_id,
                actor_id=request.activated_by,
                event_type=POLICY_REVISION_ADOPTED_AUDIT_EVENT_TYPE,
                payload=audit_payload,
            )
        )
        repository.adopt_connector_promotion_policy_revision(
            current_policy,
            revised_policy,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            note=(
                "Adopted as required policy during policy-set replacement "
                f"{request.policy_set_id}."
            ),
        )
        adoption_records.append(
            ConnectorPromotionPolicyRevisionAdoptionRecord(
                current_policy_id=adoption.current_policy_id,
                revised_policy_id=adoption.revised_policy_id,
                revision_idempotency_key=adoption.revision_idempotency_key,
                adoption_approval_id=adoption.adoption_approval_id,
                adoption_decision=adoption.adoption_decision,
                adoption_workflow_signal_status=adoption.adoption_workflow_signal_status,
                audit_event_id=audit_event.id,
                audit_event_type=audit_event.event_type,
            )
        )

    return adoption_records


def _validate_policy_revision_adoption_uniqueness(
    adoptions: list[ConnectorPromotionPolicyRevisionAdoption],
) -> None:
    current_policy_ids = [adoption.current_policy_id for adoption in adoptions]
    revised_policy_ids = [adoption.revised_policy_id for adoption in adoptions]
    if len(set(current_policy_ids)) == len(current_policy_ids) and len(
        set(revised_policy_ids)
    ) == len(revised_policy_ids):
        return
    raise ConnectorPromotionPolicySetValidationError(
        "Connector promotion policy revision adoptions cannot duplicate policies.",
        "policy_revision_adoption_duplicate_policy",
    )


def _validate_policy_revision_adoption_evidence(
    adoption: ConnectorPromotionPolicyRevisionAdoption,
) -> None:
    if adoption.adoption_approval_id is None:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy revision adoption requires approval evidence.",
            "policy_revision_adoption_approval_required",
        )
    if adoption.adoption_decision != "approve":
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy revision adoption requires an approved decision.",
            "policy_revision_adoption_not_approved",
        )
    if adoption.adoption_workflow_signal_status != REQUIRED_POLICY_REVISION_ADOPTION_SIGNAL:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy revision adoption requires workflow signal evidence.",
            "policy_revision_adoption_signal_required",
        )


def _rollback_requested(request: ConnectorPromotionPolicySetActivateRequest) -> bool:
    return any(
        value is not None
        for value in (
            request.rollback_to_policy_set_id,
            request.rollback_approval_id,
            request.rollback_decision,
            request.rollback_workflow_signal_status,
        )
    )


def _audit_event_type_for_request(active_policy_set, rollback_target) -> str:
    if rollback_target is not None:
        return POLICY_SET_ROLLED_BACK_AUDIT_EVENT_TYPE
    if active_policy_set is not None:
        return POLICY_SET_REPLACED_AUDIT_EVENT_TYPE
    return POLICY_SET_AUDIT_EVENT_TYPE


def _active_policy_set_for_replacement(
    active_sets: list,
    request: ConnectorPromotionPolicySetActivateRequest,
):
    if not active_sets:
        return None
    if request.replaces_policy_set_id is None:
        return None
    for active_set in active_sets:
        if active_set.policy_set_id == request.replaces_policy_set_id:
            return active_set
    raise ConnectorPromotionPolicySetValidationError(
        "Connector promotion policy set replacement target does not match the active set.",
        "policy_set_replacement_target_mismatch",
    )


def _rollback_policy_set_for_request(
    repository: AxisPersistenceRepository,
    request: ConnectorPromotionPolicySetActivateRequest,
):
    rollback_target = repository.get_connector_promotion_policy_set(
        request.tenant_id,
        request.rollback_to_policy_set_id or "",
    )
    if rollback_target is None:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set rollback target does not exist.",
            "policy_set_rollback_target_not_found",
        )
    if rollback_target.connector_id != request.connector_id:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set rollback target belongs to another connector.",
            "policy_set_rollback_connector_mismatch",
        )
    if rollback_target.status != "superseded":
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set rollback target must be superseded.",
            "policy_set_rollback_target_not_superseded",
        )
    return rollback_target


def _validate_replacement_evidence(request: ConnectorPromotionPolicySetActivateRequest) -> None:
    if request.replacement_approval_id is None:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set replacement requires approval evidence.",
            "policy_set_replacement_approval_required",
        )
    if request.replacement_decision != "approve":
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set replacement requires an approved decision.",
            "policy_set_replacement_not_approved",
        )
    if request.replacement_workflow_signal_status != REQUIRED_POLICY_SET_REPLACEMENT_SIGNAL:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set replacement requires workflow signal evidence.",
            "policy_set_replacement_signal_required",
        )


def _validate_rollback_evidence(request: ConnectorPromotionPolicySetActivateRequest) -> None:
    if request.rollback_approval_id is None:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set rollback requires approval evidence.",
            "policy_set_rollback_approval_required",
        )
    if request.rollback_decision != "approve":
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set rollback requires an approved decision.",
            "policy_set_rollback_not_approved",
        )
    if request.rollback_workflow_signal_status != REQUIRED_POLICY_SET_ROLLBACK_SIGNAL:
        raise ConnectorPromotionPolicySetValidationError(
            "Connector promotion policy set rollback requires workflow signal evidence.",
            "policy_set_rollback_signal_required",
        )


def _evaluate_activation_permission(
    request: ConnectorPromotionPolicySetActivateRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.activated_by,
            actor_scopes=request.actor_scopes,
            required_scopes=[REQUIRED_POLICY_SET_ACTIVATION_SCOPE],
            attributes={
                "connector_id": request.connector_id,
                "policy_set_id": request.policy_set_id,
                "policy_set_version": request.policy_set_version,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorPromotionPolicySetPermissionDenied(
            REQUIRED_POLICY_SET_ACTIVATION_SCOPE,
            decision,
        )
    return decision


def _validate_policy_set_status(status: str) -> None:
    if status in SUPPORTED_POLICY_SET_STATUSES:
        return
    raise ConnectorPromotionPolicySetValidationError(
        "Connector promotion policy sets can only be activated in this slice.",
        "unsupported_policy_set_status",
    )


def _validate_policy_ids_unique(policy_ids: list[str]) -> None:
    if len(set(policy_ids)) == len(policy_ids):
        return
    raise ConnectorPromotionPolicySetValidationError(
        "Connector promotion policy sets cannot reference duplicate policies.",
        "policy_set_duplicate_policy",
    )


def _validate_referenced_policies(
    repository: AxisPersistenceRepository,
    request: ConnectorPromotionPolicySetActivateRequest,
) -> list:
    policies = []
    for policy_id in request.policy_ids:
        policy = repository.get_connector_promotion_policy(request.tenant_id, policy_id)
        if policy is None:
            raise ConnectorPromotionPolicySetValidationError(
                "Connector promotion policy set references an unknown policy.",
                "policy_set_policy_not_found",
            )
        if policy.connector_id != request.connector_id:
            raise ConnectorPromotionPolicySetValidationError(
                "Connector promotion policy set references a policy for another connector.",
                "policy_set_connector_mismatch",
            )
        if policy.status != "enabled" or policy.enforcement_mode != "required":
            raise ConnectorPromotionPolicySetValidationError(
                "Connector promotion policy set references a policy that is not enabled required.",
                "policy_set_policy_not_enabled_required",
            )
        policies.append(policy)
    return policies


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
    raise ConnectorPromotionPolicySetValidationError(
        f"Unsupported connector_id: {connector_id}",
        "unsupported_connector_id",
    )


def _policy_set_from_record(record) -> ConnectorPromotionPolicySetRecord:
    return ConnectorPromotionPolicySetRecord(
        tenant_id=record.tenant_id,
        connector_id=record.connector_id,
        policy_set_id=record.policy_set_id,
        policy_set_version=record.policy_set_version,
        status=record.status,
        activated_by=record.activated_by,
        activation_scope=record.activation_scope,
        policy_ids=record.policy_ids,
        permission_decision=PermissionDecision.model_validate(record.permission_decision),
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        activation_reason=record.activation_reason,
        replaces_policy_set_id=record.replaces_policy_set_id,
        replaced_by_policy_set_id=record.replaced_by_policy_set_id,
        replacement_approval_id=record.replacement_approval_id,
        replacement_decision=record.replacement_decision,
        replacement_workflow_signal_status=record.replacement_workflow_signal_status,
        replaced_at=record.replaced_at,
        rollback_to_policy_set_id=record.rollback_to_policy_set_id,
        rollback_approval_id=record.rollback_approval_id,
        rollback_decision=record.rollback_decision,
        rollback_workflow_signal_status=record.rollback_workflow_signal_status,
        policy_revision_adoptions=record.policy_revision_adoptions or [],
        notes=record.notes,
        created_at=record.created_at,
    )
