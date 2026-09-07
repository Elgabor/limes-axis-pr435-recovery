"""Bounded read-only schema discovery for external Postgres sources.

Discovery is the second real source boundary after the allowlisted live
read: it verifies connectivity and enumerates base tables plus their
column fingerprints through ``information_schema``, never reading row
data. Every operation is bounded (schema allowlist, table and column
caps, statement timeouts), classified on failure without leaking driver
or database internals, and secret-safe: credentials resolve through the
same lease-scoped boundary as live reads and only public-safe evidence
is returned or persisted.

Two model families mirror the run pipeline's contract split: operator
requests reference persisted leases and egress policies by ID only,
while the governed operation layer resolves their evidence server-side
before any runtime sees the request. Discovered tables become catalog
evidence through the existing resource observation seam; this module
owns the source conversation end to end.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

import psycopg
from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from axis_api.config import Settings

from axis_api.connector_execution import (
    LEASE_SCOPED_RESOLUTION_DSN_SENTINEL,
    POSTGRES_IDENTIFIER_PATTERN,
    RUNTIME_EGRESS_ENFORCED_TARGET_MATCH,
    _psycopg_dsn,
    _resolve_lease_scoped_secret,
    lease_scoped_secret_resolver_from_settings,
    postgres_endpoint_target_sha256,
    read_only_session_connect_kwargs,
    runtime_egress_target_block_reason,
)
from axis_api.connector_secret_resolution import SecretResolutionError
from axis_api.connectors import csv_header_fingerprint
from axis_api.data_asset_discovery import (
    DataAssetResourceObservationView,
    record_data_resource_observation,
)
from axis_api.persistence import (
    AuditEventCreate,
    AxisPersistenceRepository,
)
from axis_api.s3_source_profile import S3_SOURCE_CONNECTOR_ID

SOURCE_DISCOVERY_SCOPE = "connectors:source:discover"
VERIFY_AUDIT_EVENT_TYPE = "connector.source.verify"
DISCOVER_AUDIT_EVENT_TYPE = "connector.source.discover"
OBSERVATION_SOURCE_KIND = "postgres_discovery"
DISCOVERY_COMPLETED_STATUS = "discovery_completed"
DISCOVERY_BLOCKED_STATUS = "discovery_blocked"
SOURCE_VERIFIED_STATUS = "source_verified"
VERIFICATION_BLOCKED_STATUS = "verification_blocked"
# Postgres SQLSTATE codes this adapter classifies explicitly. Everything
# else falls back to type-based classification; raw driver messages are
# never surfaced to callers either way.
PG_INVALID_PASSWORD = "28P01"
PG_INSUFFICIENT_PRIVILEGE = "42501"
PG_INVALID_CATALOG_NAME = "3D000"


class ConnectorSourceOperationError(ValueError):
    """Operator-input failure: unknown references, missing scope grants."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class SourceScopeDenied(PermissionError):
    """The verified principal lacks ``connectors:source:discover``."""

    def __init__(self) -> None:
        super().__init__(f"missing_scope:{SOURCE_DISCOVERY_SCOPE}")
        self.required_scope = SOURCE_DISCOVERY_SCOPE


