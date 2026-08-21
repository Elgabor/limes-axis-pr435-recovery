from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from axis_api.audit import AuditEventCreate
from axis_api.connector_reference import require_persisted_manufacturing_connector_registry
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    get_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.models import utc_now
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialLeaseCreate,
    ConnectorCredentialLeaseRenewalRecord,
    ConnectorCredentialLeaseRevocationRecord,
)

REQUEST_SCOPE = "connectors:credential_lease:request"
RENEW_SCOPE = "connectors:credential_lease:renew"
REVOKE_SCOPE = "connectors:credential_lease:revoke"
READ_AUDIT_EVENT_TYPE = "connector.credential_leases_read"
LEASE_MODE = "deferred_vault_kms_lease"
LEASE_RUNTIME_BOUNDARY = "axis-credential-lease-broker"
LEASE_ADAPTER = "axis-deferred-vault-kms-lease-adapter"
SELF_HOSTED_LEASE_MODE = "self_hosted_vault_kms_lease"
SELF_HOSTED_LEASE_ADAPTER = "axis-self-hosted-vault-kms-lease-adapter"
PROVIDER_SPECIFIC_LEASE_MODE = "provider_specific_vault_kms_lease"
PROVIDER_SPECIFIC_LEASE_ADAPTER = "axis-provider-specific-vault-kms-lease-adapter"


PROVIDER_PROFILES = {
    "hashicorp_vault": {
        "provider_aliases": {"external_vault", "hashicorp_vault", "vault"},
        "secret_ref_prefix": "vault://",
        "lease_ref_prefix": "vault://axis/leases",
        "requires_lease_path": True,
    },
    "aws_secrets_manager": {
        "provider_aliases": {"aws_secrets_manager", "aws-secrets-manager"},
        "secret_ref_prefix": "aws-secrets-manager://",
        "lease_ref_prefix": "aws-secrets-manager://axis/leases",
        "requires_lease_path": False,
    },
    "gcp_secret_manager": {
        "provider_aliases": {"gcp_secret_manager", "gcp-secret-manager"},
        "secret_ref_prefix": "gcp-secret-manager://",
        "lease_ref_prefix": "gcp-secret-manager://axis/leases",
        "requires_lease_path": False,
    },
    "azure_key_vault": {
        "provider_aliases": {"azure_key_vault", "azure-key-vault"},
        "secret_ref_prefix": "azure-key-vault://",
        "lease_ref_prefix": "azure-key-vault://axis/leases",
        "requires_lease_path": False,
    },
    "kms": {
        "provider_aliases": {"kms"},
        "secret_ref_prefix": "kms://",
        "lease_ref_prefix": "kms://axis/leases",
        "requires_lease_path": False,
    },
    "env_dev": {
        "provider_aliases": {"env", "env_dev", "local_env"},
        "secret_ref_prefix": "env://",
        "lease_ref_prefix": "env://axis/leases",
        "requires_lease_path": False,
    },
}


class CredentialLeaseRuntimeRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    handle_id: str = Field(min_length=1)
    lease_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    secret_provider: str = Field(min_length=1)
    secret_ref: str = Field(min_length=1)
    vault_kms_policy: dict[str, str] = Field(default_factory=dict)
    evidence_ref: str = Field(min_length=1)


class CredentialLeaseRuntimeResult(BaseModel):
    adapter: str = Field(min_length=1)
    status: str = Field(min_length=1)
    lease_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    external_secret_read: str = Field(default="false", min_length=1)
    secret_material_returned: str = Field(default="false", min_length=1)
    evidence_ref: str = Field(min_length=1)
    provider_mode: str = Field(default="deferred", min_length=1)
    provider_lease_ref: str = Field(min_length=1)


class CredentialLeaseRuntime(Protocol):
    lease_mode: str

    def request_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        pass

    def renew_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        pass

    def revoke_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        pass


