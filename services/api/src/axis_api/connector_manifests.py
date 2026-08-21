from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from axis_api.audit import AuditEventCreate
from axis_api.connector_registry_composition import (
    connector_persisted_manifest_summary,
)
from axis_api.connectors import (
    ConnectorManifest,
    ConnectorPreviewSample,
    ConnectorRegistryItem,
    ConnectorRegistryOrigin,
    ConnectorRuntimePolicy,
    ManufacturingConnectorRegistry,
)
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    find_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorManifestCreate,
    ConnectorManifestLifecycleUpdate,
    PersistenceRecordNotFound,
)


class ConnectorManifestFieldError(BaseModel):
    field_path: str = Field(min_length=1)
    message: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ConnectorManifestValidationError(ValueError):
    def __init__(
        self,
        message: str,
        reason: str,
        errors: list[ConnectorManifestFieldError],
    ) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.errors = errors


class ConnectorManifestLifecycleValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorManifestConflict(ValueError):
    def __init__(self, connector_id: str) -> None:
        super().__init__("Connector manifest already exists")
        self.connector_id = connector_id


class ConnectorManifestRevisionConflict(ValueError):
    def __init__(
        self,
        connector_id: str,
        reason: str,
        *,
        current_revision_number: int | None = None,
    ) -> None:
        super().__init__("Connector manifest revision conflict")
        self.connector_id = connector_id
        self.reason = reason
        self.current_revision_number = current_revision_number


class ConnectorManifestNotFound(LookupError):
    pass


class ConnectorManifestQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorManifestRegistrationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any] = Field(default_factory=dict)
    runtime_policy: dict[str, Any] = Field(default_factory=dict)
    preview_sample: ConnectorPreviewSample | None = None
    notes: list[str] = Field(default_factory=list)


class ConnectorManifestCreateRequest(ConnectorManifestRegistrationDocument):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    registered_by: str = Field(min_length=1, max_length=160)


class ConnectorManifestReplaceRequest(ConnectorManifestRegistrationDocument):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    registered_by: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    # Optional preserves last-write-wins for callers that do not maintain revision state.
    expected_revision_number: int | None = Field(default=None, ge=1)


MANIFEST_VALIDATION_BATCH_LIMIT = 50
ConnectorManifestValidationOutcome = Literal[
    "would_register",
    "would_replace",
    "invalid",
]


class ConnectorManifestBatchValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    registered_by: str = Field(min_length=1, max_length=160)
    manifests: list[Any] = Field(
        min_length=1,
        json_schema_extra={"maxItems": MANIFEST_VALIDATION_BATCH_LIMIT},
    )


class ConnectorManifestValidationResult(BaseModel):
    connector_id: str | None = None
    outcome: ConnectorManifestValidationOutcome = Field(
        description=(
            "Dry-run disposition. `would_register` can be submitted to the apply "
            "endpoint; `would_replace` means that connector id already exists and "
            "the document can be submitted to the replacement endpoint; `invalid` "
            "means validation failed."
        )
    )
    errors: list[ConnectorManifestFieldError] = Field(default_factory=list)


class ConnectorManifestValidationSummary(BaseModel):
    would_register: int = Field(default=0, ge=0)
    would_replace: int = Field(default=0, ge=0)
    invalid: int = Field(default=0, ge=0)


class ConnectorManifestBatchValidationResponse(BaseModel):
    tenant_id: str = Field(min_length=1)
    results: list[ConnectorManifestValidationResult] = Field(default_factory=list)
    summary: ConnectorManifestValidationSummary


@dataclass(frozen=True)
class ValidatedConnectorManifestRegistration:
    manifest: ConnectorManifest
    runtime_policy: ConnectorRuntimePolicy
    preview_sample: ConnectorPreviewSample | None


class ConnectorManifestLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    transitioned_by: str = Field(min_length=1, max_length=160)
    target_status: str = Field(min_length=1, max_length=80)
    actor_scopes: list[str] = Field(default_factory=list)
    required_scope: str = Field(default="connectors:manifest:lifecycle", min_length=1)
    transition_reason: str = Field(min_length=1, max_length=600)
    evidence_refs: list[str] = Field(default_factory=list)


class ConnectorManifestRecordView(BaseModel):
    tenant_id: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    revision_number: int = Field(ge=1)
    display_name: str = Field(min_length=1)
    connector_type: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: str = Field(min_length=1)
    runtime_boundary: str = Field(min_length=1)
    registered_by: str = Field(min_length=1)
    manifest: dict[str, Any] = Field(default_factory=dict)
    runtime_policy: dict[str, Any] = Field(default_factory=dict)
    preview_sample: ConnectorPreviewSample | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    revises_revision_number: int | None = None
    replaced_by_revision_number: int | None = None
    revision_idempotency_key: str | None = None
    idempotent_replay: bool = False
    unchanged: bool = False
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ConnectorManifestDetail(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    current_revision: ConnectorManifestRecordView
    revisions: list[ConnectorManifestRecordView] = Field(min_length=1)


class ManufacturingConnectorManifestRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    manifests: list[ConnectorManifestRecordView] = Field(default_factory=list)
    manifest_notes: list[str] = Field(default_factory=list)


RAW_SECRET_FIELD_NAMES = {
    "api_key",
    "client_secret",
    "credential_value",
    "password",
    "secret",
    "token",
}

RAW_CONNECTION_FIELD_NAMES = {
    "connection_string",
    "database_url",
    "dsn",
    "host",
    "jdbc_url",
    "port",
}

RAW_QUERY_FIELD_NAMES = {
    "query",
    "raw_sql",
    "sql",
    "statement",
    "where_clause",
}

RAW_CONNECTION_MARKERS = ("postgres://", "postgresql://", "jdbc:")
RAW_QUERY_MARKERS = ("select ", "insert ", "update ", "delete ", "drop ")
MANIFEST_LIFECYCLE_SCOPE = "connectors:manifest:lifecycle"
LIVE_MANIFEST_ENABLE_SCOPE = "connectors:manifest:enable_live"
ACTIVE_LIVE_STATUS = "active_live"
MANIFEST_LIFECYCLE_TRANSITIONS = {
    "registered_preview_only": {"active_preview", "deprecated"},
    "active_preview": {ACTIVE_LIVE_STATUS, "deprecated"},
    ACTIVE_LIVE_STATUS: {"deprecated"},
    "deprecated": set(),
}
SUPPORTED_MANIFEST_LIFECYCLE_TARGETS = {
    "active_preview",
    ACTIVE_LIVE_STATUS,
    "deprecated",
}
UNSUPPORTED_LIVE_MANIFEST_TARGETS = {
    "enabled_live",
    "live_enabled",
    "production_enabled",
}
LIVE_MANIFEST_SYNC_MODES = {"live_query", "live_sync", "scheduled_sync"}
LIVE_MANIFEST_REQUIRED_ALLOWED_OPERATIONS = {"live_query", "external_egress"}
LIVE_MANIFEST_FORBIDDEN_BLOCKED_OPERATIONS = {"live_query", "external_egress"}
LIVE_MANIFEST_EVIDENCE_PREFIXES = {
    "approval": ("approval:",),
    "policy": ("policy:",),
    "credential": ("credential:", "secret:", "vault:"),
}


def build_connector_manifest_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorManifestQuery,
) -> ManufacturingConnectorManifestRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_connector_manifests(
        tenant_id=query.tenant_id,
        connector_id=query.connector_id,
        status=query.status,
        limit=query.limit,
    )
    manifests = [_record_from_persistence(record) for record in records]
    return ManufacturingConnectorManifestRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.READY if manifests else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Persisted Manifests",
                value=str(len(manifests)),
                detail="Tenant-scoped connector manifest records",
                status=OverviewStatus.READY if manifests else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Raw Material",
                value="Rejected",
                detail="DSNs, SQL text and credential values are blocked",
                status=OverviewStatus.READY,
            ),
            OverviewMetric(
                label="Live Sync",
                value="Not Enabled",
                detail="Persisting a manifest does not start connector execution",
                status=OverviewStatus.WATCH,
            ),
        ],
        manifests=manifests,
        manifest_notes=[
            "Persisted connector manifests are tenant-scoped metadata records.",
            "Registration writes audit evidence but does not enable live sync.",
            "Raw connection strings, SQL text and credential values are rejected.",
        ],
    )


