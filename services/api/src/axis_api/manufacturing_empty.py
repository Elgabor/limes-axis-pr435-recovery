from axis_api.connectors import ManufacturingConnectorRegistry
from axis_api.demo import (
    ActionRegistryFilterOptions,
    AgentRegistryFilterOptions,
    AuditFilterOptions,
    ManufacturingActionRegistry,
    ManufacturingAgentRegistry,
    ManufacturingApprovalInbox,
    ManufacturingAuditExplorer,
    ManufacturingModelRouting,
    ManufacturingOntology,
    ManufacturingOverview,
    ManufacturingWorkflowConsole,
    ModelRoutingFilterOptions,
    OverviewStatus,
)
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    ManufacturingTenantMetadata,
)
from axis_api.ontology.queries import OntologyGraphQueryMetadata
from axis_api.permissions import PermissionDecision


def empty_manufacturing_overview(
    tenant_id: str,
    metadata: ManufacturingTenantMetadata,
) -> ManufacturingOverview:
    return ManufacturingOverview(
        tenant_id=tenant_id,
        plant_name=metadata.plant_name,
        scenario=metadata.scenario,
        provenance=ManufacturingResponseProvenance.EMPTY,
        as_of=metadata.as_of,
        metrics=[],
        risk_signals=[],
        workflows=[],
        approvals=[],
        agents=[],
        audit_events=[],
    )


def empty_manufacturing_workflow_console(
    tenant_id: str,
    metadata: ManufacturingTenantMetadata,
) -> ManufacturingWorkflowConsole:
    return ManufacturingWorkflowConsole(
        tenant_id=tenant_id,
        plant_name=metadata.plant_name,
        scenario=metadata.scenario,
        provenance=ManufacturingResponseProvenance.EMPTY,
        as_of=metadata.as_of,
        runtime_status=OverviewStatus.WATCH,
        metrics=[],
        workflow_runs=[],
        runtime_notes=[],
    )


def empty_manufacturing_agent_registry(
    tenant_id: str,
    metadata: ManufacturingTenantMetadata,
) -> ManufacturingAgentRegistry:
    return ManufacturingAgentRegistry(
        tenant_id=tenant_id,
        plant_name=metadata.plant_name,
        scenario=metadata.scenario,
        provenance=ManufacturingResponseProvenance.EMPTY,
        as_of=metadata.as_of,
        registry_status=OverviewStatus.WATCH,
        metrics=[],
        filter_options=AgentRegistryFilterOptions(),
        agents=[],
        registry_notes=[],
    )


def empty_manufacturing_action_registry(
    tenant_id: str,
    metadata: ManufacturingTenantMetadata,
) -> ManufacturingActionRegistry:
    return ManufacturingActionRegistry(
        tenant_id=tenant_id,
        plant_name=metadata.plant_name,
        scenario=metadata.scenario,
        provenance=ManufacturingResponseProvenance.EMPTY,
        as_of=metadata.as_of,
        registry_status=OverviewStatus.WATCH,
        schema_version="empty",
        metrics=[],
        filter_options=ActionRegistryFilterOptions(),
        actions=[],
        registry_notes=[],
    )


def empty_manufacturing_connector_registry(
    tenant_id: str,
    metadata: ManufacturingTenantMetadata,
) -> ManufacturingConnectorRegistry:
    return ManufacturingConnectorRegistry(
        tenant_id=tenant_id,
        plant_name=metadata.plant_name,
        scenario=metadata.scenario,
        provenance=ManufacturingResponseProvenance.EMPTY,
        registry_status=OverviewStatus.WATCH,
        metrics=[],
        connectors=[],
        connector_notes=[],
    )


def empty_manufacturing_approval_inbox(
    tenant_id: str,
    metadata: ManufacturingTenantMetadata,
) -> ManufacturingApprovalInbox:
    return ManufacturingApprovalInbox(
        tenant_id=tenant_id,
        plant_name=metadata.plant_name,
        scenario=metadata.scenario,
        provenance=ManufacturingResponseProvenance.EMPTY,
        as_of=metadata.as_of,
        queue_status=OverviewStatus.WATCH,
        policy_notes=[],
        approvals=[],
    )


def empty_manufacturing_audit_explorer(
    tenant_id: str,
    metadata: ManufacturingTenantMetadata,
) -> ManufacturingAuditExplorer:
    return ManufacturingAuditExplorer(
        tenant_id=tenant_id,
        plant_name=metadata.plant_name,
        scenario=metadata.scenario,
        provenance=ManufacturingResponseProvenance.EMPTY,
        as_of=metadata.as_of,
        ledger_status=OverviewStatus.WATCH,
        metrics=[],
        filter_options=AuditFilterOptions(tenants=[tenant_id]),
        events=[],
        retention_notes=[],
    )


def empty_manufacturing_ontology(
    tenant_id: str,
    metadata: ManufacturingTenantMetadata,
) -> ManufacturingOntology:
    return ManufacturingOntology(
        tenant_id=tenant_id,
        plant_name=metadata.plant_name,
        scenario=metadata.scenario,
        provenance=ManufacturingResponseProvenance.EMPTY,
        as_of=metadata.as_of,
        nodes=[],
        relationships=[],
        source_systems=[],
        permission_notes=[],
        graph_query=OntologyGraphQueryMetadata(
            adapter="axis-deferred-ontology-query-adapter",
            source="empty",
            query_mode="empty",
            tenant_id=tenant_id,
            actor_id="unassigned",
            permission_decision=PermissionDecision(allowed=True, reason="empty"),
            requested_scopes=[],
            applied_relationship_scopes=[],
            denied_relationship_count=0,
            returned_node_count=0,
            returned_relationship_count=0,
            typeql=None,
            notes=[],
        ),
    )


def empty_manufacturing_model_routing(
    tenant_id: str,
    metadata: ManufacturingTenantMetadata,
) -> ManufacturingModelRouting:
    return ManufacturingModelRouting(
        tenant_id=tenant_id,
        plant_name=metadata.plant_name,
        scenario=metadata.scenario,
        provenance=ManufacturingResponseProvenance.EMPTY,
        as_of=metadata.as_of,
        routing_status=OverviewStatus.WATCH,
        filter_options=ModelRoutingFilterOptions(),
    )
