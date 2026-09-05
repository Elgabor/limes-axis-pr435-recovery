"""Tenant lifecycle and per-tenant quota foundation for the platform surface.

This module provides platform-operator provisioning, suspension, reactivation
and quota administration for tenants, plus the in-process tenant state cache
consulted by the enforcement points (suspended-tenant rejection, per-tenant API
rate limits, concurrent-session caps and live-sync row caps).
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session, sessionmaker

from axis_api.audit import AuditEventCreate
from axis_api.db import session_scope
from axis_api.models import AuditEvent, Tenant
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    ActorCreate,
    AxisPersistenceRepository,
    TenantCreate,
    TenantLifecycleTransition,
    TenantQuotaUpsert,
)
from axis_api.tenant_admission import (
    TENANT_ADMISSION_CLAIMS_ONLY,
    tenant_admission_denial_reason,
)


class TenantLifecycleStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_DELETION = "pending_deletion"


class TenantQuotaKey(StrEnum):
    API_REQUESTS_PER_WINDOW = "api_requests_per_window"
    MAX_CONCURRENT_SESSIONS = "max_concurrent_sessions"
    MAX_CONNECTOR_SYNC_ROWS_PER_RUN = "max_connector_sync_rows_per_run"


class TenantPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class TenantProvisionConflict(ValueError):
    def __init__(self, tenant_id: str, reason: str) -> None:
        super().__init__("The tenant provisioning request conflicts with persisted state")
        self.tenant_id = tenant_id
        self.reason = reason


class TenantLifecycleConflict(ValueError):
    def __init__(self, tenant_id: str, reason: str) -> None:
        super().__init__("The tenant lifecycle transition conflicts with the current status")
        self.tenant_id = tenant_id
        self.reason = reason


class TenantNotFound(LookupError):
    pass


class TenantListCursorError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


REQUIRED_OPERATOR_SCOPE = "platform:tenant:operator"
REQUIRED_PROVISION_SCOPE = "platform:tenant:provision"
REQUIRED_SUSPEND_SCOPE = "platform:tenant:suspend"
REQUIRED_READ_SCOPE = "platform:tenant:read"
REQUIRED_QUOTA_SCOPE = "platform:tenant:quota"
REQUIRED_CONFIGURE_SCOPE = "platform:tenant:configure"
# Every lifecycle mutation records requested_by as AuditEvent.actor_id.
# Keep this boundary synchronized with the persisted VARCHAR(120) column.
AUDIT_ACTOR_ID_MAX_LENGTH = 120
PROVISIONED_AUDIT_EVENT_TYPE = "platform.tenant.provisioned"
FIRST_TENANT_BOOTSTRAPPED_AUDIT_EVENT_TYPE = "platform.tenant.first_bootstrap.completed"
SUSPENDED_AUDIT_EVENT_TYPE = "platform.tenant.suspended"
REACTIVATED_AUDIT_EVENT_TYPE = "platform.tenant.reactivated"
QUOTA_UPDATED_AUDIT_EVENT_TYPE = "platform.tenant.quota.updated"
VOCABULARY_UPDATED_AUDIT_EVENT_TYPE = "platform.tenant.vocabulary.updated"
TENANT_VOCABULARY_LABEL_MAX_LENGTH = 100
TENANT_VOCABULARY_MAX_DOMAIN_LABELS = 50


class TenantBootstrapAdmin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1, max_length=AUDIT_ACTOR_ID_MAX_LENGTH)
    display_name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=list)


class TenantProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=600)
    requested_by: str = Field(min_length=1, max_length=AUDIT_ACTOR_ID_MAX_LENGTH)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=200)
    bootstrap_admin: TenantBootstrapAdmin | None = None
    notes: list[str] = Field(default_factory=list)


class TenantSuspendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1, max_length=AUDIT_ACTOR_ID_MAX_LENGTH)
    actor_scopes: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=600)
    notes: list[str] = Field(default_factory=list)


class TenantReactivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1, max_length=AUDIT_ACTOR_ID_MAX_LENGTH)
    actor_scopes: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=600)
    notes: list[str] = Field(default_factory=list)


class TenantQuotaValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_requests_per_window: int | None = Field(default=None, ge=1, le=1_000_000)
    max_concurrent_sessions: int | None = Field(default=None, ge=0, le=10_000)
    max_connector_sync_rows_per_run: int | None = Field(default=None, ge=1, le=1_000_000)

    def as_mapping(self) -> dict[str, int | None]:
        return {
            TenantQuotaKey.API_REQUESTS_PER_WINDOW.value: self.api_requests_per_window,
            TenantQuotaKey.MAX_CONCURRENT_SESSIONS.value: self.max_concurrent_sessions,
            TenantQuotaKey.MAX_CONNECTOR_SYNC_ROWS_PER_RUN.value: (
                self.max_connector_sync_rows_per_run
            ),
        }


class TenantQuotaUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1, max_length=AUDIT_ACTOR_ID_MAX_LENGTH)
    actor_scopes: list[str] = Field(default_factory=list)
    quotas: TenantQuotaValues
    notes: list[str] = Field(default_factory=list)


class TenantVocabulary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_singular: str = Field(
        default="Site",
        max_length=TENANT_VOCABULARY_LABEL_MAX_LENGTH,
    )
    site_plural: str = Field(
        default="Sites",
        max_length=TENANT_VOCABULARY_LABEL_MAX_LENGTH,
    )
    workspace_label: str = Field(
        default="Operations",
        max_length=TENANT_VOCABULARY_LABEL_MAX_LENGTH,
    )
    domain_labels: dict[str, str] = Field(
        default_factory=dict,
        max_length=TENANT_VOCABULARY_MAX_DOMAIN_LABELS,
    )

    @field_validator("site_singular", "site_plural", "workspace_label")
    @classmethod
    def validate_label(cls, label: str) -> str:
        stripped = label.strip()
        if not stripped:
            raise ValueError("Tenant vocabulary labels must not be blank.")
        return stripped

    @field_validator("domain_labels")
    @classmethod
    def validate_domain_labels(cls, domain_labels: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in domain_labels.items():
            normalized_key = key.strip()
            normalized_value = value.strip()
            if not normalized_key or not normalized_value:
                raise ValueError("Tenant vocabulary domain keys and labels must not be blank.")
            if (
                len(normalized_key) > TENANT_VOCABULARY_LABEL_MAX_LENGTH
                or len(normalized_value) > TENANT_VOCABULARY_LABEL_MAX_LENGTH
            ):
                raise ValueError(
                    "Tenant vocabulary domain keys and labels must not exceed "
                    f"{TENANT_VOCABULARY_LABEL_MAX_LENGTH} characters."
                )
            if normalized_key in normalized:
                raise ValueError("Tenant vocabulary domain keys must be unique after trimming.")
            normalized[normalized_key] = normalized_value
        return normalized


class TenantVocabularyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1, max_length=AUDIT_ACTOR_ID_MAX_LENGTH)
    actor_scopes: list[str] = Field(default_factory=list)
    vocabulary: TenantVocabulary
    notes: list[str] = Field(default_factory=list)


class TenantRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = ""
    status: TenantLifecycleStatus
    created_by: str = Field(min_length=1)
    bootstrap_admin_actor_id: str | None = None
    provision_idempotency_key: str | None = None
    suspended_at: datetime | None = None
    suspended_by: str | None = None
    suspension_reason: str | None = None
    reactivated_at: datetime | None = None
    reactivated_by: str | None = None
    permission_decision: PermissionDecision | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    idempotent_replay: bool = False
    notes: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TenantRegistry(BaseModel):
    tenant_count: int = Field(ge=0)
    active_tenant_count: int = Field(ge=0)
    tenants: list[TenantRecord] = Field(default_factory=list)
    has_more: bool = False
    next_cursor: str | None = None
    tenant_notes: list[str] = Field(default_factory=list)


class TenantQuotaChange(BaseModel):
    quota_key: str = Field(min_length=1)
    previous_value: int | None = None
    new_value: int | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)


class TenantQuotaSet(BaseModel):
    tenant_id: str = Field(min_length=1)
    quotas: dict[str, int] = Field(default_factory=dict)
    changes: list[TenantQuotaChange] = Field(default_factory=list)
    quota_notes: list[str] = Field(default_factory=list)


class TenantVocabularyChange(BaseModel):
    previous_value: TenantVocabulary | None = None
    new_value: TenantVocabulary
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)


class TenantVocabularySet(BaseModel):
    tenant_id: str = Field(min_length=1)
    vocabulary: TenantVocabulary
    configured: bool
    changes: list[TenantVocabularyChange] = Field(default_factory=list)
    vocabulary_notes: list[str] = Field(default_factory=list)


_QUOTA_NOTES = [
    "Tenant quotas override the global configuration for this tenant only.",
    "api_requests_per_window overrides the global API rate limit on protected paths.",
    "max_concurrent_sessions overrides the global concurrent browser-session cap.",
    "max_connector_sync_rows_per_run caps governed live-sync row limits per run.",
    "Every quota change appends platform.tenant.quota.updated audit evidence.",
]
_VOCABULARY_NOTES = [
    "Industry-neutral defaults are returned until this tenant configures vocabulary.",
    "Every vocabulary change appends platform.tenant.vocabulary.updated audit evidence.",
]


def blocked_tenant_reason(status: str | None) -> str | None:
    """Return the fail-closed rejection reason for a non-active tenant status.

    Unknown tenants (no persisted row) return ``None``: only tenants explicitly
    moved out of the active status are blocked, so environments without seeded
    tenant rows keep their existing behavior.
    """
    return tenant_admission_denial_reason(
        status,
        admission_mode=TENANT_ADMISSION_CLAIMS_ONLY,
    )


def provision_tenant(
    repository: AxisPersistenceRepository,
    request: TenantProvisionRequest,
) -> TenantRecord:
    existing_replay = repository.get_tenant_by_provision_idempotency_key(request.idempotency_key)
    if existing_replay is not None:
        if not _provision_matches_request(repository, existing_replay, request):
            raise TenantProvisionConflict(request.tenant_id, "provision_idempotency_conflict")
        return _tenant_from_record(existing_replay, idempotent_replay=True)

    existing = repository.get_tenant(request.tenant_id)
    if existing is not None:
        raise TenantProvisionConflict(request.tenant_id, "tenant_already_exists")

    permission_decision = _evaluate_operator_permission(
        tenant_id=request.tenant_id,
        actor_id=request.requested_by,
        actor_scopes=request.actor_scopes,
        action_scope=REQUIRED_PROVISION_SCOPE,
        attributes={
            "operation": "provision_tenant",
            "idempotency_key": request.idempotency_key,
        },
    )
    bootstrap_admin = request.bootstrap_admin
    if bootstrap_admin is not None and repository.get_actor(bootstrap_admin.actor_id):
        raise TenantProvisionConflict(request.tenant_id, "bootstrap_admin_actor_exists")

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type=PROVISIONED_AUDIT_EVENT_TYPE,
            payload={
                "tenant_id": request.tenant_id,
                "display_name": request.display_name,
                "description": request.description,
                "status": TenantLifecycleStatus.ACTIVE.value,
                "idempotency_key": request.idempotency_key,
                "provision_notes": request.notes,
                "bootstrap_admin_actor_id": (bootstrap_admin.actor_id if bootstrap_admin else None),
                "bootstrap_admin_display_name": (
                    bootstrap_admin.display_name if bootstrap_admin else None
                ),
                # Scope grants stay IdP-owned; the requested bootstrap scopes are
                # recorded as audit evidence only, never as a live grant.
                "bootstrap_admin_requested_scopes": (
                    bootstrap_admin.scopes if bootstrap_admin else []
                ),
                "required_operator_scope": REQUIRED_OPERATOR_SCOPE,
                "required_provision_scope": REQUIRED_PROVISION_SCOPE,
                "permission_decision": permission_decision.model_dump(),
            },
        )
    )
    if bootstrap_admin is not None:
        repository.create_actor(
            ActorCreate(
                actor_id=bootstrap_admin.actor_id,
                tenant_id=request.tenant_id,
                display_name=bootstrap_admin.display_name,
                actor_type="human",
            )
        )
    tenant = repository.create_tenant(
        TenantCreate(
            tenant_id=request.tenant_id,
            display_name=request.display_name,
            description=request.description,
            status=TenantLifecycleStatus.ACTIVE.value,
            created_by=request.requested_by,
            bootstrap_admin_actor_id=(bootstrap_admin.actor_id if bootstrap_admin else None),
            provision_idempotency_key=request.idempotency_key,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            notes=request.notes,
        )
    )
    return _tenant_from_record(tenant, permission_decision=permission_decision)


def bootstrap_first_tenant(
    repository: AxisPersistenceRepository,
    request: TenantProvisionRequest,
) -> TenantRecord:
    """Provision the first tenant through a direct database authority.

    Production ``registered_only`` admission intentionally prevents an unknown
    OIDC tenant from calling the normal provisioning endpoint. Operators run the
    packaged bootstrap command once, after migrations, using the deployment's
    database credential. Competing commands serialize; an exact replay remains
    safe, while any later or different bootstrap must use the authenticated API.
    """

    repository.acquire_first_tenant_bootstrap_lock()
    existing = repository.list_tenants(limit=2)
    exact_replay_candidate = (
        len(existing) == 1
        and existing[0].id == request.tenant_id
        and existing[0].provision_idempotency_key == request.idempotency_key
    )
    if existing and (
        not exact_replay_candidate
        or not _has_valid_direct_bootstrap_evidence(repository, existing[0])
    ):
        raise TenantProvisionConflict(
            request.tenant_id,
            "tenant_registry_already_initialized",
        )
    result = provision_tenant(repository, request)
    if not result.idempotent_replay:
        repository.append_audit_event(
            AuditEventCreate(
                tenant_id=result.tenant_id,
                actor_id=request.requested_by,
                event_type=FIRST_TENANT_BOOTSTRAPPED_AUDIT_EVENT_TYPE,
                payload={
                    "tenant_id": result.tenant_id,
                    "authority": "direct_database",
                    "provision_audit_event_id": str(result.audit_event_id),
                    "idempotency_key": request.idempotency_key,
                },
            )
        )
    return result


def get_tenant_detail(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> TenantRecord:
    """Return a single tenant record, raising ``TenantNotFound`` when absent."""
    tenant = repository.get_tenant(tenant_id)
    if tenant is None:
        raise TenantNotFound()
    return _tenant_from_record(tenant)


def encode_tenant_cursor(record) -> str:
    """Keyset cursor for the tenant listing, ordered by ``tenant_id`` ascending.

    The tenant id is the primary key, so a single-column keyset is a total
    order and needs no tiebreaker, unlike the ``/identity/sessions`` keyset.
    """
    payload = {"tenant_id": record.id}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_tenant_cursor(cursor: str | None) -> str | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        tenant_id = str(payload["tenant_id"])
    except (
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise TenantListCursorError("invalid_tenant_cursor") from exc
    if not tenant_id:
        raise TenantListCursorError("invalid_tenant_cursor")
    return tenant_id


def build_tenant_registry(
    repository: AxisPersistenceRepository,
    status: TenantLifecycleStatus | None = None,
    limit: int = 100,
    cursor_tenant_id: str | None = None,
) -> TenantRegistry:
    # Over-fetch by one to detect a further page without a second count query,
    # matching the keyset precedent used by /identity/sessions.
    records = repository.list_tenants(
        status=status.value if status is not None else None,
        limit=limit + 1,
        cursor_tenant_id=cursor_tenant_id,
    )
    has_more = len(records) > limit
    page_records = records[:limit]
    tenants = [_tenant_from_record(record) for record in page_records]
    active_count = sum(1 for tenant in tenants if tenant.status == TenantLifecycleStatus.ACTIVE)
    next_cursor = encode_tenant_cursor(page_records[-1]) if has_more and page_records else None
    return TenantRegistry(
        tenant_count=len(tenants),
        active_tenant_count=active_count,
        tenants=tenants,
        has_more=has_more,
        next_cursor=next_cursor,
        tenant_notes=[
            "Tenant lifecycle is a platform-operator surface, not a tenant surface.",
            "Suspended and pending-deletion tenants are rejected fail-closed at the "
            "OIDC principal boundary.",
            "Lifecycle mutations append audit evidence in the target tenant's ledger "
            "with the operator recorded as actor.",
        ],
    )


def suspend_tenant(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    request: TenantSuspendRequest,
) -> TenantRecord:
    tenant = repository.get_tenant(tenant_id)
    if tenant is None:
        raise TenantNotFound()
    if tenant.status != TenantLifecycleStatus.ACTIVE.value:
        raise TenantLifecycleConflict(tenant_id, "tenant_not_active")

    permission_decision = _evaluate_operator_permission(
        tenant_id=tenant_id,
        actor_id=request.requested_by,
        actor_scopes=request.actor_scopes,
        action_scope=REQUIRED_SUSPEND_SCOPE,
        attributes={"operation": "suspend_tenant", "reason": request.reason},
    )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=request.requested_by,
            event_type=SUSPENDED_AUDIT_EVENT_TYPE,
            payload={
                "tenant_id": tenant_id,
                "previous_status": tenant.status,
                "status": TenantLifecycleStatus.SUSPENDED.value,
                "reason": request.reason,
                "required_operator_scope": REQUIRED_OPERATOR_SCOPE,
                "required_suspend_scope": REQUIRED_SUSPEND_SCOPE,
                "permission_decision": permission_decision.model_dump(),
            },
        )
    )
    updated = repository.update_tenant_lifecycle(
        TenantLifecycleTransition(
            tenant_id=tenant_id,
            status=TenantLifecycleStatus.SUSPENDED.value,
            actor_id=request.requested_by,
            reason=request.reason,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            notes=request.notes,
        )
    )
    return _tenant_from_record(updated, permission_decision=permission_decision)


def reactivate_tenant(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    request: TenantReactivateRequest,
) -> TenantRecord:
    tenant = repository.get_tenant(tenant_id)
    if tenant is None:
        raise TenantNotFound()
    if tenant.status == TenantLifecycleStatus.ACTIVE.value:
        raise TenantLifecycleConflict(tenant_id, "tenant_already_active")

    permission_decision = _evaluate_operator_permission(
        tenant_id=tenant_id,
        actor_id=request.requested_by,
        actor_scopes=request.actor_scopes,
        action_scope=REQUIRED_SUSPEND_SCOPE,
        attributes={"operation": "reactivate_tenant", "reason": request.reason},
    )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=request.requested_by,
            event_type=REACTIVATED_AUDIT_EVENT_TYPE,
            payload={
                "tenant_id": tenant_id,
                "previous_status": tenant.status,
                "status": TenantLifecycleStatus.ACTIVE.value,
                "reason": request.reason,
                "required_operator_scope": REQUIRED_OPERATOR_SCOPE,
                "required_suspend_scope": REQUIRED_SUSPEND_SCOPE,
                "permission_decision": permission_decision.model_dump(),
            },
        )
    )
    updated = repository.update_tenant_lifecycle(
        TenantLifecycleTransition(
            tenant_id=tenant_id,
            status=TenantLifecycleStatus.ACTIVE.value,
            actor_id=request.requested_by,
            reason=request.reason or None,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            notes=request.notes,
        )
    )
    return _tenant_from_record(updated, permission_decision=permission_decision)


def get_tenant_quota_set(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> TenantQuotaSet:
    if repository.get_tenant(tenant_id) is None:
        raise TenantNotFound()
    quotas = {
        quota.quota_key: quota.quota_value for quota in repository.list_tenant_quotas(tenant_id)
    }
    return TenantQuotaSet(tenant_id=tenant_id, quotas=quotas, quota_notes=_QUOTA_NOTES)


def update_tenant_quotas(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    request: TenantQuotaUpdateRequest,
) -> TenantQuotaSet:
    """Replace the tenant quota set with the requested typed values.

    ``PUT`` semantics are full replacement over the typed quota keys: a key set
    to a value is upserted in place, a key left ``None`` is cleared. Quota rows
    are update-in-place; the append-only history lives in the
    ``platform.tenant.quota.updated`` audit trail written for every change.
    """
    tenant = repository.get_tenant(tenant_id)
    if tenant is None:
        raise TenantNotFound()

    permission_decision = _evaluate_operator_permission(
        tenant_id=tenant_id,
        actor_id=request.requested_by,
        actor_scopes=request.actor_scopes,
        action_scope=REQUIRED_QUOTA_SCOPE,
        attributes={"operation": "update_tenant_quotas"},
    )
    changes: list[TenantQuotaChange] = []
    for quota_key, new_value in request.quotas.as_mapping().items():
        existing = repository.get_tenant_quota(tenant_id, quota_key)
        previous_value = existing.quota_value if existing is not None else None
        if new_value == previous_value:
            continue
        audit_event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=tenant_id,
                actor_id=request.requested_by,
                event_type=QUOTA_UPDATED_AUDIT_EVENT_TYPE,
                payload={
                    "tenant_id": tenant_id,
                    "quota_key": quota_key,
                    "previous_value": previous_value,
                    "new_value": new_value,
                    "required_operator_scope": REQUIRED_OPERATOR_SCOPE,
                    "required_quota_scope": REQUIRED_QUOTA_SCOPE,
                    "permission_decision": permission_decision.model_dump(),
                },
            )
        )
        if new_value is None:
            repository.delete_tenant_quota(tenant_id, quota_key)
        else:
            repository.upsert_tenant_quota(
                TenantQuotaUpsert(
                    tenant_id=tenant_id,
                    quota_key=quota_key,
                    quota_value=new_value,
                    updated_by=request.requested_by,
                    audit_event_id=audit_event.id,
                    audit_event_type=audit_event.event_type,
                    notes=request.notes,
                )
            )
        changes.append(
            TenantQuotaChange(
                quota_key=quota_key,
                previous_value=previous_value,
                new_value=new_value,
                audit_event_id=audit_event.id,
                audit_event_type=audit_event.event_type,
            )
        )
    quotas = {
        quota.quota_key: quota.quota_value for quota in repository.list_tenant_quotas(tenant_id)
    }
    return TenantQuotaSet(
        tenant_id=tenant_id,
        quotas=quotas,
        changes=changes,
        quota_notes=_QUOTA_NOTES,
    )


def get_tenant_vocabulary(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> TenantVocabularySet:
    tenant = repository.get_tenant(tenant_id)
    if tenant is None:
        raise TenantNotFound()
    configured = tenant.vocabulary is not None
    vocabulary = (
        TenantVocabulary.model_validate(tenant.vocabulary) if configured else TenantVocabulary()
    )
    return TenantVocabularySet(
        tenant_id=tenant_id,
        vocabulary=vocabulary,
        configured=configured,
        vocabulary_notes=_VOCABULARY_NOTES,
    )


def update_tenant_vocabulary(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    request: TenantVocabularyUpdateRequest,
) -> TenantVocabularySet:
    tenant = repository.get_tenant(tenant_id)
    if tenant is None:
        raise TenantNotFound()

    permission_decision = _evaluate_operator_permission(
        tenant_id=tenant_id,
        actor_id=request.requested_by,
        actor_scopes=request.actor_scopes,
        action_scope=REQUIRED_CONFIGURE_SCOPE,
        attributes={"operation": "update_tenant_vocabulary"},
    )
    previous_value = (
        TenantVocabulary.model_validate(tenant.vocabulary)
        if tenant.vocabulary is not None
        else None
    )
    if previous_value == request.vocabulary:
        return TenantVocabularySet(
            tenant_id=tenant_id,
            vocabulary=request.vocabulary,
            configured=True,
            vocabulary_notes=_VOCABULARY_NOTES,
        )

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=request.requested_by,
            event_type=VOCABULARY_UPDATED_AUDIT_EVENT_TYPE,
            payload={
                "tenant_id": tenant_id,
                "previous_value": (
                    previous_value.model_dump() if previous_value is not None else None
                ),
                "new_value": request.vocabulary.model_dump(),
                "required_operator_scope": REQUIRED_OPERATOR_SCOPE,
                "required_configure_scope": REQUIRED_CONFIGURE_SCOPE,
                "permission_decision": permission_decision.model_dump(),
            },
        )
    )
    repository.update_tenant_vocabulary(
        tenant_id,
        request.vocabulary.model_dump(),
    )
    return TenantVocabularySet(
        tenant_id=tenant_id,
        vocabulary=request.vocabulary,
        configured=True,
        changes=[
            TenantVocabularyChange(
                previous_value=previous_value,
                new_value=request.vocabulary,
                audit_event_id=audit_event.id,
                audit_event_type=audit_event.event_type,
            )
        ],
        vocabulary_notes=_VOCABULARY_NOTES,
    )


@dataclass(frozen=True)
class TenantStateSnapshot:
    status: str | None
    quotas: dict[str, int]


@dataclass
class _TenantStateCacheEntry:
    snapshot: TenantStateSnapshot
    expires_at: float


class TenantStateCache:
    """Bounded in-process cache for tenant status and quota lookups.

    The suspension check and the per-tenant rate limit run on the hot request
    path, so lookups are cached for a short TTL. The staleness window equals the
    TTL: a suspension or quota change on another replica (or another process)
    takes effect here within at most ``ttl_seconds``. Lifecycle and quota routes
    invalidate the local entry immediately, so single-process deployments see
    changes at once. A TTL of 0 disables caching and reads fresh state on every
    request.
    """

    def __init__(self, *, ttl_seconds: float, max_entries: int = 1024) -> None:
        self.ttl_seconds = max(0.0, ttl_seconds)
        self.max_entries = max(1, max_entries)
        self._entries: dict[str, _TenantStateCacheEntry] = {}

    def snapshot(
        self,
        session_factory: sessionmaker[Session],
        tenant_id: str,
        *,
        now: float | None = None,
    ) -> TenantStateSnapshot:
        observed_at = now if now is not None else time.monotonic()
        entry = self._entries.get(tenant_id)
        if entry is not None and observed_at < entry.expires_at:
            return entry.snapshot

        with session_scope(session_factory) as session:
            repository = AxisPersistenceRepository(session)
            tenant = repository.get_tenant(tenant_id)
            quotas = {
                quota.quota_key: quota.quota_value
                for quota in repository.list_tenant_quotas(tenant_id)
            }
            snapshot = TenantStateSnapshot(
                status=tenant.status if tenant is not None else None,
                quotas=quotas,
            )
        if self.ttl_seconds > 0:
            while len(self._entries) >= self.max_entries:
                self._entries.pop(next(iter(self._entries)))
            self._entries[tenant_id] = _TenantStateCacheEntry(
                snapshot=snapshot,
                expires_at=observed_at + self.ttl_seconds,
            )
        return snapshot

    def invalidate(self, tenant_id: str) -> None:
        self._entries.pop(tenant_id, None)


def _provision_matches_request(
    repository: AxisPersistenceRepository,
    record: Tenant,
    request: TenantProvisionRequest,
) -> bool:
    bootstrap_actor_id = request.bootstrap_admin.actor_id if request.bootstrap_admin else None
    base_fields_match = (
        record.id == request.tenant_id
        and record.name == request.display_name
        and record.description == request.description
        and record.bootstrap_admin_actor_id == bootstrap_actor_id
        and record.created_by == request.requested_by
    )
    if not base_fields_match:
        return False
    audit_event = _valid_provision_audit_event(repository, record)
    if audit_event is None:
        return False
    audited_description = audit_event.payload.get("description", record.description)
    notes_are_verifiable, audited_notes = _audited_provision_notes(record, audit_event)
    if audited_description != request.description:
        return False
    if not notes_are_verifiable or audited_notes != request.notes:
        return False
    if request.bootstrap_admin is None:
        return True

    audited_admin_name = audit_event.payload.get("bootstrap_admin_display_name")
    if audited_admin_name is None:
        # Compatibility for tenants provisioned before the display name was
        # copied into audit evidence. Actor identity is immutable in this slice.
        actor = repository.get_actor(request.bootstrap_admin.actor_id)
        audited_admin_name = actor.display_name if actor is not None else None
    return (
        audited_admin_name == request.bootstrap_admin.display_name
        and audit_event.payload.get("bootstrap_admin_requested_scopes")
        == request.bootstrap_admin.scopes
    )


def _valid_provision_audit_event(
    repository: AxisPersistenceRepository,
    record: Tenant,
) -> AuditEvent | None:
    """Return the tenant's sole internally consistent provisioning event."""

    audit_events = repository.list_audit_events(
        record.id,
        event_type=PROVISIONED_AUDIT_EVENT_TYPE,
        limit=2,
    )
    if len(audit_events) != 1:
        return None
    audit_event = audit_events[0]
    payload = audit_event.payload
    if not isinstance(payload, dict):
        return None
    audited_description = payload.get("description", record.description)
    if "provision_notes" in payload:
        audited_notes = payload["provision_notes"]
        if (
            not isinstance(audited_notes, list)
            or record.notes[: len(audited_notes)] != audited_notes
        ):
            return None
    if not (
        audit_event.actor_id == record.created_by
        and payload.get("tenant_id") == record.id
        and payload.get("display_name") == record.name
        and audited_description == record.description
        and payload.get("status") == TenantLifecycleStatus.ACTIVE.value
        and payload.get("idempotency_key") == record.provision_idempotency_key
        and payload.get("bootstrap_admin_actor_id") == record.bootstrap_admin_actor_id
    ):
        return None
    return audit_event


