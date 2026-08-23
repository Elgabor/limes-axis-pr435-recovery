"""Governed batch-envelope exports for extraction evidence.

Operators and auditors need a durable, checksummed, approval-gated package of
WHAT an ingestion request extracted — without ever touching row payloads. This
module reuses the evidence-snapshot export pattern end to end:

1. an operator REQUESTS the export (dedicated scope, required governance
   reason, explicit idempotency key); Axis snapshots the request's batch
   envelopes as metadata-only records, checksums them, and auto-creates the
   pending approval record;
2. a privileged DECISION approves or rejects it through the persisted approval
   decision boundary;
3. MATERIALIZATION writes the public-safe envelope bundle through the governed
   object store exactly once, verifying the envelope checksum first (TOCTOU);
4. RETRIEVAL serves the artifact back ONLY for the local filesystem adapter,
   verifying the recorded SHA-256 before responding and appending read-audit
   evidence. No cloud client is ever constructed by this surface.

The bundle contains counts, digests, presence-only watermark flags and storage
references. Row values and cursor-watermark values never appear here, in any
view, audit payload or error.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from axis_api.audit import AuditEventCreate
from axis_api.connector_source_ingestion import SourceExtractionBatchView
from axis_api.demo import ApprovalDecision
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    ApprovalDecisionRecord,
    ApprovalRecordCreate,
    AxisPersistenceRepository,
    ConnectorSourceBatchExportDecisionRecord,
    ConnectorSourceBatchExportMaterializationRecord,
    ConnectorSourceBatchExportRequestCreate,
)

SOURCE_BATCH_EXPORT_REQUEST_SCOPE = "connectors:source:batch_export:request"
SOURCE_BATCH_EXPORT_DECISION_SCOPE = "approvals:connectors:source:batch_export:decide"
SOURCE_BATCH_EXPORT_MATERIALIZE_SCOPE = "connectors:source:batch_export:materialize"

BATCH_EXPORT_REQUESTED_EVENT = "connector.source.batch_export.requested"
BATCH_EXPORT_DECISION_EVENT = "connector.source.batch_export.decision_recorded"
BATCH_EXPORT_MATERIALIZED_EVENT = "connector.source.batch_export.materialized"
BATCH_EXPORT_ARTIFACT_READ_EVENT = "connector.source.batch_export.artifact_read"

BATCH_EXPORT_REQUEST_STATUS = "approval_required"
BATCH_EXPORT_REQUEST_EXPORT_STATUS = "not_exported"
BATCH_EXPORT_REQUEST_STORAGE_STATUS = "not_written"
BATCH_EXPORT_REDACTION_POLICY = "source-batch-envelope-public-safe"
BATCH_EXPORT_MATERIALIZED_STATUS = "materialized"
BATCH_EXPORT_MATERIALIZED_STORAGE_STATUS = "written_local_object_store"
LOCAL_FILESYSTEM_ADAPTER_NAME = "local_filesystem"
CHECKSUM_ALGORITHM = "sha256-canonical-json-v1"
INTEGRITY_CHAIN_ALGORITHM = "sha256-hash-chain-v1"

MAX_ENVELOPES_PER_EXPORT = 1000


def _default_controls() -> list[str]:
    return [
        "approval_required",
        "idempotency_enforced",
        "metadata_only_envelopes",
        "local_artifact_retrieval_only",
    ]


class ConnectorSourceBatchExportError(ValueError):
    """Operator-input or state failure with a public-safe reason."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorSourceBatchExportScopeDenied(PermissionError):
    """The verified principal lacks the required batch-export scope."""

    def __init__(self, required_scope: str) -> None:
        super().__init__(f"missing_scope:{required_scope}")
        self.required_scope = required_scope


class ConnectorSourceBatchExportRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=180)
    export_request_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    idempotency_key: str = Field(min_length=8, max_length=200)
    requested_by: str = Field(min_length=1, max_length=160)
    owner_role: str = Field(min_length=1, max_length=160)
    risk_level: str = Field(min_length=1, max_length=40)
    approval_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    export_reason: str = Field(min_length=1, max_length=240)
    actor_scopes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConnectorSourceBatchExportEnvelopeFilter(BaseModel):
    """Identity of what the export covers; no filter can widen it."""

    connector_id: str
    request_id: str


