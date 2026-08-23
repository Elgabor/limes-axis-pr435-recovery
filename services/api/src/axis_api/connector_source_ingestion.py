"""Governed ingestion requests over active source bindings.

Activation (Batch 8) made discovered tables durable and honest about being
``pending_ingestion``. This module is the boundary that consumes that state —
without pretending extraction has happened: an operator pins eligible bindings
into a governed request, the request is dispatched through a leased, fenced
outbox exactly like approval decisions, and this batch's runtime executes the
pipeline's **validation stage**: every pinned fingerprint is re-checked against
Axis' current observations, and the recorded evidence states explicitly that no
source dial and no row read occurred. A future runtime that adds real
extraction implements the same port and flips those flags truthfully.

Creation is idempotent per ``(tenant_id, request_id)``, fails closed on stale or
inactive bindings with precise reasons, and appends audit evidence with IDs and
counts only. Dispatch state transitions live once here: claim with lease +
claim-token fencing, permanent failures dead-letter, operational failures retry
with jittered backoff.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_source_extraction import (
    EXTRACTION_ACTOR,
    EXTRACTION_STAGE,
    VALIDATE_STAGE,
    planned_extraction_limits,
)
from axis_api.db import session_scope
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorSourceExtractionBatchCreate,
    ConnectorSourceIngestionRequestCreate,
)

SOURCE_INGESTION_SCOPE = "connectors:source:ingest"
SOURCE_INGESTION_READ_SCOPE = "connectors:source:ingest:read"

INGESTION_REQUESTED_EVENT = "connector.source.ingestion.requested"
INGESTION_COMPLETED_EVENT = "connector.source.ingestion.validation_completed"
INGESTION_FAILED_EVENT = "connector.source.ingestion.dead_lettered"
INGESTION_ACTOR = "axis-source-ingestion-outbox"

# Read-side bound for the attempt timeline: durable evidence stays append-only,
# but views expose only the NEWEST window in chronological order and say so via
# ``attempts_truncated`` — never silently, never unbounded.
MAX_ATTEMPT_TIMELINE_ENTRIES = 50

BINDING_PENDING_INGESTION_STATUS = "pending_ingestion"
BINDING_ACTIVE_STATUS = "active"

_REQUEST_ID_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9._:-]*$"


class SourceIngestionScopeDenied(PermissionError):
    """The verified principal lacks ``connectors:source:ingest``."""

    def __init__(self) -> None:
        super().__init__(f"missing_scope:{SOURCE_INGESTION_SCOPE}")
        self.required_scope = SOURCE_INGESTION_SCOPE


class ConnectorSourceIngestionError(ValueError):
    """Operator-input failure with a public-safe reason."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class SourceIngestionSelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str = Field(min_length=1, max_length=180)


class ConnectorSourceIngestionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    request_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=_REQUEST_ID_PATTERN,
    )
    requested_by: str = Field(min_length=1, max_length=160)
    # Required governance reason; stored verbatim as request evidence.
    reason: str = Field(min_length=1, max_length=600)
    # "validate" (default, Batch 9 behavior) or "extract" (real bounded read;
    # rejected at create time unless the deployment enables extraction).
    stage: str = Field(default=VALIDATE_STAGE)
    selections: list[SourceIngestionSelectionInput] = Field(min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)


class SourceIngestionEligibilityRow(BaseModel):
    """One binding's readiness for governed ingestion, honestly labelled."""

    binding_id: str
    resource_name: str
    schema_fingerprint: str
    eligible: bool
    blocked_reason: str | None = None


class SourceIngestionSelectionView(BaseModel):
    binding_id: str
    resource_name: str
    schema_fingerprint: str


class ConnectorSourceIngestionCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    cancelled_by: str = Field(min_length=1, max_length=160)
    # Optional public-safe reason; truncated to the durable column bound.
    reason: str | None = Field(default=None, max_length=200)
    actor_scopes: list[str] = Field(default_factory=list)


class ConnectorSourceIngestionRequeueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    requeued_by: str = Field(min_length=1, max_length=160)
    # Required remediation governance reason; stored verbatim as evidence.
    reason: str = Field(min_length=1, max_length=600)
    # Explicit operator idempotency identity; replays must repeat it exactly.
    idempotency_key: str = Field(
        min_length=8,
        max_length=180,
        pattern="^[A-Za-z0-9_][A-Za-z0-9._:-]*$",
    )
    actor_scopes: list[str] = Field(default_factory=list)


class SourceIngestionEligibilityView(BaseModel):
    """Eligibility rows plus the deployment's truthful extraction posture."""

    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    extraction_available: bool = False
    planned_limits: dict | None = None
    rows: list[SourceIngestionEligibilityRow] = Field(default_factory=list)


class SourceExtractionSummary(BaseModel):
    """Public-safe summary of what extraction durably produced."""

    batch_count: int = Field(ge=0)
    total_rows: int = Field(ge=0)
    truncated_any: bool = False


class SourceIngestionAttemptSelectionView(BaseModel):
    """One selection's outcome inside one finalized dispatch attempt."""

    binding_id: str
    resource_name: str
    outcome: str = Field(pattern="^(validated|failed)$")
    reason: str | None = None


class SourceIngestionAttemptView(BaseModel):
    """One finalized dispatch attempt, metadata-only.

    The timeline records what the outbox actually concluded per attempt:
    completion, retry (operational), or dead-letter (permanent) — with the
    public-safe failure code and each selection's validation verdict. Row
    values, fingerprints beyond the pinned pair, and any payload-like material
    never appear here.
    """

    attempt_number: int = Field(ge=1)
    outcome: str = Field(pattern="^(completed|retried|dead_lettered)$")
    error_code: str | None = None
    finished_at: datetime | None = None
    selections: list[SourceIngestionAttemptSelectionView] = Field(default_factory=list)