class DeferredCredentialLeaseRuntime:
    lease_mode = LEASE_MODE
    adapter_name = LEASE_ADAPTER

    def request_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        return _runtime_result(
            adapter=self.adapter_name,
            status="lease_deferred",
            request=request,
            provider_mode="deferred",
            provider_lease_ref=f"deferred-lease://{request.tenant_id}/{request.lease_id}",
        )

    def renew_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        return _runtime_result(
            adapter=self.adapter_name,
            status="lease_renewal_deferred",
            request=request,
            provider_mode="deferred",
            provider_lease_ref=f"deferred-lease://{request.tenant_id}/{request.lease_id}",
        )

    def revoke_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        return _runtime_result(
            adapter=self.adapter_name,
            status="lease_revocation_deferred",
            request=request,
            provider_mode="deferred",
            provider_lease_ref=f"deferred-lease://{request.tenant_id}/{request.lease_id}",
        )


class SelfHostedVaultKmsLeaseRuntime:
    lease_mode = SELF_HOSTED_LEASE_MODE
    adapter_name = SELF_HOSTED_LEASE_ADAPTER

    def request_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        return _runtime_result(
            adapter=self.adapter_name,
            status="lease_executed",
            request=request,
            provider_mode=_provider_mode(request),
            provider_lease_ref=_provider_lease_ref(request),
        )

    def renew_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        return _runtime_result(
            adapter=self.adapter_name,
            status="lease_renewed",
            request=request,
            provider_mode=_provider_mode(request),
            provider_lease_ref=_provider_lease_ref(request),
        )

    def revoke_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        return _runtime_result(
            adapter=self.adapter_name,
            status="lease_revoked",
            request=request,
            provider_mode=_provider_mode(request),
            provider_lease_ref=_provider_lease_ref(request),
        )


class ProviderSpecificVaultKmsLeaseRuntime:
    lease_mode = PROVIDER_SPECIFIC_LEASE_MODE
    adapter_name = PROVIDER_SPECIFIC_LEASE_ADAPTER

    def request_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        return self._lease_result("lease_executed", request)

    def renew_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        return self._lease_result("lease_renewed", request)

    def revoke_lease(
        self,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        return self._lease_result("lease_revoked", request)

    def _lease_result(
        self,
        status: str,
        request: CredentialLeaseRuntimeRequest,
    ) -> CredentialLeaseRuntimeResult:
        provider_mode, profile = _provider_profile(request)
        return _runtime_result(
            adapter=self.adapter_name,
            status=status,
            request=request,
            provider_mode=provider_mode,
            provider_lease_ref=(
                f"{profile['lease_ref_prefix']}/{request.tenant_id}/{request.lease_id}"
            ),
        )


class ConnectorCredentialLeaseValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorCredentialLeasePermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ConnectorCredentialLeaseConflict(ValueError):
    def __init__(self, lease_id: str) -> None:
        super().__init__("Connector credential lease already exists")
        self.lease_id = lease_id


class ConnectorCredentialLeaseQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    handle_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorCredentialLeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    handle_id: str = Field(min_length=1, max_length=160)
    lease_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    requested_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=lambda: [REQUEST_SCOPE])
    lease_purpose: str = Field(min_length=1, max_length=160)
    requested_at: datetime | None = None
    lease_duration_seconds: int = Field(default=900, ge=60, le=24 * 60 * 60)
    renewal_window_seconds: int = Field(default=300, ge=30, le=60 * 60)
    runtime_boundary: str = Field(default=LEASE_RUNTIME_BOUNDARY, min_length=1, max_length=160)
    vault_kms_policy: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ConnectorCredentialLeaseRenewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    renewed_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=lambda: [RENEW_SCOPE])
    renewed_at: datetime | None = None
    extend_seconds: int = Field(default=900, ge=60, le=24 * 60 * 60)
    renewal_window_seconds: int = Field(default=300, ge=30, le=60 * 60)
    renewal_reason: str = Field(min_length=1, max_length=600)
    evidence_ref: str = Field(min_length=1, max_length=240)


class ConnectorCredentialLeaseRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    revoked_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=lambda: [REVOKE_SCOPE])
    revoked_at: datetime | None = None
    revocation_reason: str = Field(min_length=1, max_length=600)
    evidence_ref: str = Field(min_length=1, max_length=240)


class ConnectorCredentialLeaseRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    handle_id: str = Field(min_length=1)
    lease_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    lease_mode: str = Field(min_length=1)
    runtime_boundary: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    lease_purpose: str = Field(min_length=1)
    secret_provider: str = Field(min_length=1)
    secret_ref: str = Field(min_length=1)
    vault_kms_policy: dict[str, str] = Field(default_factory=dict)
    permission_decision: dict[str, Any] = Field(default_factory=dict)
    lease_result: dict[str, str] = Field(default_factory=dict)
    granted_at: datetime
    expires_at: datetime
    renewal_due_at: datetime
    renewed_at: datetime | None = None
    renewed_by: str | None = None
    renewal_count: int
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    revocation_reason: str | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ConnectorCredentialLeaseEvidenceInvariant(BaseModel):
    lease_id: str = Field(min_length=1)
    audit_event_id: str | None = None
    reason: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ManufacturingConnectorCredentialLeaseRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    leases: list[ConnectorCredentialLeaseRecord] = Field(default_factory=list)
    lease_evidence_invariants: list[
        ConnectorCredentialLeaseEvidenceInvariant
    ] = Field(default_factory=list)
    lease_notes: list[str] = Field(default_factory=list)


RAW_SECRET_FIELD_NAMES = {
    "api_key",
    "client_secret",
    "credential_value",
    "inline_secret",
    "password",
    "secret",
    "secret_value",
    "token",
}
RAW_SECRET_MARKERS = (
    "api_key=",
    "client_secret=",
    "credential_value",
    "literal-password",
    "password=",
    "secret_value=",
    "token=",
)


def build_connector_credential_lease_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorCredentialLeaseQuery,
) -> ManufacturingConnectorCredentialLeaseRegistry:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_connector_credential_leases(
        tenant_id=query.tenant_id,
        connector_id=query.connector_id,
        handle_id=query.handle_id,
        status=query.status,
        limit=query.limit,
    )
    leases = [_lease_from_record(record) for record in records]
    lease_evidence_invariants = [
        invariant
        for record in records
        if (invariant := _lease_evidence_invariant(repository, record)) is not None
    ]
    renewal_due = sum(
        1
        for lease in leases
        if lease.status == "active" and _aware_datetime(lease.renewal_due_at) <= utc_now()
    )
    has_persisted_records = bool(records)
    if not has_persisted_records and any(
        value is not None for value in (query.connector_id, query.handle_id, query.status)
    ):
        has_persisted_records = bool(
            repository.list_connector_credential_leases(
                tenant_id=query.tenant_id,
                limit=1,
            )
        )
    return ManufacturingConnectorCredentialLeaseRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(has_persisted_records),
        registry_status=OverviewStatus.READY if leases else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Credential Leases",
                value=str(len(leases)),
                detail="Vault/KMS lease records for connector execution",
                status=OverviewStatus.READY if leases else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Renewal Due",
                value=str(renewal_due),
                detail="Active leases at or past renewal window",
                status=OverviewStatus.WATCH if renewal_due else OverviewStatus.READY,
            ),
            OverviewMetric(
                label="Lease Evidence Invariants",
                value=str(len(lease_evidence_invariants)),
                detail="Credential lease audit ledger binding issues in this result set",
                status=(
                    OverviewStatus.WATCH
                    if lease_evidence_invariants
                    else OverviewStatus.READY
                ),
            ),
            OverviewMetric(
                label="Secret Material",
                value="Never Returned",
                detail="Lease adapter returns refs and evidence only",
                status=OverviewStatus.READY,
            ),
        ],
        leases=leases,
        lease_evidence_invariants=lease_evidence_invariants,
        lease_notes=[
            "Credential leases are short-lived records for connector execution.",
            "The default adapter is deferred and never returns secret material.",
            "Renewal and revocation write audit evidence before live sync is enabled.",
        ],
    )


def read_connector_credential_lease_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorCredentialLeaseQuery,
    *,
    actor_id: str,
) -> ManufacturingConnectorCredentialLeaseRegistry:
    registry = build_connector_credential_lease_registry(repository, query)
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=query.tenant_id,
            actor_id=actor_id,
            event_type=READ_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": query.connector_id,
                "handle_id": query.handle_id,
                "status": query.status,
                "limit": query.limit,
                "returned_lease_count": len(registry.leases),
                "lease_evidence_invariant_count": len(
                    registry.lease_evidence_invariants
                ),
                "lease_ids": [lease.lease_id for lease in registry.leases],
            },
        )
    )
    return registry


