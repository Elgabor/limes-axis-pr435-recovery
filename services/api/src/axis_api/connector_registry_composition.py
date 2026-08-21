from axis_api.connectors import ConnectorPersistedManifestSummary
from axis_api.models import ConnectorManifestRecord


def connector_persisted_manifest_summary(
    record: ConnectorManifestRecord,
) -> ConnectorPersistedManifestSummary:
    """Expose current persistence metadata without repeating a manifest payload."""

    return ConnectorPersistedManifestSummary(
        manifest_id=str(record.id),
        revision_number=record.revision_number,
        status=record.status,
        registered_by=record.registered_by,
        registered_at=record.created_at,
        notes=record.notes,
    )
