"""Real bounded source extraction behind the governed ingestion boundary.

This module is the line between the validation stage (Batch 9: no dial) and
REAL extraction: a self-hosted PostgreSQL adapter that dials the configured
source exactly once per selection, inside hardened read-only sessions, to read
ONE bound table up to strict row/byte/page/time limits, and hands the payload
to the canonical object store. Identifiers derive solely from active
tenant-scoped bindings and current observations; credentials resolve
server-side from the binding's persisted lease; egress is enforced against the
binding's approved-private-endpoint policy before any connection. No arbitrary
SQL, no client DSNs, no raw rows outside the object-store envelope.

Everything here is default-off at two levels (dispatch gate + extraction gate);
when disabled, governed ingestion stays byte-identical to validation-only.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from axis_api.config import Settings
from axis_api.connector_execution import read_only_session_connect_kwargs
from axis_api.connector_postgres_discovery import (
    _classify_postgres_error,
    postgres_discovery_profile_from_settings,
)
from axis_api.object_storage import ObjectStore
from axis_api.persistence import (
    AxisPersistenceRepository,
)

EXTRACTION_STAGE = "extract"
VALIDATE_STAGE = "validate"

EXTRACTION_BATCH_EVENT = "connector.source.extraction.batch_recorded"
EXTRACTION_ACTOR = "axis-source-ingestion-outbox"
ENVELOPE_SCHEMA_VERSION = 1

# Public-safe failure codes for the extraction stage.
STALE_FINGERPRINT = "stale_fingerprint"
OBSERVATION_MISSING = "observation_missing"
CREDENTIAL_LEASE_NOT_EXECUTED = "credential_lease_not_executed"
EGRESS_POLICY_NOT_APPROVED = "egress_policy_not_approved"


class ExtractionLimits(BaseModel):
    """Hard bounds for one selection's read; all are honest successes."""

    max_rows: int = Field(default=10_000, ge=1)
    max_bytes: int = Field(default=5_000_000, ge=1)
    page_size: int = Field(default=500, ge=1)
    time_budget_seconds: int = Field(default=30, ge=1)


def planned_extraction_limits(settings: Settings) -> dict | None:
    """The limits this deployment would apply; None when extraction is off."""
    if not (
        settings.source_ingestion_dispatch_enabled
        and settings.source_ingestion_extraction_enabled
    ):
        return None
    return ExtractionLimits(
        max_rows=settings.source_ingestion_extraction_max_rows,
        max_bytes=settings.source_ingestion_extraction_max_bytes,
        page_size=settings.source_ingestion_extraction_page_size,
        time_budget_seconds=settings.source_ingestion_extraction_time_budget_seconds,
    ).model_dump()


def _json_primitive(value: Any) -> Any:
    """Convert one cell to a JSON-safe primitive; never raises on data."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary {len(value)} bytes>"
    return str(value)


def _row_to_dict(columns: list[str], raw_row: tuple) -> dict:
    return {
        column: _json_primitive(value)
        for column, value in zip(columns, raw_row, strict=False)
    }


def _cap_gate(
    row_bytes: int,
    existing_rows: list[dict],
    existing_bytes: int,
    limits: ExtractionLimits,
    deadline: float,
    clock: Callable[[], float],
) -> str | None:
    """Decide whether one candidate row must be refused, returning why.

    Public-safe, mutually exclusive reasons: ``row_too_large`` (one row alone
    exceeds the whole byte budget), ``row_limit``, ``byte_limit``,
    ``time_budget``, or ``None`` when the row fits. The time budget is checked
    even before the FIRST row: an exhausted budget can never admit an
    unbounded read dressed up as progress.
    """
    if row_bytes > limits.max_bytes:
        return "row_too_large"
    if not existing_rows:
        return "time_budget" if clock() >= deadline else None
    if len(existing_rows) >= limits.max_rows:
        return "row_limit"
    if existing_bytes + row_bytes > limits.max_bytes:
        return "byte_limit"
    if clock() >= deadline:
        return "time_budget"
    return None


def _endpoint_target_sha256(dsn: str) -> str:
    parsed = urlparse(dsn)
    host = parsed.hostname or ""
    port = parsed.port or 5432
    return hashlib.sha256(f"{host}:{port}".encode()).hexdigest()


class SourceExtractionOutcome(BaseModel):
    """One selection's extraction result, true to what actually ran."""

    ok: bool
    retryable: bool = False
    source_dial_performed: bool = False
    extraction_performed: bool = False
    reason: str | None = None
    ordering_mode: str | None = None
    cursor_watermark: dict | None = None
    row_count: int = 0
    byte_size: int = 0
    truncated: bool = False
    limit_reason: str | None = None
    duration_ms: int = 0
    digest_sha256: str | None = None
    observed_schema_fingerprint: str | None = None
    # Write-once envelope for the object store. Never logged, audited,
    # returned over HTTP, or persisted in Postgres.
    payload_envelope: dict | None = None
    stored: dict | None = None


