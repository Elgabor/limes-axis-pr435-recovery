"""S3 host mapping into existing discovery, activation and ingestion owners."""

import hashlib
import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlsplit

import urllib3
from axis_sdk.connector_authoring.contracts import (
    Checkpoint,
    ConnectorError,
    DiscoveryRequest,
    ErrorCode,
    OperationContext,
    ReadLimits,
    ReadRequest,
)
from minio import Minio
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from axis_api.connector_postgres_discovery import (
    ConnectorSourceDiscoveryExecution,
    ConnectorSourceDiscoveryResult,
    ConnectorSourceVerificationExecution,
    ConnectorSourceVerificationResult,
    DiscoveredSourceTable,
    _resolve_operation_evidence,
)
from axis_api.connector_postgres_discovery import (
    connector_source_discovery_runtime_from_settings as postgres_runtime_from_settings,
)
from axis_api.connector_s3_source import OBJECT_FIELDS, OBJECT_SCHEMA_FINGERPRINT, S3ObjectSource
from axis_api.connector_secret_resolution import (
    EnvLeaseScopedSecretResolver,
    SecretResolutionError,
    SecretResolutionRequest,
)
from axis_api.connector_source_extraction import SourceExtractionOutcome
from axis_api.persistence import AuditEventCreate, ConnectorSourceExtractionBatchCreate
from axis_api.s3_source_profile import S3_SOURCE_CONNECTOR_ID, S3SourceProfile

S3_ADAPTER = "axis-s3-object-source"


class S3Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    access_key: SecretStr
    secret_key: SecretStr
    session_token: SecretStr | None = None