class PostgresDiscoveryProfile(BaseModel):
    """Pinned connection posture for one external Postgres source.

    Mirrors ``ExternalPostgresLiveQueryProfile``'s trust model: the DSN is
    either a static local/dev value or a per-call lease-resolved secret,
    while ``endpoint_target_sha256`` stays pinned so a swapped credential
    cannot silently retarget egress. Discovery bounds are part of the
    profile so they cannot be widened per request.
    """

    profile_id: str = Field(min_length=1)
    dsn: str = Field(min_length=1)
    allowed_schemas: list[str] = Field(min_length=1)
    private_endpoint_ref: str = Field(min_length=1)
    endpoint_target_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    max_tables: int = Field(default=25, ge=1, le=200)
    max_columns_per_table: int = Field(default=40, ge=1, le=200)
    connect_timeout_seconds: int = Field(default=3, ge=1, le=30)
    statement_timeout_seconds: int = Field(default=10, ge=1, le=300)

    def model_post_init(self, __context: object) -> None:
        for schema in self.allowed_schemas:
            if not POSTGRES_IDENTIFIER_PATTERN.fullmatch(schema):
                raise ValueError(f"Allowed schema {schema!r} is not a safe Postgres identifier.")

    def with_resolved_secret(self, resolved_secret) -> "PostgresDiscoveryProfile":
        """Swap in the lease-resolved DSN; the pinned target hash stays."""
        return self.model_copy(update={"dsn": resolved_secret.dsn})

    def allows_schema(self, schema_name: str) -> bool:
        return schema_name in self.allowed_schemas


class ConnectorSourceVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    verification_id: str = Field(min_length=1, max_length=180)
    requested_by: str = Field(min_length=1)
    connection_profile_id: str = Field(min_length=1, max_length=180)
    credential_lease_id: str = Field(min_length=1, max_length=180)
    egress_policy_id: str = Field(min_length=1, max_length=180)
    egress_boundary: str = Field(default="approved_private_endpoint", min_length=1)
    # Stamped from the verified principal when OIDC is enforced; public demo
    # traffic declares its scopes in the body (same convention as manifests).
    actor_scopes: list[str] = Field(default_factory=list)


class ConnectorSourceDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    discovery_id: str = Field(min_length=1, max_length=180)
    requested_by: str = Field(min_length=1)
    connection_profile_id: str = Field(min_length=1, max_length=180)
    schema_name: str = Field(min_length=1, max_length=120)
    credential_lease_id: str = Field(min_length=1, max_length=180)
    egress_policy_id: str = Field(min_length=1, max_length=180)
    egress_boundary: str = Field(default="approved_private_endpoint", min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)