class PreparedSourceExtraction(BaseModel):
    """Validated metadata for one read; contains no repository, session or secret."""

    model_config = ConfigDict(frozen=True)
    tenant_id: str
    connector_id: str
    request_id: str
    batch_key: str
    binding_id: str
    resource_name: str
    pinned_schema_fingerprint: str
    executed_by: str
    limits: ExtractionLimits
    hardening: dict[str, str]
    classification: str


class _SourceReadFailure(Exception):
    def __init__(self, error: psycopg.Error, *, extraction_performed: bool):
        if (error.sqlstate or "").startswith("28"):
            reason = "auth_denied"
        elif error.sqlstate == "57014":
            reason = "source_timeout"
        else:
            reason = _classify_postgres_error(error)
        self.outcome = SourceExtractionOutcome(
            ok=False,
            reason=reason,
            retryable=reason in {"source_unreachable", "source_timeout"},
            source_dial_performed=True,
            extraction_performed=extraction_performed,
        )
        super().__init__(reason)


class SourceExtractionRuntimePort(Protocol):
    """The seam a real extraction runtime implements.

    Implementations must stay truthful: flags ``source_dial_performed`` and
    ``extraction_performed`` are true only when a source was dialed and rows
    were read, and payloads travel only through ``payload_envelope``.
    """

    def extract_selection(
        self,
        *,
        repository: AxisPersistenceRepository,
        tenant_id: str,
        connector_id: str,
        request_id: str,
        batch_key: str,
        binding_id: str,
        resource_name: str,
        pinned_schema_fingerprint: str,
        executed_by: str,
    ) -> SourceExtractionOutcome: ...

    def prepare_selection(
        self,
        *,
        repository: AxisPersistenceRepository,
        tenant_id: str,
        connector_id: str,
        request_id: str,
        batch_key: str,
        binding_id: str,
        resource_name: str,
        pinned_schema_fingerprint: str,
        executed_by: str,
    ) -> PreparedSourceExtraction | SourceExtractionOutcome: ...

    def read_selection(self, prepared: PreparedSourceExtraction) -> SourceExtractionOutcome: ...

    def verify_stored_batch(self, adapter: str, key: str, digest: str, size: int) -> bool: ...


def _qualified_name_is_safe(resource_name: str) -> bool:
    parts = resource_name.split(".")
    if len(parts) != 2:
        return False
    return all(
        part and part[0].isalpha() and part.isidentifier() for part in parts
    )


