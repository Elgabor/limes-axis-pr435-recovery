import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from enum import StrEnum
from io import StringIO

from pydantic import BaseModel, ConfigDict, Field, model_validator

from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import ManufacturingResponseProvenance


def csv_header_fingerprint(columns: list[str]) -> str:
    """Stable SHA-256 over the trimmed header names; metadata only."""

    normalized = json.dumps(
        [column.strip() for column in columns],
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class ConnectorObservedSchema(BaseModel):
    """Header names actually observed on a source file, never row values."""

    columns: list[str] = Field(default_factory=list)
    fingerprint: str = Field(min_length=64, max_length=64)


class ConnectorCredentialRequirements(BaseModel):
    storage: str = Field(min_length=1)
    required_secret_refs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConnectorSchemaField(BaseModel):
    source_column: str = Field(min_length=1)
    target_field: str = Field(min_length=1)
    ontology_target: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    required: bool
    description: str = Field(min_length=1)


class ConnectorManifest(BaseModel):
    connector_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    connector_type: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    sync_modes: list[str] = Field(default_factory=list)
    runtime_boundary: str = Field(min_length=1)
    required_permissions: list[str] = Field(default_factory=list)
    credential_requirements: ConnectorCredentialRequirements
    schema_fields: list[ConnectorSchemaField] = Field(default_factory=list)
    mapping_notes: list[str] = Field(default_factory=list)


class ConnectorRuntimePolicy(BaseModel):
    allowed_operations: list[str] = Field(default_factory=list)
    blocked_operations: list[str] = Field(default_factory=list)
    egress_policy: str = Field(min_length=1)
    max_file_size_mb: int = Field(ge=1)
    row_limit: int = Field(ge=1)
    payload_policy: str = Field(min_length=1)


class ConnectorPreviewSample(BaseModel):
    file_name: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    headers: list[str] = Field(default_factory=list)
    sample_rows: list[dict[str, str]] = Field(default_factory=list)


class ConnectorSyncObservation(BaseModel):
    run_id: str = Field(min_length=1)
    completed_at: datetime
    records_read: int = Field(ge=0)


class ConnectorRegistryOrigin(StrEnum):
    REFERENCE = "reference"
    PERSISTED_MANIFEST = "persisted_manifest"


class ConnectorPersistedManifestSummary(BaseModel):
    manifest_id: str = Field(min_length=1)
    revision_number: int = Field(ge=1)
    status: str = Field(min_length=1)
    registered_by: str = Field(min_length=1)
    registered_at: datetime
    notes: list[str] = Field(default_factory=list)


class ConnectorRegistryItem(BaseModel):
    manifest: ConnectorManifest
    runtime_policy: ConnectorRuntimePolicy
    preview_sample: ConnectorPreviewSample | None = None
    last_successful_sync: ConnectorSyncObservation | None = None
    connector_status: OverviewStatus
    registry_origin: ConnectorRegistryOrigin = ConnectorRegistryOrigin.REFERENCE
    persisted_manifest: ConnectorPersistedManifestSummary | None = None

    @model_validator(mode="after")
    def validate_persisted_origin(self) -> "ConnectorRegistryItem":
        if (
            self.registry_origin == ConnectorRegistryOrigin.PERSISTED_MANIFEST
            and self.persisted_manifest is None
        ):
            raise ValueError(
                "Persisted-manifest connector registry items require persistence metadata."
            )
        return self


class ManufacturingConnectorRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    connectors: list[ConnectorRegistryItem] = Field(default_factory=list)
    connector_notes: list[str] = Field(default_factory=list)


class ConnectorCsvPreviewRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    file_name: str = Field(min_length=1, max_length=240)
    csv_content: str = Field(min_length=1)


class ProposedOntologyEntity(BaseModel):
    node_id: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    ontology_type: str = Field(min_length=1)
    field_summary: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class ConnectorAuditEventPreview(BaseModel):
    event_type: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    result: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    payload_preview: dict[str, str] = Field(default_factory=dict)


class ConnectorCsvPreviewResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    preview_status: str = Field(min_length=1)
    sync_mode: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    accepted_record_count: int = Field(ge=0)
    rejected_record_count: int = Field(ge=0)
    validation_issues: list[str] = Field(default_factory=list)
    proposed_entities: list[ProposedOntologyEntity] = Field(default_factory=list)
    audit_event_preview: ConnectorAuditEventPreview
    observed_schema: ConnectorObservedSchema | None = None
    preview_notes: list[str] = Field(default_factory=list)


class ConnectorExternalDbPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="external_db_operational_mirror", min_length=1)
    connection_profile_id: str = Field(
        default="profile_postgres_ops_readonly",
        min_length=1,
        max_length=120,
    )
    schema_name: str = Field(default="operations", min_length=1, max_length=120)
    table_name: str = Field(default="production_orders", min_length=1, max_length=120)
    selected_columns: list[str] = Field(
        default_factory=lambda: [
            "order_id",
            "asset_id",
            "work_center",
            "status",
            "risk_level",
        ],
    )
    sample_limit: int = Field(default=2, ge=1, le=100)
    credential_handle_id: str = Field(default="cred_external_db_readonly", min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class ConnectorExternalDbColumnPreview(BaseModel):
    source_column: str = Field(min_length=1)
    target_field: str = Field(min_length=1)
    ontology_target: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    nullable: bool


class ConnectorExternalDbTablePreview(BaseModel):
    schema_name: str = Field(min_length=1)
    table_name: str = Field(min_length=1)
    table_ref: str = Field(min_length=1)
    record_count_estimate: str = Field(min_length=1)
    sample_limit: int = Field(ge=1)
    columns: list[ConnectorExternalDbColumnPreview] = Field(default_factory=list)
    sample_rows: list[dict[str, str]] = Field(default_factory=list)


class ConnectorExternalDbPreviewResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    connection_profile_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    preview_status: str = Field(min_length=1)
    sync_mode: str = Field(min_length=1)
    live_query_executed: bool
    validation_issues: list[str] = Field(default_factory=list)
    inspected_table: ConnectorExternalDbTablePreview
    proposed_entities: list[ProposedOntologyEntity] = Field(default_factory=list)
    audit_event_preview: ConnectorAuditEventPreview
    preview_notes: list[str] = Field(default_factory=list)


def _connector_item_for_type(
    registry: ManufacturingConnectorRegistry,
    connector_id: str,
    connector_type: str,
) -> ConnectorRegistryItem | None:
    return next(
        (
            connector
            for connector in registry.connectors
            if connector.manifest.connector_id == connector_id
            and connector.manifest.connector_type == connector_type
        ),
        None,
    )


def _node_field(schema_fields: list[ConnectorSchemaField]) -> ConnectorSchemaField:
    return next(
        (field for field in schema_fields if field.target_field == "node_id"),
        schema_fields[0],
    )


def _node_type_from_ontology(ontology_target: str) -> str:
    if ontology_target.endswith("_asset"):
        return "asset"
    if ontology_target.endswith("_order"):
        return "work_order"
    return ontology_target


def _csv_rows(csv_content: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(StringIO(csv_content.strip()))
    headers = list(reader.fieldnames or [])
    rows = [
        {key: (value or "").strip() for key, value in row.items() if key is not None}
        for row in reader
    ]
    return headers, rows


def _required_columns(manifest: ConnectorManifest) -> list[str]:
    return [field.source_column for field in manifest.schema_fields if field.required]


def _validation_issues(
    manifest: ConnectorManifest | None,
    headers: list[str],
    rows: list[dict[str, str]],
) -> list[str]:
    if manifest is None:
        return []
    if not manifest.schema_fields:
        return ["Connector manifest must declare schema fields."]
    issues = [
        f"Missing required column: {column}"
        for column in _required_columns(manifest)
        if column not in headers
    ]
    duplicate_headers = sorted(header for header, count in Counter(headers).items() if count > 1)
    issues.extend(f"Duplicate CSV header: {header}" for header in duplicate_headers)
    if not rows:
        issues.append("CSV file must contain at least one data row.")
        return issues

    present_required_columns = [
        column for column in _required_columns(manifest) if column in headers
    ]
    for row_number, row in enumerate(rows, start=2):
        for column in present_required_columns:
            if not row.get(column, ""):
                issues.append(f"Row {row_number} has an empty required value: {column}")

    node_column = _node_field(manifest.schema_fields).source_column
    if node_column in headers:
        seen_node_ids: set[str] = set()
        for row_number, row in enumerate(rows, start=2):
            node_id = row.get(node_column, "")
            if node_id and node_id in seen_node_ids:
                issues.append(f"Row {row_number} has a duplicate node id: {node_id}")
            seen_node_ids.add(node_id)
    return issues


def _connector_issues(connector: ConnectorRegistryItem | None, connector_id: str) -> list[str]:
    if connector is not None:
        return []
    return [f"Unsupported connector_id: {connector_id}"]


def _entity_from_row(
    manifest: ConnectorManifest,
    row: dict[str, str],
    file_name: str,
) -> ProposedOntologyEntity:
    node_field = _node_field(manifest.schema_fields)
    field_summary = {
        field.source_column: row[field.source_column]
        for field in manifest.schema_fields
        if field.source_column in row and field.target_field != "node_id"
    }
    return ProposedOntologyEntity(
        node_id=row[node_field.source_column],
        node_type=_node_type_from_ontology(node_field.ontology_target),
        ontology_type=node_field.ontology_target,
        field_summary=field_summary,
        evidence_refs=[file_name, row[node_field.source_column]],
    )


def preview_file_csv_connector(
    registry: ManufacturingConnectorRegistry,
    request: ConnectorCsvPreviewRequest,
) -> ConnectorCsvPreviewResult:
    connector = _connector_item_for_type(registry, request.connector_id, "file_csv")
    manifest = connector.manifest if connector is not None else None
    headers, rows = _csv_rows(request.csv_content)
    issues = [
        *_connector_issues(connector, request.connector_id),
        *_validation_issues(manifest, headers, rows),
    ]
    row_limit = connector.runtime_policy.row_limit if connector is not None else 0
    proposed_entities = (
        []
        if issues or manifest is None
        else [_entity_from_row(manifest, row, request.file_name) for row in rows[:row_limit]]
    )
    accepted_count = len(proposed_entities)
    rejected_count = len(rows) if issues else max(len(rows) - accepted_count, 0)
    preview_status = "ready" if not issues else "blocked"

    return ConnectorCsvPreviewResult(
        tenant_id=request.tenant_id,
        connector_id=request.connector_id,
        file_name=request.file_name,
        preview_status=preview_status,
        sync_mode="preview_only",
        record_count=len(rows),
        accepted_record_count=accepted_count,
        rejected_record_count=rejected_count,
        validation_issues=issues,
        proposed_entities=proposed_entities,
        audit_event_preview=ConnectorAuditEventPreview(
            event_type="connector.preview.generated",
            scope=request.connector_id,
            actor_id="connector-preview-service",
            result="ready" if not issues else "blocked",
            evidence_refs=[request.file_name, request.connector_id],
            payload_preview={
                "file_name": request.file_name,
                "record_count": str(len(rows)),
                "accepted_record_count": str(accepted_count),
                "rejected_record_count": str(rejected_count),
            },
        ),
        observed_schema=(
            ConnectorObservedSchema(
                columns=list(headers),
                fingerprint=csv_header_fingerprint(headers),
            )
            if headers
            else None
        ),
        preview_notes=[
            "CSV content is parsed only for preview and is not persisted.",
            "Mapped rows become ontology proposals, not live graph mutations.",
            "Connector execution and scheduled sync remain outside preview boundaries.",
        ],
    )


def _external_db_requested_keys(request: ConnectorExternalDbPreviewRequest) -> set[str]:
    return {key.lower() for key in request.metadata}


def _external_db_requested_values(request: ConnectorExternalDbPreviewRequest) -> list[str]:
    return [str(value).lower() for value in request.metadata.values()]


def _external_db_validation_issues(
    connector: ConnectorRegistryItem | None,
    request: ConnectorExternalDbPreviewRequest,
) -> list[str]:
    issues: list[str] = []
    if connector is None:
        issues.append(f"Unsupported connector_id: {request.connector_id}")
    elif not connector.manifest.schema_fields:
        issues.append("Connector manifest must declare schema fields.")
    elif connector.preview_sample is None:
        issues.append("No preview sample has been recorded for this connector.")

    keys = _external_db_requested_keys(request)
    values = _external_db_requested_values(request)
    connection_keys = {"connection_string", "dsn", "jdbc_url", "database_url", "host", "port"}
    connection_markers = ("postgres://", "postgresql://", "jdbc:", "user:password")
    has_raw_connection_value = any(
        marker in value for marker in connection_markers for value in values
    )
    if keys.intersection(connection_keys) or has_raw_connection_value:
        issues.append("Raw connection material is not accepted in external DB preview.")

    query_keys = {"raw_sql", "sql", "query", "statement", "where_clause"}
    query_markers = ("select ", "insert ", "update ", "delete ", "drop ")
    has_raw_query_value = any(marker in value for marker in query_markers for value in values)
    if keys.intersection(query_keys) or has_raw_query_value:
        issues.append("Raw SQL or query text is not accepted in external DB preview.")

    credential_keys = {"api_key", "token", "secret", "secret_ref", "credential_value"}
    if keys.intersection(credential_keys):
        issues.append("Raw credential material is not accepted in external DB preview.")

    if connector is not None:
        supported_columns = {field.source_column for field in connector.manifest.schema_fields}
        unsupported_columns = [
            column for column in request.selected_columns if column not in supported_columns
        ]
        if unsupported_columns:
            issues.append(f"Unsupported metadata column(s): {', '.join(unsupported_columns)}")

    return issues


def _external_db_columns(
    connector: ConnectorRegistryItem | None,
    request: ConnectorExternalDbPreviewRequest,
    issues: list[str],
) -> list[ConnectorExternalDbColumnPreview]:
    if issues or connector is None:
        return []

    schema_by_column = {field.source_column: field for field in connector.manifest.schema_fields}
    selected_columns = request.selected_columns or list(schema_by_column)
    return [
        ConnectorExternalDbColumnPreview(
            source_column=column,
            target_field=schema_by_column[column].target_field,
            ontology_target=schema_by_column[column].ontology_target,
            data_type=schema_by_column[column].data_type,
            nullable=not schema_by_column[column].required,
        )
        for column in selected_columns
        if column in schema_by_column
    ]


def _external_db_sample_rows(
    connector: ConnectorRegistryItem | None,
    request: ConnectorExternalDbPreviewRequest,
    issues: list[str],
) -> list[dict[str, str]]:
    if issues or connector is None or connector.preview_sample is None:
        return []
    return connector.preview_sample.sample_rows[: request.sample_limit]


def _external_db_entity_from_row(
    manifest: ConnectorManifest,
    request: ConnectorExternalDbPreviewRequest,
    row: dict[str, str],
) -> ProposedOntologyEntity:
    node_field = _node_field(manifest.schema_fields)
    field_summary = {
        field.source_column: row[field.source_column]
        for field in manifest.schema_fields
        if field.source_column in row and field.target_field != "node_id"
    }
    return ProposedOntologyEntity(
        node_id=row[node_field.source_column],
        node_type=_node_type_from_ontology(node_field.ontology_target),
        ontology_type=node_field.ontology_target,
        field_summary=field_summary,
        evidence_refs=[
            request.connection_profile_id,
            f"{request.schema_name}.{request.table_name}",
            row[node_field.source_column],
        ],
    )


def _external_db_proposed_entities(
    connector: ConnectorRegistryItem | None,
    request: ConnectorExternalDbPreviewRequest,
    issues: list[str],
) -> list[ProposedOntologyEntity]:
    if issues or connector is None:
        return []

    return [
        _external_db_entity_from_row(connector.manifest, request, row)
        for row in _external_db_sample_rows(connector, request, issues)
    ]


def preview_external_db_connector(
    registry: ManufacturingConnectorRegistry,
    request: ConnectorExternalDbPreviewRequest,
) -> ConnectorExternalDbPreviewResult:
    connector = _connector_item_for_type(registry, request.connector_id, "external_db")
    issues = _external_db_validation_issues(connector, request)
    table_ref = f"{request.schema_name}.{request.table_name}"
    preview_status = "ready" if not issues else "blocked"

    return ConnectorExternalDbPreviewResult(
        tenant_id=request.tenant_id,
        connector_id=request.connector_id,
        connection_profile_id=request.connection_profile_id,
        source_type="database",
        preview_status=preview_status,
        sync_mode="schema_preview_only",
        live_query_executed=False,
        validation_issues=issues,
        inspected_table=ConnectorExternalDbTablePreview(
            schema_name=request.schema_name,
            table_name=request.table_name,
            table_ref=table_ref,
            record_count_estimate="not_queried",
            sample_limit=request.sample_limit,
            columns=_external_db_columns(connector, request, issues),
            sample_rows=_external_db_sample_rows(connector, request, issues),
        ),
        proposed_entities=_external_db_proposed_entities(connector, request, issues),
        audit_event_preview=ConnectorAuditEventPreview(
            event_type="connector.external_db.previewed",
            scope=request.connector_id,
            actor_id="connector-preview-service",
            result=preview_status,
            evidence_refs=[
                request.connection_profile_id,
                table_ref,
                request.credential_handle_id,
            ],
            payload_preview={
                "connection_profile_id": request.connection_profile_id,
                "table_ref": table_ref,
                "live_query_executed": "false",
                "credential_handle_id": request.credential_handle_id,
            },
        ),
        preview_notes=[
            "External DB preview is metadata-only and does not execute SQL.",
            "Connection details remain outside Axis behind profile ids and credential handles.",
            "Mapped rows become ontology proposals, not live graph mutations.",
        ],
    )