def record_demo_connector_credential_lease(
    repository: AxisPersistenceRepository,
    request: ConnectorCredentialLeaseRequest,
    lease_runtime: CredentialLeaseRuntime | None = None,
) -> ConnectorCredentialLeaseRecord:
    _validate_public_safe_payload(request.model_dump(mode="json"))
    existing = repository.get_connector_credential_lease(request.tenant_id, request.lease_id)
    if existing is not None:
        raise ConnectorCredentialLeaseConflict(existing.lease_id)

    handle = repository.get_connector_credential_handle(request.tenant_id, request.handle_id)
    if handle is None:
        raise ConnectorCredentialLeaseValidationError(
            "Connector credential handle not found.",
            "credential_handle_not_found",
        )
    if handle.connector_id != request.connector_id:
        raise ConnectorCredentialLeaseValidationError(
            "Connector credential handle does not belong to the requested connector.",
            "credential_handle_connector_mismatch",
        )
    if handle.status != "active":
        raise ConnectorCredentialLeaseValidationError(
            "Connector credential handle must be active before lease request.",
            "credential_handle_not_active",
        )
    _active_preview_manifest_for_connector(repository, request.tenant_id, request.connector_id)

    permission_decision = _evaluate_permission(
        tenant_id=request.tenant_id,
        actor_id=request.requested_by,
        actor_scopes=request.actor_scopes,
        required_scopes=request.required_scopes,
        action="request",
    )
    granted_at = _aware_datetime(request.requested_at or utc_now())
    expires_at = granted_at + timedelta(seconds=request.lease_duration_seconds)
    renewal_due_at = expires_at - timedelta(seconds=request.renewal_window_seconds)
    runtime = lease_runtime or DeferredCredentialLeaseRuntime()
    lease_result = runtime.request_lease(
        CredentialLeaseRuntimeRequest(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            handle_id=request.handle_id,
            lease_id=request.lease_id,
            secret_provider=handle.secret_provider,
            secret_ref=handle.secret_ref,
            vault_kms_policy=request.vault_kms_policy,
            evidence_ref=f"lease:{request.lease_id}",
            action="request",
        )
    ).model_dump(mode="json")
    lease_mode = runtime.lease_mode
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type="connector.credential_lease.requested",
            payload={
                "connector_id": request.connector_id,
                "handle_id": request.handle_id,
                "lease_id": request.lease_id,
                "lease_mode": lease_mode,
                "lease_purpose": request.lease_purpose,
                "runtime_boundary": request.runtime_boundary,
                "secret_provider": handle.secret_provider,
                "secret_material_returned": lease_result["secret_material_returned"],
                "adapter": lease_result["adapter"],
            },
        )
    )
    record = repository.create_connector_credential_lease(
        ConnectorCredentialLeaseCreate(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            handle_id=request.handle_id,
            lease_id=request.lease_id,
            status="active",
            lease_mode=lease_mode,
            runtime_boundary=request.runtime_boundary,
            requested_by=request.requested_by,
            lease_purpose=request.lease_purpose,
            secret_provider=handle.secret_provider,
            secret_ref=handle.secret_ref,
            vault_kms_policy=request.vault_kms_policy,
            permission_decision=permission_decision.model_dump(mode="json"),
            lease_result=lease_result,
            granted_at=granted_at,
            expires_at=expires_at,
            renewal_due_at=renewal_due_at,
            audit_event_id=audit_event.id,
            audit_event_type="connector.credential_lease.requested",
            notes=request.notes,
        )
    )
    return _lease_from_record(record)