def overlay_registered_connector_manifest(
    repository: AxisPersistenceRepository,
    registry: ManufacturingConnectorRegistry,
    tenant_id: str,
    connector_id: str,
) -> ManufacturingConnectorRegistry:
    record = repository.get_connector_manifest(tenant_id, connector_id)
    if record is None:
        return registry

    persistence = connector_persisted_manifest_summary(record)
    connectors: list[ConnectorRegistryItem] = []
    matched = False
    for connector in registry.connectors:
        if connector.manifest.connector_id != connector_id:
            connectors.append(connector)
            continue
        matched = True
        connectors.append(
            connector.model_copy(
                update={
                    "manifest": ConnectorManifest.model_validate(record.manifest_payload),
                    "runtime_policy": ConnectorRuntimePolicy.model_validate(
                        record.runtime_policy
                    ),
                    "preview_sample": (
                        ConnectorPreviewSample.model_validate(record.preview_sample)
                        if record.preview_sample is not None
                        else None
                    ),
                    "persisted_manifest": persistence,
                }
            )
        )
    if not matched:
        connectors.append(
            ConnectorRegistryItem(
                manifest=record.manifest_payload,
                runtime_policy=record.runtime_policy,
                preview_sample=record.preview_sample,
                connector_status=OverviewStatus.WATCH,
                registry_origin=ConnectorRegistryOrigin.PERSISTED_MANIFEST,
                persisted_manifest=persistence,
            )
        )
    return registry.model_copy(update={"connectors": connectors})


def record_demo_connector_manifest(
    repository: AxisPersistenceRepository,
    request: ConnectorManifestCreateRequest,
) -> ConnectorManifestRecordView:
    validated = validate_connector_manifest_registration(request)
    manifest = validated.manifest

    existing = repository.get_connector_manifest(request.tenant_id, manifest.connector_id)
    if existing is not None:
        raise ConnectorManifestConflict(existing.connector_id)

    manifest_payload = manifest.model_dump(mode="json")
    runtime_policy = validated.runtime_policy.model_dump(mode="json")
    preview_sample = (
        validated.preview_sample.model_dump(mode="json")
        if validated.preview_sample is not None
        else None
    )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.registered_by,
            event_type="connector.manifest.registered",
            payload={
                "connector_id": manifest.connector_id,
                "connector_type": manifest.connector_type,
                "source_type": manifest.source_type,
                "runtime_boundary": manifest.runtime_boundary,
                "sync_modes": manifest.sync_modes,
                "live_sync_enabled": "false",
            },
        )
    )
    record = repository.create_connector_manifest(
        ConnectorManifestCreate(
            tenant_id=request.tenant_id,
            connector_id=manifest.connector_id,
            revision_number=1,
            display_name=manifest.display_name,
            connector_type=manifest.connector_type,
            source_type=manifest.source_type,
            version=manifest.version,
            status="registered_preview_only",
            runtime_boundary=manifest.runtime_boundary,
            registered_by=request.registered_by,
            manifest_payload=manifest_payload,
            runtime_policy=runtime_policy,
            preview_sample=preview_sample,
            audit_event_id=audit_event.id,
            audit_event_type="connector.manifest.registered",
            notes=request.notes,
        )
    )
    return _record_from_persistence(record)