class ConnectorSourceBatchExportRequestRecord(BaseModel):
    tenant_id: str
    export_request_id: str
    idempotency_key: str
    status: str
    export_status: str
    storage_status: str
    requested_by: str
    owner_role: str
    risk_level: str
    approval_id: str
    workflow_id: str
    envelope_filter: ConnectorSourceBatchExportEnvelopeFilter
    export_reason: str
    requested_batch_count: int = Field(ge=0)
    total_row_count: int = Field(ge=0)
    envelope_checksum_sha256: str = Field(min_length=64, max_length=64)
    redaction_policy: str
    controls: list[str]
    permission_decision: dict
    decision: str | None = None
    decision_actor_id: str | None = None
    decision_note: str | None = None
    decided_at: datetime | None = None
    materialization_id: str | None = None
    materialization_idempotency_key: str | None = None
    materialized_by: str | None = None
    materialized_at: datetime | None = None
    storage_adapter: str | None = None
    storage_key: str | None = None
    storage_uri: str | None = None
    artifact_checksum_sha256: str | None = None
    artifact_size_bytes: int | None = None
    artifact_content_type: str | None = None
    audit_event_id: str | None = None
    audit_event_type: str
    notes: list[str]
    created_at: datetime
    updated_at: datetime
    idempotent_replay: bool = False


class ConnectorSourceBatchExportDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    decision: ApprovalDecision
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=600)


class ConnectorSourceBatchExportDecisionResult(BaseModel):
    tenant_id: str
    export_request_id: str
    approval_id: str
    workflow_id: str
    decision: ApprovalDecision
    status: str
    export_status: str
    actor_id: str
    export_request: ConnectorSourceBatchExportRequestRecord
    audit_event_id: str
    audit_event_type: str


class ConnectorSourceBatchExportMaterializationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    materialization_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    idempotency_key: str = Field(min_length=8, max_length=200)
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=240)


class ConnectorSourceBatchExportMaterializationResult(BaseModel):
    tenant_id: str
    export_request_id: str
    materialization_id: str
    idempotency_key: str
    status: str
    export_status: str
    storage_status: str
    storage_adapter: str
    storage_key: str
    storage_uri: str
    artifact_checksum_sha256: str = Field(min_length=64, max_length=64)
    artifact_size_bytes: int = Field(ge=0)
    artifact_content_type: str
    export_request: ConnectorSourceBatchExportRequestRecord
    audit_event_id: str
    audit_event_type: str
    idempotent_replay: bool = False


class ConnectorSourceBatchExportBundle(BaseModel):
    """The materialized artifact: metadata-only envelopes, nothing else."""

    manifest: dict
    integrity_proof: dict
    envelopes: list[dict]