def renew_demo_connector_credential_lease(
    repository: AxisPersistenceRepository,
    lease_id: str,
    request: ConnectorCredentialLeaseRenewRequest,
    lease_runtime: CredentialLeaseRuntime | None = None,
) -> ConnectorCredentialLeaseRecord:
    _validate_public_safe_payload(request.model_dump(mode="json"))
    lease = _active_lease(repository, request.tenant_id, lease_id)
    _evaluate_permission(
        tenant_id=request.tenant_id,
        actor_id=request.renewed_by,
        actor_scopes=request.actor_scopes,
        required_scopes=request.required_scopes,
        action="renew",
    )
    renewed_at = _aware_datetime(request.renewed_at or utc_now())
    expires_at = renewed_at + timedelta(seconds=request.extend_seconds)
    renewal_due_at = expires_at - timedelta(seconds=request.renewal_window_seconds)
    runtime = lease_runtime or DeferredCredentialLeaseRuntime()
    lease_result = runtime.renew_lease(
        CredentialLeaseRuntimeRequest(
            tenant_id=request.tenant_id,
            connector_id=lease.connector_id,
            handle_id=lease.handle_id,
            lease_id=lease_id,
            secret_provider=lease.secret_provider,
            secret_ref=lease.secret_ref,
            vault_kms_policy=lease.vault_kms_policy,
            evidence_ref=request.evidence_ref,
            action="renew",
        )
    ).model_dump(mode="json")
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.renewed_by,
            event_type="connector.credential_lease.renewed",
            payload={
                "connector_id": lease.connector_id,
                "handle_id": lease.handle_id,
                "lease_id": lease_id,
                "renewal_reason": request.renewal_reason,
                "evidence_ref": request.evidence_ref,
                "secret_material_returned": lease_result["secret_material_returned"],
                "adapter": lease_result["adapter"],
            },
        )
    )
    renewed = repository.renew_connector_credential_lease(
        ConnectorCredentialLeaseRenewalRecord(
            tenant_id=request.tenant_id,
            lease_id=lease_id,
            renewed_by=request.renewed_by,
            renewed_at=renewed_at,
            expires_at=expires_at,
            renewal_due_at=renewal_due_at,
            audit_event_id=audit_event.id,
            audit_event_type="connector.credential_lease.renewed",
            lease_result=lease_result,
            note=f"Lease renewed: {request.renewal_reason}",
        )
    )
    return _lease_from_record(renewed)


def revoke_demo_connector_credential_lease(
    repository: AxisPersistenceRepository,
    lease_id: str,
    request: ConnectorCredentialLeaseRevokeRequest,
    lease_runtime: CredentialLeaseRuntime | None = None,
) -> ConnectorCredentialLeaseRecord:
    _validate_public_safe_payload(request.model_dump(mode="json"))
    lease = _active_lease(repository, request.tenant_id, lease_id)
    _evaluate_permission(
        tenant_id=request.tenant_id,
        actor_id=request.revoked_by,
        actor_scopes=request.actor_scopes,
        required_scopes=request.required_scopes,
        action="revoke",
    )
    revoked_at = _aware_datetime(request.revoked_at or utc_now())
    runtime = lease_runtime or DeferredCredentialLeaseRuntime()
    lease_result = runtime.revoke_lease(
        CredentialLeaseRuntimeRequest(
            tenant_id=request.tenant_id,
            connector_id=lease.connector_id,
            handle_id=lease.handle_id,
            lease_id=lease_id,
            secret_provider=lease.secret_provider,
            secret_ref=lease.secret_ref,
            vault_kms_policy=lease.vault_kms_policy,
            evidence_ref=request.evidence_ref,
            action="revoke",
        )
    ).model_dump(mode="json")
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.revoked_by,
            event_type="connector.credential_lease.revoked",
            payload={
                "connector_id": lease.connector_id,
                "handle_id": lease.handle_id,
                "lease_id": lease_id,
                "revocation_reason": request.revocation_reason,
                "evidence_ref": request.evidence_ref,
                "secret_material_returned": lease_result["secret_material_returned"],
                "adapter": lease_result["adapter"],
            },
        )
    )
    revoked = repository.revoke_connector_credential_lease(
        ConnectorCredentialLeaseRevocationRecord(
            tenant_id=request.tenant_id,
            lease_id=lease_id,
            revoked_by=request.revoked_by,
            revoked_at=revoked_at,
            revocation_reason=request.revocation_reason,
            audit_event_id=audit_event.id,
            audit_event_type="connector.credential_lease.revoked",
            lease_result=lease_result,
        )
    )
    return _lease_from_record(revoked)