def replace_demo_connector_manifest(
    repository: AxisPersistenceRepository,
    request: ConnectorManifestReplaceRequest,
) -> ConnectorManifestRecordView:
    validated = validate_connector_manifest_registration(
        ConnectorManifestCreateRequest(
            tenant_id=request.tenant_id,
            registered_by=request.registered_by,
            manifest=request.manifest,
            runtime_policy=request.runtime_policy,
            preview_sample=(
                request.preview_sample.model_dump(mode="json")
                if request.preview_sample is not None
                else None
            ),
            notes=request.notes,
        )
    )
    manifest = validated.manifest
    manifest_payload = manifest.model_dump(mode="json")
    runtime_policy = validated.runtime_policy.model_dump(mode="json")
    submitted_preview_sample = (
        validated.preview_sample.model_dump(mode="json")
        if validated.preview_sample is not None
        else None
    )
    preview_sample_was_provided = "preview_sample" in request.model_fields_set

    existing_replay = repository.get_connector_manifest_by_revision_idempotency_key(
        request.tenant_id,
        request.idempotency_key,
    )
    if existing_replay is not None:
        replay_preview_sample = (
            submitted_preview_sample
            if preview_sample_was_provided
            else existing_replay.preview_sample
        )
        if existing_replay.connector_id != manifest.connector_id or not (
            existing_replay.manifest_payload == manifest_payload
            and existing_replay.runtime_policy == runtime_policy
            and existing_replay.preview_sample == replay_preview_sample
            and existing_replay.notes == request.notes
        ):
            raise ConnectorManifestRevisionConflict(
                manifest.connector_id,
                "revision_idempotency_conflict",
            )
        return _record_from_persistence(existing_replay, idempotent_replay=True)

    current_manifest = repository.get_connector_manifest(
        request.tenant_id,
        manifest.connector_id,
    )
    if current_manifest is None:
        raise ConnectorManifestNotFound()
    preview_sample = (
        submitted_preview_sample
        if preview_sample_was_provided
        else current_manifest.preview_sample
    )
    if (
        request.expected_revision_number is not None
        and request.expected_revision_number != current_manifest.revision_number
    ):
        raise ConnectorManifestRevisionConflict(
            manifest.connector_id,
            "expected_revision_mismatch",
            current_revision_number=current_manifest.revision_number,
        )
    if (
        current_manifest.manifest_payload == manifest_payload
        and current_manifest.runtime_policy == runtime_policy
        and current_manifest.preview_sample == preview_sample
        and current_manifest.notes == request.notes
    ):
        return _record_from_persistence(current_manifest, unchanged=True)

    revision_number = current_manifest.revision_number + 1
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.registered_by,
            event_type="connector.manifest.replaced",
            payload={
                "connector_id": manifest.connector_id,
                "manifest_version": manifest.version,
                "previous_manifest_version": current_manifest.version,
                "revision_number": revision_number,
                "revises_revision_number": current_manifest.revision_number,
                "display_name": manifest.display_name,
                "connector_type": manifest.connector_type,
                "source_type": manifest.source_type,
                "runtime_boundary": manifest.runtime_boundary,
                "status": "registered_preview_only",
                "idempotency_key": request.idempotency_key,
                "preview_sample_action": (
                    "preserved"
                    if not preview_sample_was_provided
                    else "cleared"
                    if submitted_preview_sample is None
                    else "replaced"
                ),
            },
        )
    )
    revised_manifest = repository.append_connector_manifest_revision(
        current_manifest,
        ConnectorManifestCreate(
            tenant_id=request.tenant_id,
            connector_id=manifest.connector_id,
            revision_number=revision_number,
            display_name=manifest.display_name,
            connector_type=manifest.connector_type,
            source_type=manifest.source_type,
            version=manifest.version,
            status="registered_preview_only",
            runtime_boundary=manifest.runtime_boundary,
            registered_by=request.registered_by,
            manifest_payload=manifest_payload,
            runtime_policy=runtime_policy,
            preview_sample=preview_sample,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            revises_revision_number=current_manifest.revision_number,
            revision_idempotency_key=request.idempotency_key,
            notes=request.notes,
        ),
    )
    return _record_from_persistence(revised_manifest)