def _envelope_from_batch(batch: SourceExtractionBatchView) -> dict:
    return batch.model_dump(mode="json")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _checksum(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _envelopes_checksum(envelopes: list[dict], request_id: str) -> str:
    return _checksum({"envelopes": envelopes, "request_id": request_id})


def _load_envelopes(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    request_id: str,
) -> list[dict]:
    rows = repository.get_connector_source_ingestion_request_batches(
        tenant_id,
        request_id,
        limit=MAX_ENVELOPES_PER_EXPORT + 1,
    )
    if len(rows) > MAX_ENVELOPES_PER_EXPORT:
        raise ConnectorSourceBatchExportError(
            "This request has more batches than one export may carry.",
            "batch_envelope_too_large",
        )
    return [
        _envelope_from_batch(
            SourceExtractionBatchView(
                batch_key=row.batch_key,
                binding_id=row.binding_id,
                resource_name=row.resource_name,
                pinned_schema_fingerprint=row.pinned_schema_fingerprint,
                observed_schema_fingerprint=row.observed_schema_fingerprint,
                ordering_mode=row.ordering_mode,
                has_watermark=row.cursor_watermark is not None,
                row_count=row.row_count,
                byte_size=row.byte_size,
                truncated=row.truncated,
                limit_reason=row.limit_reason,
                duration_ms=row.duration_ms,
                digest_sha256=row.digest_sha256,
                storage_uri=row.storage_uri,
                content_type=row.content_type,
                stored_size_bytes=row.stored_size_bytes,
                classification=row.classification,
                executed_by=row.executed_by,
                created_at=row.created_at,
            )
        )
        for row in rows
    ]


def _integrity_proof(envelopes: list[dict]) -> dict:
    chain_tip = "0" * 64
    hashes: list[str] = []
    for envelope in envelopes:
        envelope_hash = _checksum(envelope)
        chain_tip = hashlib.sha256(f"{chain_tip}:{envelope_hash}".encode()).hexdigest()
        hashes.append(envelope_hash)
    return {
        "algorithm": INTEGRITY_CHAIN_ALGORITHM,
        "verification_status": "verified",
        "envelope_count": len(envelopes),
        "chain_tip_sha256": chain_tip,
        "envelope_hashes": hashes,
    }


def _bundle_for_envelopes(
    *,
    record_row,
    envelopes: list[dict],
    generated_at: datetime,
) -> ConnectorSourceBatchExportBundle:
    manifest = {
        "export_id": (
            f"source-batch-envelope-export-{record_row.envelope_checksum_sha256[:16]}"
        ),
        "generated_at": generated_at.isoformat(),
        "tenant_id": record_row.tenant_id,
        "connector_id": record_row.connector_id,
        "request_id": record_row.request_id,
        "export_request_id": record_row.export_request_id,
        "batch_count": len(envelopes),
        "total_row_count": sum(int(env["row_count"]) for env in envelopes),
        "format": "json",
        "redaction_policy": BATCH_EXPORT_REDACTION_POLICY,
        "checksum_algorithm": CHECKSUM_ALGORITHM,
        "envelope_checksum_sha256": record_row.envelope_checksum_sha256,
        "watermark_disclosure": "presence_only",
    }
    return ConnectorSourceBatchExportBundle(
        manifest=manifest,
        integrity_proof=_integrity_proof(envelopes),
        envelopes=envelopes,
    )


def _record_from_row(row, *, idempotent_replay: bool = False):
    audit_event_id = row.audit_event_id
    if isinstance(audit_event_id, UUID):
        audit_event_id = str(audit_event_id)
    return ConnectorSourceBatchExportRequestRecord(
        tenant_id=row.tenant_id,
        export_request_id=row.export_request_id,
        idempotency_key=row.idempotency_key,
        status=row.status,
        export_status=row.export_status,
        storage_status=row.storage_status,
        requested_by=row.requested_by,
        owner_role=row.owner_role,
        risk_level=row.risk_level,
        approval_id=row.approval_id,
        workflow_id=row.workflow_id,
        envelope_filter=ConnectorSourceBatchExportEnvelopeFilter(
            connector_id=row.connector_id,
            request_id=row.request_id,
        ),
        export_reason=row.export_reason,
        requested_batch_count=row.batch_count,
        total_row_count=row.total_row_count,
        envelope_checksum_sha256=row.envelope_checksum_sha256,
        redaction_policy=row.redaction_policy,
        controls=list(row.controls),
        permission_decision=dict(row.permission_decision),
        decision=row.decision,
        decision_actor_id=row.decision_actor_id,
        decision_note=row.decision_note,
        decided_at=row.decided_at,
        materialization_id=row.materialization_id,
        materialization_idempotency_key=row.materialization_idempotency_key,
        materialized_by=row.materialized_by,
        materialized_at=row.materialized_at,
        storage_adapter=row.storage_adapter,
        storage_key=row.storage_key,
        storage_uri=row.storage_uri,
        artifact_checksum_sha256=row.artifact_checksum_sha256,
        artifact_size_bytes=row.artifact_size_bytes,
        artifact_content_type=row.artifact_content_type,
        audit_event_id=audit_event_id,
        audit_event_type=row.audit_event_type,
        notes=list(row.notes),
        created_at=row.created_at,
        updated_at=row.updated_at,
        idempotent_replay=idempotent_replay,
    )


def _request_fingerprint(request: ConnectorSourceBatchExportRequestInput) -> tuple:
    return (
        request.connector_id,
        request.request_id,
        request.export_reason,
        request.owner_role,
        request.risk_level,
        request.approval_id,
        request.workflow_id,
    )


def _row_fingerprint(row) -> tuple:
    return (
        row.connector_id,
        row.request_id,
        row.export_reason,
        row.owner_role,
        row.risk_level,
        row.approval_id,
        row.workflow_id,
    )


def _evaluate_permission_or_raise(
    *,
    scope: str,
    tenant_id: str,
    actor_id: str,
    actor_scopes: list[str],
    attributes: dict,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_scopes=actor_scopes,
            required_scopes=[scope],
            attributes=attributes,
        )
    )
    if not decision.allowed:
        raise ConnectorSourceBatchExportScopeDenied(scope)
    return decision


def ensure_connector_source_batch_export_approval_record(
    repository: AxisPersistenceRepository,
    row,
) -> None:
    existing = repository.get_approval_record(row.tenant_id, row.approval_id)
    if existing is not None:
        return
    repository.create_approval_record(
        ApprovalRecordCreate(
            tenant_id=row.tenant_id,
            approval_id=row.approval_id,
            workflow_id=row.workflow_id,
            action_id=f"connector_source_batch_export:{row.connector_id}",
            requested_by=row.requested_by,
            owner_role=row.owner_role,
            risk_level=row.risk_level,
            payload={
                "export_request_id": row.export_request_id,
                "idempotency_key": row.idempotency_key,
                "connector_id": row.connector_id,
                "ingestion_request_id": row.request_id,
                "export_reason": row.export_reason,
                "required_permission": SOURCE_BATCH_EXPORT_REQUEST_SCOPE,
                "requested_batch_count": row.batch_count,
                "total_row_count": row.total_row_count,
                "envelope_checksum_sha256": row.envelope_checksum_sha256,
                "redaction_policy": row.redaction_policy,
                "storage_status": row.storage_status,
            },
        )
    )


