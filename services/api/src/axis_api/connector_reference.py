from datetime import UTC

from pydantic import ValidationError

from axis_api.connector_registry_composition import (
    connector_persisted_manifest_summary,
)
from axis_api.connectors import (
    ConnectorRegistryItem,
    ConnectorRegistryOrigin,
    ConnectorSyncObservation,
    ManufacturingConnectorRegistry,
)
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_empty import empty_manufacturing_connector_registry
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    ManufacturingTenantNotFound,
    get_manufacturing_tenant_metadata,
)
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_CONNECTOR_REGISTRY_REFERENCE_ID = "manufacturing-connector-registry"
CONNECTOR_REGISTRY_SURFACE = "connectors"
SUCCESSFUL_SYNC_STATUS = "sync_execution_completed"


class ConnectorReferenceRecordNotFound(LookupError):
    pass


class ConnectorReferenceRecordInvalid(ValueError):
    pass


def _with_registered_connector_manifests(
    repository: AxisPersistenceRepository,
    registry: ManufacturingConnectorRegistry,
) -> ManufacturingConnectorRegistry:
    records = repository.list_all_current_connector_manifests(
        tenant_id=registry.tenant_id,
    )
    records_by_connector_id = {record.connector_id: record for record in records}
    connectors: list[ConnectorRegistryItem] = []
    for connector in registry.connectors:
        record = records_by_connector_id.pop(connector.manifest.connector_id, None)
        if record is None:
            connectors.append(
                connector.model_copy(
                    update={
                        "registry_origin": ConnectorRegistryOrigin.REFERENCE,
                        "persisted_manifest": None,
                    }
                )
            )
            continue
        connectors.append(
            ConnectorRegistryItem(
                manifest=record.manifest_payload,
                runtime_policy=record.runtime_policy,
                preview_sample=record.preview_sample,
                last_successful_sync=connector.last_successful_sync,
                connector_status=connector.connector_status,
                registry_origin=ConnectorRegistryOrigin.REFERENCE,
                persisted_manifest=connector_persisted_manifest_summary(record),
            )
        )
    connectors.extend(
        ConnectorRegistryItem(
            manifest=record.manifest_payload,
            runtime_policy=record.runtime_policy,
            preview_sample=record.preview_sample,
            connector_status="watch",
            registry_origin=ConnectorRegistryOrigin.PERSISTED_MANIFEST,
            persisted_manifest=connector_persisted_manifest_summary(record),
        )
        for record in records_by_connector_id.values()
    )
    updates: dict[str, object] = {"connectors": connectors}
    if records:
        persisted_metric = OverviewMetric(
            label="Persisted Manifests",
            value=str(len(records)),
            detail="Tenant-scoped connector manifest records",
            status=OverviewStatus.READY,
        )
        metrics = [
            metric.model_copy(update={"value": str(len(connectors))})
            if metric.label == "Connector Manifests"
            else metric
            for metric in registry.metrics
            if metric.label != persisted_metric.label
        ]
        updates["metrics"] = [persisted_metric, *metrics]

    if records and registry.provenance == ManufacturingResponseProvenance.EMPTY:
        updates.update(
            provenance=ManufacturingResponseProvenance.LIVE,
            registry_status=OverviewStatus.READY,
            connector_notes=[
                "Registry is composed from tenant-scoped persisted connector manifests."
            ],
        )
    return registry.model_copy(update=updates)


def _with_last_successful_sync_observations(
    repository: AxisPersistenceRepository,
    registry: ManufacturingConnectorRegistry,
) -> ManufacturingConnectorRegistry:
    if not registry.connectors:
        return registry

    runs_by_connector_id = {
        run.connector_id: run
        for run in repository.list_latest_connector_runs_by_connector(
            tenant_id=registry.tenant_id,
            status=SUCCESSFUL_SYNC_STATUS,
        )
    }
    connectors: list[ConnectorRegistryItem] = []
    for connector in registry.connectors:
        run = runs_by_connector_id.get(connector.manifest.connector_id)
        observation = None
        if run is not None:
            records_read = run.result_summary.get("records_read")
            if isinstance(records_read, str) and records_read.isdecimal():
                # This is derived from redacted run evidence at read time: storing it
                # on the manifest would create drift, and no source rows cross the boundary.
                observation = ConnectorSyncObservation(
                    run_id=run.run_id,
                    completed_at=(
                        run.updated_at
                        if run.updated_at.tzinfo is not None
                        else run.updated_at.replace(tzinfo=UTC)
                    ),
                    records_read=int(records_read),
                )
        connectors.append(
            connector.model_copy(update={"last_successful_sync": observation})
        )
    return registry.model_copy(update={"connectors": connectors})


def get_persisted_manufacturing_connector_registry(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingConnectorRegistry:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, tenant_id)
    record = repository.get_demo_reference_record(
        tenant_id=tenant_id,
        surface=CONNECTOR_REGISTRY_SURFACE,
        reference_id=MANUFACTURING_CONNECTOR_REGISTRY_REFERENCE_ID,
    )
    if record is None:
        registry = empty_manufacturing_connector_registry(tenant_id, tenant_metadata)
    else:
        try:
            registry = ManufacturingConnectorRegistry.model_validate(record.payload)
        except ValidationError as exc:
            raise ConnectorReferenceRecordInvalid(
                "Manufacturing connector registry reference payload is invalid"
            ) from exc

        if registry.tenant_id != tenant_id:
            raise ConnectorReferenceRecordInvalid(
                "Manufacturing connector registry tenant does not match record tenant"
            )

        registry = registry.model_copy(
            update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
        )
    registry = _with_registered_connector_manifests(repository, registry)
    return _with_last_successful_sync_observations(repository, registry)


def require_persisted_manufacturing_connector_registry(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingConnectorRegistry:
    try:
        registry = get_persisted_manufacturing_connector_registry(repository, tenant_id)
    except ManufacturingTenantNotFound as exc:
        raise ConnectorReferenceRecordNotFound(
            "Manufacturing connector registry reference record not found"
        ) from exc
    if registry.provenance == ManufacturingResponseProvenance.EMPTY:
        raise ConnectorReferenceRecordNotFound(
            "Manufacturing connector registry reference record not found"
        )
    return registry