def get_connector_manifest_detail(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str,
) -> ConnectorManifestDetail:
    revisions = repository.list_connector_manifest_revisions(tenant_id, connector_id)
    if not revisions:
        raise ConnectorManifestNotFound()
    records = [_record_from_persistence(revision) for revision in revisions]
    current_revision = next(
        (
            record
            for record in reversed(records)
            if record.replaced_by_revision_number is None
        ),
        records[-1],
    )
    return ConnectorManifestDetail(
        tenant_id=tenant_id,
        connector_id=connector_id,
        current_revision=current_revision,
        revisions=records,
    )


def validate_connector_manifest_registration(
    request: ConnectorManifestCreateRequest,
) -> ValidatedConnectorManifestRegistration:
    errors = _public_safe_manifest_errors(request)
    validated_models: dict[str, BaseModel] = {}
    model_specs = (
        ("manifest", ConnectorManifest, request.manifest, "invalid_manifest_payload"),
        (
            "runtime_policy",
            ConnectorRuntimePolicy,
            request.runtime_policy,
            "invalid_runtime_policy_payload",
        ),
    )
    for field_name, model_type, payload, reason in model_specs:
        try:
            validated_models[field_name] = model_type.model_validate(payload)
        except ValidationError as exc:
            errors.extend(_pydantic_field_errors(exc, prefix=field_name, reason=reason))

    preview_sample: ConnectorPreviewSample | None = None
    if request.preview_sample is not None:
        try:
            preview_sample = ConnectorPreviewSample.model_validate(request.preview_sample)
        except ValidationError as exc:
            errors.extend(
                _pydantic_field_errors(
                    exc,
                    prefix="preview_sample",
                    reason="invalid_preview_sample_payload",
                )
            )

    if errors:
        first_error = errors[0]
        raise ConnectorManifestValidationError(
            _validation_message(first_error.reason),
            first_error.reason,
            errors,
        )

    return ValidatedConnectorManifestRegistration(
        manifest=validated_models["manifest"],
        runtime_policy=validated_models["runtime_policy"],
        preview_sample=preview_sample,
    )


def validate_connector_manifest_batch(
    repository: AxisPersistenceRepository,
    request: ConnectorManifestBatchValidationRequest,
) -> ConnectorManifestBatchValidationResponse:
    connector_ids = [_connector_id_from_document(document) for document in request.manifests]
    duplicate_ids = {
        connector_id
        for connector_id, count in Counter(connector_ids).items()
        if connector_id is not None and count > 1
    }
    results: list[ConnectorManifestValidationResult] = []

    for document, connector_id in zip(request.manifests, connector_ids, strict=True):
        errors: list[ConnectorManifestFieldError] = []
        registration_request: ConnectorManifestCreateRequest | None = None
        try:
            registration_document = ConnectorManifestRegistrationDocument.model_validate(
                document
            )
            registration_request = ConnectorManifestCreateRequest(
                tenant_id=request.tenant_id,
                registered_by=request.registered_by,
                **registration_document.model_dump(),
            )
            validated = validate_connector_manifest_registration(registration_request)
            connector_id = validated.manifest.connector_id
        except ValidationError as exc:
            errors.extend(
                _pydantic_field_errors(
                    exc,
                    reason="invalid_manifest_registration_document",
                )
            )
        except ConnectorManifestValidationError as exc:
            errors.extend(exc.errors)

        if connector_id in duplicate_ids:
            errors.append(
                ConnectorManifestFieldError(
                    field_path="manifest.connector_id",
                    message=(
                        "Duplicate connector_id within this manifest validation request."
                    ),
                    reason="duplicate_connector_id",
                )
            )

        if errors or registration_request is None:
            results.append(
                ConnectorManifestValidationResult(
                    connector_id=connector_id,
                    outcome="invalid",
                    errors=errors,
                )
            )
            continue

        existing = repository.get_connector_manifest(request.tenant_id, connector_id)
        results.append(
            ConnectorManifestValidationResult(
                connector_id=connector_id,
                outcome=(
                    "would_replace" if existing is not None else "would_register"
                ),
            )
        )

    summary_counts = Counter(result.outcome for result in results)
    return ConnectorManifestBatchValidationResponse(
        tenant_id=request.tenant_id,
        results=results,
        summary=ConnectorManifestValidationSummary(
            would_register=summary_counts["would_register"],
            would_replace=summary_counts["would_replace"],
            invalid=summary_counts["invalid"],
        ),
    )