class ConnectorSourceVerificationExecution(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    verification_id: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    connection_profile_id: str = Field(min_length=1)
    credential_lease_result: dict = Field(default_factory=dict)
    credential_secret_provider: str = Field(default="")
    credential_secret_ref: str = Field(default="")
    egress_policy_evidence: dict[str, str] = Field(default_factory=dict)


class ConnectorSourceDiscoveryExecution(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    discovery_id: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    connection_profile_id: str = Field(min_length=1)
    schema_name: str = Field(min_length=1, max_length=120)
    credential_lease_result: dict = Field(default_factory=dict)
    credential_secret_provider: str = Field(default="")
    credential_secret_ref: str = Field(default="")
    egress_policy_evidence: dict[str, str] = Field(default_factory=dict)


class ConnectorSourceVerificationResult(BaseModel):
    adapter: str = Field(min_length=1)
    status: str = Field(min_length=1)
    block_reason: str = Field(default="", min_length=0)
    database_name: str = Field(default="", min_length=0)
    # Public-safe runtime evidence only: decisions and hashes, never
    # connection strings or credential material.
    evidence_summary: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class DiscoveredSourceTable(BaseModel):
    schema_name: str = Field(min_length=1)
    table_name: str = Field(min_length=1, max_length=240)
    column_names: list[str] = Field(default_factory=list)
    column_fingerprint: str = Field(min_length=64, max_length=64)
    columns_truncated: bool


class ConnectorSourceDiscoveryResult(BaseModel):
    adapter: str = Field(min_length=1)
    status: str = Field(min_length=1)
    block_reason: str = Field(default="", min_length=0)
    discovered_schema: str = Field(default="", min_length=0)
    tables: list[DiscoveredSourceTable] = Field(default_factory=list)
    tables_truncated: bool = False
    evidence_summary: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ConnectorSourceDiscoveryRuntime(Protocol):
    def verify(
        self, request: ConnectorSourceVerificationExecution
    ) -> ConnectorSourceVerificationResult: ...

    def discover(
        self, request: ConnectorSourceDiscoveryExecution
    ) -> ConnectorSourceDiscoveryResult: ...


class DeferredConnectorSourceDiscoveryRuntime:
    """Default-off adapter: records the operation as deferred, touches nothing."""

    adapter_name = "axis-deferred-source-discovery"

    def verify(
        self, request: ConnectorSourceVerificationExecution
    ) -> ConnectorSourceVerificationResult:
        return ConnectorSourceVerificationResult(
            adapter=self.adapter_name,
            status="verification_deferred",
            evidence_summary={
                "runtime_status": "verification_deferred",
                "external_query_started": "false",
                "credential_material_returned": "false",
            },
            notes=[
                "Source connectivity verification is deferred by the Axis runtime adapter.",
                "No external query or credential retrieval was started.",
            ],
        )

    def discover(
        self, request: ConnectorSourceDiscoveryExecution
    ) -> ConnectorSourceDiscoveryResult:
        return ConnectorSourceDiscoveryResult(
            adapter=self.adapter_name,
            status="discovery_deferred",
            evidence_summary={
                "runtime_status": "discovery_deferred",
                "external_query_started": "false",
                "credential_material_returned": "false",
            },
            notes=[
                "Source schema discovery is deferred by the Axis runtime adapter.",
                "No external query or credential retrieval was started.",
            ],
        )


class SelfHostedPostgresDiscoveryRuntime:
    """Real information_schema discovery against one allowlisted profile.

    Gate order mirrors ``SelfHostedConnectorSyncExecutionRuntime``'s live
    read exactly: profile presence, then lease-scoped secret resolution,
    then runtime egress enforcement against the actual connect target,
    then the bounded introspection itself.
    """

    adapter_name = "axis-postgres-source-discovery"

    def __init__(
        self,
        *,
        profile: PostgresDiscoveryProfile | None,
        lease_scoped_secret_resolution_enabled: bool = False,
        runtime_egress_enforcement_enabled: bool = False,
        secret_resolver=None,
    ) -> None:
        self.profile = profile
        self.lease_scoped_secret_resolution_enabled = lease_scoped_secret_resolution_enabled
        self.runtime_egress_enforcement_enabled = runtime_egress_enforcement_enabled
        self.secret_resolver = secret_resolver

    def verify(
        self, request: ConnectorSourceVerificationExecution
    ) -> ConnectorSourceVerificationResult:
        effective_profile, blocked, evidence = self._prepare(request)
        if blocked is not None:
            return _blocked_verification(blocked, evidence)
        assert effective_profile is not None
        try:
            database_name = _verify_connectivity(
                effective_profile,
                session_hardening_enabled=self.runtime_egress_enforcement_enabled,
            )
        except psycopg.Error as exc:
            return _blocked_verification(
                _classify_postgres_error(exc),
                {**evidence, "external_query_started": "true"},
            )
        return ConnectorSourceVerificationResult(
            adapter=self.adapter_name,
            status=SOURCE_VERIFIED_STATUS,
            database_name=database_name,
            evidence_summary={
                **evidence,
                "runtime_status": SOURCE_VERIFIED_STATUS,
                "external_query_started": "true",
                "credential_material_returned": "false",
                "row_data_read": "false",
            },
            notes=[
                "Connectivity verified through the allowlisted discovery profile "
                "with a read-only probe.",
                "Only the database name and public-safe evidence are reported.",
            ],
        )

    def discover(
        self, request: ConnectorSourceDiscoveryExecution
    ) -> ConnectorSourceDiscoveryResult:
        effective_profile, blocked, evidence = self._prepare(request)
        if blocked is not None:
            return _blocked_discovery(request.schema_name, blocked, evidence)
        assert effective_profile is not None
        if not effective_profile.allows_schema(request.schema_name):
            return _blocked_discovery(request.schema_name, "schema_not_allowlisted", evidence)
        try:
            tables, tables_truncated = _discover_tables(
                effective_profile,
                schema_name=request.schema_name,
                session_hardening_enabled=self.runtime_egress_enforcement_enabled,
            )
        except psycopg.Error as exc:
            return _blocked_discovery(
                request.schema_name,
                _classify_postgres_error(exc),
                {**evidence, "external_query_started": "true"},
            )
        return ConnectorSourceDiscoveryResult(
            adapter=self.adapter_name,
            status=DISCOVERY_COMPLETED_STATUS,
            discovered_schema=request.schema_name,
            tables=tables,
            tables_truncated=tables_truncated,
            evidence_summary={
                **evidence,
                "runtime_status": DISCOVERY_COMPLETED_STATUS,
                "external_query_started": "true",
                "credential_material_returned": "false",
                "row_data_read": "false",
                "discovered_table_count": str(len(tables)),
                "tables_truncated": _bool_as_text(tables_truncated),
                "requested_schema": request.schema_name,
            },
            notes=[
                "Schema discovery enumerated base tables and column names only.",
                "No row data was read; fingerprints cover column names alone.",
            ],
        )

    def _prepare(
        self,
        request: ConnectorSourceVerificationExecution | ConnectorSourceDiscoveryExecution,
    ) -> tuple[PostgresDiscoveryProfile | None, str | None, dict[str, str]]:
        """Shared gate order: profile -> secret resolution -> egress enforcement."""
        evidence: dict[str, str] = {}
        profile = self.profile
        if profile is None:
            return None, "profile_not_configured", evidence
        effective_profile = profile
        if self.lease_scoped_secret_resolution_enabled:
            try:
                resolved_secret = _resolve_lease_scoped_secret(
                    resolver=self.secret_resolver,
                    connector_id=request.connector_id,
                    connection_profile_id=request.connection_profile_id,
                    credential_access_mode="lease_scoped_secret_ref",
                    secret_provider=request.credential_secret_provider,
                    secret_ref=request.credential_secret_ref,
                    lease_result=request.credential_lease_result,
                )
            except SecretResolutionError as exc:
                return None, exc.reason, evidence
            effective_profile = profile.with_resolved_secret(resolved_secret)
            evidence.update(resolved_secret.public_evidence())
        if self.runtime_egress_enforcement_enabled:
            egress_block_reason = runtime_egress_target_block_reason(
                dsn=effective_profile.dsn,
                profile=profile,
                egress_policy_evidence=request.egress_policy_evidence,
            )
            if egress_block_reason is not None:
                return None, egress_block_reason, evidence
            evidence["runtime_egress_enforcement"] = RUNTIME_EGRESS_ENFORCED_TARGET_MATCH
        return effective_profile, None, evidence


def _blocked_verification(
    reason: str, evidence: dict[str, str]
) -> ConnectorSourceVerificationResult:
    return ConnectorSourceVerificationResult(
        adapter=SelfHostedPostgresDiscoveryRuntime.adapter_name,
        status=f"{VERIFICATION_BLOCKED_STATUS}_{reason}",
        block_reason=reason,
        evidence_summary={
            **evidence,
            "runtime_status": VERIFICATION_BLOCKED_STATUS,
            "block_reason": reason,
            "credential_material_returned": "false",
        },
        notes=[
            "Source connectivity verification was blocked by Axis runtime "
            "policy or failed at the source boundary.",
        ],
    )


def _blocked_discovery(
    schema_name: str,
    reason: str,
    evidence: dict[str, str],
) -> ConnectorSourceDiscoveryResult:
    return ConnectorSourceDiscoveryResult(
        adapter=SelfHostedPostgresDiscoveryRuntime.adapter_name,
        status=f"{DISCOVERY_BLOCKED_STATUS}_{reason}",
        block_reason=reason,
        discovered_schema=(
            schema_name if POSTGRES_IDENTIFIER_PATTERN.fullmatch(schema_name) else ""
        ),
        evidence_summary={
            **evidence,
            "runtime_status": DISCOVERY_BLOCKED_STATUS,
            "block_reason": reason,
            "credential_material_returned": "false",
            "row_data_read": "false",
        },
        notes=[
            "Source schema discovery was blocked by Axis runtime policy or "
            "failed at the source boundary.",
        ],
    )


class SourceVerificationOutcome(BaseModel):
    verification_id: str = Field(min_length=1)
    result: ConnectorSourceVerificationResult
    correlation_ref: str = Field(min_length=1)


class SourceDiscoveryObservation(BaseModel):
    table_name: str = Field(min_length=1)
    observation: DataAssetResourceObservationView


class SourceDiscoveryOutcome(BaseModel):
    discovery_id: str = Field(min_length=1)
    result: ConnectorSourceDiscoveryResult
    observations: list[SourceDiscoveryObservation] = Field(default_factory=list)
    correlation_ref: str = Field(min_length=1)


def record_connector_source_verification(
    repository: AxisPersistenceRepository,
    *,
    runtime: ConnectorSourceDiscoveryRuntime,
    request: ConnectorSourceVerifyRequest,
    principal_scopes: list[str],
) -> SourceVerificationOutcome:
    _require_source_discovery_scope(principal_scopes)
    lease, egress_evidence = _resolve_operation_evidence(repository, request)
    execution = ConnectorSourceVerificationExecution(
        tenant_id=request.tenant_id,
        connector_id=request.connector_id,
        verification_id=request.verification_id,
        requested_by=request.requested_by,
        connection_profile_id=request.connection_profile_id,
        credential_lease_result=dict(lease.lease_result),
        credential_secret_provider=lease.secret_provider,
        credential_secret_ref=lease.secret_ref,
        egress_policy_evidence=egress_evidence,
    )
    result = runtime.verify(execution)
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type=VERIFY_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": request.connector_id,
                "connection_profile_id": request.connection_profile_id,
                "verification_id": request.verification_id,
                "status": result.status,
                "block_reason": result.block_reason,
                "database_name": result.database_name,
                "credential_lease_id": request.credential_lease_id,
                "egress_policy_id": request.egress_policy_id,
                "credential_material_returned": "false",
            },
        )
    )
    return SourceVerificationOutcome(
        verification_id=request.verification_id,
        result=result,
        correlation_ref=(
            f"source-verify://{request.tenant_id}/{request.connector_id}/{request.verification_id}"
        ),
    )