def record_connector_source_batch_export_request(
    repository: AxisPersistenceRepository,
    *,
    request: ConnectorSourceBatchExportRequestInput,
) -> ConnectorSourceBatchExportRequestRecord:
    """Record an approval-gated export of one request's batch envelopes."""
    permission_decision = _evaluate_permission_or_raise(
        scope=SOURCE_BATCH_EXPORT_REQUEST_SCOPE,
        tenant_id=request.tenant_id,
        actor_id=request.requested_by,
        actor_scopes=request.actor_scopes,
        attributes={
            "connector_id": request.connector_id,
            "request_id": request.request_id,
            "export_request_id": request.export_request_id,
            "approval_id": request.approval_id,
            "workflow_id": request.workflow_id,
            "risk_level": request.risk_level,
            "export_reason": request.export_reason,
            "storage_status": BATCH_EXPORT_REQUEST_STORAGE_STATUS,
        },
    )

    existing_replay = (
        repository.get_connector_source_batch_export_request_by_idempotency_key(
            request.tenant_id,
            request.idempotency_key,
        )
    )
    if existing_replay is not None:
        if _row_fingerprint(existing_replay) != _request_fingerprint(request):
            raise ConnectorSourceBatchExportError(
                "That idempotency key already names a different export request.",
                "idempotency_conflict",
            )
        return _record_from_row(existing_replay, idempotent_replay=True)

    if (
        repository.get_connector_source_batch_export_request(
            request.tenant_id,
            request.export_request_id,
        )
        is not None
    ):
        raise ConnectorSourceBatchExportError(
            "That export request ID already exists.",
            "export_request_id_already_exists",
        )

    ingestion_request = repository.get_connector_source_ingestion_request(
        request.tenant_id,
        request.request_id,
    )
    if ingestion_request is None:
        raise ConnectorSourceBatchExportError(
            "That ingestion request does not exist.",
            "ingestion_request_not_found",
        )
    if ingestion_request.connector_id != request.connector_id:
        raise ConnectorSourceBatchExportError(
            "That ingestion request does not exist for this connector.",
            "ingestion_request_not_found",
        )

    envelopes = _load_envelopes(
        repository,
        tenant_id=request.tenant_id,
        request_id=request.request_id,
    )
    envelope_checksum = _envelopes_checksum(envelopes, request.request_id)
    batch_count = len(envelopes)
    total_row_count = sum(int(env["row_count"]) for env in envelopes)

    try:
        # The unique (tenant, idempotency_key)/(tenant, export_request_id)
        # constraints are the concurrency backstop. Audit append and row
        # insert share ONE savepoint: a racing duplicate loses both, so the
        # winner commits exactly one row plus one event.
        with repository.session.begin_nested():
            audit_event = repository.append_audit_event(
                AuditEventCreate(
                    tenant_id=request.tenant_id,
                    actor_id=request.requested_by,
                    event_type=BATCH_EXPORT_REQUESTED_EVENT,
                    payload={
                        "export_request_id": request.export_request_id,
                        "idempotency_key": request.idempotency_key,
                        "connector_id": request.connector_id,
                        "request_id": request.request_id,
                        "export_reason": request.export_reason,
                        "status": BATCH_EXPORT_REQUEST_STATUS,
                        "export_status": BATCH_EXPORT_REQUEST_EXPORT_STATUS,
                        "storage_status": BATCH_EXPORT_REQUEST_STORAGE_STATUS,
                        "approval_id": request.approval_id,
                        "workflow_id": request.workflow_id,
                        "owner_role": request.owner_role,
                        "risk_level": request.risk_level,
                        "required_scope": SOURCE_BATCH_EXPORT_REQUEST_SCOPE,
                        "permission_decision": permission_decision.model_dump(),
                        "batch_count": batch_count,
                        "total_row_count": total_row_count,
                        "envelope_checksum_sha256": envelope_checksum,
                        "redaction_policy": BATCH_EXPORT_REDACTION_POLICY,
                        "controls": _default_controls(),
                    },
                )
            )
            row = repository.create_connector_source_batch_export_request(
                ConnectorSourceBatchExportRequestCreate(
                    tenant_id=request.tenant_id,
                    connector_id=request.connector_id,
                    request_id=request.request_id,
                    export_request_id=request.export_request_id,
                    idempotency_key=request.idempotency_key,
                    requested_by=request.requested_by,
                    owner_role=request.owner_role,
                    risk_level=request.risk_level,
                    approval_id=request.approval_id,
                    workflow_id=request.workflow_id,
                    export_reason=request.export_reason,
                    batch_count=batch_count,
                    total_row_count=total_row_count,
                    envelope_checksum_sha256=envelope_checksum,
                    redaction_policy=BATCH_EXPORT_REDACTION_POLICY,
                    controls=_default_controls(),
                    permission_decision=permission_decision.model_dump(),
                    audit_event_id=audit_event.id,
                    audit_event_type=BATCH_EXPORT_REQUESTED_EVENT,
                    notes=request.notes,
                )
            )
    except IntegrityError:
        raced = (
            repository.get_connector_source_batch_export_request_by_idempotency_key(
                request.tenant_id,
                request.idempotency_key,
            )
        ) or repository.get_connector_source_batch_export_request(
            request.tenant_id,
            request.export_request_id,
        )
        if raced is None:
            raise
        if _row_fingerprint(raced) != _request_fingerprint(request):
            raise ConnectorSourceBatchExportError(
                "That idempotency key already names a different export request.",
                "idempotency_conflict",
            ) from None
        return _record_from_row(raced, idempotent_replay=True)
    ensure_connector_source_batch_export_approval_record(repository, row)
    return _record_from_row(row)