def transition_demo_connector_manifest_lifecycle(
    repository: AxisPersistenceRepository,
    connector_id: str,
    request: ConnectorManifestLifecycleRequest,
) -> ConnectorManifestRecordView:
    required_scopes = _required_scopes_for_target(
        request.target_status,
        request.required_scope,
    )
    missing_scopes = [
        required_scope
        for required_scope in required_scopes
        if required_scope not in request.actor_scopes
    ]
    if missing_scopes:
        reason = _missing_scope_reason(missing_scopes)
        raise ConnectorManifestLifecycleValidationError(
            "Connector manifest lifecycle transition requires lifecycle scope.",
            reason,
        )
    if request.target_status in UNSUPPORTED_LIVE_MANIFEST_TARGETS:
        raise ConnectorManifestLifecycleValidationError(
            "Connector manifest lifecycle cannot enable live connector operation.",
            "unsupported_manifest_lifecycle_target",
        )
    if request.target_status not in SUPPORTED_MANIFEST_LIFECYCLE_TARGETS:
        raise ConnectorManifestLifecycleValidationError(
            "Connector manifest lifecycle target is not supported.",
            "unsupported_manifest_lifecycle_target",
        )

    manifest = repository.get_connector_manifest(request.tenant_id, connector_id)
    if manifest is None:
        raise ConnectorManifestLifecycleValidationError(
            "Connector manifest was not found.",
            "manifest_not_found",
        )
    allowed_targets = MANIFEST_LIFECYCLE_TRANSITIONS.get(manifest.status, set())
    if request.target_status not in allowed_targets:
        raise ConnectorManifestLifecycleValidationError(
            "Connector manifest lifecycle transition is not allowed.",
            "manifest_lifecycle_transition_not_allowed",
        )
    if request.target_status == ACTIVE_LIVE_STATUS:
        _validate_live_manifest_enablement(manifest, request)

    audit_event_type = (
        "connector.manifest.live_enabled"
        if request.target_status == ACTIVE_LIVE_STATUS
        else "connector.manifest.lifecycle_transitioned"
    )
    live_sync_enabled = "true" if request.target_status == ACTIVE_LIVE_STATUS else "false"
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.transitioned_by,
            event_type=audit_event_type,
            payload={
                "connector_id": connector_id,
                "from_status": manifest.status,
                "target_status": request.target_status,
                "required_scope": required_scopes[-1],
                "required_scopes": required_scopes,
                "transition_reason": request.transition_reason,
                "evidence_refs": request.evidence_refs,
                "live_sync_enabled": live_sync_enabled,
                "external_sync_started": "false",
            },
        )
    )
    try:
        updated = repository.update_connector_manifest_lifecycle(
            ConnectorManifestLifecycleUpdate(
                tenant_id=request.tenant_id,
                connector_id=connector_id,
                status=request.target_status,
                audit_event_id=audit_event.id,
                audit_event_type=audit_event_type,
                note=f"Lifecycle transition: {request.target_status}",
            )
        )
    except PersistenceRecordNotFound as exc:
        raise ConnectorManifestLifecycleValidationError(
            "Connector manifest was not found.",
            "manifest_not_found",
        ) from exc
    return _record_from_persistence(updated)


