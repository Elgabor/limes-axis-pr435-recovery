"""Small, request-scoped projections for the connector console.

Authorization belongs to the HTTP boundary, before any of these reads. Counters
retain the legacy first-100 semantics; they are not tenant-wide totals. No
process, tenant-only, or shared HTTP cache stores this projection.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from axis_api.audit import AuditEventCreate
from axis_api.connector_egress_policies import (
    ConnectorEgressPolicyQuery,
    read_connector_egress_policy_registry,
)
from axis_api.connector_evidence_invariants import (
    ConnectorEvidenceInvariantQuery,
    read_connector_evidence_invariant_report,
)
from axis_api.connector_ontology_proposals import (
    ConnectorOntologyProposalQuery,
    build_connector_ontology_proposal_registry,
)
from axis_api.connector_reference import get_persisted_manufacturing_connector_registry
from axis_api.connector_runs import ConnectorRunQuery, build_connector_run_registry
from axis_api.connectors import ConnectorRegistryItem, ConnectorRegistryOrigin
from axis_api.demo import OverviewStatus
from axis_api.manufacturing_metadata import ManufacturingResponseProvenance
from axis_api.persistence import AxisPersistenceRepository

logger = logging.getLogger(__name__)
COUNTER_LIMIT = 100
MAX_SUMMARY_BYTES = 65_536


class ConnectorWorkspaceManifestLabel(BaseModel):
    connector_id: str = Field(min_length=1, max_length=512)
    display_name: str = Field(min_length=1, max_length=512)
    connector_type: str = Field(min_length=1, max_length=128)


class ConnectorWorkspaceManifestStatus(BaseModel):
    status: str = Field(min_length=1, max_length=128)


class ConnectorWorkspaceSampleCount(BaseModel):
    record_count: int = Field(ge=0)


class ConnectorWorkspaceSyncObservation(BaseModel):
    run_id: str = Field(min_length=1, max_length=512)
    completed_at: datetime
    records_read: int = Field(ge=0)


class ConnectorWorkspaceItem(BaseModel):
    manifest: ConnectorWorkspaceManifestLabel
    connector_status: OverviewStatus
    registry_origin: ConnectorRegistryOrigin
    persisted_manifest: ConnectorWorkspaceManifestStatus | None
    preview_sample: ConnectorWorkspaceSampleCount | None
    last_successful_sync: ConnectorWorkspaceSyncObservation | None


class ConnectorWorkspaceCounts(BaseModel):
    # Null means the source read failed, never a fabricated zero.
    runs: int | None = Field(ge=0)
    pending_proposals: int | None = Field(ge=0)
    egress_policies: int | None = Field(ge=0)
    evidence_issues: int | None = Field(ge=0)
    source_limit: int = COUNTER_LIMIT


class ConnectorWorkspaceSummary(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=512)
    plant_name: str | None = Field(max_length=512)
    scenario: str | None = Field(max_length=512)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    generated_at: datetime
    connectors: list[ConnectorWorkspaceItem] = Field(max_length=50)
    total_connectors: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=50)
    next_offset: int | None = Field(ge=0)
    counts: ConnectorWorkspaceCounts


class ConnectorWorkspaceDetail(BaseModel):
    tenant_id: str
    connector: ConnectorRegistryItem


def _count(
    repository: AxisPersistenceRepository,
    name: str,
    read: Callable[[], int],
) -> int | None:
    try:
        # A failing audit append or malformed side registry must not poison
        # the request transaction or hide the list and other counters.
        with repository.session.begin_nested():
            return read()
    except (SQLAlchemyError, ValueError, LookupError) as exc:
        # Validation/SQL exceptions can contain source values. Log only the
        # surface and exception class, never those values or SQL parameters.
        logger.warning("Connector workspace counter unavailable: %s (%s)", name, type(exc).__name__)
        return None


def read_connector_workspace_summary(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    actor_id: str,
    offset: int = 0,
    limit: int = 25,
) -> ConnectorWorkspaceSummary:
    registry = get_persisted_manufacturing_connector_registry(repository, tenant_id)
    # Preserve the existing registry's reference/override/order semantics.
    # Only the page projection crosses the HTTP boundary, never schemas, rows,
    # histories, notes, endpoint references, credentials or policy documents.
    items = [
        ConnectorWorkspaceItem.model_validate(connector, from_attributes=True)
        for connector in registry.connectors[offset : offset + limit]
    ]
    total = len(registry.connectors)
    # Bind the reader/page to the caller's transaction before any savepoint.
    # SQLite's legacy driver otherwise releases a first savepoint as a commit;
    # a later caller rollback must also roll back every counter read audit.
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=actor_id,
            event_type="connector.workspace_read",
            payload={
                "offset": offset,
                "limit": limit,
                "source_limit": COUNTER_LIMIT,
                "returned_connector_count": len(items),
            },
        )
    )
    counts = ConnectorWorkspaceCounts(
        runs=_count(
            repository,
            "runs",
            lambda: len(
                build_connector_run_registry(
                    repository, ConnectorRunQuery(tenant_id=tenant_id, limit=COUNTER_LIMIT)
                ).runs
            ),
        ),
        pending_proposals=_count(
            repository,
            "pending_proposals",
            lambda: sum(
                proposal.promoted_at is None
                for proposal in build_connector_ontology_proposal_registry(
                    repository,
                    ConnectorOntologyProposalQuery(tenant_id=tenant_id, limit=COUNTER_LIMIT),
                ).proposals
            ),
        ),
        egress_policies=_count(
            repository,
            "egress_policies",
            lambda: len(
                read_connector_egress_policy_registry(
                    repository,
                    ConnectorEgressPolicyQuery(tenant_id=tenant_id, limit=COUNTER_LIMIT),
                    actor_id=actor_id,
                ).policies
            ),
        ),
        evidence_issues=_count(
            repository,
            "evidence_issues",
            lambda: len(
                read_connector_evidence_invariant_report(
                    repository,
                    ConnectorEvidenceInvariantQuery(tenant_id=tenant_id, limit=COUNTER_LIMIT),
                    actor_id=actor_id,
                ).invariants
            ),
        ),
    )
    summary = ConnectorWorkspaceSummary(
        tenant_id=registry.tenant_id,
        plant_name=registry.plant_name,
        scenario=registry.scenario,
        provenance=registry.provenance,
        registry_status=registry.registry_status,
        generated_at=datetime.now(UTC),
        connectors=items,
        total_connectors=total,
        offset=offset,
        limit=limit,
        next_offset=offset + limit if offset + limit < total else None,
        counts=counts,
    )
    if len(summary.model_dump_json().encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise ValueError("Connector workspace page exceeds its byte budget")
    return summary


def read_connector_workspace_detail(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    connector_id: str,
) -> ConnectorWorkspaceDetail:
    registry = get_persisted_manufacturing_connector_registry(repository, tenant_id)
    for connector in registry.connectors:
        if connector.manifest.connector_id == connector_id:
            return ConnectorWorkspaceDetail(tenant_id=tenant_id, connector=connector)
    raise LookupError("Connector not found in the tenant registry")