class SourceIngestionRequestView(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    stage: str = Field(pattern="^(validate|extract)$")
    status: str = Field(pattern="^(pending|dispatching|completed|failed|cancelled)$")
    attempt_count: int = Field(ge=0)
    selections: list[SourceIngestionSelectionView]
    outcome: str = Field(pattern="^(created|replayed)$")
    planned_limits: dict | None = None
    extraction: SourceExtractionSummary | None = None
    attempts: list[SourceIngestionAttemptView] = Field(default_factory=list)
    attempts_truncated: bool = False
    last_error: str | None = None
    completed_at: datetime | None = None
    dead_lettered_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


def max_source_ingestion_selections(settings: Settings) -> int:
    return settings.connector_source_ingestion_max_selections


def _request_view(row, *, outcome: str, settings=None) -> SourceIngestionRequestView:
    attempts, attempts_truncated = _attempt_views(row)
    return SourceIngestionRequestView(
        tenant_id=row.tenant_id,
        connector_id=row.connector_id,
        request_id=row.request_id,
        requested_by=row.requested_by,
        reason=row.reason,
        stage=row.stage,
        status=row.status,
        attempt_count=row.attempt_count,
        selections=[
            SourceIngestionSelectionView.model_validate(selection)
            for selection in row.selections
        ],
        outcome=outcome,
        planned_limits=planned_extraction_limits(settings) if settings else None,
        extraction=_extraction_summary(row),
        attempts=attempts,
        attempts_truncated=attempts_truncated,
        last_error=row.last_error,
        completed_at=row.completed_at,
        dead_lettered_at=row.dead_lettered_at,
        cancelled_at=getattr(row, "cancelled_at", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _attempt_views(row) -> tuple[list[SourceIngestionAttemptView], bool]:
    """Bounded read model over the durable attempt timeline.

    Durable evidence stays append-only; this view exposes only the NEWEST
    :data:`MAX_ATTEMPT_TIMELINE_ENTRIES` valid entries in their recorded
    chronological order and reports via ``attempts_truncated`` when older
    valid evidence exists. Malformed historical entries are skipped before
    windowing — they can never break a read and never count as visible
    history. Row values and watermark values cannot appear here because the
    parser accepts exactly five metadata fields per selection.
    """
    evidence = row.evidence if isinstance(row.evidence, dict) else {}
    raw_attempts = evidence.get("attempts")
    if not isinstance(raw_attempts, list):
        return [], False
    parsed: list[SourceIngestionAttemptView] = []
    for entry in raw_attempts:
        if not isinstance(entry, dict):
            continue
        finished_at: datetime | None = None
        raw_finished = entry.get("finished_at")
        if isinstance(raw_finished, str):
            try:
                finished_at = datetime.fromisoformat(raw_finished)
            except ValueError:
                finished_at = None
        try:
            parsed.append(
                SourceIngestionAttemptView(
                    attempt_number=int(entry["attempt_number"]),
                    outcome=str(entry["outcome"]),
                    error_code=entry.get("error_code"),
                    finished_at=finished_at,
                    selections=[
                        SourceIngestionAttemptSelectionView.model_validate(selection)
                        for selection in entry.get("selections", [])
                        if isinstance(selection, dict)
                    ],
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            continue
    if len(parsed) <= MAX_ATTEMPT_TIMELINE_ENTRIES:
        return parsed, False
    return parsed[-MAX_ATTEMPT_TIMELINE_ENTRIES:], True


def _attempt_timeline_entry(
    *,
    attempt_number: int,
    outcome: str,
    selections_evidence: list[dict],
    finished_at: datetime,
    error_code: str | None = None,
) -> dict:
    """Build one metadata-only attempt record for the durable timeline."""
    entry: dict = {
        "attempt_number": attempt_number,
        "outcome": outcome,
        "finished_at": finished_at.isoformat(),
        "selections": [
            {
                "binding_id": str(selection_evidence.get("binding_id", "")),
                "resource_name": str(selection_evidence.get("resource_name", "")),
                "outcome": str(
                    selection_evidence.get("outcome", "failed")
                ),
                **(
                    {"reason": str(selection_evidence["reason"])}
                    if selection_evidence.get("reason") is not None
                    else {}
                ),
            }
            for selection_evidence in selections_evidence
            if isinstance(selection_evidence, dict)
        ],
    }
    if error_code is not None:
        entry["error_code"] = error_code
    return entry


def _extraction_summary(row) -> SourceExtractionSummary | None:
    if getattr(row, "stage", VALIDATE_STAGE) != EXTRACTION_STAGE:
        return None
    evidence = row.evidence if isinstance(row.evidence, dict) else {}
    batches = evidence.get("batches") if isinstance(evidence.get("batches"), list) else []
    return SourceExtractionSummary(
        batch_count=len(batches),
        total_rows=sum(int(batch.get("row_count", 0)) for batch in batches),
        truncated_any=bool(batches)
        and any(bool(batch.get("truncated")) for batch in batches),
    )


def _binding_is_currently_fresh(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    connector_id: str,
    resource_name: str,
    schema_fingerprint: str,
) -> bool:
    observation = repository.get_data_resource_observation(
        tenant_id,
        connector_id,
        resource_name,
    )
    if observation is None:
        return False
    return (observation.schema_fingerprint or "") == schema_fingerprint


def preview_source_ingestion_eligibility(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    connector_id: str,
) -> list[SourceIngestionEligibilityRow]:
    """Per-binding readiness against current observations, fail-closed labels.

    A binding is eligible when it is active, still pending ingestion, and its
    activation-time fingerprint still matches the latest observed schema.
    """
    rows = repository.list_active_connector_source_bindings(tenant_id, connector_id)
    eligibility: list[SourceIngestionEligibilityRow] = []
    for row in rows:
        blocked_reason: str | None = None
        if row.ingestion_status != BINDING_PENDING_INGESTION_STATUS:
            blocked_reason = "binding_not_pending_ingestion"
        elif not _binding_is_currently_fresh(
            repository,
            tenant_id=tenant_id,
            connector_id=connector_id,
            resource_name=row.resource_name,
            schema_fingerprint=row.schema_fingerprint,
        ):
            blocked_reason = "stale_fingerprint"
        eligibility.append(
            SourceIngestionEligibilityRow(
                binding_id=row.binding_id,
                resource_name=row.resource_name,
                schema_fingerprint=row.schema_fingerprint,
                eligible=blocked_reason is None,
                blocked_reason=blocked_reason,
            )
        )
    return eligibility


def record_connector_source_ingestion_request(
    repository: AxisPersistenceRepository,
    *,
    submission: ConnectorSourceIngestionSubmission,
    principal_scopes: list[str],
    max_selections: int,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> SourceIngestionRequestView:
    """Create (or deterministically replay) one governed ingestion request.

    Replay is judged on identity alone (connector + reason + ordered binding
    IDs) and returns the stored request unchanged — never refreshed evidence.
    New requests fail closed unless every referenced binding belongs to this
    tenant/connector pair, is active, still awaits ingestion, and carries
    fingerprint evidence that is still current at request time. The server pins
    the fingerprints from the bindings themselves — clients never supply them.
    """
    if SOURCE_INGESTION_SCOPE not in principal_scopes:
        raise SourceIngestionScopeDenied()
    extraction_enabled = bool(
        settings
        and settings.source_ingestion_dispatch_enabled
        and settings.source_ingestion_extraction_enabled
    )
    if submission.stage == EXTRACTION_STAGE and not extraction_enabled:
        raise ConnectorSourceIngestionError(
            "Extraction is not enabled on this deployment; requests run validation only.",
            "extraction_disabled",
        )
    if len(submission.selections) > max_selections:
        raise ConnectorSourceIngestionError(
            f"At most {max_selections} bindings can be requested per submission.",
            "selection_too_large",
        )

    seen_binding_ids: set[str] = set()
    for selection in submission.selections:
        if selection.binding_id in seen_binding_ids:
            raise ConnectorSourceIngestionError(
                "Each binding may be selected only once per request.",
                "duplicate_binding_id",
            )
        seen_binding_ids.add(selection.binding_id)

    # Replay is judged on identity alone — same connector, same governance
    # reason, same ordered binding list — exactly like activation: re-submitting
    # the ask that produced an existing request returns it unchanged even if
    # evidence drifted afterwards. A replay never refreshes a claim.
    submitted_ids = [selection.binding_id for selection in submission.selections]
    existing = repository.get_connector_source_ingestion_request(
        submission.tenant_id,
        submission.request_id,
    )
    if existing is not None:
        _ensure_replay_matches(existing, submission, submitted_ids)
        return _request_view(existing, outcome="replayed", settings=settings)

    pinned: list[dict] = []
    for selection in submission.selections:
        binding = repository.get_connector_source_binding(
            submission.tenant_id,
            selection.binding_id,
        )
        if binding is None or binding.connector_id != submission.connector_id:
            raise ConnectorSourceIngestionError(
                "That binding does not exist for this connector.",
                "binding_not_found",
            )
        if binding.status != BINDING_ACTIVE_STATUS:
            raise ConnectorSourceIngestionError(
                "That binding is not active.",
                "binding_inactive",
            )
        if binding.ingestion_status != BINDING_PENDING_INGESTION_STATUS:
            raise ConnectorSourceIngestionError(
                "That binding is not waiting for ingestion.",
                "binding_not_pending_ingestion",
            )
        if not _binding_is_currently_fresh(
            repository,
            tenant_id=submission.tenant_id,
            connector_id=submission.connector_id,
            resource_name=binding.resource_name,
            schema_fingerprint=binding.schema_fingerprint,
        ):
            raise ConnectorSourceIngestionError(
                "A selected table's schema changed since it was activated; "
                "run discovery again and activate the fresh schema first.",
                "stale_fingerprint",
            )
        pinned.append(
            {
                "binding_id": binding.binding_id,
                "resource_name": binding.resource_name,
                "schema_fingerprint": binding.schema_fingerprint,
            }
        )

    now = now or datetime.now(UTC)

    try:
        # The unique constraint on (tenant_id, request_id) is the concurrency
        # backstop. Audit append and request insert share ONE savepoint: a
        # duplicate racing this insert loses both, so a replayed ask can never
        # leave two `requested` audit events behind, and the winner commits
        # exactly one row plus one event.
        with repository.session.begin_nested():
            audit_event = repository.append_audit_event(
                AuditEventCreate(
                    tenant_id=submission.tenant_id,
                    actor_id=submission.requested_by,
                    event_type=INGESTION_REQUESTED_EVENT,
                    payload={
                        "connector_id": submission.connector_id,
                        "request_id": submission.request_id,
                        "binding_count": str(len(pinned)),
                        "bindings": [
                            {
                                "binding_id": selection["binding_id"],
                                "resource_name": selection["resource_name"],
                                "schema_fingerprint": selection["schema_fingerprint"],
                            }
                            for selection in pinned
                        ],
                        "ingestion_status": BINDING_PENDING_INGESTION_STATUS,
                    },
                )
            )
            row = repository.create_connector_source_ingestion_request(
                ConnectorSourceIngestionRequestCreate(
                    tenant_id=submission.tenant_id,
                    connector_id=submission.connector_id,
                    request_id=submission.request_id,
                    requested_by=submission.requested_by,
                    reason=submission.reason,
                    stage=submission.stage,
                    selections=pinned,
                    audit_event_id=audit_event.id,
                    audit_event_type=INGESTION_REQUESTED_EVENT,
                ),
                available_at=now,
            )
    except IntegrityError:
        raced = repository.get_connector_source_ingestion_request(
            submission.tenant_id,
            submission.request_id,
        )
        if raced is None:
            raise
        _ensure_replay_matches(raced, submission, submitted_ids)
        return _request_view(raced, outcome="replayed", settings=settings)
    return _request_view(row, outcome="created", settings=settings)


def _ensure_replay_matches(
    existing,
    submission: ConnectorSourceIngestionSubmission,
    submitted_ids: list[str],
) -> None:
    """Replay only when the stored request is exactly the same ask.

    Identity means stage, connector, governance reason, and the ordered
    binding list.
    Fingerprints stay whatever the stored row pinned — a replay never refreshes
    evidence. Anything else is a different request wearing a used ID.
    """

    if (
        existing.stage != submission.stage
        or existing.connector_id != submission.connector_id
        or existing.reason != submission.reason
        or [selection["binding_id"] for selection in existing.selections] != submitted_ids
    ):
        raise ConnectorSourceIngestionError(
            "That request ID already names a different ingestion request.",
            "request_id_conflict",
        )


def get_connector_source_ingestion_request_view(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    request_id: str,
    settings: Settings | None = None,
) -> SourceIngestionRequestView | None:
    row = repository.get_connector_source_ingestion_request(tenant_id, request_id)
    if row is None:
        return None
    return _request_view(row, outcome="created", settings=settings)


class SourceExtractionBatchView(BaseModel):
    """Metadata-only operator view of one extraction batch.

    Carries counts, digests and storage references — never row values. The
    watermark is disclosed as presence only; its value can name source key
    columns and stays out of operator surfaces.
    """

    batch_key: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    resource_name: str = Field(min_length=1)
    pinned_schema_fingerprint: str = Field(min_length=64, max_length=64)
    observed_schema_fingerprint: str = Field(min_length=64, max_length=64)
    ordering_mode: str = Field(pattern="^(primary_key|none)$")
    has_watermark: bool
    row_count: int = Field(ge=0)
    byte_size: int = Field(ge=0)
    truncated: bool
    limit_reason: str | None = None
    duration_ms: int = Field(ge=0)
    digest_sha256: str = Field(min_length=64, max_length=64)
    storage_uri: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    stored_size_bytes: int = Field(ge=0)
    classification: str = Field(min_length=1, max_length=40)
    executed_by: str = Field(min_length=1)
    created_at: datetime


class SourceExtractionBatchesPage(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    total_count: int = Field(ge=0)
    next_cursor: str | None = None
    batches: list[SourceExtractionBatchView] = Field(default_factory=list)


def list_connector_source_extraction_batches_page(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    request_id: str,
    limit: int,
    cursor_key: str | None = None,
    binding_id: str | None = None,
    truncated: bool | None = None,
) -> SourceExtractionBatchesPage:
    """Stable, bounded, filterable metadata page for one ingestion request."""
    request_row = repository.get_connector_source_ingestion_request(
        tenant_id, request_id
    )
    if request_row is None:
        return None
    rows = repository.get_connector_source_ingestion_request_batches(
        tenant_id,
        request_id,
        limit=limit + 1,
        cursor_key=cursor_key,
        binding_id=binding_id,
        truncated=truncated,
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1].batch_key
    return SourceExtractionBatchesPage(
        tenant_id=tenant_id,
        connector_id=request_row.connector_id,
        request_id=request_id,
        total_count=repository.count_connector_source_ingestion_request_batches(
            tenant_id,
            request_id,
            binding_id=binding_id,
            truncated=truncated,
        ),
        next_cursor=next_cursor,
        batches=[
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
            for row in rows
        ],
    )


REQUEUED_EVENT = "connector.source.ingestion.requeued"


def requeue_connector_source_ingestion_request(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    request_id: str,
    requeued_by: str,
    reason: str,
    idempotency_key: str,
    principal_scopes: list[str] | None = None,
    now: datetime | None = None,
) -> tuple[SourceIngestionRequestView | None, str]:
    """Re-dispatch one dead-lettered governed ingestion request (write scope).

    Fenced transition plus exactly one public-safe audit event in the same
    transaction; identical asks replay without new writes. Pinned selections
    and stage are immutable — the next dispatch pass revalidates current
    fingerprints, so remediation (fresh discovery/activation) is still what
    makes an extraction succeed again.
    """
    if SOURCE_INGESTION_SCOPE not in (principal_scopes or []):
        raise SourceIngestionScopeDenied()
    now = now or datetime.now(UTC)
    outcome = repository.requeue_connector_source_ingestion_request(
        tenant_id=tenant_id,
        request_id=request_id,
        requeued_by=requeued_by,
        requeue_reason=reason,
        idempotency_key=idempotency_key,
        now=now,
    )
    row = repository.get_connector_source_ingestion_request(tenant_id, request_id)
    if outcome == "requeued":
        audit_event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=tenant_id,
                actor_id=requeued_by,
                event_type=REQUEUED_EVENT,
                payload={
                    "request_id": request_id,
                    "requeue_reason": reason[:200],
                    "idempotency_key": idempotency_key[:180],
                },
            )
        )
        repository.mark_connector_source_ingestion_request_audit(
            tenant_id=tenant_id,
            request_id=request_id,
            audit_event_id=audit_event.id,
            audit_event_type=REQUEUED_EVENT,
        )
        return _request_view(row, outcome="created"), "requeued"
    return (
        _request_view(row, outcome="created") if row is not None else None,
        outcome,
    )


CANCELLED_EVENT = "connector.source.ingestion.cancelled"


def cancel_connector_source_ingestion_request(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    request_id: str,
    cancelled_by: str,
    cancel_reason: str | None = None,
    principal_scopes: list[str] | None = None,
    now: datetime | None = None,
) -> tuple[SourceIngestionRequestView | None, str]:
    """Cancel a pending governed ingestion request (write-scope protected).

    Outcomes: ``cancelled`` (fenced transition + one audit event), ``replayed``
    (identical repeat: no new writes), ``conflict`` (already dispatched or
    terminal), or ``not_found``. The audit event is written only on the real
    transition, in the same transaction as the state change.
    """
    if SOURCE_INGESTION_SCOPE not in (principal_scopes or []):
        raise SourceIngestionScopeDenied()
    now = now or datetime.now(UTC)
    outcome = repository.cancel_connector_source_ingestion_request(
        tenant_id=tenant_id,
        request_id=request_id,
        cancelled_by=cancelled_by,
        cancel_reason=cancel_reason,
        now=now,
    )
    row = repository.get_connector_source_ingestion_request(tenant_id, request_id)
    if outcome == "cancelled":
        audit_event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=tenant_id,
                actor_id=cancelled_by,
                event_type=CANCELLED_EVENT,
                payload={
                    "request_id": request_id,
                    "cancel_reason": (cancel_reason or "")[:200],
                },
            )
        )
        repository.mark_connector_source_ingestion_request_audit(
            tenant_id=tenant_id,
            request_id=request_id,
            audit_event_id=audit_event.id,
            audit_event_type=CANCELLED_EVENT,
        )
        return _request_view(row, outcome="created"), "cancelled"
    return (
        _request_view(row, outcome="created") if row is not None else None,
        outcome,
    )


def list_connector_source_ingestion_request_views(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    connector_id: str,
    limit: int = 50,
    settings: Settings | None = None,
) -> list[SourceIngestionRequestView]:
    rows = repository.list_connector_source_ingestion_requests(
        tenant_id,
        connector_id,
        limit=limit,
    )
    return [
        _request_view(row, outcome="created", settings=settings) for row in rows
    ]


class SourceIngestionOverviewSummary(BaseModel):
    """Cross-request status aggregates for one connector, honestly counted."""

    status_counts: dict[str, int]
    total_count: int = Field(ge=0)
    dead_lettered_count: int = Field(ge=0)
    extract_stage_count: int = Field(ge=0)
    last_activity_at: datetime | None = None


class ConnectorSourceIngestionOverview(BaseModel):
    """The daily operator landing read model for governed ingestion.

    Aggregates plus a bounded newest-first page of requests. Metadata only —
    every entry reuses the same public-safe view contract as single-request
    reads.
    """

    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    summary: SourceIngestionOverviewSummary
    requests: list[SourceIngestionRequestView] = Field(default_factory=list)
    next_cursor: str | None = Field(
        default=None,
        description="Opaque keyset cursor over (created_at, request_id).",
    )


def build_connector_source_ingestion_overview(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    connector_id: str,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_request_id: str | None = None,
    settings: Settings | None = None,
) -> ConnectorSourceIngestionOverview:
    """Aggregates plus one keyset page of recent requests for a connector."""
    summary = repository.summarize_connector_source_ingestion_requests(
        tenant_id,
        connector_id,
    )
    rows = repository.list_connector_source_ingestion_requests_page(
        tenant_id,
        connector_id,
        limit=limit + 1,
        cursor_created_at=cursor_created_at,
        cursor_request_id=cursor_request_id,
    )
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = f"{last.created_at.isoformat()}|{last.request_id}"
    return ConnectorSourceIngestionOverview(
        tenant_id=tenant_id,
        connector_id=connector_id,
        summary=SourceIngestionOverviewSummary(**summary),
        requests=[
            _request_view(row, outcome="created", settings=settings) for row in rows
        ],
        next_cursor=next_cursor,
    )


@dataclass(frozen=True)
class _ClaimedIngestionRequest:
    id: UUID
    tenant_id: str
    connector_id: str
    request_id: str
    requested_by: str
    stage: str
    selections: list[dict]
    attempt_count: int
    claim_token: UUID


class SourceIngestionRunResult(BaseModel):
    claimed: int = Field(ge=0)
    completed: int = Field(ge=0)
    retried: int = Field(ge=0)
    dead_lettered: int = Field(ge=0)
    fenced: int = Field(ge=0)


class SourceIngestionValidationOutcome(BaseModel):
    """One selection's supported-stage result, true to what actually ran."""

    ok: bool
    reason: str | None = None
    source_dial_performed: bool = False
    extraction_performed: bool = False


class SourceIngestionRuntimePort(Protocol):
    """The seam a real extraction runtime will implement later.

    Implementations must stay truthful: until a runtime actually dials a source
    and reads rows, ``source_dial_performed`` and ``extraction_performed``
    remain false and the evidence must say so.
    """

    def validate_selection(
        self,
        *,
        repository: AxisPersistenceRepository,
        tenant_id: str,
        connector_id: str,
        binding_id: str,
        resource_name: str,
        schema_fingerprint: str,
    ) -> SourceIngestionValidationOutcome: ...


class ObservationFreshnessIngestionRuntime:
    """Deterministic validation stage over Axis' own observed evidence.

    Compares each pinned fingerprint with the CURRENT observation record. The
    source database is never contacted and no row data is touched — the check
    runs entirely against evidence discovery already brought into Axis.
    """

    def validate_selection(
        self,
        *,
        repository: AxisPersistenceRepository,
        tenant_id: str,
        connector_id: str,
        binding_id: str,
        resource_name: str,
        schema_fingerprint: str,
    ) -> SourceIngestionValidationOutcome:
        observation = repository.get_data_resource_observation(
            tenant_id,
            connector_id,
            resource_name,
        )
        if observation is None:
            return SourceIngestionValidationOutcome(ok=False, reason="observation_missing")
        if (observation.schema_fingerprint or "") != schema_fingerprint:
            return SourceIngestionValidationOutcome(ok=False, reason="stale_fingerprint")
        binding = repository.get_connector_source_binding(tenant_id, binding_id)
        if binding is None or binding.status != BINDING_ACTIVE_STATUS:
            return SourceIngestionValidationOutcome(ok=False, reason="binding_inactive")
        return SourceIngestionValidationOutcome(ok=True)


class SourceIngestionOutboxDispatcher:
    """Claim due ingestion requests and drive them through the runtime port.

    Mirrors the approval-decision outbox machinery: lease-fenced claims,
    permanent-validation failures dead-letter immediately, unexpected
    operational failures retry with jittered exponential backoff, and every
    terminal transition writes append-only audit evidence under a dedicated
    outbox actor.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        runtime: SourceIngestionRuntimePort,
        extraction_runtime: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        random_uniform: Callable[[float, float], float] | None = None,
    ) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self._runtime = runtime
        self._extraction_runtime = extraction_runtime
        self._clock = clock or (lambda: datetime.now(UTC))
        self._random_uniform = random_uniform or random.uniform

    async def run_once(self) -> SourceIngestionRunResult:
        claimed = await asyncio.to_thread(self._claim)
        if not claimed:
            return SourceIngestionRunResult(
                claimed=0, completed=0, retried=0, dead_lettered=0, fenced=0
            )
        counts = {
            "completed": 0,
            "retried": 0,
            "dead_lettered": 0,
            "fenced": 0,
        }
        for row in claimed:
            outcome = await asyncio.to_thread(self._process, row)
            counts[outcome.status] += 1
        return SourceIngestionRunResult(claimed=len(claimed), **counts)

    def _claim(self) -> list[_ClaimedIngestionRequest]:
        now = self._clock()
        lease_expires_at = now + timedelta(
            seconds=self.settings.source_ingestion_claim_timeout_seconds
        )
        with session_scope(self._session_factory) as session:
            rows = AxisPersistenceRepository(session).claim_connector_source_ingestion_requests(
                now=now,
                lease_expires_at=lease_expires_at,
                limit=self.settings.source_ingestion_batch_size,
            )
            return [
                _ClaimedIngestionRequest(
                    id=row.id,
                    tenant_id=row.tenant_id,
                    connector_id=row.connector_id,
                    request_id=row.request_id,
                    requested_by=row.requested_by,
                    stage=getattr(row, "stage", VALIDATE_STAGE),
                    selections=[dict(selection) for selection in row.selections],
                    attempt_count=row.attempt_count,
                    claim_token=row.claim_token,
                )
                for row in rows
                if row.claim_token is not None
            ]

    def _process(self, row: _ClaimedIngestionRequest) -> _ProcessOutcome:
        selection_evidence: list[dict] = []
        failed_permanently = False
        try:
            with session_scope(self._session_factory) as session:
                repository = AxisPersistenceRepository(session)
                for selection in row.selections:
                    outcome = self._runtime.validate_selection(
                        repository=repository,
                        tenant_id=row.tenant_id,
                        connector_id=row.connector_id,
                        binding_id=str(selection["binding_id"]),
                        resource_name=str(selection["resource_name"]),
                        schema_fingerprint=str(selection["schema_fingerprint"]),
                    )
                    entry: dict = {
                        "binding_id": selection["binding_id"],
                        "resource_name": selection["resource_name"],
                        "outcome": "validated" if outcome.ok else "failed",
                        "source_dial_performed": outcome.source_dial_performed,
                        "extraction_performed": outcome.extraction_performed,
                    }
                    if outcome.reason is not None:
                        entry["reason"] = outcome.reason
                    selection_evidence.append(entry)
                    if not outcome.ok:
                        failed_permanently = True
        except Exception as exc:
            return self._finalize_failure(row, self._safe_error_code(exc), permanent=False)
        evidence = {
            "stage": (
                "validate+extract" if row.stage == EXTRACTION_STAGE else "validation"
            ),
            "limits_applied": planned_extraction_limits(self.settings) or {},
            "validated_count": sum(
                1 for entry in selection_evidence if entry["outcome"] == "validated"
            ),
            "failed_count": sum(
                1 for entry in selection_evidence if entry["outcome"] == "failed"
            ),
            "source_dial_performed": False,
            "extraction_performed": False,
            "selections": selection_evidence,
        }
        if failed_permanently:
            reasons = sorted(
                {
                    entry["reason"]
                    for entry in selection_evidence
                    if entry.get("reason") is not None
                }
            )
            return self._finalize_failure(
                row,
                "+".join(reasons)[:80] if reasons else "validation_failed",
                permanent=True,
                evidence=evidence,
            )
        if row.stage == EXTRACTION_STAGE:
            if (
                not self.settings.source_ingestion_extraction_enabled
                or self._extraction_runtime is None
            ):
                return self._finalize_failure(
                    row,
                    "extraction_disabled",
                    permanent=True,
                    evidence=evidence,
                )
            return self._extract_selections(row, evidence)
        return self._finalize_success(row, evidence)

    def _extract_selections(self, row: _ClaimedIngestionRequest, evidence: dict) -> _ProcessOutcome:
        """Real bounded extraction per validated selection, then completion.

        Batch metadata rows, their audit events, and the terminal request
        transition share one transaction; payloads live only in the object
        store. Any extraction failure dead-letters the whole request with a
        public-safe reason — a partial read never looks complete.

        Store/DB boundary honesty: ``put_json`` precedes the metadata insert
        and the two stores cannot commit atomically. Batch keys are fully
        deterministic (``request_id:binding_id:index``), so a retry overwrites
        the same object instead of duplicating it. If the request still ends
        dead-lettered after its attempts, an object may exist without a DB row;
        operators reconcile by listing the tenant-scoped key prefix against
        recorded batches — documented behaviour, not silent atomicity.
        """
        batches_summary: list[dict] = []
        try:
            with session_scope(self._session_factory) as session:
                repository = AxisPersistenceRepository(session)
                for selection in row.selections:
                    # Generation-scoped key: operational retries (no committed
                    # predecessor for this selection) keep one stable key; an
                    # explicit RE-DISPATCH after remediation starts a new
                    # generation so genuinely new bytes never collide with
                    # immutable recorded history.
                    binding_id = str(selection["binding_id"])
                    generation = (
                        repository.count_connector_source_extraction_batches_for_binding(
                            row.tenant_id,
                            row.request_id,
                            binding_id,
                        )
                    )
                    batch_key = f"{row.request_id}:{binding_id}:{generation}"
                    outcome = self._extraction_runtime.extract_selection(
                        repository=repository,
                        tenant_id=row.tenant_id,
                        connector_id=row.connector_id,
                        request_id=row.request_id,
                        batch_key=batch_key,
                        binding_id=str(selection["binding_id"]),
                        resource_name=str(selection["resource_name"]),
                        pinned_schema_fingerprint=str(selection["schema_fingerprint"]),
                        executed_by=EXTRACTION_ACTOR,
                    )
                    if not outcome.ok or outcome.stored is None:
                        reason = (outcome.reason or "extraction_failed")[:80]
                        failure_evidence = {
                            **evidence,
                            "source_dial_performed": True,
                            "extraction_performed": True,
                            "batches": batches_summary,
                            "failed_stage": EXTRACTION_STAGE,
                        }
                        return self._finalize_failure(
                            row, reason, permanent=True, evidence=failure_evidence
                        )
                    existing = repository.get_connector_source_extraction_batch_by_key(
                        row.tenant_id, batch_key
                    )
                    if existing is not None:
                        # Idempotent replay of a prior attempt's successful
                        # batch: reuse ONLY when digest and storage reference
                        # are consistent; anything else is an anomaly that
                        # must stop the request, never be overwritten quietly.
                        consistent = (
                            existing.digest_sha256 == outcome.digest_sha256
                            and existing.storage_key == outcome.stored["storage_key"]
                        )
                        if not consistent:
                            return self._finalize_failure(
                                row,
                                "batch_key_conflict",
                                permanent=True,
                                evidence={
                                    **evidence,
                                    "source_dial_performed": True,
                                    "extraction_performed": True,
                                    "failed_stage": EXTRACTION_STAGE,
                                    "batches": batches_summary,
                                },
                            )
                        batches_summary.append(
                            {
                                "batch_key": batch_key,
                                "binding_id": selection["binding_id"],
                                "resource_name": selection["resource_name"],
                                "row_count": existing.row_count,
                                "truncated": existing.truncated,
                                "digest_sha256": existing.digest_sha256,
                                "storage_uri": existing.storage_uri,
                            }
                        )
                        continue

                    batch_event = repository.append_audit_event(
                        AuditEventCreate(
                            tenant_id=row.tenant_id,
                            actor_id=EXTRACTION_ACTOR,
                            event_type="connector.source.extraction.batch_recorded",
                            payload={
                                "request_id": row.request_id,
                                "connector_id": row.connector_id,
                                "binding_id": selection["binding_id"],
                                "resource_name": selection["resource_name"],
                                "batch_key": batch_key,
                                "ordering_mode": outcome.ordering_mode,
                                "row_count": str(outcome.row_count),
                                "truncated": "true" if outcome.truncated else "false",
                                "limit_reason": outcome.limit_reason or "",
                                "digest_sha256": outcome.digest_sha256,
                                "storage_uri": outcome.stored["storage_uri"],
                            },
                        )
                    )
                    repository.create_connector_source_extraction_batch(
                        ConnectorSourceExtractionBatchCreate(
                            tenant_id=row.tenant_id,
                            connector_id=row.connector_id,
                            request_id=row.request_id,
                            batch_key=batch_key,
                            binding_id=str(selection["binding_id"]),
                            resource_name=str(selection["resource_name"]),
                            pinned_schema_fingerprint=str(selection["schema_fingerprint"]),
                            observed_schema_fingerprint=(
                                outcome.observed_schema_fingerprint or ""
                            ),
                            ordering_mode=outcome.ordering_mode or "none",
                            cursor_watermark=outcome.cursor_watermark,
                            row_count=outcome.row_count,
                            byte_size=outcome.byte_size,
                            truncated=outcome.truncated,
                            limit_reason=outcome.limit_reason,
                            duration_ms=outcome.duration_ms,
                            limits_applied=dict(evidence.get("limits_applied", {})),
                            provenance={
                                "stage": EXTRACTION_STAGE,
                                "requested_by": row.requested_by,
                                "attempt_count": row.attempt_count,
                            },
                            digest_sha256=outcome.digest_sha256 or "",
                            storage_adapter=outcome.stored["storage_adapter"],
                            storage_key=outcome.stored["storage_key"],
                            storage_uri=outcome.stored["storage_uri"],
                            content_type=outcome.stored["content_type"],
                            stored_size_bytes=outcome.stored["stored_size_bytes"],
                            classification=outcome.stored["classification"],
                            executed_by=outcome.stored["executed_by"],
                            audit_event_id=batch_event.id,
                            audit_event_type="connector.source.extraction.batch_recorded",
                        )
                    )
                    batches_summary.append(
                        {
                            "batch_key": batch_key,
                            "binding_id": selection["binding_id"],
                            "resource_name": selection["resource_name"],
                            "row_count": outcome.row_count,
                            "truncated": outcome.truncated,
                            "digest_sha256": outcome.digest_sha256,
                            "storage_uri": outcome.stored["storage_uri"],
                        }
                    )
        except Exception as exc:
            return self._finalize_failure(row, self._safe_error_code(exc), permanent=False)
        completed_evidence = {
            **evidence,
            "source_dial_performed": True,
            "extraction_performed": True,
            "batches": batches_summary,
        }
        return self._finalize_success(row, completed_evidence)

    def _finalize_success(self, row: _ClaimedIngestionRequest, evidence: dict) -> _ProcessOutcome:
        now = self._clock()
        with session_scope(self._session_factory) as session:
            repository = AxisPersistenceRepository(session)
            # The attempt timeline is durable history appended in the SAME
            # transaction as the terminal/retry transition: a fenced loser
            # (claim token lost) writes neither state nor timeline entry.
            evidence = {
                **evidence,
                "attempts": [
                    *repository.get_connector_source_ingestion_request_attempts(
                        row.id
                    ),
                    _attempt_timeline_entry(
                        attempt_number=row.attempt_count,
                        outcome="completed",
                        selections_evidence=list(
                            evidence.get("selections", [])
                        ),
                        finished_at=now,
                    ),
                ],
            }
            changed = repository.complete_connector_source_ingestion_request(
                row.id,
                row.claim_token,
                completed_at=now,
                evidence=evidence,
            )
            if changed:
                repository.append_audit_event(
                    AuditEventCreate(
                        tenant_id=row.tenant_id,
                        actor_id=INGESTION_ACTOR,
                        event_type=INGESTION_COMPLETED_EVENT,
                        payload={
                            "request_id": row.request_id,
                            "connector_id": row.connector_id,
                            "attempt_count": row.attempt_count,
                            "validated_count": str(evidence["validated_count"]),
                            "source_dial_performed": "false",
                            "extraction_performed": "false",
                        },
                    )
                )
        return _ProcessOutcome(status="completed" if changed else "fenced")

    def _finalize_failure(
        self,
        row: _ClaimedIngestionRequest,
        error_code: str,
        *,
        permanent: bool,
        evidence: dict | None = None,
    ) -> _ProcessOutcome:
        now = self._clock()
        exhausted = (
            row.attempt_count >= self.settings.source_ingestion_max_attempts
        )
        dead_letter = permanent or exhausted
        available_at = (
            now if dead_letter else now + self._retry_delay(row.attempt_count)
        )
        with session_scope(self._session_factory) as session:
            repository = AxisPersistenceRepository(session)
            if evidence is None:
                evidence = {}
            # Durable, append-only attempt history — same transaction as the
            # fenced transition, so a fenced loser records nothing.
            evidence = {
                **evidence,
                "attempts": [
                    *repository.get_connector_source_ingestion_request_attempts(
                        row.id
                    ),
                    _attempt_timeline_entry(
                        attempt_number=row.attempt_count,
                        outcome="dead_lettered" if dead_letter else "retried",
                        selections_evidence=list(
                            evidence.get("selections", [])
                        ),
                        finished_at=now,
                        error_code=error_code,
                    ),
                ],
            }
            changed = repository.retry_connector_source_ingestion_request(
                row.id,
                row.claim_token,
                available_at=available_at,
                updated_at=now,
                error=error_code,
                dead_letter=dead_letter,
                evidence=evidence,
            )
            if changed and dead_letter:
                repository.append_audit_event(
                    AuditEventCreate(
                        tenant_id=row.tenant_id,
                        actor_id=INGESTION_ACTOR,
                        event_type=INGESTION_FAILED_EVENT,
                        payload={
                            "request_id": row.request_id,
                            "connector_id": row.connector_id,
                            "attempt_count": row.attempt_count,
                            "error_code": error_code,
                            "permanent": "true" if permanent else "false",
                        },
                    )
                )
        if not changed:
            return _ProcessOutcome(status="fenced")
        return _ProcessOutcome(status="dead_lettered" if dead_letter else "retried")

    @staticmethod
    def _safe_error_code(exc: Exception) -> str:
        """Public-safe error code; never leaks messages, SQL, or DSNs."""

        value = exc.__class__.__name__
        sanitized = "".join(
            character for character in value if character.isalnum() or character in "._-"
        )
        return sanitized[:80] or "ingestion_error"

    def _retry_delay(self, attempt_count: int) -> timedelta:
        maximum = min(
            self.settings.source_ingestion_retry_max_seconds,
            self.settings.source_ingestion_retry_base_seconds
            * (2 ** max(0, attempt_count - 1)),
        )
        return timedelta(seconds=self._random_uniform(0.0, maximum))


@dataclass(frozen=True)
class _ProcessOutcome:
    status: str