def normalize_decision_note(note: str | None) -> str | None:
    """Canonical form of an optional decision note.

    Whitespace runs collapse to single spaces and the result is trimmed;
    a blank note is stored exactly like an absent one. Comparison, persistence
    and audit all use this normalized value, so cosmetic whitespace never
    fabricates a replay conflict while a materially different note does.
    """
    if note is None:
        return None
    collapsed = " ".join(note.split())
    return collapsed or None


def _decision_statuses(decision: ApprovalDecision) -> tuple[str, str]:
    if decision == ApprovalDecision.APPROVE:
        return "approval_approved", "approved_not_exported"
    if decision == ApprovalDecision.REJECT:
        return "approval_rejected", "rejected_not_exported"
    return "changes_requested", "changes_requested_not_exported"


def decide_connector_source_batch_export_request(
    repository: AxisPersistenceRepository,
    *,
    request_id: str,
    export_request_id: str,
    decision_input: ConnectorSourceBatchExportDecisionInput,
) -> ConnectorSourceBatchExportDecisionResult:
    tenant_id = decision_input.tenant_id
    decision_input = decision_input.model_copy(
        update={"note": normalize_decision_note(decision_input.note)}
    )
    row = _get_export_request_or_error(
        repository,
        tenant_id=tenant_id,
        request_id=request_id,
        export_request_id=export_request_id,
    )
    # Authorization FIRST: even an exact replay must prove the mutation scope
    # against the authenticated tenant/actor before any persisted state is
    # reflected back. No early return bypasses this gate.
    _evaluate_permission_or_raise(
        scope=SOURCE_BATCH_EXPORT_DECISION_SCOPE,
        tenant_id=row.tenant_id,
        actor_id=decision_input.actor_id,
        actor_scopes=decision_input.actor_scopes,
        attributes={
            "connector_id": row.connector_id,
            "request_id": row.request_id,
            "export_request_id": row.export_request_id,
            "approval_id": row.approval_id,
            "workflow_id": row.workflow_id,
            "risk_level": row.risk_level,
            "decision": decision_input.decision.value,
            "storage_status": row.storage_status,
        },
    )
    # Semantic identity is the FULL recorded ask — decision, actor, and the
    # normalized note — mirroring the approval boundary, where a different
    # actor, decision, OR NOTE can never silently replay as identical.
    if (
        row.decision == decision_input.decision.value
        and row.decision_actor_id == decision_input.actor_id
        and row.decision_note == decision_input.note
    ):
        return _decision_result_from_row(row, decision_input)
    if row.decision is not None:
        raise ConnectorSourceBatchExportError(
            "That export request already carries a final decision.",
            "decision_conflict",
        )
    status, export_status = _decision_statuses(decision_input.decision)
    changed = repository.record_connector_source_batch_export_decision(
        ConnectorSourceBatchExportDecisionRecord(
            tenant_id=row.tenant_id,
            export_request_id=row.export_request_id,
            status=status,
            export_status=export_status,
            decision=decision_input.decision.value,
            decision_actor_id=decision_input.actor_id,
            decision_note=decision_input.note,
        )
    )
    if not changed:
        # A concurrent decision won the fence. An ask identical to the
        # winner's FULL recorded ask replays canonical truth; anything else
        # conflicts. Nothing was written on this losing path.
        winner = repository.get_connector_source_batch_export_request(
            row.tenant_id,
            row.export_request_id,
        )
        assert winner is not None
        if (
            winner.decision == decision_input.decision.value
            and winner.decision_actor_id == decision_input.actor_id
            and winner.decision_note == decision_input.note
        ):
            return _decision_result_from_row(winner, decision_input)
        raise ConnectorSourceBatchExportError(
            "That export request already carries a final decision.",
            "decision_conflict",
        )
    # All writes happen only after the fence is won, inside one transaction:
    # the canonical approval decision, the audit event, and its row linkage.
    ensure_connector_source_batch_export_approval_record(repository, row)
    repository.record_approval_decision(
        ApprovalDecisionRecord(
            tenant_id=row.tenant_id,
            approval_id=row.approval_id,
            decision=decision_input.decision.value,
            decision_actor_id=decision_input.actor_id,
            decision_note=decision_input.note,
        )
    )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=row.tenant_id,
            actor_id=decision_input.actor_id,
            event_type=BATCH_EXPORT_DECISION_EVENT,
            payload={
                "export_request_id": row.export_request_id,
                "idempotency_key": row.idempotency_key,
                "connector_id": row.connector_id,
                "request_id": row.request_id,
                "approval_id": row.approval_id,
                "workflow_id": row.workflow_id,
                "decision": decision_input.decision.value,
                "status": status,
                "export_status": export_status,
                "storage_status": row.storage_status,
                "required_scope": SOURCE_BATCH_EXPORT_DECISION_SCOPE,
                "batch_count": row.batch_count,
                "envelope_checksum_sha256": row.envelope_checksum_sha256,
                "decision_note_recorded": str(decision_input.note is not None).lower(),
            },
        )
    )
    repository.link_connector_source_batch_export_audit(
        tenant_id=row.tenant_id,
        export_request_id=row.export_request_id,
        audit_event_id=audit_event.id,
        audit_event_type=BATCH_EXPORT_DECISION_EVENT,
    )
    refreshed = repository.get_connector_source_batch_export_request(
        row.tenant_id,
        row.export_request_id,
    )
    assert refreshed is not None
    return _decision_result_from_row(refreshed, decision_input)


