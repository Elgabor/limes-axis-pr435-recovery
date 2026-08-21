"""Endpoint specifications for the governed Axis REST surface.

Each function builds the ``RequestSpec`` and names the response model for
one API route. The sync and async resource clients both delegate here, so
paths, parameters and idempotency semantics are defined exactly once and
mirror the committed OpenAPI artifact.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from pydantic import BaseModel

from axis_sdk import models
from axis_sdk._transport import RequestSpec
from axis_sdk.models import ApprovalDecision

OPERATIONS_PREFIX = "/operations"
DEMO_PREFIX = "/demo/manufacturing"

Endpoint = tuple[RequestSpec, type[BaseModel]]


def _path(template: str, **segments: str) -> str:
    return template.format(**{key: quote(value, safe="") for key, value in segments.items()})


# --- System ---------------------------------------------------------------


def health() -> Endpoint:
    return RequestSpec("GET", "/health", idempotent=True), models.HealthStatus


def ready() -> Endpoint:
    return RequestSpec("GET", "/ready", idempotent=True), models.ReadinessStatus


def deployment_readiness() -> Endpoint:
    return (
        RequestSpec("GET", "/deployment/readiness", idempotent=True),
        models.DeploymentReadinessReport,
    )


# --- Approvals --------------------------------------------------------------


def list_approvals(tenant_id: str | None = None) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            f"{OPERATIONS_PREFIX}/approvals",
            params={"tenant_id": tenant_id},
            tenant_scoped=True,
            idempotent=True,
        ),
        models.ApprovalInbox,
    )


def decide_approval(
    approval_id: str,
    *,
    decision: ApprovalDecision | str,
    actor_id: str,
    actor_scopes: list[str] | None = None,
    note: str | None = None,
) -> Endpoint:
    body: dict[str, Any] = {
        "decision": str(decision),
        "actor_id": actor_id,
        "actor_scopes": actor_scopes or [],
    }
    if note is not None:
        body["note"] = note
    return (
        RequestSpec(
            "POST",
            _path(
                f"{OPERATIONS_PREFIX}/approvals/{{approval_id}}/decision",
                approval_id=approval_id,
            ),
            json_body=body,
        ),
        models.ApprovalDecisionResult,
    )


# --- Actions ----------------------------------------------------------------


def action_catalog(tenant_id: str | None = None) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            f"{OPERATIONS_PREFIX}/actions",
            params={"tenant_id": tenant_id},
            tenant_scoped=True,
            idempotent=True,
        ),
        models.ActionRegistry,
    )


def create_action_run(
    action_id: str,
    *,
    actor_id: str,
    payload: dict[str, Any],
    actor_scopes: list[str] | None = None,
    idempotency_key: str | None = None,
) -> Endpoint:
    body: dict[str, Any] = {
        "actor_id": actor_id,
        "actor_scopes": actor_scopes or [],
        "payload": payload,
    }
    if idempotency_key is not None:
        body["idempotency_key"] = idempotency_key
    return (
        RequestSpec(
            "POST",
            _path(f"{OPERATIONS_PREFIX}/actions/{{action_id}}/runs", action_id=action_id),
            json_body=body,
            # Idempotency-keyed creates replay the persisted run, so they
            # are safe to retry; keyless creates are not.
            idempotent=idempotency_key is not None,
        ),
        models.ActionRunResult,
    )


def record_action_run_outcome(
    action_run_id: str,
    *,
    actor_id: str,
    status: str,
    result_summary: str,
    idempotency_key: str,
    evidence_refs: list[str],
    actor_scopes: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
    external_mutation_started: bool = False,
) -> Endpoint:
    body: dict[str, Any] = {
        "actor_id": actor_id,
        "actor_scopes": actor_scopes or [],
        "idempotency_key": idempotency_key,
        "status": status,
        "result_summary": result_summary,
        # The API requires at least one evidence reference per outcome.
        "evidence_refs": evidence_refs,
        "metrics": metrics or {},
        "external_mutation_started": external_mutation_started,
    }
    return (
        RequestSpec(
            "POST",
            _path(
                f"{OPERATIONS_PREFIX}/actions/runs/{{action_run_id}}/outcome",
                action_run_id=action_run_id,
            ),
            json_body=body,
            idempotent=True,
        ),
        models.ActionRunOutcomeResult,
    )


# --- Workflows --------------------------------------------------------------


def workflow_console(tenant_id: str | None = None) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            f"{OPERATIONS_PREFIX}/workflows",
            params={"tenant_id": tenant_id},
            tenant_scoped=True,
            idempotent=True,
        ),
        models.WorkflowConsole,
    )


def list_workflow_runs(
    tenant_id: str | None = None,
    *,
    state: str | None = None,
    limit: int | None = None,
) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            f"{OPERATIONS_PREFIX}/workflows/runs",
            params={"tenant_id": tenant_id, "state": state, "limit": limit},
            tenant_scoped=True,
            idempotent=True,
        ),
        models.WorkflowConsole,
    )


# --- Audit ------------------------------------------------------------------


def audit_explorer(tenant_id: str | None = None) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            f"{OPERATIONS_PREFIX}/audit",
            params={"tenant_id": tenant_id},
            tenant_scoped=True,
            idempotent=True,
        ),
        models.AuditExplorer,
    )


def query_audit_events(
    tenant_id: str | None = None,
    *,
    event_type: str | None = None,
    actor_id: str | None = None,
    scope: str | None = None,
    limit: int | None = None,
) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            f"{OPERATIONS_PREFIX}/audit/events",
            params={
                "tenant_id": tenant_id,
                "event_type": event_type,
                "actor_id": actor_id,
                "scope": scope,
                "limit": limit,
            },
            tenant_scoped=True,
            idempotent=True,
        ),
        models.AuditExplorer,
    )


def export_audit_events(
    tenant_id: str | None = None,
    *,
    event_type: str | None = None,
    actor_id: str | None = None,
    scope: str | None = None,
    limit: int | None = None,
    export_reason: str | None = None,
    retention_days: int | None = None,
    legal_hold: bool | None = None,
) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            f"{OPERATIONS_PREFIX}/audit/export",
            params={
                "tenant_id": tenant_id,
                "event_type": event_type,
                "actor_id": actor_id,
                "scope": scope,
                "limit": limit,
                "export_reason": export_reason,
                "retention_days": retention_days,
                "legal_hold": legal_hold,
            },
            tenant_scoped=True,
            idempotent=True,
        ),
        models.AuditExportBundle,
    )


# --- Ontology ---------------------------------------------------------------


def ontology_graph(tenant_id: str | None = None, *, limit: int | None = None) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            f"{OPERATIONS_PREFIX}/ontology",
            params={"tenant_id": tenant_id, "limit": limit},
            tenant_scoped=True,
            idempotent=True,
        ),
        models.OntologyGraph,
    )


def ontology_entity(node_id: str, tenant_id: str | None = None) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            _path(f"{OPERATIONS_PREFIX}/ontology/entities/{{node_id}}", node_id=node_id),
            params={"tenant_id": tenant_id},
            tenant_scoped=True,
            idempotent=True,
        ),
        models.OntologyEntityDetail,
    )


# --- Agents -----------------------------------------------------------------


def agent_registry(tenant_id: str | None = None) -> Endpoint:
    return (
        RequestSpec(
            "GET",
            f"{OPERATIONS_PREFIX}/agents",
            params={"tenant_id": tenant_id},
            tenant_scoped=True,
            idempotent=True,
        ),
        models.AgentRegistry,
    )
