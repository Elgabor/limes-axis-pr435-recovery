import pytest

from axis_api.identity import OidcPrincipal
from axis_api.permissions import (
    TENANT_MISMATCH_REASON,
    PermissionDecision,
    PermissionRequest,
    ScopeAuthorizationError,
    authorize_principal_scopes,
    evaluate_permission,
)


def test_permission_denied_without_required_scope() -> None:
    request = PermissionRequest(
        tenant_id="tenant_demo",
        actor_id="actor_quality",
        actor_scopes=["quality:read"],
        required_scopes=["quality:write"],
        attributes={"risk_level": "medium"},
    )
    decision = evaluate_permission(request)
    assert decision == PermissionDecision(
        allowed=False,
        reason="missing_scope:quality:write",
    )


def test_permission_allows_actor_with_required_scope() -> None:
    request = PermissionRequest(
        tenant_id="tenant_demo",
        actor_id="actor_quality",
        actor_scopes=["quality:read", "quality:write"],
        required_scopes=["quality:write"],
        attributes={"risk_level": "low"},
    )
    decision = evaluate_permission(request)
    assert decision.allowed is True


def test_permission_denies_missing_relationship_scope_after_action_scopes_pass() -> None:
    request = PermissionRequest(
        tenant_id="tenant_demo",
        actor_id="agent_supply_risk",
        actor_scopes=["supply:read", "approvals:supply:request"],
        required_scopes=["supply:read", "approvals:supply:request"],
        relationship_scopes=["quality:read"],
        attributes={
            "action_id": "request_supplier_expedite",
            "resource_refs": ["asset_batch_q_1842"],
        },
    )

    decision = evaluate_permission(request)

    assert decision == PermissionDecision(
        allowed=False,
        reason="missing_relationship_scope:quality:read",
    )


def _principal(
    tenant: str = "tenant_demo",
    actor: str = "operator",
    scopes: list[str] | None = None,
) -> OidcPrincipal:
    return OidcPrincipal(actor_id=actor, tenant_id=tenant, scopes=scopes or [])


def test_authorize_principal_scopes_allows_unauthenticated_demo_traffic() -> None:
    decision = authorize_principal_scopes(
        tenant_id="tenant_demo",
        principal=None,
        required_scopes=["quality:read"],
        attributes={"surface": "demo"},
        message="denied",
    )

    assert decision.allowed is True
    assert decision.reason == "unauthenticated_demo_allowed"


def test_authorize_principal_scopes_evaluates_fallback_scopes_without_principal() -> None:
    with pytest.raises(ScopeAuthorizationError) as excinfo:
        authorize_principal_scopes(
            tenant_id="tenant_demo",
            principal=None,
            required_scopes=["connectors:sync:checkpoint:read"],
            attributes={"surface": "connectors"},
            message="The actor cannot read connector sync checkpoints.",
            actor_fallback_id="anonymous-operator",
            scope_fallback=["wrong:scope"],
        )

    assert excinfo.value.decision.reason == "missing_scope:connectors:sync:checkpoint:read"
    assert excinfo.value.required_scopes == ["connectors:sync:checkpoint:read"]


def test_authorize_principal_scopes_binds_verified_tenant_fail_closed() -> None:
    with pytest.raises(ScopeAuthorizationError) as excinfo:
        authorize_principal_scopes(
            tenant_id="tenant_demo",
            principal=_principal(
                tenant="tenant_other",
                scopes=["quality:read"],
            ),
            required_scopes=["quality:read"],
            attributes={"surface": "audit"},
            message="cross-tenant",
        )

    assert excinfo.value.decision.reason == TENANT_MISMATCH_REASON


def test_authorize_principal_scopes_cross_tenant_surface_skips_binding() -> None:
    decision = authorize_principal_scopes(
        tenant_id="tenant_operator_home",
        principal=_principal(
            tenant="tenant_operator_home",
            scopes=["platform:tenants:read"],
        ),
        required_scopes=["platform:tenants:read"],
        attributes={"surface": "platform_tenants"},
        message="denied",
        bind_tenant=False,
    )

    assert decision.allowed is True


def test_authorize_principal_scopes_requires_every_scope() -> None:
    with pytest.raises(ScopeAuthorizationError) as excinfo:
        authorize_principal_scopes(
            tenant_id="tenant_demo",
            principal=_principal(scopes=["platform:tenants:operate"]),
            required_scopes=["platform:tenants:operate", "platform:tenant:usage"],
            attributes={"surface": "platform_tenant_usage"},
            message="denied",
        )

    assert excinfo.value.decision.reason == "missing_scope:platform:tenant:usage"