def _required_scopes_for_target(target_status: str, default_scope: str) -> list[str]:
    if target_status == ACTIVE_LIVE_STATUS:
        return [MANIFEST_LIFECYCLE_SCOPE, LIVE_MANIFEST_ENABLE_SCOPE]
    return [default_scope]


def _missing_scope_reason(missing_scopes: list[str]) -> str:
    if LIVE_MANIFEST_ENABLE_SCOPE in missing_scopes:
        return "missing_manifest_live_scope"
    return "missing_manifest_lifecycle_scope"


def _validate_live_manifest_enablement(
    manifest,
    request: ConnectorManifestLifecycleRequest,
) -> None:
    manifest_payload = manifest.manifest_payload or {}
    runtime_policy = manifest.runtime_policy or {}
    sync_modes = set(manifest_payload.get("sync_modes") or [])
    allowed_operations = set(runtime_policy.get("allowed_operations") or [])
    blocked_operations = set(runtime_policy.get("blocked_operations") or [])

    if not sync_modes.intersection(LIVE_MANIFEST_SYNC_MODES):
        raise ConnectorManifestLifecycleValidationError(
            "Connector manifest must declare a live sync mode before active_live.",
            "manifest_live_sync_mode_missing",
        )
    missing_allowed_operations = sorted(
        LIVE_MANIFEST_REQUIRED_ALLOWED_OPERATIONS - allowed_operations
    )
    if missing_allowed_operations:
        raise ConnectorManifestLifecycleValidationError(
            "Connector runtime policy must explicitly allow live connector operations.",
            "manifest_runtime_policy_missing_live_operations",
        )
    blocked_live_operations = sorted(
        LIVE_MANIFEST_FORBIDDEN_BLOCKED_OPERATIONS.intersection(blocked_operations)
    )
    if blocked_live_operations:
        blocked_operation = blocked_live_operations[0]
        reason = (
            "manifest_runtime_policy_blocks_live_query"
            if blocked_operation == "live_query"
            else "manifest_runtime_policy_blocks_external_egress"
        )
        raise ConnectorManifestLifecycleValidationError(
            "Connector runtime policy still blocks a required live operation.",
            reason,
        )
    egress_policy = str(runtime_policy.get("egress_policy", "")).strip().lower()
    if egress_policy in {"", "none", "no-external-egress"}:
        raise ConnectorManifestLifecycleValidationError(
            "Connector runtime policy must name the reviewed live egress boundary.",
            "manifest_runtime_policy_missing_live_egress_boundary",
        )
    if not _has_required_live_evidence(request.evidence_refs):
        raise ConnectorManifestLifecycleValidationError(
            "Connector live enablement requires approval, policy and credential evidence.",
            "manifest_live_evidence_incomplete",
        )


def _has_required_live_evidence(evidence_refs: list[str]) -> bool:
    normalized_refs = [evidence_ref.strip().lower() for evidence_ref in evidence_refs]
    return all(
        any(evidence_ref.startswith(prefixes) for evidence_ref in normalized_refs)
        for prefixes in LIVE_MANIFEST_EVIDENCE_PREFIXES.values()
    )


