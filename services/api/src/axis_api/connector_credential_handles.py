from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from axis_api.audit import AuditEventCreate
from axis_api.connector_reference import require_persisted_manufacturing_connector_registry
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    find_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.models import utc_now
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialHandleCreate,
    ConnectorCredentialRotationCreate,
    PersistenceRecordNotFound,
)


class ConnectorCredentialHandleValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorCredentialHandleQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorCredentialHandleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    handle_id: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=200)
    secret_provider: str = Field(min_length=1, max_length=120)
    secret_ref: str = Field(min_length=1, max_length=500)
    purpose: str = Field(min_length=1, max_length=160)
    rotation_interval_days: int = Field(default=30, ge=1, le=3660)
    created_by: str = Field(min_length=1, max_length=160)
    labels: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ConnectorCredentialRotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    rotated_by: str = Field(min_length=1, max_length=160)
    rotated_at: datetime | None = None
    evidence_ref: str = Field(min_length=1, max_length=240)
    notes: list[str] = Field(default_factory=list)


class ConnectorCredentialRotationRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    handle_id: str = Field(min_length=1)
    rotated_by: str = Field(min_length=1)
    rotated_at: datetime
    evidence_ref: str = Field(min_length=1)
    status: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorCredentialHandleRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    handle_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    status: str = Field(min_length=1)
    secret_provider: str = Field(min_length=1)
    secret_ref: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    rotation_interval_days: int
    rotation_status: str = Field(min_length=1)
    rotation_count: int
    last_rotated_at: datetime | None = None
    next_rotation_due_at: datetime | None = None
    created_by: str = Field(min_length=1)
    labels: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    last_rotation: ConnectorCredentialRotationRecord | None = None


class ManufacturingConnectorCredentialHandleRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    handles: list[ConnectorCredentialHandleRecord] = Field(default_factory=list)
    handle_notes: list[str] = Field(default_factory=list)


ALLOWED_SECRET_REF_PREFIXES = (
    "vault://",
    "external-secret://",
    "kms://",
    "env://",
    "aws-secrets-manager://",
    "gcp-secret-manager://",
    "azure-key-vault://",
)
RAW_SECRET_MARKERS = (
    "api_key=",
    "client_secret=",
    "credential_value",
    "literal-password",
    "password=",
    "secret_value",
    "token=",
)


def build_connector_credential_handle_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorCredentialHandleQuery,
) -> ManufacturingConnectorCredentialHandleRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_connector_credential_handles(
        tenant_id=query.tenant_id,
        connector_id=query.connector_id,
        status=query.status,
        limit=query.limit,
    )
    handles = [
        _credential_handle_from_record(
            record,
            repository.list_connector_credential_rotations(
                query.tenant_id,
                record.handle_id,
                limit=25,
            ),
        )
        for record in records
    ]
    rotation_due = sum(1 for handle in handles if handle.rotation_status == "rotation_due")
    return ManufacturingConnectorCredentialHandleRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.READY if handles else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Credential Handles",
                value=str(len(handles)),
                detail="External secret references stored as metadata only",
                status=OverviewStatus.READY if handles else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Rotation Due",
                value=str(rotation_due),
                detail="Handles needing rotation review",
                status=OverviewStatus.WATCH if rotation_due else OverviewStatus.READY,
            ),
            OverviewMetric(
                label="Raw Values",
                value="Never Stored",
                detail="Axis stores references, not credential material",
                status=OverviewStatus.READY,
            ),
        ],
        handles=handles,
        handle_notes=[
            "Credential handles point to external secret managers or local dev refs.",
            "Rotation updates metadata and history without storing raw credential values.",
            "Connector run execution remains future work.",
        ],
    )


def record_demo_connector_credential_handle(
    repository: AxisPersistenceRepository,
    request: ConnectorCredentialHandleCreateRequest,
) -> ConnectorCredentialHandleRecord:
    _validate_secret_ref(request.secret_ref)
    _active_preview_manifest_for_connector(repository, request.tenant_id, request.connector_id)
    last_rotated_at = utc_now()
    next_rotation_due_at = last_rotated_at + timedelta(days=request.rotation_interval_days)
    record = repository.create_connector_credential_handle(
        ConnectorCredentialHandleCreate(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            handle_id=request.handle_id,
            display_name=request.display_name,
            status="active",
            secret_provider=request.secret_provider,
            secret_ref=request.secret_ref,
            purpose=request.purpose,
            rotation_interval_days=request.rotation_interval_days,
            last_rotated_at=last_rotated_at,
            next_rotation_due_at=next_rotation_due_at,
            created_by=request.created_by,
            labels=request.labels,
            notes=request.notes,
        )
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.created_by,
            event_type="connector.credential_handle.created",
            payload={
                "connector_id": request.connector_id,
                "handle_id": request.handle_id,
                "secret_provider": request.secret_provider,
                "purpose": request.purpose,
                "rotation_interval_days": request.rotation_interval_days,
            },
        )
    )
    return _credential_handle_from_record(record, [])