class SelfHostedPostgresExtractionRuntime:
    """Bounded read-only extraction from the configured Postgres source.

    The DSN comes from deployment settings only. Every dial revalidates schema
    freshness immediately before reading, verifies the binding's lease posture
    and approved-private-endpoint policy against the actual dial target, and
    enforces READ ONLY sessions with statement timeout plus row/byte/page/time
    caps. Payloads leave only through the canonical object store.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        object_store: ObjectStore,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        # Timeouts come from the shared discovery profile, exactly like every
        # other self-hosted Postgres boundary.
        self._profile = postgres_discovery_profile_from_settings(settings)
        self._object_store = object_store
        self._clock = clock or time.monotonic

    def extract_selection(
        self,
        *,
        repository: AxisPersistenceRepository,
        tenant_id: str,
        connector_id: str,
        request_id: str,
        batch_key: str,
        binding_id: str,
        resource_name: str,
        pinned_schema_fingerprint: str,
        executed_by: str,
    ) -> SourceExtractionOutcome:
        prepared = self.prepare_selection(
            repository=repository,
            tenant_id=tenant_id,
            connector_id=connector_id,
            request_id=request_id,
            batch_key=batch_key,
            binding_id=binding_id,
            resource_name=resource_name,
            pinned_schema_fingerprint=pinned_schema_fingerprint,
            executed_by=executed_by,
        )
        if isinstance(prepared, SourceExtractionOutcome):
            return prepared
        return self.read_selection(prepared)

    def prepare_selection(
        self,
        *,
        repository: AxisPersistenceRepository,
        tenant_id: str,
        connector_id: str,
        request_id: str,
        batch_key: str,
        binding_id: str,
        resource_name: str,
        pinned_schema_fingerprint: str,
        executed_by: str,
    ) -> PreparedSourceExtraction | SourceExtractionOutcome:
        if not (
            self.settings.source_ingestion_dispatch_enabled
            and self.settings.source_ingestion_extraction_enabled
        ):
            return SourceExtractionOutcome(ok=False, reason="extraction_disabled")
        if not _qualified_name_is_safe(resource_name):
            return SourceExtractionOutcome(ok=False, reason="unsafe_resource_name")

        binding = repository.get_connector_source_binding(tenant_id, binding_id)
        if binding is None or binding.status != "active":
            return SourceExtractionOutcome(ok=False, reason="binding_inactive")
        if (
            binding.connector_id != connector_id
            or binding.resource_name != resource_name
            or binding.schema_fingerprint != pinned_schema_fingerprint
        ):
            return SourceExtractionOutcome(ok=False, reason="binding_selection_mismatch")

        observation = repository.get_data_resource_observation(
            tenant_id, connector_id, resource_name
        )
        if observation is None:
            return SourceExtractionOutcome(ok=False, reason=OBSERVATION_MISSING)
        observed_fingerprint = observation.schema_fingerprint or ""
        if observed_fingerprint != pinned_schema_fingerprint:
            return SourceExtractionOutcome(ok=False, reason=STALE_FINGERPRINT)

        lease_gate = self._verify_lease(
            repository, tenant_id, connector_id, binding.credential_lease_id
        )
        if lease_gate is not None:
            return SourceExtractionOutcome(ok=False, reason=lease_gate)

        policy_gate = self._verify_egress_policy(
            repository, tenant_id, connector_id,
            binding.egress_policy_id, binding.connection_profile_id,
        )
        if policy_gate is not None:
            return SourceExtractionOutcome(ok=False, reason=policy_gate)

        limits = ExtractionLimits(
            max_rows=self.settings.source_ingestion_extraction_max_rows,
            max_bytes=self.settings.source_ingestion_extraction_max_bytes,
            page_size=self.settings.source_ingestion_extraction_page_size,
            time_budget_seconds=self.settings.source_ingestion_extraction_time_budget_seconds,
        )
        hardening = read_only_session_connect_kwargs(
            statement_timeout_seconds=self._profile.statement_timeout_seconds,
            session_hardening_enabled=(
                self.settings.external_db_runtime_egress_enforcement_enabled
            ),
        )
        classification = "undeclared"
        stewardship = repository.get_current_data_asset_stewardship(
            tenant_id, f"source:{connector_id}:default"
        )
        if stewardship is not None:
            classification = stewardship.classification

        return PreparedSourceExtraction(
            tenant_id=tenant_id,
            connector_id=connector_id,
            request_id=request_id,
            batch_key=batch_key,
            binding_id=binding_id,
            resource_name=resource_name,
            pinned_schema_fingerprint=pinned_schema_fingerprint,
            executed_by=executed_by,
            limits=limits,
            hardening=hardening,
            classification=classification,
        )

    def verify_stored_batch(self, adapter: str, key: str, digest: str, size: int) -> bool:
        if adapter != self._object_store.adapter_name:
            return False
        return self._object_store.verify_json(key, digest, size)

    def read_selection(self, prepared: PreparedSourceExtraction) -> SourceExtractionOutcome:
        started = self._clock()
        try:
            read = self._read_bounded(prepared.resource_name, prepared.limits, prepared.hardening)
        except _SourceReadFailure as exc:
            return exc.outcome
        except psycopg.Error as exc:
            return SourceExtractionOutcome(ok=False, reason=_classify_postgres_error(exc))

        duration_ms = int((self._clock() - started) * 1000)
        envelope = {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "tenant_id": prepared.tenant_id,
            "connector_id": prepared.connector_id,
            "request_id": prepared.request_id,
            "binding_id": prepared.binding_id,
            "resource_name": prepared.resource_name,
            "pinned_schema_fingerprint": prepared.pinned_schema_fingerprint,
            "observed_schema_fingerprint": prepared.pinned_schema_fingerprint,
            "ordering_mode": read["ordering_mode"],
            "cursor_watermark": read["cursor_watermark"],
            "truncated": read["truncated"],
            "limit_reason": read["limit_reason"],
            "limits_applied": prepared.limits.model_dump(),
            "row_count": len(read["rows"]),
            "rows": read["rows"],
        }
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()

        storage_key = (
            f"tenants/{prepared.tenant_id}/source-ingestion/{prepared.request_id}/"
            f"{prepared.binding_id}/{prepared.batch_key}/{digest}.json"
        )
        try:
            stored_meta = self._object_store.put_json(storage_key, json.loads(encoded.decode()))
        except Exception:
            # The read happened even when its payload could not be persisted.
            # Storage diagnostics and raw rows must not enter attempt evidence.
            return SourceExtractionOutcome(
                ok=False,
                reason="object_store_unavailable",
                retryable=True,
                source_dial_performed=True,
                extraction_performed=True,
            )

        if (
            stored_meta.checksum_sha256 != digest or stored_meta.size_bytes != len(encoded)
            or stored_meta.storage_key != storage_key
        ):
            return SourceExtractionOutcome(
                ok=False, reason="object_store_integrity_mismatch",
                source_dial_performed=True, extraction_performed=True,
            )

        return SourceExtractionOutcome(
            ok=True,
            source_dial_performed=True,
            extraction_performed=True,
            ordering_mode=read["ordering_mode"],
            cursor_watermark=read["cursor_watermark"],
            row_count=len(read["rows"]),
            byte_size=read["byte_size"],
            truncated=read["truncated"],
            limit_reason=read["limit_reason"],
            duration_ms=duration_ms,
            digest_sha256=digest,
            observed_schema_fingerprint=prepared.pinned_schema_fingerprint,
            payload_envelope=envelope,
            stored={
                "storage_adapter": stored_meta.storage_adapter,
                "storage_key": stored_meta.storage_key,
                "storage_uri": stored_meta.storage_uri,
                "content_type": stored_meta.content_type,
                "stored_size_bytes": stored_meta.size_bytes,
                "checksum_sha256": stored_meta.checksum_sha256,
                "digest_sha256": digest,
                "classification": prepared.classification,
                "executed_by": prepared.executed_by,
            },
        )

    @staticmethod
    def _verify_lease(
        repository, tenant_id: str, connector_id: str, lease_id: str,
    ) -> str | None:
        lease = repository.get_connector_credential_lease(tenant_id, lease_id)
        if lease is None or lease.connector_id != connector_id or lease.status != "active":
            return CREDENTIAL_LEASE_NOT_EXECUTED
        expires_at = lease.expires_at
        if expires_at is None:
            return CREDENTIAL_LEASE_NOT_EXECUTED
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            return CREDENTIAL_LEASE_NOT_EXECUTED
        allowed = (lease.permission_decision or {}).get("allowed")
        if allowed is not True and allowed != "true":
            return CREDENTIAL_LEASE_NOT_EXECUTED
        result = lease.lease_result or {}
        executed = result.get("status") in {"lease_executed", "lease_renewed"}
        # The durable contract records this flag as a string ("false"/"true");
        # a boolean false is accepted defensively so both honest encodings pass.
        secret_flag = result.get("secret_material_returned")
        no_secret = (
            secret_flag is False
            or (isinstance(secret_flag, str) and secret_flag.lower() == "false")
        )
        if not executed or not no_secret or not result.get("provider_lease_ref"):
            return CREDENTIAL_LEASE_NOT_EXECUTED
        return None

    def _verify_egress_policy(
        self,
        repository,
        tenant_id: str,
        connector_id: str,
        policy_id: str,
        connection_profile_id: str,
    ) -> str | None:
        policy = repository.get_connector_egress_policy(tenant_id, policy_id)
        if policy is None or policy.status != "active" or policy.connector_id != connector_id:
            return EGRESS_POLICY_NOT_APPROVED
        if policy.policy_mode != "approved_private_endpoint":
            return EGRESS_POLICY_NOT_APPROVED
        if policy.connection_profile_id != connection_profile_id:
            return EGRESS_POLICY_NOT_APPROVED
        document = policy.policy_document or {}
        approved_hash = document.get("approved_endpoint_target_sha256")
        dsn = self.settings.external_db_live_query_dsn
        if not approved_hash or approved_hash != _endpoint_target_sha256(dsn):
            return EGRESS_POLICY_NOT_APPROVED
        return None

    def _read_bounded(
        self,
        resource_name: str,
        limits: ExtractionLimits,
        hardening: dict[str, str],
    ) -> dict:
        schema_name, table_name = resource_name.split(".")
        qualified = psycopg.sql.SQL("{}.{}").format(
            psycopg.sql.Identifier(schema_name),
            psycopg.sql.Identifier(table_name),
        )
        dsn = self.settings.external_db_live_query_dsn
        rows: list[dict] = []
        byte_size = 0
        truncated = False
        limit_reason: str | None = None
        deadline = self._clock() + limits.time_budget_seconds

        extraction_performed = False
        try:
            with psycopg.connect(
                dsn,
                connect_timeout=self._profile.connect_timeout_seconds,
                **hardening,
            ) as connection, connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                statement_timeout_ms = (
                    self._profile.statement_timeout_seconds * 1000
                )
                cursor.execute(f"SET LOCAL statement_timeout = {statement_timeout_ms}")
                ordering_mode, pk_column = self._primary_key_probe(
                    cursor, schema_name, table_name
                )
                watermark: dict | None = None
                if ordering_mode == "primary_key":
                    # Keyset paging over a verified single-column primary key:
                    # deterministic order within this snapshot; watermark is not a checkpoint.
                    while True:
                        if watermark is not None:
                            cursor.execute(
                                psycopg.sql.SQL(
                                    "SELECT * FROM {} WHERE {} > %s ORDER BY {} LIMIT %s"
                                ).format(
                                    qualified,
                                    psycopg.sql.Identifier(pk_column),
                                    psycopg.sql.Identifier(pk_column),
                                ),
                                (watermark[pk_column], limits.page_size),
                            )
                        else:
                            cursor.execute(
                                psycopg.sql.SQL("SELECT * FROM {} ORDER BY {} LIMIT %s").format(
                                    qualified, psycopg.sql.Identifier(pk_column)
                                ),
                                (limits.page_size,),
                            )
                        columns = [desc.name for desc in cursor.description]
                        fetched = cursor.fetchmany(limits.page_size)
                        extraction_performed = True
                        if not fetched:
                            break
                        stop = False
                        for raw_row in fetched:
                            row = _row_to_dict(columns, raw_row)
                            row_bytes = len(json.dumps(row, sort_keys=True).encode())
                            gate = _cap_gate(
                                row_bytes,
                                rows,
                                byte_size,
                                limits,
                                deadline,
                                self._clock,
                            )
                            if gate is not None:
                                truncated = True
                                limit_reason = gate
                                stop = True
                                break
                            rows.append(row)
                            byte_size += row_bytes
                            watermark = {pk_column: row[pk_column]}
                        if stop or len(fetched) < limits.page_size:
                            break
                    if not truncated and len(rows) >= limits.max_rows:
                        # Exact-fit final page: probe once so truncation truth is exact.
                        has_more = self._probe_more_pk(cursor, qualified, pk_column, watermark)
                        if has_more:
                            truncated = True
                            limit_reason = "row_limit"
                else:
                    # No stable ordering key: one single bounded pass, no cursor,
                    # no resume claim. LIMIT max_rows+1 makes truncation truth
                    # structural; the watermark stays null by construction.
                    cursor.execute(
                        psycopg.sql.SQL("SELECT * FROM {} LIMIT %s").format(qualified),
                        (limits.max_rows + 1,),
                    )
                    columns = [desc.name for desc in cursor.description]
                    while True:
                        fetched = cursor.fetchmany(limits.page_size)
                        extraction_performed = True
                        if not fetched:
                            break
                        stop = False
                        for raw_row in fetched:
                            row = _row_to_dict(columns, raw_row)
                            row_bytes = len(json.dumps(row, sort_keys=True).encode())
                            gate = _cap_gate(
                                row_bytes,
                                rows,
                                byte_size,
                                limits,
                                deadline,
                                self._clock,
                            )
                            if gate is not None:
                                truncated = True
                                limit_reason = gate
                                stop = True
                                break
                            rows.append(row)
                            byte_size += row_bytes
                        if stop or len(fetched) < limits.page_size:
                            break

                if truncated:
                    limit_reason = limit_reason or (
                        "time_budget"
                        if self._clock() >= deadline
                        else ("byte_limit" if byte_size >= limits.max_bytes else "row_limit")
                    )
        except psycopg.Error as exc:
            raise _SourceReadFailure(exc, extraction_performed=extraction_performed) from None

        return {
            "ordering_mode": ordering_mode,
            "cursor_watermark": watermark,
            "rows": rows,
            "byte_size": byte_size,
            "truncated": truncated,
            "limit_reason": limit_reason,
        }

    @staticmethod
    def _probe_more_pk(cursor, qualified, pk_column: str | None, watermark) -> bool:
        """Exact-fit check for keyset paging: is there one more row after?"""

        if pk_column is None:
            return False
        if watermark is not None:
            cursor.execute(
                psycopg.sql.SQL("SELECT 1 FROM {} WHERE {} > %s LIMIT 1").format(
                    qualified, psycopg.sql.Identifier(pk_column)
                ),
                (watermark[pk_column],),
            )
            return cursor.fetchone() is not None
        cursor.execute(
            psycopg.sql.SQL("SELECT 1 FROM {} LIMIT 2").format(qualified)
        )
        return len(cursor.fetchall()) > 1

    @staticmethod
    def _primary_key_probe(cursor, schema_name: str, table_name: str) -> tuple[str, str | None]:
        cursor.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = %s
              AND tc.table_name = %s
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
            """,
            (schema_name, table_name),
        )
        columns = [str(row[0]) for row in cursor.fetchall()]
        if len(columns) == 1:
            return "primary_key", columns[0]
        return "none", None
