"""Tenant-scoped Data Asset Catalog: the governed layer between connectors and ontology.

The catalog projects connector manifests and sync evidence into stable,
addressable data assets. It is metadata-only by contract: source rows, preview
samples and credential material never cross this boundary. Assets are
connector-level aggregates until resource-level discovery lands; the
kind/evidence/governance vocabulary is already granular so later discovery
slices can narrow assets without breaking consumers.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from axis_api.connector_reference import get_persisted_manufacturing_connector_registry
from axis_api.connectors import (
    ConnectorManifest,
    ConnectorRegistryItem,
    ConnectorRegistryOrigin,
    ConnectorSchemaField,
    ConnectorSyncObservation,
    ManufacturingConnectorRegistry,
)
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import ManufacturingResponseProvenance


class DataAssetNotInCatalog(LookupError):
    """Raised when an asset ID does not resolve in a tenant catalog."""

    def __init__(self, tenant_id: str, asset_id: str) -> None:
        super().__init__(
            f"Data asset {asset_id!r} is not part of tenant {tenant_id!r} catalog"
        )
        self.tenant_id = tenant_id
        self.asset_id = asset_id


def connector_id_for_asset(
    repository,
    *,
    tenant_id: str,
    asset_id: str,
) -> str:
    """Resolve an asset id to its connector id, failing closed outside the catalog."""

    registry = get_persisted_manufacturing_connector_registry(
        repository,
        tenant_id=tenant_id,
    )
    connector_ids = {
        data_asset_id_for_connector(item.manifest.connector_id): item.manifest.connector_id
        for item in registry.connectors
    }
    if asset_id not in connector_ids:
        raise DataAssetNotInCatalog(tenant_id, asset_id)
    return connector_ids[asset_id]


def ensure_data_asset_in_catalog(
    repository,
    *,
    tenant_id: str,
    asset_id: str,
) -> None:
    """Fail closed when an operation targets an asset outside the catalog."""

    connector_id_for_asset(repository, tenant_id=tenant_id, asset_id=asset_id)


class DataAssetKind(StrEnum):
    DEFAULT = "default"
    TABLE = "table"
    VIEW = "view"
    FILE = "file"
    FOLDER = "folder"
    OBJECT_PREFIX = "object_prefix"
    TOPIC = "topic"
    API_RESOURCE = "api_resource"
    DOCUMENT_COLLECTION = "document_collection"


class DataAssetEvidence(StrEnum):
    SYNC_OBSERVED = "sync_observed"
    PREVIEW_ONLY = "preview_only"
    DECLARED_ONLY = "declared_only"


class DataAssetGovernanceState(StrEnum):
    DECLARED = "declared"
    PARTIAL = "partial"
    NOT_DECLARED = "not_declared"


class DataAssetSchemaField(BaseModel):
    source_column: str = Field(min_length=1)
    target_field: str = Field(min_length=1)
    ontology_target: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    required: bool
    description: str = Field(min_length=1)


class DataAssetStewardshipSummary(BaseModel):
    """Metadata-only projection of the current stewardship declaration."""

    owner: str = Field(min_length=1)
    classification: str = Field(min_length=1)
    residency: str = Field(min_length=1)
    retention: str = Field(min_length=1)
    revision_number: int = Field(ge=1)


class DataAsset(BaseModel):
    asset_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    kind: DataAssetKind = DataAssetKind.DEFAULT
    evidence: DataAssetEvidence
    governance: DataAssetGovernanceState
    source_type: str = Field(min_length=1)
    connector_type: str = Field(min_length=1)
    runtime_boundary: str = Field(min_length=1)
    egress_policy: str = Field(min_length=1)
    payload_policy: str = Field(min_length=1)
    sync_modes: list[str] = Field(default_factory=list)
    schema_fields: list[DataAssetSchemaField] = Field(default_factory=list)
    ontology_targets: list[str] = Field(default_factory=list)
    last_successful_sync: ConnectorSyncObservation | None = None
    registry_origin: ConnectorRegistryOrigin
    manifest_revision: int | None = None
    stewardship: DataAssetStewardshipSummary | None = None
    observed_resource_count: int | None = Field(default=None, ge=0)
    notes: list[str] = Field(default_factory=list)


class DataAssetCatalog(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    catalog_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    assets: list[DataAsset] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def data_asset_id_for_connector(connector_id: str) -> str:
    """Stable asset identity: one connector-level aggregate per source."""
    return f"source:{connector_id}:default"


def _governance_state(
    schema_fields: list[ConnectorSchemaField],
    *,
    stewardship_declared: bool,
) -> DataAssetGovernanceState:
    # Stewardship is declared only when an operator has explicitly declared
    # owner, classification, residency and retention; semantic field mappings
    # alone leave the asset partially governed.
    if stewardship_declared:
        return DataAssetGovernanceState.DECLARED
    if not schema_fields:
        return DataAssetGovernanceState.NOT_DECLARED
    return DataAssetGovernanceState.PARTIAL


def _evidence(item: ConnectorRegistryItem) -> DataAssetEvidence:
    if item.last_successful_sync is not None:
        return DataAssetEvidence.SYNC_OBSERVED
    if item.preview_sample is not None:
        return DataAssetEvidence.PREVIEW_ONLY
    return DataAssetEvidence.DECLARED_ONLY


def _asset_notes(item: ConnectorRegistryItem, evidence: DataAssetEvidence) -> list[str]:
    notes: list[str] = []
    if evidence == DataAssetEvidence.SYNC_OBSERVED:
        notes.append(
            "Sync observation present: this asset reflects a completed connector run."
        )
    elif evidence == DataAssetEvidence.PREVIEW_ONLY:
        notes.append(
            "Preview evidence only: metadata was inspected, no completed sync exists yet."
        )
    else:
        notes.append(
            "Declared only: the manifest describes this source, nothing observed it yet."
        )
    if item.preview_sample is not None:
        notes.append(
            "Preview sample rows stay inside the connector boundary and are not "
            "projected into the catalog."
        )
    return notes


def data_asset_for_connector(
    item: ConnectorRegistryItem,
    tenant_id: str,
    *,
    stewardship: DataAssetStewardshipSummary | None = None,
    observed_resource_count: int | None = None,
) -> DataAsset:
    manifest: ConnectorManifest = item.manifest
    evidence = _evidence(item)
    return DataAsset(
        asset_id=data_asset_id_for_connector(manifest.connector_id),
        tenant_id=tenant_id,
        connector_id=manifest.connector_id,
        display_name=manifest.display_name,
        kind=DataAssetKind.DEFAULT,
        evidence=evidence,
        governance=_governance_state(
            manifest.schema_fields,
            stewardship_declared=stewardship is not None,
        ),
        source_type=manifest.source_type,
        connector_type=manifest.connector_type,
        runtime_boundary=manifest.runtime_boundary,
        egress_policy=item.runtime_policy.egress_policy,
        payload_policy=item.runtime_policy.payload_policy,
        sync_modes=list(manifest.sync_modes),
        schema_fields=[
            DataAssetSchemaField(
                source_column=field.source_column,
                target_field=field.target_field,
                ontology_target=field.ontology_target,
                data_type=field.data_type,
                required=field.required,
                description=field.description,
            )
            for field in manifest.schema_fields
        ],
        ontology_targets=sorted({field.ontology_target for field in manifest.schema_fields}),
        last_successful_sync=item.last_successful_sync,
        registry_origin=item.registry_origin,
        manifest_revision=(
            item.persisted_manifest.revision_number if item.persisted_manifest else None
        ),
        stewardship=stewardship,
        observed_resource_count=observed_resource_count,
        notes=_asset_notes(item, evidence),
    )


def _catalog_metrics(assets: list[DataAsset]) -> list[OverviewMetric]:
    sync_observed = sum(1 for asset in assets if asset.evidence == DataAssetEvidence.SYNC_OBSERVED)
    semantic_targets = len({target for asset in assets for target in asset.ontology_targets})
    stewardship_gaps = sum(
        1 for asset in assets if asset.governance != DataAssetGovernanceState.DECLARED
    )
    unmapped = sum(
        1 for asset in assets if asset.governance == DataAssetGovernanceState.NOT_DECLARED
    )
    return [
        OverviewMetric(
            label="Data Assets",
            value=str(len(assets)),
            detail="Connector-level assets projected into the catalog",
            status=OverviewStatus.READY if assets else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Sync Observed",
            value=str(sync_observed),
            detail="Assets backed by a completed connector run",
            status=OverviewStatus.READY if sync_observed else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Semantic Targets",
            value=str(semantic_targets),
            detail="Distinct ontology targets declared across assets",
            status=OverviewStatus.READY if semantic_targets else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Stewardship Gaps",
            value=str(stewardship_gaps),
            detail=(
                "Assets without fully declared ownership, classification, "
                "residency and retention"
            ),
            status=(
                OverviewStatus.ACTION_REQUIRED if unmapped else OverviewStatus.WATCH
            ),
        ),
    ]


def _catalog_notes(assets: list[DataAsset]) -> list[str]:
    notes = [
        "Assets are connector-level aggregates until resource-level discovery "
        "(tables, topics, prefixes) narrows them.",
        "The catalog is metadata-only: source rows and preview samples never "
        "cross this boundary.",
    ]
    if any(asset.governance != DataAssetGovernanceState.DECLARED for asset in assets):
        notes.append(
            "Stewardship attributes are not inventable: they must be declared "
            "and audited before an asset can be considered fully governed."
        )
    return notes


def build_data_asset_catalog(
    registry: ManufacturingConnectorRegistry,
    *,
    stewardship_by_asset: dict[str, DataAssetStewardshipSummary] | None = None,
    observed_resource_counts: dict[str, int] | None = None,
) -> DataAssetCatalog:
    stewardship = stewardship_by_asset or {}
    resource_counts = observed_resource_counts or {}
    assets = [
        data_asset_for_connector(
            item,
            registry.tenant_id,
            stewardship=stewardship.get(data_asset_id_for_connector(item.manifest.connector_id)),
            observed_resource_count=resource_counts.get(
                data_asset_id_for_connector(item.manifest.connector_id)
            ),
        )
        for item in registry.connectors
    ]
    return DataAssetCatalog(
        tenant_id=registry.tenant_id,
        plant_name=registry.plant_name,
        scenario=registry.scenario,
        provenance=registry.provenance,
        catalog_status=registry.registry_status,
        metrics=_catalog_metrics(assets),
        assets=assets,
        notes=_catalog_notes(assets),
    )