def _decision_result_from_row(
    row,
    decision_input: ConnectorSourceBatchExportDecisionInput,
) -> ConnectorSourceBatchExportDecisionResult:
    status, export_status = _decision_statuses(decision_input.decision)
    audit_event_id = row.audit_event_id
    if isinstance(audit_event_id, UUID):
        audit_event_id = str(audit_event_id)
    return ConnectorSourceBatchExportDecisionResult(
        tenant_id=row.tenant_id,
        export_request_id=row.export_request_id,
        approval_id=row.approval_id,
        workflow_id=row.workflow_id,
        decision=decision_input.decision,
        status=status,
        export_status=export_status,
        actor_id=decision_input.actor_id,
        export_request=_record_from_row(row),
        audit_event_id=audit_event_id or "",
        audit_event_type=row.audit_event_type,
    )


def materialize_connector_source_batch_export_request(
    repository: AxisPersistenceRepository,
    *,
    object_store,
    request_id: str,
    export_request_id: str,
    materialization_input: ConnectorSourceBatchExportMaterializationInput,
    now: datetime | None = None,
) -> ConnectorSourceBatchExportMaterializationResult:
    tenant_id = materialization_input.tenant_id
    now = now or datetime.now(UTC)
    row = _get_export_request_or_error(
        repository,
        tenant_id=tenant_id,
        request_id=request_id,
        export_request_id=export_request_id,
    )
    _evaluate_permission_or_raise(
        scope=SOURCE_BATCH_EXPORT_MATERIALIZE_SCOPE,
        tenant_id=row.tenant_id,
        actor_id=materialization_input.actor_id,
        actor_scopes=materialization_input.actor_scopes,
        attributes={
            "connector_id": row.connector_id,
            "request_id": row.request_id,
            "export_request_id": row.export_request_id,
            "approval_id": row.approval_id,
            "workflow_id": row.workflow_id,
            "decision": row.decision,
            "storage_status": row.storage_status,
            "materialization_id": materialization_input.materialization_id,
        },
    )
    replay = _existing_materialization_result(row, materialization_input)
    if replay is not None:
        return replay
    _ensure_export_request_can_materialize(row)

    envelopes = _load_envelopes(
        repository,
        tenant_id=row.tenant_id,
        request_id=row.request_id,
    )
    recomputed = _envelopes_checksum(envelopes, row.request_id)
    if recomputed != row.envelope_checksum_sha256:
        raise ConnectorSourceBatchExportError(
            "The batch evidence changed since this export was requested.",
            "envelope_checksum_changed",
        )

    # State-machine ordering: the single-shot DATABASE fence is taken BEFORE
    # any byte reaches the object store. A concurrent loser therefore writes
    # neither a second audit event nor an orphan local object; only the
    # winner's bytes land, inside its still-open transaction.
    bundle = _bundle_for_envelopes(record_row=row, envelopes=envelopes, generated_at=now)
    storage_key = _materialization_storage_key(row, materialization_input)
    encoded_bundle = _canonical_json(bundle.model_dump(mode="json")).encode("utf-8")
    artifact_checksum = hashlib.sha256(encoded_bundle).hexdigest()
    artifact_size = len(encoded_bundle)
    changed = repository.record_connector_source_batch_export_materialization(
        ConnectorSourceBatchExportMaterializationRecord(
            tenant_id=row.tenant_id,
            export_request_id=row.export_request_id,
            status=BATCH_EXPORT_MATERIALIZED_STATUS,
            export_status=BATCH_EXPORT_MATERIALIZED_STATUS,
            storage_status=BATCH_EXPORT_MATERIALIZED_STORAGE_STATUS,
            materialization_id=materialization_input.materialization_id,
            materialization_idempotency_key=materialization_input.idempotency_key,
            materialized_by=materialization_input.actor_id,
            materialization_reason=materialization_input.reason,
            storage_adapter=getattr(object_store, "adapter_name", LOCAL_FILESYSTEM_ADAPTER_NAME),
            storage_key=storage_key,
            storage_uri=f"axis-local-object-store://{storage_key}",
            artifact_checksum_sha256=artifact_checksum,
            artifact_size_bytes=artifact_size,
            artifact_content_type="application/json",
        )
    )
    if not changed:
        # A concurrent materializer won the single-shot fence; NOTHING was
        # written to the object store on this losing path. An ask identical to
        # the winner's replays canonical truth, anything else conflicts.
        winner = repository.get_connector_source_batch_export_request(
            row.tenant_id,
            row.export_request_id,
        )
        assert winner is not None
        replayed = _existing_materialization_result(winner, materialization_input)
        if replayed is not None:
            return replayed
        raise ConnectorSourceBatchExportError(
            "A different materialization already exists for that export request.",
            "materialization_idempotency_conflict",
        )
    stored_object = object_store.put_json(storage_key, bundle.model_dump(mode="json"))
    if (
        stored_object.checksum_sha256 != artifact_checksum
        or stored_object.size_bytes != artifact_size
        or stored_object.storage_key != storage_key
    ):
        # Deterministic adapters must agree with the precomputed metadata; any
        # divergence rolls the whole transaction back rather than recording a
        # digest the stored bytes do not carry.
        raise ConnectorSourceBatchExportError(
            "The object store returned unexpected artifact metadata.",
            "artifact_metadata_mismatch",
        )
    # Audit + linkage are written only after the fence is won, inside the
    # same transaction: exactly one materialized event can ever exist.
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=row.tenant_id,
            actor_id=materialization_input.actor_id,
            event_type=BATCH_EXPORT_MATERIALIZED_EVENT,
            payload={
                "export_request_id": row.export_request_id,
                "materialization_id": materialization_input.materialization_id,
                "idempotency_key": materialization_input.idempotency_key,
                "connector_id": row.connector_id,
                "request_id": row.request_id,
                "approval_id": row.approval_id,
                "workflow_id": row.workflow_id,
                "decision": row.decision,
                "export_status": BATCH_EXPORT_MATERIALIZED_STATUS,
                "storage_status": BATCH_EXPORT_MATERIALIZED_STORAGE_STATUS,
                "storage_adapter": stored_object.storage_adapter,
                "storage_key": stored_object.storage_key,
                "storage_uri": stored_object.storage_uri,
                "artifact_checksum_sha256": stored_object.checksum_sha256,
                "artifact_size_bytes": stored_object.size_bytes,
                "artifact_content_type": stored_object.content_type,
                "batch_count": row.batch_count,
                "total_row_count": row.total_row_count,
                "required_scope": SOURCE_BATCH_EXPORT_MATERIALIZE_SCOPE,
            },
        )
    )
    repository.link_connector_source_batch_export_audit(
        tenant_id=row.tenant_id,
        export_request_id=row.export_request_id,
        audit_event_id=audit_event.id,
        audit_event_type=BATCH_EXPORT_MATERIALIZED_EVENT,
    )
    refreshed = repository.get_connector_source_batch_export_request(
        row.tenant_id,
        row.export_request_id,
    )
    assert refreshed is not None
    return _materialization_result_from_record(refreshed)