def _active_lease(repository: AxisPersistenceRepository, tenant_id: str, lease_id: str):
    lease = repository.get_connector_credential_lease(tenant_id, lease_id)
    if lease is None:
        raise ConnectorCredentialLeaseValidationError(
            "Connector credential lease not found.",
            "credential_lease_not_found",
        )
    if lease.status != "active":
        raise ConnectorCredentialLeaseValidationError(
            "Connector credential lease must be active.",
            "credential_lease_not_active",
        )
    return lease


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
    raise ConnectorCredentialLeaseValidationError(
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
        raise ConnectorCredentialLeaseValidationError(
            "Connector manifest must be registered before credential lease request.",
            "connector_manifest_not_found",
        )
    if manifest.status != "active_preview":
        raise ConnectorCredentialLeaseValidationError(
            "Connector manifest must be active_preview before credential lease request.",
            "connector_manifest_not_active_preview",
        )
    return manifest


def _evaluate_permission(
    *,
    tenant_id: str,
    actor_id: str,
    actor_scopes: list[str],
    required_scopes: list[str],
    action: str,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_scopes=actor_scopes,
            required_scopes=required_scopes,
            attributes={"action": action, "resource": "connector_credential_lease"},
        )
    )
    if not decision.allowed:
        required_permission = required_scopes[0] if required_scopes else REQUEST_SCOPE
        raise ConnectorCredentialLeasePermissionDenied(required_permission, decision)
    return decision


def _lease_from_record(record) -> ConnectorCredentialLeaseRecord:
    return ConnectorCredentialLeaseRecord(
        tenant_id=record.tenant_id,
        connector_id=record.connector_id,
        handle_id=record.handle_id,
        lease_id=record.lease_id,
        status=record.status,
        lease_mode=record.lease_mode,
        runtime_boundary=record.runtime_boundary,
        requested_by=record.requested_by,
        lease_purpose=record.lease_purpose,
        secret_provider=record.secret_provider,
        secret_ref=record.secret_ref,
        vault_kms_policy=record.vault_kms_policy,
        permission_decision=record.permission_decision,
        lease_result=record.lease_result,
        granted_at=_aware_datetime(record.granted_at),
        expires_at=_aware_datetime(record.expires_at),
        renewal_due_at=_aware_datetime(record.renewal_due_at),
        renewed_at=_optional_aware_datetime(record.renewed_at),
        renewed_by=record.renewed_by,
        renewal_count=record.renewal_count,
        revoked_at=_optional_aware_datetime(record.revoked_at),
        revoked_by=record.revoked_by,
        revocation_reason=record.revocation_reason,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        notes=record.notes,
        created_at=_aware_datetime(record.created_at),
    )


def _lease_evidence_invariant(
    repository: AxisPersistenceRepository,
    record,
) -> ConnectorCredentialLeaseEvidenceInvariant | None:
    audit_event_id = str(record.audit_event_id) if record.audit_event_id else None
    if record.audit_event_id is None:
        return ConnectorCredentialLeaseEvidenceInvariant(
            lease_id=record.lease_id,
            audit_event_id=None,
            reason="lease_audit_event_missing",
            detail="Lease must reference an append-only audit event.",
        )
    audit_event = repository.get_audit_event(record.tenant_id, record.audit_event_id)
    if audit_event is None:
        return ConnectorCredentialLeaseEvidenceInvariant(
            lease_id=record.lease_id,
            audit_event_id=audit_event_id,
            reason="lease_audit_event_not_found",
            detail="Lease audit event id must resolve in the tenant ledger.",
        )
    if audit_event.event_type != record.audit_event_type:
        return ConnectorCredentialLeaseEvidenceInvariant(
            lease_id=record.lease_id,
            audit_event_id=audit_event_id,
            reason="lease_audit_event_type_mismatch",
            detail="Lease audit event type must match the lease record.",
        )
    if (
        audit_event.payload.get("connector_id") != record.connector_id
        or audit_event.payload.get("handle_id") != record.handle_id
        or audit_event.payload.get("lease_id") != record.lease_id
    ):
        return ConnectorCredentialLeaseEvidenceInvariant(
            lease_id=record.lease_id,
            audit_event_id=audit_event_id,
            reason="lease_audit_event_payload_mismatch",
            detail=(
                "Lease audit event payload must match connector_id, "
                "handle_id and lease_id."
            ),
        )
    if not _lease_evidence_payload_is_public_safe(audit_event.payload):
        return ConnectorCredentialLeaseEvidenceInvariant(
            lease_id=record.lease_id,
            audit_event_id=audit_event_id,
            reason="lease_audit_payload_unsafe",
            detail="Lease audit event payload must not report secret material access.",
        )
    if not _lease_evidence_payload_is_public_safe(record.lease_result):
        return ConnectorCredentialLeaseEvidenceInvariant(
            lease_id=record.lease_id,
            audit_event_id=audit_event_id,
            reason="lease_result_unsafe",
            detail="Lease result evidence must not include secret material access.",
        )
    return None