def record_connector_source_discovery(
    repository: AxisPersistenceRepository,
    *,
    runtime: ConnectorSourceDiscoveryRuntime,
    request: ConnectorSourceDiscoveryRequest,
    principal_scopes: list[str],
) -> SourceDiscoveryOutcome:
    _require_source_discovery_scope(principal_scopes)
    lease, egress_evidence = _resolve_operation_evidence(repository, request)
    execution = ConnectorSourceDiscoveryExecution(
        tenant_id=request.tenant_id,
        connector_id=request.connector_id,
        discovery_id=request.discovery_id,
        requested_by=request.requested_by,
        connection_profile_id=request.connection_profile_id,
        schema_name=request.schema_name,
        credential_lease_result=dict(lease.lease_result),
        credential_secret_provider=lease.secret_provider,
        credential_secret_ref=lease.secret_ref,
        egress_policy_evidence=egress_evidence,
    )
    result = runtime.discover(execution)
    observations: list[SourceDiscoveryObservation] = []
    if result.status == DISCOVERY_COMPLETED_STATUS:
        for table in result.tables:
            view, _drift = record_data_resource_observation(
                repository,
                tenant_id=request.tenant_id,
                connector_id=request.connector_id,
                file_name=_resource_name_for_table(table),
                columns=list(table.column_names),
                observed_by=request.requested_by,
                source_kind=("s3_object_discovery" if request.connector_id == S3_SOURCE_CONNECTOR_ID
                             else OBSERVATION_SOURCE_KIND),
            )
            observations.append(
                SourceDiscoveryObservation(
                    table_name=table.table_name,
                    observation=view,
                )
            )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type=DISCOVER_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": request.connector_id,
                "connection_profile_id": request.connection_profile_id,
                "discovery_id": request.discovery_id,
                "status": result.status,
                "block_reason": result.block_reason,
                "schema_name": result.discovered_schema,
                "discovered_table_count": str(len(result.tables)),
                "observed_resource_count": str(len(observations)),
                "tables_truncated": _bool_as_text(result.tables_truncated),
                "credential_material_returned": "false",
            },
        )
    )
    return SourceDiscoveryOutcome(
        discovery_id=request.discovery_id,
        result=result,
        observations=observations,
        correlation_ref=(
            f"source-discovery://{request.tenant_id}/{request.connector_id}/{request.discovery_id}"
        ),
    )


