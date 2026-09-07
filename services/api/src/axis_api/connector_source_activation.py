"""Governed activation of discovered source tables into durable bindings.

Activation is the third real source boundary after the allowlisted live read
and bounded discovery: it turns selected discovered tables into durable,
auditable source bindings that a future ingestion boundary can act on.
Activation itself never dials the source -- it validates operator selections
against evidence Axis already observed (current resource observations), so a
binding can only exist for a table whose schema Axis has actually seen.

Every gate is server-owned: scope ``connectors:source:activate``, the same
lease/egress evidence resolution live reads and discovery use, bounded batch
selections, per-selection expected fingerprints closing the gap between
discovery and activation, and one active binding per source resource backed by
a partial unique index. Repeated submissions of the same binding identity are
deterministic replays, never duplicate rows or duplicate audit noise.

Bindings are honest about what they are: each carries an explicit
``pending_ingestion`` status because no ingestion boundary reads row data yet.
"""

import re
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from axis_api.connector_postgres_discovery import (
    _resolve_operation_evidence,
)
from axis_api.connector_source_schema import SchemaFingerprintVersion
from axis_api.persistence import (
    AuditEventCreate,
    AxisPersistenceRepository,
    ConnectorSourceBindingCreate,
)

if TYPE_CHECKING:
    pass

SOURCE_ACTIVATION_SCOPE = "connectors:source:activate"
ACTIVATION_AUDIT_EVENT_TYPE = "connector.source.bindings.activated"
BINDING_ACTIVE_STATUS = "active"
BINDING_PENDING_INGESTION_STATUS = "pending_ingestion"
# Qualified names produced by discovery are exactly ``schema.table`` with each
# part matching Postgres' safe identifier shape; activation refuses anything
# else before it ever touches persistence.
_PG_IDENTIFIER_FRAGMENT = r"[A-Za-z_][A-Za-z0-9_]*"
_QUALIFIED_RESOURCE_NAME_PATTERN = (
    rf"{_PG_IDENTIFIER_FRAGMENT}\.{_PG_IDENTIFIER_FRAGMENT}"
)
_BINDING_ID_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9._:-]*$"


class SourceActivationScopeDenied(PermissionError):
    """The verified principal lacks ``connectors:source:activate``."""

    def __init__(self) -> None:
        super().__init__(f"missing_scope:{SOURCE_ACTIVATION_SCOPE}")
        self.required_scope = SOURCE_ACTIVATION_SCOPE