def _get_export_request_or_error(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    request_id: str,
    export_request_id: str,
):
    row = repository.get_connector_source_batch_export_request(
        tenant_id,
        export_request_id,
    )
    if row is None or row.request_id != request_id:
        raise ConnectorSourceBatchExportError(
            "That batch-envelope export request does not exist.",
            "batch_export_request_not_found",
        )
    return row


def _ensure_export_request_can_materialize(row) -> None:
    if (
        row.status != "approval_approved"
        or row.export_status != "approved_not_exported"
        or row.decision != ApprovalDecision.APPROVE.value
    ):
        raise ConnectorSourceBatchExportError(
            "Only approved export requests can be materialized.",
            "export_request_not_approved",
        )
    if row.storage_status != BATCH_EXPORT_REQUEST_STORAGE_STATUS:
        raise ConnectorSourceBatchExportError(
            "That export request already has a written artifact.",
            "export_request_already_materialized",
        )


def _existing_materialization_result(
    row,
    materialization_input: ConnectorSourceBatchExportMaterializationInput,
):
    if row.materialization_id is None:
        return None
    if (
        row.materialization_id == materialization_input.materialization_id
        and row.materialization_idempotency_key == materialization_input.idempotency_key
    ):
        return _materialization_result_from_record(row, idempotent_replay=True)
    raise ConnectorSourceBatchExportError(
        "A different materialization already exists for that export request.",
        "materialization_idempotency_conflict",
    )