def _audited_provision_notes(
    record: Tenant,
    audit_event: AuditEvent,
) -> tuple[bool, list[str]]:
    """Return whether original provisioning notes remain exactly provable."""

    payload = audit_event.payload
    if "provision_notes" in payload:
        notes = payload["provision_notes"]
        return (True, notes) if isinstance(notes, list) else (False, [])
    # Older events did not copy notes into immutable evidence. The tenant row
    # remains authoritative only until a lifecycle transition replaces its
    # latest-event pointer and may append unrelated notes.
    if (
        record.audit_event_id == audit_event.id
        and record.audit_event_type == PROVISIONED_AUDIT_EVENT_TYPE
    ):
        return True, record.notes
    return False, []


def _has_valid_direct_bootstrap_evidence(
    repository: AxisPersistenceRepository,
    record: Tenant,
) -> bool:
    """Verify that the sole tenant was created by the out-of-band authority."""

    provision_event = _valid_provision_audit_event(repository, record)
    if provision_event is None:
        return False
    bootstrap_events = repository.list_audit_events(
        record.id,
        event_type=FIRST_TENANT_BOOTSTRAPPED_AUDIT_EVENT_TYPE,
        limit=2,
    )
    if len(bootstrap_events) != 1:
        return False
    bootstrap_event = bootstrap_events[0]
    payload = bootstrap_event.payload
    if not isinstance(payload, dict):
        return False
    return (
        bootstrap_event.actor_id == provision_event.actor_id
        and payload.get("tenant_id") == record.id
        and payload.get("authority") == "direct_database"
        and payload.get("provision_audit_event_id") == str(provision_event.id)
        and payload.get("idempotency_key") == record.provision_idempotency_key
    )