def _record_from_persistence(
    record,
    *,
    idempotent_replay: bool = False,
    unchanged: bool = False,
) -> ConnectorManifestRecordView:
    return ConnectorManifestRecordView(
        tenant_id=record.tenant_id,
        manifest_id=str(record.id),
        connector_id=record.connector_id,
        revision_number=record.revision_number,
        display_name=record.display_name,
        connector_type=record.connector_type,
        source_type=record.source_type,
        version=record.version,
        status=record.status,
        runtime_boundary=record.runtime_boundary,
        registered_by=record.registered_by,
        manifest=record.manifest_payload,
        runtime_policy=record.runtime_policy,
        preview_sample=record.preview_sample,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        revises_revision_number=record.revises_revision_number,
        replaced_by_revision_number=record.replaced_by_revision_number,
        revision_idempotency_key=record.revision_idempotency_key,
        idempotent_replay=idempotent_replay,
        unchanged=unchanged,
        notes=record.notes,
        created_at=record.created_at,
    )


def _public_safe_manifest_errors(
    request: ConnectorManifestCreateRequest,
) -> list[ConnectorManifestFieldError]:
    payload = request.model_dump(mode="json")
    entries = list(_walk_payload(payload))
    errors: list[ConnectorManifestFieldError] = []
    checks = (
        (
            RAW_CONNECTION_FIELD_NAMES,
            RAW_CONNECTION_MARKERS,
            "raw_connection_field",
            "Connector manifest cannot include raw connection material.",
        ),
        (
            RAW_QUERY_FIELD_NAMES,
            RAW_QUERY_MARKERS,
            "raw_query_field",
            "Connector manifest cannot include raw SQL or query text.",
        ),
        (
            RAW_SECRET_FIELD_NAMES,
            (),
            "raw_secret_field",
            "Connector manifest cannot include raw credential material.",
        ),
    )
    for blocked_keys, blocked_markers, reason, message in checks:
        matching_paths = {
            path
            for path, key, value in entries
            if key in blocked_keys
            or any(marker in value for marker in blocked_markers)
        }
        errors.extend(
            ConnectorManifestFieldError(
                field_path=path,
                message=message,
                reason=reason,
            )
            for path in sorted(matching_paths)
        )
    return errors


def _walk_payload(
    value: Any,
    path: str = "$",
) -> Iterator[tuple[str, str, str]]:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized_key = str(key).lower()
            nested_path = f"{path}.{key}" if path != "$" else str(key)
            yield nested_path, normalized_key, ""
            yield from _walk_payload(nested_value, nested_path)
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            yield from _walk_payload(nested_value, f"{path}[{index}]")
    elif value is not None:
        yield path, "", str(value).lower()


def _pydantic_field_errors(
    error: ValidationError,
    *,
    reason: str,
    prefix: str | None = None,
) -> list[ConnectorManifestFieldError]:
    return [
        ConnectorManifestFieldError(
            field_path=_field_path(validation_error["loc"], prefix=prefix),
            message=validation_error["msg"],
            reason=reason,
        )
        for validation_error in error.errors()
    ]


def _field_path(location: tuple[Any, ...], *, prefix: str | None = None) -> str:
    path = prefix or "$"
    for part in location:
        if isinstance(part, int):
            path = f"{path}[{part}]"
        elif path == "$":
            path = str(part)
        else:
            path = f"{path}.{part}"
    return path


def _validation_message(reason: str) -> str:
    return {
        "raw_connection_field": (
            "Connector manifest cannot include raw connection material."
        ),
        "raw_query_field": "Connector manifest cannot include raw SQL or query text.",
        "raw_secret_field": (
            "Connector manifest cannot include raw credential material."
        ),
        "invalid_manifest_payload": "Connector manifest payload is invalid.",
        "invalid_runtime_policy_payload": (
            "Connector runtime policy payload is invalid."
        ),
        "invalid_preview_sample_payload": (
            "Connector preview sample payload is invalid."
        ),
    }[reason]


def _connector_id_from_document(document: Any) -> str | None:
    if not isinstance(document, dict):
        return None
    manifest = document.get("manifest")
    if not isinstance(manifest, dict):
        return None
    connector_id = manifest.get("connector_id")
    if not isinstance(connector_id, str) or not connector_id.strip():
        return None
    return connector_id
