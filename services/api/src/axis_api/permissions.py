from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, Field


class PermissionRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    actor_scopes: list[str]
    required_scopes: list[str]
    relationship_scopes: list[str] = Field(default_factory=list)
    attributes: dict


class PermissionDecision(BaseModel):
    allowed: bool
    reason: str


def evaluate_permission(request: PermissionRequest) -> PermissionDecision:
    actor_scopes = set(request.actor_scopes)
    for scope in request.required_scopes:
        if scope not in actor_scopes:
            return PermissionDecision(allowed=False, reason=f"missing_scope:{scope}")
    for scope in request.relationship_scopes:
        if scope not in actor_scopes:
            return PermissionDecision(
                allowed=False,
                reason=f"missing_relationship_scope:{scope}",
            )
    return PermissionDecision(allowed=True, reason="allowed")


TENANT_MISMATCH_REASON = "tenant_mismatch"


class ScopePrincipal(Protocol):
    """The verified identity surface scope checks consume."""

    @property
    def tenant_id(self) -> str: ...

    @property
    def actor_id(self) -> str: ...

    @property
    def scopes(self) -> list[str]: ...


class ScopeAuthorizationError(PermissionError):
    """A governed read/write whose required scopes are not satisfied.

    ``decision.reason`` distinguishes a cross-tenant attempt
    (``tenant_mismatch``) from a missing grant (``missing_scope:<scope>``);
    callers map both to their own transport-specific denial shape.
    """

    def __init__(
        self,
        *,
        decision: PermissionDecision,
        required_scopes: Sequence[str],
        message: str,
    ) -> None:
        super().__init__(message)
        self.decision = decision
        self.required_scopes = list(required_scopes)
        self.message = message


def authorize_principal_scopes(
    *,
    tenant_id: str,
    principal: ScopePrincipal | None,
    required_scopes: Sequence[str],
    attributes: dict,
    message: str,
    tenant_mismatch_message: str = "The authenticated OIDC tenant cannot access this tenant scope.",
    actor_fallback_id: str | None = None,
    scope_fallback: Sequence[str] | None = None,
    bind_tenant: bool = True,
) -> PermissionDecision:
    """Evaluate required scopes for one tenant-scoped operation.

    One contract for every governed read/write gate:

    - With no principal and no fallback, unauthenticated demo traffic is
      allowed through (the route's demo-mode convention).
    - With no principal but a declared fallback (body-supplied actor/scopes),
      the evaluation runs against that fallback so anonymous demo writes still
      need the same grants.
    - A verified principal bound to another tenant fails closed when
      ``bind_tenant`` is set; cross-tenant operator surfaces pass
      ``bind_tenant=False`` and rely purely on dedicated operator scopes.
    """
    if principal is not None:
        if bind_tenant and principal.tenant_id != tenant_id:
            raise ScopeAuthorizationError(
                decision=PermissionDecision(
                    allowed=False,
                    reason=TENANT_MISMATCH_REASON,
                ),
                required_scopes=required_scopes,
                message=tenant_mismatch_message,
            )
        actor_id = principal.actor_id
        actor_scopes = principal.scopes
    elif scope_fallback is not None:
        actor_id = actor_fallback_id or "anonymous-operator"
        actor_scopes = list(scope_fallback)
    else:
        return PermissionDecision(allowed=True, reason="unauthenticated_demo_allowed")

    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_scopes=actor_scopes,
            required_scopes=list(required_scopes),
            attributes=attributes,
        )
    )
    if not decision.allowed:
        raise ScopeAuthorizationError(
            decision=decision,
            required_scopes=required_scopes,
            message=message,
        )
    return decision
