"""Tenant-scoped bootstrap of the manufacturing demo scenario.

The canonical scenario payloads are seeded into ``demo_reference_records`` for
``tenant_demo_manufacturing`` by the Alembic bootstrap migrations (0022-0030).
This module copies those persisted canonical records into another tenant so
the console can offer an "explore with demo data" switch without duplicating
fixture data in the API: the source of truth stays the persisted bootstrap
rows, with every tenant identifier rewritten to the target tenant.

A successful bootstrap also persists a tenant-scoped marker record (surface
``bootstrap``) that carries the record view returned to clients; re-posting
for an already-bootstrapped tenant returns that stored record with
``idempotent_replay`` semantics and never duplicates scenario records.
"""

from copy import deepcopy
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from axis_api.action_reference import (
    ACTION_REGISTRY_SURFACE,
    MANUFACTURING_ACTION_REGISTRY_REFERENCE_ID,
)
from axis_api.agent_reference import (
    AGENT_REGISTRY_SURFACE,
    MANUFACTURING_AGENT_REGISTRY_REFERENCE_ID,
)
from axis_api.approval_reference import (
    APPROVAL_INBOX_SURFACE,
    MANUFACTURING_APPROVAL_INBOX_REFERENCE_ID,
)
from axis_api.audit import AuditEventCreate
from axis_api.audit_reference import (
    AUDIT_EXPLORER_SURFACE,
    MANUFACTURING_AUDIT_EXPLORER_REFERENCE_ID,
)
from axis_api.connector_reference import (
    CONNECTOR_REGISTRY_SURFACE,
    MANUFACTURING_CONNECTOR_REGISTRY_REFERENCE_ID,
)
from axis_api.demo_reference import (
    MANUFACTURING_OVERVIEW_REFERENCE_ID,
    OVERVIEW_SURFACE,
)
from axis_api.model_routing_reference import (
    MANUFACTURING_MODEL_ROUTING_REFERENCE_ID,
    MODEL_ROUTING_SURFACE,
)
from axis_api.ontology_reference import (
    MANUFACTURING_ONTOLOGY_REFERENCE_ID,
    ONTOLOGY_SURFACE,
)
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    AxisPersistenceRepository,
    DemoReferenceRecordCreate,
    TenantCreate,
)
from axis_api.workflow_reference import (
    MANUFACTURING_WORKFLOW_CONSOLE_REFERENCE_ID,
    WORKFLOW_CONSOLE_SURFACE,
)

CANONICAL_DEMO_TENANT_ID = "tenant_demo_manufacturing"
DEMO_BOOTSTRAP_SCOPE = "demo:scenario:bootstrap"
DEMO_BOOTSTRAP_AUDIT_EVENT_TYPE = "demo.scenario.bootstrapped"
DEMO_BOOTSTRAP_TENANT_AUDIT_EVENT_TYPE = "platform.tenant.bootstrapped"
DEMO_BOOTSTRAP_SURFACE = "bootstrap"
DEMO_BOOTSTRAP_REFERENCE_ID = "manufacturing-demo-bootstrap"
DEMO_BOOTSTRAP_RECORD_SOURCE = "demo-bootstrap"

# Every scenario surface persisted by the Alembic bootstrap migrations. The
# overview record is the scenario anchor and must exist on the canonical
# tenant; the remaining surfaces are copied when present.
BOOTSTRAP_SURFACES: tuple[tuple[str, str], ...] = (
    (OVERVIEW_SURFACE, MANUFACTURING_OVERVIEW_REFERENCE_ID),
    (CONNECTOR_REGISTRY_SURFACE, MANUFACTURING_CONNECTOR_REGISTRY_REFERENCE_ID),
    (AGENT_REGISTRY_SURFACE, MANUFACTURING_AGENT_REGISTRY_REFERENCE_ID),
    (ACTION_REGISTRY_SURFACE, MANUFACTURING_ACTION_REGISTRY_REFERENCE_ID),
    (WORKFLOW_CONSOLE_SURFACE, MANUFACTURING_WORKFLOW_CONSOLE_REFERENCE_ID),
    (APPROVAL_INBOX_SURFACE, MANUFACTURING_APPROVAL_INBOX_REFERENCE_ID),
    (AUDIT_EXPLORER_SURFACE, MANUFACTURING_AUDIT_EXPLORER_REFERENCE_ID),
    (MODEL_ROUTING_SURFACE, MANUFACTURING_MODEL_ROUTING_REFERENCE_ID),
    (ONTOLOGY_SURFACE, MANUFACTURING_ONTOLOGY_REFERENCE_ID),
)


class DemoBootstrapPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__("Demo scenario bootstrap permission denied")
        self.required_permission = required_permission
        self.decision = decision


class DemoBootstrapValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class DemoBootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    requested_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)


class DemoBootstrapSurfaceView(BaseModel):
    surface: str = Field(min_length=1)
    reference_id: str = Field(min_length=1)
    state: str = Field(pattern=r"^(created|existing)$")


class DemoBootstrapRecordView(BaseModel):
    tenant_id: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    plant_name: str = Field(min_length=1)
    bootstrapped: bool
    source_tenant_id: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    surfaces: list[DemoBootstrapSurfaceView] = Field(min_length=1)
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)
    idempotent_replay: bool = False
    notes: list[str] = Field(default_factory=list)