def _lease_evidence_payload_is_public_safe(payload: dict) -> bool:
    if str(payload.get("secret_material_returned", "false")).lower() != "false":
        return False
    return str(payload.get("external_secret_read", "false")).lower() == "false"


def _runtime_result(
    *,
    adapter: str,
    status: str,
    request: CredentialLeaseRuntimeRequest,
    provider_mode: str,
    provider_lease_ref: str,
) -> CredentialLeaseRuntimeResult:
    return CredentialLeaseRuntimeResult(
        adapter=adapter,
        status=status,
        lease_id=request.lease_id,
        action=request.action,
        external_secret_read="false",
        secret_material_returned="false",
        evidence_ref=request.evidence_ref,
        provider_mode=provider_mode,
        provider_lease_ref=provider_lease_ref,
    )


def _provider_mode(request: CredentialLeaseRuntimeRequest) -> str:
    return request.vault_kms_policy.get("provider_mode") or "self_hosted_vault"


def _provider_lease_ref(request: CredentialLeaseRuntimeRequest) -> str:
    return f"vault-lease://{request.tenant_id}/{request.lease_id}"


def _provider_profile(
    request: CredentialLeaseRuntimeRequest,
) -> tuple[str, dict[str, Any]]:
    provider_mode = _normalized_provider_mode(request.vault_kms_policy.get("provider_mode"))
    if not provider_mode:
        raise ConnectorCredentialLeaseValidationError(
            "Provider-specific credential leases require vault_kms_policy.provider_mode.",
            "missing_provider_mode",
        )
    profile = PROVIDER_PROFILES.get(provider_mode)
    if profile is None:
        raise ConnectorCredentialLeaseValidationError(
            "Unsupported provider-specific Vault/KMS credential lease mode.",
            "unsupported_provider_mode",
        )

    secret_provider = _normalized_provider_mode(request.secret_provider)
    if secret_provider not in profile["provider_aliases"]:
        raise ConnectorCredentialLeaseValidationError(
            "Credential handle secret_provider does not match provider lease mode.",
            "provider_secret_provider_mismatch",
        )

    secret_ref = request.secret_ref.strip().lower()
    if not secret_ref.startswith(profile["secret_ref_prefix"]):
        raise ConnectorCredentialLeaseValidationError(
            "Credential handle secret_ref does not match provider lease mode.",
            "provider_secret_ref_mismatch",
        )

    if profile["requires_lease_path"] and not request.vault_kms_policy.get("lease_path"):
        raise ConnectorCredentialLeaseValidationError(
            "Provider-specific Vault leases require vault_kms_policy.lease_path.",
            "missing_provider_lease_path",
        )

    kms_key_ref = request.vault_kms_policy.get("kms_key_ref")
    if kms_key_ref is not None and not kms_key_ref.strip().lower().startswith("kms://"):
        raise ConnectorCredentialLeaseValidationError(
            "Provider-specific Vault/KMS leases require kms_key_ref to use kms://.",
            "invalid_kms_key_ref",
        )

    return provider_mode, profile


def _normalized_provider_mode(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_")


def _validate_public_safe_payload(payload: dict[str, Any]) -> None:
    keys = {key for key, _ in _walk_payload(payload)}
    values = [value for _, value in _walk_payload(payload)]
    if keys.intersection(RAW_SECRET_FIELD_NAMES) or any(
        marker in value for value in values for marker in RAW_SECRET_MARKERS
    ):
        raise ConnectorCredentialLeaseValidationError(
            "Connector credential leases cannot include raw credential material.",
            "raw_secret_material",
        )


def _walk_payload(value: Any) -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized_key = str(key).lower()
            yield normalized_key, ""
            yield from _walk_payload(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            yield from _walk_payload(nested_value)
    elif value is not None:
        yield "", str(value).lower()


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def _optional_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _aware_datetime(value)
