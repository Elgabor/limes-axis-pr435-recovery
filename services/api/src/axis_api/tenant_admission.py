"""Pure tenant-admission policy shared by identity and lifecycle boundaries.

Local/demo deployments retain the historical ``claims_only`` behavior: a
verified identity-provider tenant claim does not require a persisted tenant
row. Production deployments use ``registered_only`` so provisioning and
lifecycle state remain the authoritative admission boundary.
"""

from __future__ import annotations

TENANT_ADMISSION_CLAIMS_ONLY = "claims_only"
TENANT_ADMISSION_REGISTERED_ONLY = "registered_only"
TENANT_NOT_REGISTERED_REASON = "tenant_not_registered"
TENANT_STATUS_NOT_ACTIVE_REASON = "tenant_status_not_active"

SUSPENDED_REQUEST_DENIED_AUDIT_EVENT_TYPE = (
    "platform.tenant.suspended_request.denied"
)
UNREGISTERED_REQUEST_DENIED_AUDIT_EVENT_TYPE = (
    "platform.tenant.unregistered_request.denied"
)

_SUPPORTED_ADMISSION_MODES = frozenset(
    {TENANT_ADMISSION_CLAIMS_ONLY, TENANT_ADMISSION_REGISTERED_ONLY}
)
_BLOCKED_STATUS_REASONS = {
    "suspended": "tenant_suspended",
    "pending_deletion": "tenant_pending_deletion",
}


def tenant_admission_denial_reason(
    status: str | None,
    *,
    admission_mode: str,
) -> str | None:
    """Return the public-safe reason that a tenant principal must be denied."""

    normalized_mode = admission_mode.strip().casefold()
    if normalized_mode not in _SUPPORTED_ADMISSION_MODES:
        raise ValueError(f"Unsupported tenant admission mode: {admission_mode}")
    if status is None:
        return (
            TENANT_NOT_REGISTERED_REASON
            if normalized_mode == TENANT_ADMISSION_REGISTERED_ONLY
            else None
        )
    if status == "active":
        return None
    # Lifecycle state is an allowlist boundary. A corrupt or future status must
    # not become an accidental admission path before its semantics are defined.
    return _BLOCKED_STATUS_REASONS.get(status, TENANT_STATUS_NOT_ACTIVE_REASON)


def tenant_admission_denial_audit_event_type(reason: str) -> str:
    """Map a denial reason to its stable append-only audit event type."""

    if reason == TENANT_NOT_REGISTERED_REASON:
        return UNREGISTERED_REQUEST_DENIED_AUDIT_EVENT_TYPE
    return SUSPENDED_REQUEST_DENIED_AUDIT_EVENT_TYPE
