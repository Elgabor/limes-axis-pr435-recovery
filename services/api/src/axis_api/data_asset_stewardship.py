"""Persistent stewardship declarations for data assets.

Stewardship attributes (owner, classification, residency, retention) are
declared by operators and never inferred. Declarations are append-only
revisions bound to the asset identity minted by the catalog, serialized by an
advisory transaction lock so concurrent replicas cannot both observe the same
current revision.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from axis_api.connector_reference import get_persisted_manufacturing_connector_registry
from axis_api.data_assets import (
    DataAssetStewardshipSummary,
    data_asset_id_for_connector,
)
from axis_api.persistence import (
    AuditEventCreate,
    AxisPersistenceRepository,
    DataAssetStewardshipCreate,
)


class DataAssetClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class DataAssetNotFound(LookupError):
    def __init__(self, tenant_id: str, asset_id: str) -> None:
        super().__init__(
            f"Data asset {asset_id!r} is not part of tenant {tenant_id!r} catalog"
        )
        self.tenant_id = tenant_id
        self.asset_id = asset_id


class DataAssetStewardshipConflict(ValueError):
    def __init__(
        self,
        asset_id: str,
        reason: str,
        *,
        current_revision_number: int | None = None,
    ) -> None:
        super().__init__(f"Data asset stewardship conflict: {reason}")
        self.asset_id = asset_id
        self.reason = reason
        self.current_revision_number = current_revision_number


class DataAssetStewardshipDeclarationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=1, max_length=200)
    classification: DataAssetClassification
    residency: str = Field(min_length=1, max_length=80)
    retention: str = Field(min_length=1, max_length=80)
    notes: list[str] = Field(default_factory=list)
    expected_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    declared_by: str | None = Field(default=None, min_length=1)


class DataAssetStewardshipRecord(BaseModel):
    owner: str = Field(min_length=1)
    classification: DataAssetClassification
    residency: str = Field(min_length=1)
    retention: str = Field(min_length=1)
    notes: list[str]
    revision_number: int = Field(ge=1)
    declared_by: str = Field(min_length=1)
    declared_at: datetime


class DataAssetStewardshipView(BaseModel):
    tenant_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    stewardship: DataAssetStewardshipRecord | None


def _fingerprint(request: DataAssetStewardshipDeclarationRequest) -> tuple:
    return (
        request.owner,
        request.classification.value,
        request.residency,
        request.retention,
        list(request.notes),
    )


def _fingerprint_of_record(record) -> tuple:
    return (
        record.owner,
        record.classification,
        record.residency,
        record.retention,
        list(record.notes),
    )


def _record_view(record) -> DataAssetStewardshipRecord:
    return DataAssetStewardshipRecord(
        owner=record.owner,
        classification=DataAssetClassification(record.classification),
        residency=record.residency,
        retention=record.retention,
        notes=list(record.notes),
        revision_number=record.revision_number,
        declared_by=record.declared_by,
        declared_at=record.created_at,
    )


def stewardship_summary_for_asset(
    record,
) -> DataAssetStewardshipSummary:
    """Project a persisted record into the catalog's metadata-only summary."""

    return DataAssetStewardshipSummary(
        owner=record.owner,
        classification=record.classification,
        residency=record.residency,
        retention=record.retention,
        revision_number=record.revision_number,
    )


def ensure_data_asset_in_catalog(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    asset_id: str,
) -> None:
    """Fail closed when stewardship targets an asset outside the catalog."""

    registry = get_persisted_manufacturing_connector_registry(
        repository,
        tenant_id=tenant_id,
    )
    known_asset_ids = {
        data_asset_id_for_connector(item.manifest.connector_id)
        for item in registry.connectors
    }
    if asset_id not in known_asset_ids:
        raise DataAssetNotFound(tenant_id, asset_id)


def resolve_declared_by(
    request: DataAssetStewardshipDeclarationRequest,
    principal_actor_id: str | None,
) -> str:
    """The verified principal owns the declaration when one is present."""

    if principal_actor_id is not None:
        return principal_actor_id
    if request.declared_by is not None:
        return request.declared_by
    return "public-demo-steward"


def declare_data_asset_stewardship(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    asset_id: str,
    request: DataAssetStewardshipDeclarationRequest,
    principal_actor_id: str | None,
) -> tuple[DataAssetStewardshipRecord, str]:
    """Declare or update stewardship for one catalogued asset.

    Returns the current record and one of ``created`` (first declaration),
    ``updated`` (new revision), ``unchanged`` (identical current declaration)
    or ``replayed`` (same idempotency key).
    """
    repository.acquire_data_asset_stewardship_lock(
        tenant_id=tenant_id,
        asset_id=asset_id,
    )

    submitted_fingerprint = _fingerprint(request)
    existing_replay = repository.get_data_asset_stewardship_by_revision_idempotency_key(
        tenant_id,
        request.idempotency_key,
    )
    if existing_replay is not None:
        if existing_replay.asset_id != asset_id or _fingerprint_of_record(
            existing_replay
        ) != submitted_fingerprint:
            raise DataAssetStewardshipConflict(
                asset_id,
                "revision_idempotency_conflict",
            )
        return _record_view(existing_replay), "replayed"

    current = repository.get_current_data_asset_stewardship(tenant_id, asset_id)
    declared_by = resolve_declared_by(request, principal_actor_id)

    if current is not None:
        if (
            request.expected_revision is None
            or request.expected_revision != current.revision_number
        ):
            raise DataAssetStewardshipConflict(
                asset_id,
                "expected_revision_mismatch",
                current_revision_number=current.revision_number,
            )
        if _fingerprint_of_record(current) == submitted_fingerprint:
            return _record_view(current), "unchanged"

    is_first_declaration = current is None
    revision_number = 1 if is_first_declaration else current.revision_number + 1
    audit_event_type = (
        "data.stewardship.declared" if is_first_declaration else "data.stewardship.updated"
    )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=declared_by,
            event_type=audit_event_type,
            payload={
                "asset_id": asset_id,
                "classification": request.classification.value,
                "revision_number": revision_number,
                "revises_revision_number": (
                    None if is_first_declaration else current.revision_number
                ),
                "idempotency_key": request.idempotency_key,
            },
        )
    )
    record_payload = DataAssetStewardshipCreate(
        tenant_id=tenant_id,
        asset_id=asset_id,
        revision_number=revision_number,
        owner=request.owner,
        classification=request.classification.value,
        residency=request.residency,
        retention=request.retention,
        declared_by=declared_by,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event_type,
        revises_revision_number=(
            None if is_first_declaration else current.revision_number
        ),
        replaced_by_revision_number=None,
        revision_idempotency_key=request.idempotency_key,
        notes=list(request.notes),
    )
    if is_first_declaration:
        record = repository.create_data_asset_stewardship_record(record_payload)
    else:
        record = repository.append_data_asset_stewardship_revision(
            current,
            record_payload,
        )
    return _record_view(record), "created" if is_first_declaration else "updated"


def get_data_asset_stewardship_view(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    asset_id: str,
) -> DataAssetStewardshipView:
    record = repository.get_current_data_asset_stewardship(tenant_id, asset_id)
    return DataAssetStewardshipView(
        tenant_id=tenant_id,
        asset_id=asset_id,
        stewardship=_record_view(record) if record is not None else None,
    )
