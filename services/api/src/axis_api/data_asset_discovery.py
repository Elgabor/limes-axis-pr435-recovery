"""Resource-level discovery observations for data assets.

An observation records that Axis actually saw a source resource through a
governed boundary (today: successful CSV previews). Observations are
metadata-only: resource names and header fingerprints, never row values.
Drift states are strictly evidence-derived — ``added``, ``changed`` and
``unchanged`` come from comparing fingerprints; there is no ``missing``
state because absence cannot be proven without a complete scan, and no
complete scanner exists yet.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from axis_api.connectors import csv_header_fingerprint
from axis_api.data_assets import data_asset_id_for_connector
from axis_api.persistence import (
    AuditEventCreate,
    AxisPersistenceRepository,
    DataResourceObservationCreate,
)

DRIFT_ADDED = "added"
DRIFT_CHANGED = "changed"
DRIFT_UNCHANGED = "unchanged"


class DataAssetResourceObservationView(BaseModel):
    resource_name: str = Field(min_length=1)
    schema_fingerprint: str | None
    previous_fingerprint: str | None
    drift_state: str = Field(pattern="^(added|changed|unchanged)$")
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int = Field(ge=1)
    observed_by: str = Field(min_length=1)


class DataAssetResourcesView(BaseModel):
    tenant_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    resources: list[DataAssetResourceObservationView]
    notes: list[str] = Field(default_factory=list)


def _observation_view(record) -> DataAssetResourceObservationView:
    return DataAssetResourceObservationView(
        resource_name=record.resource_name,
        schema_fingerprint=record.schema_fingerprint,
        previous_fingerprint=record.previous_fingerprint,
        drift_state=record.drift_state,
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        observation_count=record.observation_count,
        observed_by=record.observed_by,
    )


def record_data_resource_observation(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    connector_id: str,
    file_name: str,
    columns: list[str],
    observed_by: str,
) -> tuple[DataAssetResourceObservationView, str]:
    """Upsert one observation for an observed CSV file.

    Returns the current view and the derived drift state. The advisory lock
    covers the first-observation race where the row does not exist yet; every
    accepted observation appends audit evidence.
    """
    repository.acquire_data_resource_observation_lock(
        tenant_id=tenant_id,
        connector_id=connector_id,
        resource_name=file_name,
    )

    fingerprint = csv_header_fingerprint(columns)
    existing = repository.get_data_resource_observation(
        tenant_id,
        connector_id,
        file_name,
    )
    if existing is None:
        record = repository.create_data_resource_observation(
            DataResourceObservationCreate(
                tenant_id=tenant_id,
                connector_id=connector_id,
                asset_id=data_asset_id_for_connector(connector_id),
                resource_name=file_name,
                schema_fingerprint=fingerprint,
                drift_state=DRIFT_ADDED,
                observed_by=observed_by,
            )
        )
        drift_state = DRIFT_ADDED
    else:
        drift_state = (
            DRIFT_UNCHANGED
            if existing.schema_fingerprint == fingerprint
            else DRIFT_CHANGED
        )
        record = repository.record_repeat_data_resource_observation(
            existing,
            schema_fingerprint=fingerprint,
            drift_state=drift_state,
            observed_by=observed_by,
        )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=observed_by,
            event_type="data.resource.observed",
            payload={
                "asset_id": record.asset_id,
                "connector_id": connector_id,
                "resource_name": file_name,
                "drift_state": drift_state,
                "observation_count": record.observation_count,
            },
        )
    )
    return _observation_view(record), drift_state


def list_data_asset_resources(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    asset_id: str,
) -> DataAssetResourcesView:
    records = repository.list_data_resource_observations_by_asset(tenant_id, asset_id)
    return DataAssetResourcesView(
        tenant_id=tenant_id,
        asset_id=asset_id,
        resources=[_observation_view(record) for record in records],
        notes=[
            "Observations come from governed preview boundaries; only "
            "complete scans could ever prove a resource missing.",
        ],
    )