def _require_source_discovery_scope(principal_scopes: list[str]) -> None:
    if SOURCE_DISCOVERY_SCOPE not in principal_scopes:
        raise SourceScopeDenied()


def _resolve_operation_evidence(
    repository: AxisPersistenceRepository,
    request: ConnectorSourceVerifyRequest | ConnectorSourceDiscoveryRequest,
    *,
    for_update: bool = False,
):
    lease = repository.get_connector_credential_lease(
        request.tenant_id,
        request.credential_lease_id,
        **({"for_update": True} if for_update else {}),
    )
    if lease is None or lease.connector_id != request.connector_id:
        raise ConnectorSourceOperationError(
            "Credential lease was not found for this connector.",
            "credential_lease_not_found",
        )
    # Lease posture parity with the live-read preflight: only an executed or
    # renewed lease whose result proves no secret material was returned may
    # authorize a source operation. A merely persisted/deferred lease is not
    # evidence that a credential broker approved anything.
    lease_result = dict(lease.lease_result)
    lease_status = str(lease_result.get("status", ""))
    secret_material_returned = str(lease_result.get("secret_material_returned", True)).lower()
    if (
        lease_status not in {"lease_executed", "lease_renewed"}
        or not str(lease_result.get("provider_lease_ref", ""))
        or secret_material_returned != "false"
    ):
        raise ConnectorSourceOperationError(
            "Credential lease was never executed by a credential broker.",
            "credential_lease_not_executed",
        )
    policy = repository.get_connector_egress_policy(
        request.tenant_id,
        request.egress_policy_id,
        **({"for_update": True} if for_update else {}),
    )
    if policy is None:
        raise ConnectorSourceOperationError(
            "Egress policy was not found.",
            "egress_policy_not_found",
        )
    if policy.connector_id != request.connector_id:
        raise ConnectorSourceOperationError(
            "Egress policy does not belong to this connector.",
            "egress_policy_connector_mismatch",
        )
    if policy.connection_profile_id != request.connection_profile_id:
        raise ConnectorSourceOperationError(
            "Egress policy does not belong to this connection profile.",
            "egress_policy_profile_mismatch",
        )
    if policy.policy_mode != "approved_private_endpoint":
        raise ConnectorSourceOperationError(
            "Egress policy must approve a private endpoint boundary.",
            "egress_policy_not_approved",
        )
    if request.connector_id == S3_SOURCE_CONNECTOR_ID:
        # New S3 I/O requires the existing live lifecycle and current credential
        # posture, including revocation/expiry; a historical lease is insufficient.
        manifest = repository.get_connector_manifest(
            request.tenant_id, request.connector_id, for_update=for_update
        )
        runtime_policy = manifest.runtime_policy if manifest is not None else {}
        required = {"live_query", "external_egress"}
        if (
            manifest is None or manifest.status != "active_live"
            or not required <= set(runtime_policy.get("allowed_operations", []))
            or required & set(runtime_policy.get("blocked_operations", []))
        ):
            raise ConnectorSourceOperationError(
                "S3 source is not enabled for live reads.", "s3_source_inactive"
            )
        handle = repository.get_connector_credential_handle(
            request.tenant_id, lease.handle_id, for_update=for_update
        )
        expiry = (
            lease.expires_at.replace(tzinfo=UTC)
            if lease.expires_at.tzinfo is None
            else lease.expires_at
        )
        if (
            lease.status != "active"
            or lease.revoked_at is not None
            or expiry <= datetime.now(UTC)
            or lease.permission_decision.get("allowed") is not True
            or handle is None
            or handle.status != "active"
            or handle.connector_id != request.connector_id
            or handle.secret_ref != lease.secret_ref
            or handle.secret_provider != lease.secret_provider
        ):
            raise ConnectorSourceOperationError(
                "S3 credential lease is no longer active.", "s3_credential_inactive"
            )
        if policy.status != "active":
            raise ConnectorSourceOperationError(
                "S3 egress policy is no longer active.", "s3_egress_inactive"
            )
    egress_evidence = {
        "egress_policy_evidence_status": "validated",
        "egress_policy_runtime_boundary": policy.runtime_boundary,
        "egress_policy_result_status": "egress_policy_approved",
        "egress_policy_ref": (f"self-hosted-egress-policy://{policy.tenant_id}/{policy.policy_id}"),
        "egress_policy_scope": (f"{policy.connector_id}:{policy.connection_profile_id}"),
        "egress_policy_mode": policy.policy_mode,
        "egress_policy_private_endpoint_ref": policy.private_endpoint_ref,
        "egress_policy_endpoint_target_sha256": str(
            policy.policy_document.get("approved_endpoint_target_sha256", "")
        ),
    }
    if request.connector_id == S3_SOURCE_CONNECTOR_ID:
        egress_evidence["credential_lease_expires_at"] = expiry.isoformat()
    return lease, egress_evidence