def record_demo_connector_credential_rotation(
    repository: AxisPersistenceRepository,
    handle_id: str,
    request: ConnectorCredentialRotationRequest,
) -> ConnectorCredentialHandleRecord:
    rotated_at = request.rotated_at or utc_now()
    try:
        rotation = repository.record_connector_credential_rotation(
            ConnectorCredentialRotationCreate(
                tenant_id=request.tenant_id,
                handle_id=handle_id,
                rotated_by=request.rotated_by,
                rotated_at=rotated_at,
                evidence_ref=request.evidence_ref,
                status="rotated",
                notes=request.notes,
            )
        )
    except PersistenceRecordNotFound as exc:
        raise ConnectorCredentialHandleValidationError(
            "Connector credential handle not found.",
            "credential_handle_not_found",
        ) from exc

    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.rotated_by,
            event_type="connector.credential_handle.rotated",
            payload={
                "handle_id": handle_id,
                "evidence_ref": request.evidence_ref,
                "status": "rotated",
            },
        )
    )
    handle = repository.get_connector_credential_handle(request.tenant_id, handle_id)
    if handle is None:
        raise ConnectorCredentialHandleValidationError(
            "Connector credential handle not found.",
            "credential_handle_not_found",
        )
    return _credential_handle_from_record(handle, [rotation])


def _credential_handle_from_record(record, rotations) -> ConnectorCredentialHandleRecord:
    rotation_records = [_rotation_from_record(rotation) for rotation in rotations]
    last_rotation = rotation_records[0] if rotation_records else None
    return ConnectorCredentialHandleRecord(
        tenant_id=record.tenant_id,
        connector_id=record.connector_id,
        handle_id=record.handle_id,
        display_name=record.display_name,
        status=record.status,
        secret_provider=record.secret_provider,
        secret_ref=record.secret_ref,
        purpose=record.purpose,
        rotation_interval_days=record.rotation_interval_days,
        rotation_status=_rotation_status(record),
        rotation_count=len(rotation_records),
        last_rotated_at=_optional_aware_datetime(record.last_rotated_at),
        next_rotation_due_at=_optional_aware_datetime(record.next_rotation_due_at),
        created_by=record.created_by,
        labels=record.labels,
        notes=record.notes,
        last_rotation=last_rotation,
    )


def _rotation_from_record(record) -> ConnectorCredentialRotationRecord:
    return ConnectorCredentialRotationRecord(
        tenant_id=record.tenant_id,
        handle_id=record.handle_id,
        rotated_by=record.rotated_by,
        rotated_at=_aware_datetime(record.rotated_at),
        evidence_ref=record.evidence_ref,
        status=record.status,
        notes=record.notes,
    )


def _rotation_status(record) -> str:
    if record.status != "active":
        return record.status
    if record.next_rotation_due_at is not None and _aware_datetime(
        record.next_rotation_due_at
    ) < utc_now():
        return "rotation_due"
    return "healthy"


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def _optional_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _aware_datetime(value)


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
    raise ConnectorCredentialHandleValidationError(
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
        raise ConnectorCredentialHandleValidationError(
            "Connector manifest must be registered before credential handle creation.",
            "connector_manifest_not_found",
        )
    if manifest.status != "active_preview":
        raise ConnectorCredentialHandleValidationError(
            "Connector manifest must be active_preview before credential handle creation.",
            "connector_manifest_not_active_preview",
        )
    return manifest


def _validate_secret_ref(secret_ref: str) -> None:
    normalized = secret_ref.strip().lower()
    if not normalized.startswith(ALLOWED_SECRET_REF_PREFIXES):
        raise ConnectorCredentialHandleValidationError(
            "Credential handles must reference an external secret manager or dev secret ref.",
            "invalid_secret_ref",
        )
    if any(marker in normalized for marker in RAW_SECRET_MARKERS):
        raise ConnectorCredentialHandleValidationError(
            "Credential handles cannot include inline credential values.",
            "raw_secret_value",
        )