class PinnedS3Transport(urllib3.PoolManager):
    """Refuse SDK retargeting and redirects before attaching source credentials."""

    def __init__(self, endpoint):
        self._origin = self._target(endpoint)
        self.deadline = None
        super().__init__(timeout=urllib3.Timeout(connect=3, read=5), retries=False, maxsize=1)

    @staticmethod
    def _target(url):
        parsed = urlsplit(url)
        return (
            parsed.scheme,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    def urlopen(self, method, url, **kwargs):
        if self._target(url) != self._origin:
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise ConnectorError(ErrorCode.TIME_BUDGET_EXCEEDED)
            kwargs["timeout"] = urllib3.Timeout(
                total=remaining, connect=min(3, remaining), read=min(5, remaining)
            )
        return super().urlopen(method, url, **{**kwargs, "redirect": False, "retries": False})


@contextmanager
def minio_source_client(profile, credentials):
    transport = PinnedS3Transport(profile.endpoint)
    target = urlsplit(profile.endpoint)
    client = Minio(
        target.netloc,
        access_key=credentials.access_key.get_secret_value(),
        secret_key=credentials.secret_key.get_secret_value(),
        session_token=credentials.session_token.get_secret_value()
        if credentials.session_token
        else None,
        secure=target.scheme == "https",
        region=profile.region,
        http_client=transport,
    )
    client.disable_virtual_style_endpoint()
    try:
        yield client
    finally:
        transport.clear()


@dataclass(frozen=True)
class PreparedS3Extraction:
    tenant_id: str
    request_id: str
    binding_id: str
    profile: S3SourceProfile
    execution: ConnectorSourceVerificationExecution
    revision: int
    checkpoint_state: dict | None
    classification: str
    executed_by: str


@dataclass(frozen=True)
class CompletedS3Extraction:
    prepared: PreparedS3Extraction
    outcome: SourceExtractionOutcome
    checkpoint_state: dict

    @property
    def batch_key(self) -> str:
        # IDs can contain colons and each can be 180 characters. Hash a framed
        # identity so distinct tuples cannot alias and the SQL key stays bounded.
        identity = (
            self.prepared.tenant_id,
            S3_SOURCE_CONNECTOR_ID,
            self.prepared.request_id,
            self.prepared.binding_id,
            self.prepared.revision + 1,
        )
        digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        return f"s3:{digest}"


class S3CheckpointConflict(RuntimeError):
    """A different committed request advanced the binding; retry from current state."""


class S3IngestionRuntime:
    def __init__(
        self, settings, object_store=None, *, client_factory=minio_source_client, resolver=None
    ):
        self.settings = settings
        self.object_store = object_store
        self.client_factory = client_factory
        self.resolver = resolver or EnvLeaseScopedSecretResolver()
        identities = [(p.tenant_id, p.profile_id) for p in settings.s3_source_profiles]
        if len(set(identities)) != len(identities):
            raise ValueError("S3 source profile identities must be unique per tenant")

    def profile(self, tenant_id, profile_id):
        if not (
            self.settings.connector_sync_execution_enabled
            and self.settings.s3_source_ingestion_enabled
        ):
            raise ConnectorError(ErrorCode.UNSUPPORTED_CAPABILITY)
        for profile in self.settings.s3_source_profiles:
            if (profile.tenant_id, profile.profile_id) == (tenant_id, profile_id):
                return profile
        raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)

    @contextmanager
    def source(self, execution, *, inventory=None):
        profile = self.profile(execution.tenant_id, execution.connection_profile_id)
        self.validate_execution_profile(profile, execution)
        with self.authorized_source(profile, execution, inventory=inventory) as source:
            yield source

    @staticmethod
    def validate_execution_profile(profile, execution):
        policy = execution.egress_policy_evidence
        if (
            execution.connector_id != S3_SOURCE_CONNECTOR_ID
            or execution.credential_secret_ref != profile.credential_secret_ref
            or policy.get("egress_policy_evidence_status") != "validated"
            or policy.get("egress_policy_mode") != "approved_private_endpoint"
            or policy.get("egress_policy_scope") != f"{S3_SOURCE_CONNECTOR_ID}:{profile.profile_id}"
            or policy.get("egress_policy_endpoint_target_sha256") != profile.endpoint_target_sha256
            or policy.get("egress_policy_private_endpoint_ref") != profile.private_endpoint_ref
        ):
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)

        try:
            expires = datetime.fromisoformat(policy["credential_lease_expires_at"])
            if expires.tzinfo is None or expires <= datetime.now(UTC):
                raise ValueError("inactive lease")
        except (KeyError, ValueError, TypeError):
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH) from None

    @contextmanager
    def authorized_source(self, profile, execution, *, inventory):
        try:
            lease = execution.credential_lease_result
            resolved = self.resolver.resolve(
                SecretResolutionRequest(
                    connector_id=execution.connector_id,
                    connection_profile_id=profile.profile_id,
                    credential_access_mode="lease_scoped_secret_ref",
                    secret_provider=execution.credential_secret_provider,
                    secret_ref=execution.credential_secret_ref,
                    lease_status=str(lease.get("status", "")),
                    lease_ref=str(lease.get("provider_lease_ref", "")),
                    secret_material_returned=str(
                        lease.get("secret_material_returned", True)
                    ).lower(),
                )
            )
            credentials = S3Credentials.model_validate_json(resolved.dsn)
            if (
                not credentials.access_key.get_secret_value()
                or not credentials.secret_key.get_secret_value()
            ):
                raise ValueError("empty credentials")
        except (SecretResolutionError, ValidationError, ValueError):
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH) from None
        with self.client_factory(profile, credentials) as client:
            expiry = datetime.fromisoformat(
                execution.egress_policy_evidence["credential_lease_expires_at"]
            )
            remaining = (expiry - datetime.now(UTC)).total_seconds()
            deadline = time.monotonic() + remaining
            # This is the exact injected transport owned by this host. Fakes
            # need no driver callback; source deadlines still apply to them.
            transport = getattr(client, "_http", None)

            def set_network_deadline(value):
                if isinstance(transport, PinnedS3Transport):
                    transport.deadline = value

            set_network_deadline(deadline)
            yield S3ObjectSource(
                profile,
                client,
                inventory=inventory,
                authorization_deadline=deadline,
                set_network_deadline=set_network_deadline,
            )

    @staticmethod
    def context(execution):
        return OperationContext(
            tenant_id=execution.tenant_id,
            connector_id=execution.connector_id,
            actor_id=execution.requested_by,
            operation_id=getattr(execution, "verification_id", None) or execution.discovery_id,
        )

    def prepare_selection(
        self,
        repository,
        *,
        tenant_id,
        connector_id,
        request_id,
        binding_id,
        resource_name,
        pinned_schema_fingerprint,
        executed_by,
        lock_current=False,
    ):
        if connector_id != S3_SOURCE_CONNECTOR_ID or any(
            not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._:-]*", value)
            for value in (tenant_id, request_id, binding_id)
        ):
            raise ConnectorError(ErrorCode.CONTEXT_MISMATCH)
        binding = repository.get_connector_source_binding(
            tenant_id, binding_id, for_update=lock_current
        )
        if binding is None or binding.status != "active" or binding.connector_id != connector_id:
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
        profile = self.profile(tenant_id, binding.connection_profile_id)
        observation = repository.get_data_resource_observation(
            tenant_id, connector_id, resource_name
        )
        if (
            binding.resource_name != resource_name
            or resource_name != profile.resource_name
            or binding.schema_fingerprint != pinned_schema_fingerprint
            or pinned_schema_fingerprint != OBJECT_SCHEMA_FINGERPRINT
            or observation is None
            or observation.schema_fingerprint != pinned_schema_fingerprint
            or observation.last_source_kind != "s3_object_discovery"
        ):
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
        request = SimpleNamespace(
            tenant_id=tenant_id,
            connector_id=connector_id,
            connection_profile_id=profile.profile_id,
            credential_lease_id=binding.credential_lease_id,
            egress_policy_id=binding.egress_policy_id,
        )
        lease, policy = _resolve_operation_evidence(repository, request, for_update=lock_current)
        execution = ConnectorSourceVerificationExecution(
            tenant_id=tenant_id,
            connector_id=connector_id,
            verification_id=request_id,
            requested_by=executed_by,
            connection_profile_id=profile.profile_id,
            credential_lease_result=dict(lease.lease_result),
            credential_secret_provider=lease.secret_provider,
            credential_secret_ref=lease.secret_ref,
            egress_policy_evidence=policy,
        )
        self.validate_execution_profile(profile, execution)
        stewardship = repository.get_current_data_asset_stewardship(
            tenant_id, f"source:{connector_id}:default"
        )
        return PreparedS3Extraction(
            tenant_id,
            request_id,
            binding_id,
            profile,
            execution,
            binding.source_checkpoint_revision,
            binding.source_checkpoint,
            stewardship.classification if stewardship else "undeclared",
            executed_by,
        )

    def extract_prepared(self, prepared, *, progress=None):
        if self.object_store is None:
            raise ConnectorError(ErrorCode.UNSUPPORTED_CAPABILITY)
        previous = prepared.checkpoint_state
        if previous is not None and (
            not isinstance(previous, dict) or set(previous) != {"inventory", "checkpoint"}
        ):
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
        try:
            checkpoint = Checkpoint.model_validate(previous["checkpoint"]) if previous else None
        except ValidationError:
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT) from None
        started = time.monotonic()
        with self.source(
            prepared.execution, inventory=previous["inventory"] if previous else None
        ) as source:
            if progress is not None:
                source.progress = progress
            request = ReadRequest(
                context=self.context(prepared.execution),
                resource=source.selection,
                checkpoint=checkpoint,
                limits=ReadLimits(
                    max_records=min(self.settings.source_ingestion_extraction_max_rows, 1_000),
                    max_bytes=min(self.settings.source_ingestion_extraction_max_bytes, 8_388_608),
                    time_budget_seconds=min(
                        self.settings.source_ingestion_extraction_time_budget_seconds, 300
                    ),
                ),
            )
            batch = source.read(request)
            batch.validate_for(request)
            source.progress.extraction_performed = True
            next_inventory = source.next_inventory
        if batch.checkpoint is None or next_inventory is None:
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
        envelope = {
            "schema_version": 1,
            "tenant_id": prepared.tenant_id,
            "connector_id": S3_SOURCE_CONNECTOR_ID,
            "request_id": prepared.request_id,
            "binding_id": prepared.binding_id,
            "resource_name": prepared.profile.resource_name,
            "source_revision": prepared.profile.revision,
            "ordering_mode": "none",
            "cursor_watermark": batch.checkpoint.storage_record(),
            "completion": batch.completion,
            "truncated": batch.completion != "complete",
            "row_count": len(batch.records),
            "rows": list(batch.records),
        }
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        key = (
            f"tenants/{prepared.tenant_id}/source-ingestion/{prepared.request_id}/"
            f"{prepared.binding_id}/{digest}.json"
        )
        stored = self.object_store.put_json(key, envelope)
        if stored.checksum_sha256 != digest or stored.size_bytes != len(encoded):
            raise ConnectorError(ErrorCode.SOURCE_UNAVAILABLE)
        outcome = SourceExtractionOutcome(
            ok=True,
            source_dial_performed=True,
            extraction_performed=True,
            ordering_mode="none",
            cursor_watermark={"checkpoint_revision": prepared.revision + 1},
            row_count=len(batch.records),
            byte_size=batch.evidence().byte_size,
            truncated=batch.completion != "complete",
            limit_reason="s3_batch_limit" if batch.completion != "complete" else None,
            duration_ms=int((time.monotonic() - started) * 1000),
            digest_sha256=digest,
            observed_schema_fingerprint=OBJECT_SCHEMA_FINGERPRINT,
            stored={
                **stored.model_dump(),
                "stored_size_bytes": stored.size_bytes,
                "classification": prepared.classification,
                "executed_by": prepared.executed_by,
            },
        )
        return CompletedS3Extraction(
            prepared,
            outcome,
            {
                "inventory": next_inventory,
                "checkpoint": batch.checkpoint.storage_record(),
            },
        )

    def commit(self, repository, result):
        """Revalidate current grants and CAS the checkpoint inside the host transaction."""
        prepared = result.prepared
        # Take the shared connector lock before any binding lock. Requests can
        # contain overlapping binding sets; the opposite order can deadlock
        # while each request holds a binding the other still needs.
        repository.get_connector_manifest(
            prepared.tenant_id, S3_SOURCE_CONNECTOR_ID, for_update=True
        )
        current = self.prepare_selection(
            repository,
            tenant_id=prepared.tenant_id,
            connector_id=S3_SOURCE_CONNECTOR_ID,
            request_id=prepared.request_id,
            binding_id=prepared.binding_id,
            resource_name=prepared.profile.resource_name,
            pinned_schema_fingerprint=OBJECT_SCHEMA_FINGERPRINT,
            executed_by=prepared.executed_by,
            lock_current=True,
        )
        if (
            current.revision != prepared.revision
            or not repository.advance_connector_source_checkpoint(
                tenant_id=prepared.tenant_id,
                connector_id=S3_SOURCE_CONNECTOR_ID,
                binding_id=prepared.binding_id,
                expected_revision=prepared.revision,
                checkpoint=result.checkpoint_state,
            )
        ):
            raise S3CheckpointConflict()
        outcome = result.outcome
        batch_key = result.batch_key
        event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=prepared.tenant_id,
                actor_id=prepared.executed_by,
                event_type="connector.source.extraction.batch_recorded",
                payload={
                    "request_id": prepared.request_id,
                    "connector_id": S3_SOURCE_CONNECTOR_ID,
                    "binding_id": prepared.binding_id,
                    "resource_name": prepared.profile.resource_name,
                    "batch_key": batch_key,
                    "row_count": str(outcome.row_count),
                    "truncated": str(outcome.truncated).lower(),
                    "digest_sha256": outcome.digest_sha256,
                    "storage_uri": outcome.stored["storage_uri"],
                    "checkpoint_revision": str(prepared.revision + 1),
                },
            )
        )
        repository.create_connector_source_extraction_batch(
            ConnectorSourceExtractionBatchCreate(
                tenant_id=prepared.tenant_id,
                connector_id=S3_SOURCE_CONNECTOR_ID,
                request_id=prepared.request_id,
                batch_key=batch_key,
                binding_id=prepared.binding_id,
                resource_name=prepared.profile.resource_name,
                pinned_schema_fingerprint=OBJECT_SCHEMA_FINGERPRINT,
                observed_schema_fingerprint=OBJECT_SCHEMA_FINGERPRINT,
                ordering_mode="none",
                cursor_watermark=outcome.cursor_watermark,
                row_count=outcome.row_count,
                byte_size=outcome.byte_size,
                truncated=outcome.truncated,
                limit_reason=outcome.limit_reason,
                duration_ms=outcome.duration_ms,
                limits_applied={
                    "max_objects": prepared.profile.max_objects,
                    "max_object_bytes": prepared.profile.max_object_bytes,
                },
                provenance={
                    "stage": "extract",
                    "source_adapter": S3_ADAPTER,
                    "checkpoint_revision": prepared.revision + 1,
                },
                digest_sha256=outcome.digest_sha256,
                storage_adapter=outcome.stored["storage_adapter"],
                storage_key=outcome.stored["storage_key"],
                storage_uri=outcome.stored["storage_uri"],
                content_type=outcome.stored["content_type"],
                stored_size_bytes=outcome.stored["stored_size_bytes"],
                classification=current.classification,
                executed_by=prepared.executed_by,
                audit_event_id=event.id,
                audit_event_type=event.event_type,
            )
        )


