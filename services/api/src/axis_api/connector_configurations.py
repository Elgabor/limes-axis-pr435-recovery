from pydantic import BaseModel, Field

from axis_api.connector_reference import require_persisted_manufacturing_connector_registry
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    find_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.persistence import AxisPersistenceRepository, ConnectorConfigurationCreate


class ConnectorConfigurationValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorConfigurationQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorConfigurationCreateRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    display_name: str = Field(min_length=1, max_length=200)
    sync_mode: str = Field(default="preview", min_length=1, max_length=80)
    created_by: str = Field(min_length=1, max_length=160)
    configuration_payload: dict[str, str] = Field(default_factory=dict)
    credential_ref_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConnectorTenantConfiguration(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    status: str = Field(min_length=1)
    sync_mode: str = Field(min_length=1)
    runtime_boundary: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    configuration_payload: dict[str, str] = Field(default_factory=dict)
    credential_ref_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ManufacturingConnectorConfigurationRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    configurations: list[ConnectorTenantConfiguration] = Field(default_factory=list)
    configuration_notes: list[str] = Field(default_factory=list)


RAW_SECRET_FIELD_NAMES = {
    "api_key",
    "client_secret",
    "credential_value",
    "password",
    "secret",
    "token",
}


def build_connector_configuration_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorConfigurationQuery,
) -> ManufacturingConnectorConfigurationRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_connector_configurations(
        tenant_id=query.tenant_id,
        connector_id=query.connector_id,
        status=query.status,
        limit=query.limit,
    )
    configurations = [_configuration_from_record(record) for record in records]
    return ManufacturingConnectorConfigurationRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Configured Connectors",
                value=str(len(configurations)),
                detail="Tenant-scoped preview connector configurations",
                status=OverviewStatus.READY if configurations else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Credential Values",
                value="Blocked",
                detail="Configurations store handles and public-safe settings only",
                status=OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Live Sync",
                value="Disabled",
                detail="Configuration is preview-only until connector run governance matures",
                status=OverviewStatus.WATCH,
            ),
        ],
        configurations=configurations,
        configuration_notes=[
            "Connector configurations are tenant-scoped and preview-only.",
            "Raw credential values are rejected; future work must use credential handles.",
            "Persisted connector runs, scheduled sync and audit writes remain future work.",
        ],
    )


def record_demo_connector_configuration(
    repository: AxisPersistenceRepository,
    request: ConnectorConfigurationCreateRequest,
) -> ConnectorTenantConfiguration:
    manifest = _active_preview_manifest_for_connector(
        repository,
        request.tenant_id,
        request.connector_id,
    )
    _validate_preview_sync_mode(request.sync_mode)
    _validate_public_safe_payload(request.configuration_payload)
    record = repository.create_connector_configuration(
        ConnectorConfigurationCreate(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            display_name=request.display_name,
            status="configured_preview_only",
            sync_mode=request.sync_mode,
            runtime_boundary=manifest.runtime_boundary,
            created_by=request.created_by,
            configuration_payload=request.configuration_payload,
            credential_ref_ids=request.credential_ref_ids,
            notes=request.notes,
        )
    )
    return _configuration_from_record(record)


def _configuration_from_record(record) -> ConnectorTenantConfiguration:
    return ConnectorTenantConfiguration(
        tenant_id=record.tenant_id,
        connector_id=record.connector_id,
        display_name=record.display_name,
        status=record.status,
        sync_mode=record.sync_mode,
        runtime_boundary=record.runtime_boundary,
        created_by=record.created_by,
        configuration_payload=record.configuration_payload,
        credential_ref_ids=record.credential_ref_ids,
        notes=record.notes,
    )


def _manifest_for_connector(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str,
):
    registry = require_persisted_manufacturing_connector_registry(
        repository, tenant_id=tenant_id
    )
    for connector in registry.connectors:
        if connector.manifest.connector_id == connector_id:
            return connector.manifest
    raise ConnectorConfigurationValidationError(
        f"Unsupported connector_id: {connector_id}",
        "unsupported_connector_id",
    )


def _active_preview_manifest_for_connector(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str,
):
    _manifest_for_connector(repository, tenant_id, connector_id)
    manifest = repository.get_connector_manifest(tenant_id, connector_id)
    if manifest is None:
        raise ConnectorConfigurationValidationError(
            "Connector manifest must be registered before tenant configuration.",
            "connector_manifest_not_found",
        )
    if manifest.status != "active_preview":
        raise ConnectorConfigurationValidationError(
            "Connector manifest must be active_preview before tenant configuration.",
            "connector_manifest_not_active_preview",
        )
    return manifest


def _validate_preview_sync_mode(sync_mode: str) -> None:
    if sync_mode == "preview":
        return
    raise ConnectorConfigurationValidationError(
        "Only preview sync mode can be configured in this foundation slice.",
        "unsupported_sync_mode",
    )


def _validate_public_safe_payload(payload: dict[str, str]) -> None:
    for key in payload:
        if key.lower() in RAW_SECRET_FIELD_NAMES:
            raise ConnectorConfigurationValidationError(
                "Connector configuration payload cannot include raw credential fields.",
                "raw_secret_field",
            )