def bootstrap_demo_scenario(
    repository: AxisPersistenceRepository,
    request: DemoBootstrapRequest,
) -> DemoBootstrapRecordView:
    _authorize_bootstrap(request)

    marker = repository.get_demo_reference_record(
        tenant_id=request.tenant_id,
        surface=DEMO_BOOTSTRAP_SURFACE,
        reference_id=DEMO_BOOTSTRAP_REFERENCE_ID,
    )
    if marker is not None:
        try:
            view = DemoBootstrapRecordView.model_validate(marker.payload)
        except ValidationError as exc:
            raise DemoBootstrapValidationError(
                "The persisted demo bootstrap record is invalid.",
                "demo_bootstrap_record_invalid",
            ) from exc
        replay_notes = list(view.notes)
        replay_notes.append(
            "Idempotent replay: the stored demo bootstrap record is returned."
        )
        return view.model_copy(update={"idempotent_replay": True, "notes": replay_notes})

    canonical_overview = repository.get_demo_reference_record(
        tenant_id=CANONICAL_DEMO_TENANT_ID,
        surface=OVERVIEW_SURFACE,
        reference_id=MANUFACTURING_OVERVIEW_REFERENCE_ID,
    )
    if canonical_overview is None:
        raise DemoBootstrapValidationError(
            "The canonical manufacturing demo scenario records are not seeded.",
            "demo_scenario_reference_missing",
        )
    scenario = str(canonical_overview.payload.get("scenario", ""))
    plant_name = str(canonical_overview.payload.get("plant_name", ""))
    if not scenario or not plant_name:
        raise DemoBootstrapValidationError(
            "The canonical manufacturing overview payload is invalid.",
            "demo_scenario_reference_invalid",
        )

    # Bootstrap used to seed reference records without registering the tenant,
    # so a bootstrapped tenant was invisible to /platform/tenants and to every
    # tenant-scoped resource that resolves through the registry (vocabulary,
    # quotas, usage). Register it here, idempotently.
    if repository.get_tenant(request.tenant_id) is None:
        repository.create_tenant(
            TenantCreate(
                tenant_id=request.tenant_id,
                display_name=plant_name,
                description=scenario,
                created_by=request.requested_by,
                audit_event_type=DEMO_BOOTSTRAP_TENANT_AUDIT_EVENT_TYPE,
            )
        )

    surfaces: list[DemoBootstrapSurfaceView] = []
    for surface, reference_id in BOOTSTRAP_SURFACES:
        canonical_record = repository.get_demo_reference_record(
            tenant_id=CANONICAL_DEMO_TENANT_ID,
            surface=surface,
            reference_id=reference_id,
        )
        if canonical_record is None:
            continue
        existing_record = repository.get_demo_reference_record(
            tenant_id=request.tenant_id,
            surface=surface,
            reference_id=reference_id,
        )
        if existing_record is not None:
            surfaces.append(
                DemoBootstrapSurfaceView(
                    surface=surface,
                    reference_id=reference_id,
                    state="existing",
                )
            )
            continue
        repository.upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=request.tenant_id,
                surface=surface,
                reference_id=reference_id,
                status="active",
                source=DEMO_BOOTSTRAP_RECORD_SOURCE,
                version=canonical_record.version,
                payload=_rewrite_tenant_id(
                    deepcopy(canonical_record.payload),
                    CANONICAL_DEMO_TENANT_ID,
                    request.tenant_id,
                ),
            )
        )
        surfaces.append(
            DemoBootstrapSurfaceView(
                surface=surface,
                reference_id=reference_id,
                state="created",
            )
        )

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type=DEMO_BOOTSTRAP_AUDIT_EVENT_TYPE,
            payload={
                "scenario": scenario,
                "source_tenant_id": CANONICAL_DEMO_TENANT_ID,
                "required_scope": DEMO_BOOTSTRAP_SCOPE,
                "created_surfaces": [
                    item.surface for item in surfaces if item.state == "created"
                ],
                "existing_surfaces": [
                    item.surface for item in surfaces if item.state == "existing"
                ],
            },
        )
    )

    view = DemoBootstrapRecordView(
        tenant_id=request.tenant_id,
        scenario=scenario,
        plant_name=plant_name,
        bootstrapped=True,
        source_tenant_id=CANONICAL_DEMO_TENANT_ID,
        requested_by=request.requested_by,
        surfaces=surfaces,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        idempotent_replay=False,
        notes=[
            "Scenario records were copied from the persisted canonical demo tenant.",
            "Re-posting for this tenant replays the stored bootstrap record.",
        ],
    )
    repository.upsert_demo_reference_record(
        DemoReferenceRecordCreate(
            tenant_id=request.tenant_id,
            surface=DEMO_BOOTSTRAP_SURFACE,
            reference_id=DEMO_BOOTSTRAP_REFERENCE_ID,
            status="active",
            source=DEMO_BOOTSTRAP_RECORD_SOURCE,
            version=canonical_overview.version,
            payload=view.model_dump(mode="json"),
        )
    )
    return view


def _authorize_bootstrap(request: DemoBootstrapRequest) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            actor_scopes=request.actor_scopes,
            required_scopes=[DEMO_BOOTSTRAP_SCOPE],
            attributes={"source_tenant_id": CANONICAL_DEMO_TENANT_ID},
        )
    )
    if not decision.allowed:
        raise DemoBootstrapPermissionDenied(DEMO_BOOTSTRAP_SCOPE, decision)
    return decision


def _rewrite_tenant_id(value, source_tenant_id: str, target_tenant_id: str):
    """Rewrite every canonical tenant identifier in a copied scenario payload.

    Canonical payloads embed the tenant id beyond the top-level ``tenant_id``
    field (per-event tenant ids in the audit explorer, tenant filter options),
    so the whole structure is walked and exact string matches are replaced.
    """
    if isinstance(value, str):
        return target_tenant_id if value == source_tenant_id else value
    if isinstance(value, list):
        return [_rewrite_tenant_id(item, source_tenant_id, target_tenant_id) for item in value]
    if isinstance(value, dict):
        return {
            key: _rewrite_tenant_id(item, source_tenant_id, target_tenant_id)
            for key, item in value.items()
        }
    return value