class SourceDiscoveryRouter:
    def __init__(self, settings, *, s3=None):
        self.postgres = postgres_runtime_from_settings(settings)
        self.s3 = s3 or S3IngestionRuntime(settings)

    def verify(self, request: ConnectorSourceVerificationExecution):
        if request.connector_id != S3_SOURCE_CONNECTOR_ID:
            return self.postgres.verify(request)
        try:
            with self.s3.source(request) as source:
                result = source.health(self.s3.context(request))
            if result.status != "ready":
                raise ConnectorError(result.reason)
            return ConnectorSourceVerificationResult(adapter=S3_ADAPTER, status="source_verified")
        except ConnectorError as exc:
            return ConnectorSourceVerificationResult(
                adapter=S3_ADAPTER,
                status=f"verification_blocked_{exc.code.value}",
                block_reason=exc.code.value,
            )

    def discover(self, request: ConnectorSourceDiscoveryExecution):
        if request.connector_id != S3_SOURCE_CONNECTOR_ID:
            return self.postgres.discover(request)
        try:
            if request.schema_name != "s3":
                raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
            with self.s3.source(request) as source:
                discovered = source.discover(DiscoveryRequest(context=self.s3.context(request)))
            resource = discovered.resources[0]
            return ConnectorSourceDiscoveryResult(
                adapter=S3_ADAPTER,
                status="discovery_completed",
                discovered_schema="s3",
                tables=[
                    DiscoveredSourceTable(
                        schema_name="s3",
                        table_name=resource.resource_id.split(".", 1)[1],
                        column_names=list(OBJECT_FIELDS),
                        column_fingerprint=OBJECT_SCHEMA_FINGERPRINT,
                        columns_truncated=False,
                    )
                ],
                evidence_summary={
                    "row_data_read": "false",
                    "credential_material_returned": "false",
                },
            )
        except ConnectorError as exc:
            return ConnectorSourceDiscoveryResult(
                adapter=S3_ADAPTER,
                status=f"discovery_blocked_{exc.code.value}",
                block_reason=exc.code.value,
            )


def connector_source_discovery_runtime_from_settings(settings):
    return SourceDiscoveryRouter(settings)