def _resource_name_for_table(table: DiscoveredSourceTable) -> str:
    """Stable catalog resource identity for one source table."""
    return f"{table.schema_name}.{table.table_name}"


def postgres_discovery_profile_from_settings(
    settings: "Settings",
) -> PostgresDiscoveryProfile | None:
    dsn = settings.external_db_live_query_dsn
    schemas = settings.external_db_discovery_schemas
    if dsn:
        return PostgresDiscoveryProfile(
            profile_id=settings.external_db_discovery_profile_id,
            dsn=dsn,
            allowed_schemas=schemas,
            private_endpoint_ref=settings.external_db_live_query_private_endpoint_ref,
            endpoint_target_sha256=postgres_endpoint_target_sha256(dsn),
            max_tables=settings.external_db_discovery_max_tables,
            max_columns_per_table=settings.external_db_discovery_max_columns_per_table,
        )
    if (
        settings.external_db_lease_scoped_secret_resolution_enabled
        and settings.external_db_live_query_endpoint_target_sha256
    ):
        # Lease-scoped path: same sentinel pattern as the live-query profile —
        # the pinned target hash authorizes egress, the DSN resolves per call.
        return PostgresDiscoveryProfile(
            profile_id=settings.external_db_discovery_profile_id,
            dsn=LEASE_SCOPED_RESOLUTION_DSN_SENTINEL,
            allowed_schemas=schemas,
            private_endpoint_ref=settings.external_db_live_query_private_endpoint_ref,
            endpoint_target_sha256=(settings.external_db_live_query_endpoint_target_sha256),
            max_tables=settings.external_db_discovery_max_tables,
            max_columns_per_table=settings.external_db_discovery_max_columns_per_table,
        )
    return None