class ConnectorSourceActivationError(ValueError):
    """Operator-input failure with a public-safe reason and selection index."""

    def __init__(
        self,
        message: str,
        reason: str,
        *,
        selection_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.selection_index = selection_index


class ConnectorSourceActivationConflict(ValueError):
    """Deterministic conflict with existing binding state."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class SourceBindingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=_BINDING_ID_PATTERN,
    )
    resource_name: str = Field(min_length=1, max_length=240)
    # Required on purpose: the operator activates exactly the schema they
    # reviewed during discovery; anything else is stale and rejected.
    expected_schema_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    expected_schema_fingerprint_version: SchemaFingerprintVersion = "column_names_v1"
    supersedes_binding_id: str | None = Field(
        default=None, min_length=1, max_length=180, pattern=_BINDING_ID_PATTERN,
    )


class ConnectorSourceActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    activation_id: str = Field(min_length=1, max_length=180)
    requested_by: str = Field(min_length=1)
    connection_profile_id: str = Field(min_length=1, max_length=180)
    credential_lease_id: str = Field(min_length=1, max_length=180)
    egress_policy_id: str = Field(min_length=1, max_length=180)
    # Required governance reason; stored with the binding as activation evidence.
    activation_reason: str = Field(min_length=1, max_length=600)
    selections: list[SourceBindingSelection] = Field(min_length=1)
    # Stamped from the verified principal when OIDC is enforced; public demo
    # traffic declares its scopes in the body (same convention as discovery).
    actor_scopes: list[str] = Field(default_factory=list)


class SourceBindingView(BaseModel):
    binding_id: str = Field(min_length=1)
    resource_name: str = Field(min_length=1)
    schema_fingerprint: str = Field(min_length=64, max_length=64)
    schema_fingerprint_version: str = "column_names_v1"
    supersedes_binding_id: str | None = None
    status: str = Field(min_length=1)
    ingestion_status: str = Field(min_length=1)
    outcome: str = Field(pattern="^(activated|replayed)$")
    connection_profile_id: str = Field(min_length=1)
    activated_by: str = Field(min_length=1)
    activated_at: datetime


class ConnectorSourceActivationOutcome(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    activation_id: str = Field(min_length=1)
    bindings: list[SourceBindingView]
    correlation_ref: str = Field(min_length=1)


class ConnectorSourceBindingsView(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    bindings: list[SourceBindingView]


def _qualified_resource_name_is_safe(resource_name: str) -> bool:
    return re.fullmatch(_QUALIFIED_RESOURCE_NAME_PATTERN, resource_name) is not None


def _binding_view(binding, *, outcome: str) -> SourceBindingView:
    return SourceBindingView(
        binding_id=binding.binding_id,
        resource_name=binding.resource_name,
        schema_fingerprint=binding.schema_fingerprint,
        status=binding.status,
        schema_fingerprint_version=binding.schema_fingerprint_version,
        supersedes_binding_id=binding.supersedes_binding_id,
        ingestion_status=binding.ingestion_status,
        outcome=outcome,
        connection_profile_id=binding.connection_profile_id,
        activated_by=binding.activated_by,
        activated_at=binding.activated_at,
    )


def record_connector_source_activation(
    repository: AxisPersistenceRepository,
    *,
    request: ConnectorSourceActivationRequest,
    principal_scopes: list[str],
    max_selections: int,
) -> ConnectorSourceActivationOutcome:
    """Activate selected discovered tables atomically.

    The whole batch succeeds or nothing is written: every selection is
    validated against current observations and existing bindings before the
    single audit event and the binding rows are committed in one transaction.
    """
    if SOURCE_ACTIVATION_SCOPE not in principal_scopes:
        raise SourceActivationScopeDenied()
    if len(request.selections) > max_selections:
        raise ConnectorSourceActivationError(
            f"At most {max_selections} tables can be activated per submission.",
            "selection_too_large",
        )
    seen_binding_ids: set[str] = set()
    seen_resources: set[str] = set()
    for selection in request.selections:
        if not _qualified_resource_name_is_safe(selection.resource_name):
            raise ConnectorSourceActivationError(
                "Resource names must be qualified Postgres table names.",
                "unsafe_resource_name",
            )
        if selection.binding_id in seen_binding_ids:
            raise ConnectorSourceActivationError(
                "Each selection needs its own binding ID.",
                "duplicate_binding_id",
            )
        if selection.resource_name in seen_resources:
            raise ConnectorSourceActivationError(
                "Each table may be selected only once per submission.",
                "duplicate_resource_name",
            )
        seen_binding_ids.add(selection.binding_id)
        seen_resources.add(selection.resource_name)

    # Same lease/egress posture as live reads and discovery: an executed or
    # renewed lease proving no secret material was returned, plus an approved
    # private-endpoint policy pinned to this connection profile.
    _resolve_operation_evidence(repository, request)

    repository.acquire_connector_source_activation_lock(
        tenant_id=request.tenant_id,
        connector_id=request.connector_id,
    )

    # Validate every selection against current truth before writing anything.
    validated: list[tuple[SourceBindingSelection, object]] = []
    replayed_bindings: list[SourceBindingView] = []
    predecessors = []
    for index, selection in enumerate(request.selections):
        observation = repository.get_data_resource_observation(
            request.tenant_id,
            request.connector_id,
            selection.resource_name,
        )
        if observation is None:
            raise ConnectorSourceActivationError(
                "That table has never been observed by source discovery.",
                "resource_not_observed",
                selection_index=index,
            )

        # Replay is judged on binding identity alone: re-submitting the exact
        # submission that produced an existing binding returns that binding
        # unchanged, even if the source drifted afterwards -- a replay never
        # creates or refreshes a claim.
        existing_for_resource = (
            repository.get_active_connector_source_binding_for_resource(
                request.tenant_id,
                request.connector_id,
                selection.resource_name,
            )
        )
        if existing_for_resource is not None:
            if (
                existing_for_resource.binding_id == selection.binding_id
                and existing_for_resource.schema_fingerprint
                == selection.expected_schema_fingerprint
                and existing_for_resource.schema_fingerprint_version
                == selection.expected_schema_fingerprint_version
                and existing_for_resource.supersedes_binding_id == selection.supersedes_binding_id
            ):
                replayed_bindings.append(
                    _binding_view(existing_for_resource, outcome="replayed")
                )
                validated.append((selection, existing_for_resource))
                continue
            if selection.supersedes_binding_id != existing_for_resource.binding_id:
                raise ConnectorSourceActivationConflict(
                    "Name the active predecessor to replace this table binding.",
                    "binding_already_active",
                )
            predecessors.append(existing_for_resource)
        elif selection.supersedes_binding_id is not None:
            raise ConnectorSourceActivationConflict(
                "The named predecessor is not the active binding for this resource.",
                "binding_predecessor_conflict",
            )
        current_fingerprint = observation.schema_fingerprint or ""
        if (current_fingerprint != selection.expected_schema_fingerprint or
            observation.schema_fingerprint_version
            != selection.expected_schema_fingerprint_version):
            raise ConnectorSourceActivationError(
                "The table's schema changed since it was discovered; run discovery again.",
                "schema_fingerprint_stale",
                selection_index=index,
            )
        other_binding = repository.get_connector_source_binding(
            request.tenant_id,
            selection.binding_id,
        )
        if other_binding is not None:
            raise ConnectorSourceActivationConflict(
                "That binding ID is already used for a different table.",
                "binding_id_in_use",
            )
        validated.append((selection, None))

    new_selections = [
        (selection, existing)
        for selection, existing in validated
        if existing is None
    ]
    # A pure replay re-submits nothing new: it returns the existing bindings
    # without writing rows or appending duplicate audit evidence.
    audit_event = None
    if new_selections:
        audit_event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=request.tenant_id,
                actor_id=request.requested_by,
                event_type=ACTIVATION_AUDIT_EVENT_TYPE,
                payload={
                    "connector_id": request.connector_id,
                    "connection_profile_id": request.connection_profile_id,
                    "activation_id": request.activation_id,
                    "binding_count": str(len(request.selections)),
                    "activated_count": str(len(new_selections)),
                    "replayed_count": str(len(replayed_bindings)),
                    "bindings": [
                        {
                            "binding_id": selection.binding_id,
                            "resource_name": selection.resource_name,
                            "schema_fingerprint": selection.expected_schema_fingerprint,
                            "outcome": "activated",
                            "schema_fingerprint_version": (
                                selection.expected_schema_fingerprint_version
                            ),
                            "supersedes_binding_id": selection.supersedes_binding_id,
                        }
                        for selection, _existing in new_selections
                    ],
                    "credential_lease_id": request.credential_lease_id,
                    "egress_policy_id": request.egress_policy_id,
                    "ingestion_status": BINDING_PENDING_INGESTION_STATUS,
                    "secret_material_returned": "false",
                },
            )
        )
    for predecessor in predecessors:
        predecessor.status = "superseded"
    # Release the partial unique resource index before inserting successors.
    if predecessors:
        repository.session.flush()
    created_views: list[SourceBindingView] = []
    for selection, _existing in new_selections:
        binding = repository.create_connector_source_binding(
            ConnectorSourceBindingCreate(
                tenant_id=request.tenant_id,
                connector_id=request.connector_id,
                asset_id=f"source:{request.connector_id}:default",
                binding_id=selection.binding_id,
                connection_profile_id=request.connection_profile_id,
                resource_name=selection.resource_name,
                schema_fingerprint=selection.expected_schema_fingerprint,
                credential_lease_id=request.credential_lease_id,
                schema_fingerprint_version=selection.expected_schema_fingerprint_version,
                supersedes_binding_id=selection.supersedes_binding_id,
                egress_policy_id=request.egress_policy_id,
                ingestion_status=BINDING_PENDING_INGESTION_STATUS,
                activated_by=request.requested_by,
                activation_reason=request.activation_reason,
                audit_event_id=audit_event.id,
                audit_event_type=ACTIVATION_AUDIT_EVENT_TYPE,
            )
        )
        created_views.append(_binding_view(binding, outcome="activated"))

    bindings = [*created_views, *replayed_bindings]
    return ConnectorSourceActivationOutcome(
        tenant_id=request.tenant_id,
        connector_id=request.connector_id,
        activation_id=request.activation_id,
        bindings=bindings,
        correlation_ref=(
            f"source-activation://{request.tenant_id}/"
            f"{request.connector_id}/{request.activation_id}"
        ),
    )


def list_connector_source_bindings(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    connector_id: str,
) -> ConnectorSourceBindingsView:
    """Active bindings for one tenant connector, deterministically ordered."""
    records = repository.list_active_connector_source_bindings(tenant_id, connector_id)
    return ConnectorSourceBindingsView(
        tenant_id=tenant_id,
        connector_id=connector_id,
        bindings=[_binding_view(record, outcome="activated") for record in records],
    )