def _evaluate_operator_permission(
    *,
    tenant_id: str,
    actor_id: str,
    actor_scopes: list[str],
    action_scope: str,
    attributes: dict,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_scopes=actor_scopes,
            required_scopes=[REQUIRED_OPERATOR_SCOPE, action_scope],
            attributes={
                "surface": "platform_tenants",
                **attributes,
            },
        )
    )
    if not decision.allowed:
        required_permission = decision.reason.removeprefix("missing_scope:")
        if required_permission == decision.reason:
            required_permission = action_scope
        raise TenantPermissionDenied(required_permission, decision)
    return decision


def _tenant_from_record(
    record,
    *,
    permission_decision: PermissionDecision | None = None,
    idempotent_replay: bool = False,
) -> TenantRecord:
    return TenantRecord(
        tenant_id=record.id,
        display_name=record.name,
        description=record.description,
        status=TenantLifecycleStatus(record.status),
        created_by=record.created_by,
        bootstrap_admin_actor_id=record.bootstrap_admin_actor_id,
        provision_idempotency_key=record.provision_idempotency_key,
        suspended_at=record.suspended_at,
        suspended_by=record.suspended_by,
        suspension_reason=record.suspension_reason,
        reactivated_at=record.reactivated_at,
        reactivated_by=record.reactivated_by,
        permission_decision=permission_decision,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        idempotent_replay=idempotent_replay,
        notes=list(record.notes),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