def _materialization_storage_key(row, materialization_input) -> str:
    return (
        f"{row.tenant_id}/source-batch-envelope-exports/"
        f"{row.export_request_id}/{materialization_input.materialization_id}.json"
    )


def _materialization_result_from_record(
    row,
    *,
    idempotent_replay: bool = False,
):
    return ConnectorSourceBatchExportMaterializationResult(
        tenant_id=row.tenant_id,
        export_request_id=row.export_request_id,
        materialization_id=row.materialization_id,
        idempotency_key=row.materialization_idempotency_key,
        status=row.status,
        export_status=row.export_status,
        storage_status=row.storage_status,
        storage_adapter=row.storage_adapter,
        storage_key=row.storage_key,
        storage_uri=row.storage_uri,
        artifact_checksum_sha256=row.artifact_checksum_sha256,
        artifact_size_bytes=row.artifact_size_bytes,
        artifact_content_type=row.artifact_content_type,
        export_request=_record_from_row(row),
        audit_event_id=str(row.audit_event_id),
        audit_event_type=row.audit_event_type,
        idempotent_replay=idempotent_replay,
    )


class LocalBatchExportArtifactReader:
    """Containment-checked read-back of materialized artifacts.

    Deliberately local-only: serving operator downloads must never construct a
    cloud client. Non-local adapters are rejected upstream with
    ``store_adapter_unsupported`` before any read is attempted.
    """

    adapter_name = LOCAL_FILESYSTEM_ADAPTER_NAME

    def __init__(self, root: Path) -> None:
        self._root = root

    def read_bytes(self, key: str) -> bytes:
        if key.startswith("/") or any(part in ("", ".", "..") for part in key.split("/")):
            raise ConnectorSourceBatchExportError(
                "That artifact reference is not readable.",
                "artifact_key_unsafe",
            )
        path = self._root.joinpath(*key.split("/"))
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ConnectorSourceBatchExportError(
                "The materialized artifact could not be read.",
                "artifact_unreadable",
            ) from exc


def read_connector_source_batch_export_artifact(
    repository: AxisPersistenceRepository,
    *,
    reader: LocalBatchExportArtifactReader,
    tenant_id: str,
    request_id: str,
    export_request_id: str,
    actor_id: str,
) -> tuple[ConnectorSourceBatchExportBundle, ConnectorSourceBatchExportRequestRecord, bytes]:
    """Verify and return one materialized artifact; every read is audited.

    The exact stored bytes are returned so operators receive byte-for-byte what
    the checksum was recorded over — no re-serialization drift.
    """
    row = _get_export_request_or_error(
        repository,
        tenant_id=tenant_id,
        request_id=request_id,
        export_request_id=export_request_id,
    )
    if row.storage_status != BATCH_EXPORT_MATERIALIZED_STORAGE_STATUS:
        raise ConnectorSourceBatchExportError(
            "No artifact exists yet for that export request.",
            "artifact_not_written",
        )
    if row.storage_adapter != LOCAL_FILESYSTEM_ADAPTER_NAME:
        raise ConnectorSourceBatchExportError(
            "Artifact retrieval supports only the local filesystem adapter.",
            "store_adapter_unsupported",
        )
    raw = reader.read_bytes(str(row.storage_key))
    digest = hashlib.sha256(raw).hexdigest()
    if digest != row.artifact_checksum_sha256:
        raise ConnectorSourceBatchExportError(
            "The stored artifact no longer matches its recorded checksum.",
            "artifact_checksum_mismatch",
        )
    try:
        bundle = ConnectorSourceBatchExportBundle.model_validate(json.loads(raw))
    except (ValueError, TypeError) as exc:
        raise ConnectorSourceBatchExportError(
            "The stored artifact could not be parsed.",
            "artifact_unparseable",
        ) from exc
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=row.tenant_id,
            actor_id=actor_id,
            event_type=BATCH_EXPORT_ARTIFACT_READ_EVENT,
            payload={
                "export_request_id": row.export_request_id,
                "connector_id": row.connector_id,
                "request_id": row.request_id,
                "materialization_id": row.materialization_id,
                "artifact_checksum_sha256": row.artifact_checksum_sha256,
                "artifact_size_bytes": row.artifact_size_bytes,
            },
        )
    )
    return bundle, _record_from_row(row), raw