def connector_source_discovery_runtime_from_settings(
    settings: "Settings",
) -> ConnectorSourceDiscoveryRuntime:
    if not (settings.connector_sync_execution_enabled and settings.external_db_discovery_enabled):
        return DeferredConnectorSourceDiscoveryRuntime()
    return SelfHostedPostgresDiscoveryRuntime(
        profile=postgres_discovery_profile_from_settings(settings),
        lease_scoped_secret_resolution_enabled=(
            settings.external_db_lease_scoped_secret_resolution_enabled
        ),
        runtime_egress_enforcement_enabled=(
            settings.external_db_runtime_egress_enforcement_enabled
        ),
        secret_resolver=lease_scoped_secret_resolver_from_settings(settings),
    )


def _verify_connectivity(
    profile: PostgresDiscoveryProfile,
    *,
    session_hardening_enabled: bool,
) -> str:
    query = sql.SQL("SELECT current_database()")
    with (
        psycopg.connect(
            _psycopg_dsn(profile.dsn),
            connect_timeout=profile.connect_timeout_seconds,
            **read_only_session_connect_kwargs(
                statement_timeout_seconds=profile.statement_timeout_seconds,
                session_hardening_enabled=session_hardening_enabled,
            ),
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute(query)
        row = cursor.fetchone()
    if row is None or not row[0]:
        raise psycopg.ProgrammingError("current_database() returned no value")
    return str(row[0])


def _discover_tables(
    profile: PostgresDiscoveryProfile,
    *,
    schema_name: str,
    session_hardening_enabled: bool,
) -> tuple[list[DiscoveredSourceTable], bool]:
    tables_query = (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
        "ORDER BY table_name LIMIT %s"
    )
    columns_query = (
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s "
        "ORDER BY ordinal_position LIMIT %s"
    )
    discovered: list[DiscoveredSourceTable] = []
    truncated_overall = False
    with (
        psycopg.connect(
            _psycopg_dsn(profile.dsn),
            connect_timeout=profile.connect_timeout_seconds,
            **read_only_session_connect_kwargs(
                statement_timeout_seconds=profile.statement_timeout_seconds,
                session_hardening_enabled=session_hardening_enabled,
            ),
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute(tables_query, (schema_name, profile.max_tables + 1))
        table_names = [str(row[0]) for row in cursor.fetchall()]
        if len(table_names) > profile.max_tables:
            truncated_overall = True
            table_names = table_names[: profile.max_tables]
        for table_name in table_names:
            cursor.execute(
                columns_query,
                (schema_name, table_name, profile.max_columns_per_table + 1),
            )
            column_rows = cursor.fetchall()
            columns_truncated = len(column_rows) > profile.max_columns_per_table
            column_names = [str(row[0]) for row in column_rows[: profile.max_columns_per_table]]
            discovered.append(
                DiscoveredSourceTable(
                    schema_name=schema_name,
                    table_name=table_name,
                    column_names=column_names,
                    column_fingerprint=csv_header_fingerprint(column_names),
                    columns_truncated=columns_truncated,
                )
            )
    return discovered, truncated_overall


def _classify_postgres_error(exc: psycopg.Error) -> str:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == PG_INVALID_PASSWORD:
        return "auth_denied"
    if sqlstate == PG_INSUFFICIENT_PRIVILEGE:
        return "permission_denied"
    if sqlstate == PG_INVALID_CATALOG_NAME:
        return "source_database_missing"
    if isinstance(exc, psycopg.OperationalError):
        # psycopg3 wraps connect-time auth failures in a bare
        # ``OperationalError`` without a SQLSTATE. The driver message is
        # inspected only to pick a classification code; messages themselves
        # never reach API payloads or audit evidence.
        if "password authentication failed" in str(exc):
            return "auth_denied"
        return "source_unreachable"
    return "query_failed"


def _bool_as_text(value: bool) -> str:
    return "true" if value else "false"
