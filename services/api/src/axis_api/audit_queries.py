import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from axis_api.audit import AuditEventCreate
from axis_api.audit_signing import (
    AuditLedgerSignatureProof,
    AuditLedgerSigner,
    canonical_ledger_signature_payload,
    unsigned_audit_ledger_signature,
)
from axis_api.demo import (
    AuditFilterOptions,
    AuditLedgerEvent,
    ManufacturingAuditExplorer,
    OverviewMetric,
    OverviewStatus,
)
from axis_api.manufacturing_metadata import (
    get_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.models import AuditEvent, AuditLegalHold
from axis_api.object_storage import (
    COMPLIANCE_RETENTION_MODE,
    ObjectLockCapability,
)
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    AuditLegalHoldCreate,
    AuditLegalHoldRelease,
    AxisPersistenceRepository,
)

RETENTION_DELETION_REQUIRED_SCOPE = "audit:retention:delete"
RETENTION_DELETION_EVENT_TYPE = "audit.retention_deletion.executed"
LEGAL_HOLD_REQUIRED_SCOPE = "audit:legal_hold:write"
LEGAL_HOLD_ACTIVATED_EVENT_TYPE = "audit.legal_hold.activated"
LEGAL_HOLD_RELEASED_EVENT_TYPE = "audit.legal_hold.released"
OBJECT_LEGAL_HOLD_APPLIED_EVENT_TYPE = "audit.object_legal_hold.applied"
OBJECT_LEGAL_HOLD_RELEASED_EVENT_TYPE = "audit.object_legal_hold.released"


class AuditExportWormEnforcementError(RuntimeError):
    """Raised when a COMPLIANCE audit export cannot be WORM-enforced.

    Fail-closed: the backing object store cannot enforce object-lock (e.g. the
    bucket was not created with object-lock enabled, or the store is a local
    filesystem), so a COMPLIANCE-configured export must refuse rather than
    emit a bundle that falsely claims WORM protection.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AuditEventQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    event_type: str | None = Field(default=None, min_length=1)
    actor_id: str | None = Field(default=None, min_length=1)
    scope: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class AuditExportQuery(AuditEventQuery):
    export_reason: str = Field(default="governance-review", min_length=1, max_length=120)
    retention_days: int = Field(default=365, ge=30, le=3650)
    legal_hold: bool = False
    format: str = Field(default="json", pattern="^json$")


class AuditRetentionPolicy(BaseModel):
    policy_id: str = Field(min_length=1)
    retention_days: int = Field(ge=1)
    retention_basis: str = Field(min_length=1)
    disposal_action: str = Field(min_length=1)
    legal_hold: bool
    export_requires_review: bool
    notes: list[str] = Field(default_factory=list)


class AuditIntegrityProof(BaseModel):
    algorithm: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    chain_tip_sha256: str = Field(min_length=64, max_length=64)
    event_hashes: list[str] = Field(default_factory=list)


class AuditExportManifest(BaseModel):
    export_id: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    format: str = Field(min_length=1)
    redaction_policy: str = Field(min_length=1)
    retention_policy_id: str = Field(min_length=1)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    integrity_chain_tip_sha256: str = Field(min_length=64, max_length=64)
    retention_enforced: bool
    retention_window_start: str = Field(min_length=1)
    excluded_record_count: int = Field(ge=0)
    # WORM fields describe the object-lock posture of the export.
    # ``worm_status`` disambiguates the guarantee:
    #   - "none": no object-lock capability (GOVERNANCE / local / unverified).
    #   - "capability_attested": the backing store's object-lock capability is
    #     verified, but THIS bundle is returned in the HTTP response and is NOT
    #     itself written under object-lock. Immutability of this response
    #     payload rests on the hash-chain integrity proof + ledger signature.
    #   - "object_locked": the bundle was written to the object store under an
    #     S3 Retention (RetainUntilDate) — produced by the connector-evidence
    #     materialization path, not by the export-response endpoint.
    worm_status: str = Field(default="none", min_length=1)
    worm_retention_mode: str = Field(default="none", min_length=1)
    worm_retention_enforced: bool = False
    worm_retain_until: str | None = None


class AuditExportBundle(BaseModel):
    tenant_id: str = Field(min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    format: str = Field(min_length=1)
    export_reason: str = Field(min_length=1)
    filters: AuditEventQuery
    retention_policy: AuditRetentionPolicy
    manifest: AuditExportManifest
    integrity_proof: AuditIntegrityProof
    ledger_signature: AuditLedgerSignatureProof
    events: list[AuditLedgerEvent] = Field(default_factory=list)
    retention_notes: list[str] = Field(default_factory=list)


class AuditLegalHoldCreateRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    hold_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=600)
    event_type: str | None = Field(default=None, min_length=1, max_length=120)
    actor_filter: str | None = Field(default=None, min_length=1, max_length=160)
    approved_by: str = Field(min_length=1, max_length=160)
    notes: list[str] = Field(default_factory=list)


class AuditLegalHoldReleaseRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    hold_id: str = Field(min_length=1, max_length=180)
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    release_reason: str = Field(min_length=1, max_length=600)


class AuditLegalHoldRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    hold_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    event_type: str | None = None
    actor_filter: str | None = None
    requested_by: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    released_by: str | None = None
    release_reason: str | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None
    release_audit_event_id: UUID | None = None
    release_audit_event_type: str | None = None
    permission_decision: PermissionDecision | None = None
    notes: list[str] = Field(default_factory=list)
    created_at: datetime
    released_at: datetime | None = None


class AuditObjectLegalHoldRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    storage_key: str = Field(min_length=1, max_length=1024)
    reason: str = Field(min_length=1, max_length=600)
    hold_id: str | None = Field(
        default=None, min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$"
    )


class AuditObjectLegalHoldRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    storage_adapter: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    hold_id: str | None = None
    actor_id: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    permission_decision: PermissionDecision | None = None


class AuditRetentionDeletionRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    actor_id: str = Field(min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)
    retention_days: int = Field(default=365, ge=30, le=3650)
    legal_hold: bool = False
    dry_run: bool = True
    event_type: str | None = Field(default=None, min_length=1)
    actor_filter: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=1000)
    reason: str = Field(default="retention-deletion", min_length=1, max_length=160)


class AuditRetentionDeletionResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    retention_days: int = Field(ge=1)
    cutoff: str = Field(min_length=1)
    dry_run: bool
    legal_hold: bool
    status: str = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    deleted_count: int = Field(ge=0)
    retained_count: int = Field(ge=0)
    deleted_event_hashes: list[str] = Field(default_factory=list)
    permission_decision: PermissionDecision
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None
    notes: list[str] = Field(default_factory=list)


class AuditRetentionDeletionPermissionDenied(PermissionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class AuditLegalHoldPermissionDenied(PermissionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class AuditLegalHoldNotFound(LookupError):
    pass


class AuditLegalHoldConflict(ValueError):
    def __init__(self, hold_id: str, reason: str) -> None:
        super().__init__(reason)
        self.hold_id = hold_id
        self.reason = reason


def _string_value(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return ",".join(_string_value(item) for item in value[:4])
    if isinstance(value, dict):
        return ",".join(sorted(value.keys())[:4]) or "object"
    return str(value)


def _first_payload_value(payload: dict, keys: list[str], default: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return _string_value(value)
    return default


def _actor_type(actor_id: str) -> str:
    if actor_id.startswith("agent_") or actor_id.endswith("-agent"):
        return "agent"
    if "role" in actor_id:
        return "role"
    return "service"


def _category(event_type: str, payload: dict) -> str:
    category = payload.get("category")
    if isinstance(category, str) and category:
        return category
    return event_type.split(".", maxsplit=1)[0]


def _scope(event: AuditEvent) -> str:
    return _first_payload_value(
        event.payload,
        ["scope", "workflow_id", "approval_id", "action_id", "idempotency_key"],
        event.event_type,
    )


def _result(payload: dict) -> str:
    return _first_payload_value(
        payload,
        ["status", "decision", "result", "workflow_signal_status"],
        "recorded",
    )


def _severity(payload: dict, result: str) -> OverviewStatus:
    if payload.get("approval_required") is True:
        return OverviewStatus.ACTION_REQUIRED
    if result in {
        "approval_required",
        "pending",
        "runtime_signal_unavailable",
        "waiting_for_approval",
    }:
        return OverviewStatus.ACTION_REQUIRED
    if "unavailable" in result or "failed" in result or "request_changes" in result:
        return OverviewStatus.WATCH
    return OverviewStatus.READY


def _summary(event: AuditEvent, scope: str, result: str) -> str:
    return f"Persisted {event.event_type} for {scope} with result {result}."


def _evidence_refs(payload: dict, fallback: str) -> list[str]:
    refs = []
    for key in [
        "workflow_id",
        "approval_id",
        "action_id",
        "action_run_id",
        "idempotency_key",
        "required_permission",
    ]:
        value = payload.get(key)
        if value:
            refs.append(_string_value(value))
    return refs or [fallback]


def _payload_preview(payload: dict) -> dict[str, str]:
    preview_keys = [
        "action_id",
        "approval_id",
        "workflow_id",
        "decision",
        "status",
        "execution_mode",
        "idempotency_key",
        "snapshot_id",
        "connector_id",
        "policy_id",
        "workflow_signal_status",
        "permission_decision",
        "payload_field_names",
    ]
    preview = {
        key: _string_value(payload[key])
        for key in preview_keys
        if key in payload and payload[key] is not None
    }
    if not preview:
        preview = {"payload_keys": ",".join(sorted(payload.keys())[:6]) or "none"}
    return preview


def _audit_event_to_ledger_event(event: AuditEvent) -> AuditLedgerEvent:
    scope = _scope(event)
    result = _result(event.payload)
    occurred_at = event.created_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return AuditLedgerEvent(
        audit_event_id=str(event.id),
        occurred_at=occurred_at.astimezone(UTC).isoformat(),
        tenant_id=event.tenant_id,
        actor_id=event.actor_id,
        actor_type=_actor_type(event.actor_id),
        event_type=event.event_type,
        category=_category(event.event_type, event.payload),
        domain=_first_payload_value(event.payload, ["domain", "risk_level"], "Operations"),
        scope=scope,
        result=result,
        severity=_severity(event.payload, result),
        source=_first_payload_value(event.payload, ["source"], "Axis API"),
        summary=_summary(event, scope, result),
        permission_scope=_first_payload_value(
            event.payload,
            ["required_permission", "permission_scope"],
            "audit:read",
        ),
        data_classification="public-demo",
        related_workflow_id=event.payload.get("workflow_id"),
        related_approval_id=event.payload.get("approval_id"),
        related_agent_id=event.payload.get("agent_id"),
        evidence_refs=_evidence_refs(event.payload, event.event_type),
        payload_preview=_payload_preview(event.payload),
    )


def _filter_options(events: list[AuditLedgerEvent], tenant_id: str) -> AuditFilterOptions:
    return AuditFilterOptions(
        tenants=sorted({event.tenant_id for event in events}) or [tenant_id],
        event_types=sorted({event.event_type for event in events}),
        scopes=sorted({event.scope for event in events}),
        actors=sorted({event.actor_id for event in events}),
        categories=sorted({event.category for event in events}),
    )


def _metrics(events: list[AuditLedgerEvent]) -> list[OverviewMetric]:
    action_required_count = sum(
        event.severity == OverviewStatus.ACTION_REQUIRED for event in events
    )
    return [
        OverviewMetric(
            label="Persisted Events",
            value=str(len(events)),
            detail="Append-only audit events read from Postgres",
            status=OverviewStatus.READY if events else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Action Required",
            value=str(action_required_count),
            detail="Persisted events currently marked as requiring attention",
            status=(
                OverviewStatus.ACTION_REQUIRED
                if action_required_count
                else OverviewStatus.READY
            ),
        ),
        OverviewMetric(
            label="Query Source",
            value="Postgres",
            detail="Tenant-scoped query over audit_events",
            status=OverviewStatus.READY,
        ),
        OverviewMetric(
            label="Replay",
            value="Preview",
            detail="Redacted audit events can feed replay preview artifacts",
            status=OverviewStatus.WATCH,
        ),
    ]


def _query_filters(query: AuditEventQuery) -> AuditEventQuery:
    return AuditEventQuery(
        tenant_id=query.tenant_id,
        event_type=query.event_type,
        actor_id=query.actor_id,
        scope=query.scope,
        limit=query.limit,
    )


def query_persisted_audit_events(
    repository: AxisPersistenceRepository,
    query: AuditEventQuery,
) -> ManufacturingAuditExplorer:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_audit_events(
        tenant_id=query.tenant_id,
        event_type=query.event_type,
        actor_id=query.actor_id,
        limit=query.limit,
    )
    events = [_audit_event_to_ledger_event(record) for record in records]
    if query.scope is not None:
        events = [event for event in events if event.scope == query.scope]
    has_persisted_records = bool(records)
    if not has_persisted_records and any(
        value is not None for value in (query.event_type, query.actor_id, query.scope)
    ):
        has_persisted_records = bool(
            repository.list_audit_events(tenant_id=query.tenant_id, limit=1)
        )

    return ManufacturingAuditExplorer(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(has_persisted_records),
        as_of=events[0].occurred_at if events else tenant_metadata.as_of,
        ledger_status=OverviewStatus.READY if events else OverviewStatus.WATCH,
        metrics=_metrics(events),
        filter_options=_filter_options(events, query.tenant_id),
        events=events,
        retention_notes=[
            "This view is backed by persisted append-only audit events.",
            "Payload previews expose governed field summaries, not raw sensitive payloads.",
            "Queries are tenant-scoped before optional event, actor and scope filters.",
            "Export manifests are available through the retention/export endpoint; "
            "deterministic replay remains Platform work.",
        ],
    )


def _retention_policy(query: AuditExportQuery) -> AuditRetentionPolicy:
    legal_hold = query.legal_hold
    return AuditRetentionPolicy(
        policy_id="axis-demo-audit-standard",
        retention_days=query.retention_days,
        retention_basis="tenant-scoped operational audit ledger",
        disposal_action="retain_legal_hold" if legal_hold else "enforced_exclusion",
        legal_hold=legal_hold,
        export_requires_review=True,
        notes=[
            "Demo exports are payload-preview-only and require governance review before sharing.",
            (
                "Legal hold suspends retention exclusion for matching records."
                if legal_hold
                else "Retention windows are enforced before records enter the export bundle."
            ),
            "Immutable storage hardening is represented by a deterministic export hash chain.",
        ],
    )


def _parse_event_time(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _apply_retention_policy(
    events: list[AuditLedgerEvent],
    query: AuditExportQuery,
    generated_at: datetime,
) -> tuple[list[AuditLedgerEvent], datetime, int, bool]:
    window_start = generated_at - timedelta(days=query.retention_days)
    if query.legal_hold:
        return events, window_start, 0, False

    retained = [
        event
        for event in events
        if _parse_event_time(event.occurred_at) >= window_start
    ]
    return retained, window_start, len(events) - len(retained), True


def _events_checksum(events: list[AuditLedgerEvent]) -> str:
    encoded_events = json.dumps(
        [event.model_dump(mode="json") for event in events],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded_events.encode("utf-8")).hexdigest()


def _integrity_proof(events: list[AuditLedgerEvent]) -> AuditIntegrityProof:
    event_hashes: list[str] = []
    chain_tip = "0" * 64
    for event in events:
        encoded_event = json.dumps(
            event.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        event_hash = hashlib.sha256(encoded_event.encode("utf-8")).hexdigest()
        chain_tip = hashlib.sha256(f"{chain_tip}:{event_hash}".encode()).hexdigest()
        event_hashes.append(event_hash)

    return AuditIntegrityProof(
        algorithm="sha256-hash-chain-v1",
        verification_status="verified",
        record_count=len(events),
        chain_tip_sha256=chain_tip,
        event_hashes=event_hashes,
    )


def _resolve_worm_enforcement(
    object_lock_capability: ObjectLockCapability | None,
    *,
    retention_days: int,
    generated_at: datetime,
) -> tuple[str, str, bool, str | None]:
    """Return the truthful (status, mode, enforced, retain_until) WORM fields.

    ``object_lock_capability`` is the actual verified capability of the
    audit-export object store. This function serves the export-RESPONSE path:
    the bundle is returned over HTTP and is NOT itself written under
    object-lock, so an enforceable capability yields ``worm_status`` of
    "capability_attested" (the store CAN enforce WORM and the retain-until is
    the date such a write would use), not "object_locked". The
    ``worm_retention_enforced`` flag reflects the verified capability
    non-optimistically; the compliance gate refuses the export separately when
    the capability is missing.
    """

    if object_lock_capability is None or not object_lock_capability.compliance_enforceable:
        return "none", "none", False, None
    retain_until = (generated_at + timedelta(days=retention_days)).isoformat()
    return "capability_attested", COMPLIANCE_RETENTION_MODE, True, retain_until


def export_persisted_audit_events(
    repository: AxisPersistenceRepository,
    query: AuditExportQuery,
    ledger_signer: AuditLedgerSigner | None = None,
    *,
    object_lock_capability: ObjectLockCapability | None = None,
    require_worm_compliance: bool = False,
) -> AuditExportBundle:
    # Fail closed: a COMPLIANCE-configured export must refuse to emit a bundle
    # if the backing store cannot actually enforce object-lock.
    if require_worm_compliance and (
        object_lock_capability is None
        or not object_lock_capability.compliance_enforceable
    ):
        reason = (
            object_lock_capability.reason
            if object_lock_capability is not None
            else "object_lock_capability_not_probed"
        )
        raise AuditExportWormEnforcementError(reason)

    explorer = query_persisted_audit_events(repository, query)
    retention_policy = _retention_policy(query)
    generated_at_datetime = datetime.now(UTC)
    generated_at = generated_at_datetime.isoformat()
    retained_events, retention_window_start, excluded_count, retention_enforced = (
        _apply_retention_policy(explorer.events, query, generated_at_datetime)
    )
    worm_status, worm_retention_mode, worm_retention_enforced, worm_retain_until = (
        _resolve_worm_enforcement(
            object_lock_capability,
            retention_days=query.retention_days,
            generated_at=generated_at_datetime,
        )
    )
    checksum = _events_checksum(retained_events)
    integrity_proof = _integrity_proof(retained_events)
    manifest = AuditExportManifest(
        export_id=f"audit-export-{checksum[:16]}",
        generated_at=generated_at,
        tenant_id=query.tenant_id,
        record_count=len(retained_events),
        format=query.format,
        redaction_policy="payload-preview-only",
        retention_policy_id=retention_policy.policy_id,
        checksum_sha256=checksum,
        integrity_chain_tip_sha256=integrity_proof.chain_tip_sha256,
        retention_enforced=retention_enforced,
        retention_window_start=retention_window_start.isoformat(),
        excluded_record_count=excluded_count,
        worm_status=worm_status,
        worm_retention_mode=worm_retention_mode,
        worm_retention_enforced=worm_retention_enforced,
        worm_retain_until=worm_retain_until,
    )
    signature_payload = canonical_ledger_signature_payload(manifest, integrity_proof)
    ledger_signature = (
        ledger_signer.sign_payload(signature_payload)
        if ledger_signer is not None
        else unsigned_audit_ledger_signature(signature_payload)
    )
    retention_summary = (
        "Legal hold is active; retention exclusion is suspended for this export."
        if query.legal_hold
        else f"Retention enforcement excluded {excluded_count} expired event"
        f"{'' if excluded_count == 1 else 's'} from this export."
    )
    worm_summary = (
        "Object-store WORM capability is attested: the backing bucket enforces "
        f"S3 object-lock in {worm_retention_mode} mode and a stored copy would "
        f"be retained until {worm_retain_until}. This response payload is NOT "
        "itself object-locked; its integrity here rests on the hash-chain proof "
        "and ledger signature. A stored, object-locked artifact is produced by "
        "the connector-evidence materialization path."
        if worm_retention_enforced
        else "Object-store WORM is not enforced for this export; the bundle "
        "relies on the deterministic hash-chain integrity proof only."
    )
    return AuditExportBundle(
        tenant_id=query.tenant_id,
        scenario=explorer.scenario,
        format=query.format,
        export_reason=query.export_reason,
        filters=_query_filters(query),
        retention_policy=retention_policy,
        manifest=manifest,
        integrity_proof=integrity_proof,
        ledger_signature=ledger_signature,
        events=retained_events,
        retention_notes=[
            "Export bundle is tenant-scoped before optional filters are applied.",
            "Events include ledger metadata and redacted payload previews only.",
            "Manifest checksum covers the exported event payload previews and metadata.",
            retention_summary,
            "Integrity proof links exported records with a deterministic SHA-256 hash chain.",
            worm_summary,
        ],
    )


def _retention_cutoff(retention_days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=retention_days)


def _event_deletion_hash(event: AuditEvent) -> str:
    payload = {
        "id": str(event.id),
        "tenant_id": event.tenant_id,
        "actor_id": event.actor_id,
        "event_type": event.event_type,
        "created_at": event.created_at.astimezone(UTC).isoformat()
        if event.created_at.tzinfo is not None
        else event.created_at.replace(tzinfo=UTC).isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _evaluate_legal_hold_permission(
    tenant_id: str,
    actor_id: str,
    actor_scopes: list[str],
    operation: str,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_scopes=actor_scopes,
            required_scopes=[LEGAL_HOLD_REQUIRED_SCOPE],
            attributes={"operation": operation},
        )
    )
    if not decision.allowed:
        raise AuditLegalHoldPermissionDenied(decision)
    return decision


def _legal_hold_to_record(
    legal_hold: AuditLegalHold,
    *,
    permission_decision: PermissionDecision | None = None,
) -> AuditLegalHoldRecord:
    return AuditLegalHoldRecord(
        tenant_id=legal_hold.tenant_id,
        hold_id=legal_hold.hold_id,
        status=legal_hold.status,
        reason=legal_hold.reason,
        event_type=legal_hold.event_type,
        actor_filter=legal_hold.actor_id,
        requested_by=legal_hold.requested_by,
        approved_by=legal_hold.approved_by,
        released_by=legal_hold.released_by,
        release_reason=legal_hold.release_reason,
        audit_event_id=legal_hold.audit_event_id,
        audit_event_type=LEGAL_HOLD_ACTIVATED_EVENT_TYPE
        if legal_hold.audit_event_id
        else None,
        release_audit_event_id=legal_hold.release_audit_event_id,
        release_audit_event_type=LEGAL_HOLD_RELEASED_EVENT_TYPE
        if legal_hold.release_audit_event_id
        else None,
        permission_decision=permission_decision,
        notes=legal_hold.notes,
        created_at=legal_hold.created_at,
        released_at=legal_hold.released_at,
    )


def create_audit_legal_hold(
    repository: AxisPersistenceRepository,
    request: AuditLegalHoldCreateRequest,
) -> AuditLegalHoldRecord:
    decision = _evaluate_legal_hold_permission(
        request.tenant_id,
        request.actor_id,
        request.actor_scopes,
        "audit.legal_hold.activate",
    )
    existing = repository.get_audit_legal_hold(request.tenant_id, request.hold_id)
    if existing is not None and existing.status == "active":
        raise AuditLegalHoldConflict(request.hold_id, "active_hold_exists")

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=LEGAL_HOLD_ACTIVATED_EVENT_TYPE,
            payload={
                "category": "audit",
                "status": "active",
                "hold_id": request.hold_id,
                "reason": request.reason,
                "event_type_filter": request.event_type,
                "actor_filter": request.actor_filter,
                "approved_by": request.approved_by,
                "permission_decision": decision.model_dump(),
                "raw_payload_exported": False,
            },
        )
    )
    legal_hold = repository.create_audit_legal_hold(
        AuditLegalHoldCreate(
            tenant_id=request.tenant_id,
            hold_id=request.hold_id,
            reason=request.reason,
            requested_by=request.actor_id,
            approved_by=request.approved_by,
            event_type=request.event_type,
            actor_id=request.actor_filter,
            audit_event_id=audit_event.id,
            notes=request.notes,
        )
    )
    return _legal_hold_to_record(legal_hold, permission_decision=decision)


def release_audit_legal_hold(
    repository: AxisPersistenceRepository,
    request: AuditLegalHoldReleaseRequest,
) -> AuditLegalHoldRecord:
    decision = _evaluate_legal_hold_permission(
        request.tenant_id,
        request.actor_id,
        request.actor_scopes,
        "audit.legal_hold.release",
    )
    existing = repository.get_audit_legal_hold(request.tenant_id, request.hold_id)
    if existing is None:
        raise AuditLegalHoldNotFound("Audit legal hold record not found")
    if existing.status != "active":
        raise AuditLegalHoldConflict(request.hold_id, "hold_not_active")

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=LEGAL_HOLD_RELEASED_EVENT_TYPE,
            payload={
                "category": "audit",
                "status": "released",
                "hold_id": request.hold_id,
                "release_reason": request.release_reason,
                "permission_decision": decision.model_dump(),
                "raw_payload_exported": False,
            },
        )
    )
    legal_hold = repository.release_audit_legal_hold(
        AuditLegalHoldRelease(
            tenant_id=request.tenant_id,
            hold_id=request.hold_id,
            released_by=request.actor_id,
            release_reason=request.release_reason,
            release_audit_event_id=audit_event.id,
        )
    )
    return _legal_hold_to_record(legal_hold, permission_decision=decision)


def list_audit_legal_holds(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> list[AuditLegalHoldRecord]:
    return [
        _legal_hold_to_record(legal_hold)
        for legal_hold in repository.list_active_audit_legal_holds(tenant_id)
    ]


class ObjectLegalHoldStore(Protocol):
    """Minimal object-store surface for export-artifact legal holds.

    Reconciliation note: this is a *complementary* layer to the DB-level audit
    legal hold. The DB legal hold (:func:`create_audit_legal_hold`) suspends
    physical retention deletion of ledger *rows*; the object legal hold pins the
    materialized export *artifact* under S3 object-lock so the WORM bundle
    cannot be deleted or overwritten before retention expiry. Both are audited
    through the same append-only ledger.
    """

    adapter_name: str

    def apply_legal_hold(self, key: str) -> None:
        ...

    def release_legal_hold(self, key: str) -> None:
        ...


def _object_legal_hold_supported(object_store: ObjectLegalHoldStore) -> bool:
    return hasattr(object_store, "apply_legal_hold") and hasattr(
        object_store, "release_legal_hold"
    )


def apply_object_legal_hold(
    repository: AxisPersistenceRepository,
    object_store: ObjectLegalHoldStore,
    request: AuditObjectLegalHoldRequest,
) -> AuditObjectLegalHoldRecord:
    """Apply an S3 object-lock legal hold on a stored export artifact, audited."""

    decision = _evaluate_legal_hold_permission(
        request.tenant_id,
        request.actor_id,
        request.actor_scopes,
        "audit.object_legal_hold.apply",
    )
    if not _object_legal_hold_supported(object_store):
        raise AuditExportWormEnforcementError(
            "object_store_cannot_hold: the configured object store does not "
            "support S3 object-lock legal holds."
        )
    object_store.apply_legal_hold(request.storage_key)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=OBJECT_LEGAL_HOLD_APPLIED_EVENT_TYPE,
            payload={
                "category": "audit",
                "status": "applied",
                "storage_key": request.storage_key,
                "storage_adapter": object_store.adapter_name,
                "hold_id": request.hold_id,
                "reason": request.reason,
                "permission_decision": decision.model_dump(),
                "raw_payload_exported": False,
            },
        )
    )
    return AuditObjectLegalHoldRecord(
        tenant_id=request.tenant_id,
        storage_key=request.storage_key,
        storage_adapter=object_store.adapter_name,
        status="applied",
        reason=request.reason,
        hold_id=request.hold_id,
        actor_id=request.actor_id,
        audit_event_id=audit_event.id,
        audit_event_type=OBJECT_LEGAL_HOLD_APPLIED_EVENT_TYPE,
        permission_decision=decision,
    )


def release_object_legal_hold(
    repository: AxisPersistenceRepository,
    object_store: ObjectLegalHoldStore,
    request: AuditObjectLegalHoldRequest,
) -> AuditObjectLegalHoldRecord:
    """Release an S3 object-lock legal hold on a stored export artifact, audited."""

    decision = _evaluate_legal_hold_permission(
        request.tenant_id,
        request.actor_id,
        request.actor_scopes,
        "audit.object_legal_hold.release",
    )
    if not _object_legal_hold_supported(object_store):
        raise AuditExportWormEnforcementError(
            "object_store_cannot_hold: the configured object store does not "
            "support S3 object-lock legal holds."
        )
    object_store.release_legal_hold(request.storage_key)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=OBJECT_LEGAL_HOLD_RELEASED_EVENT_TYPE,
            payload={
                "category": "audit",
                "status": "released",
                "storage_key": request.storage_key,
                "storage_adapter": object_store.adapter_name,
                "hold_id": request.hold_id,
                "reason": request.reason,
                "permission_decision": decision.model_dump(),
                "raw_payload_exported": False,
            },
        )
    )
    return AuditObjectLegalHoldRecord(
        tenant_id=request.tenant_id,
        storage_key=request.storage_key,
        storage_adapter=object_store.adapter_name,
        status="released",
        reason=request.reason,
        hold_id=request.hold_id,
        actor_id=request.actor_id,
        audit_event_id=audit_event.id,
        audit_event_type=OBJECT_LEGAL_HOLD_RELEASED_EVENT_TYPE,
        permission_decision=decision,
    )


def _legal_hold_matches_event(legal_hold: AuditLegalHold, event: AuditEvent) -> bool:
    if legal_hold.event_type is not None and legal_hold.event_type != event.event_type:
        return False
    return not (legal_hold.actor_id is not None and legal_hold.actor_id != event.actor_id)


def _matching_legal_holds(
    legal_holds: list[AuditLegalHold],
    candidates: list[AuditEvent],
) -> list[AuditLegalHold]:
    matched: dict[str, AuditLegalHold] = {}
    for legal_hold in legal_holds:
        if any(_legal_hold_matches_event(legal_hold, event) for event in candidates):
            matched[legal_hold.hold_id] = legal_hold
    return list(matched.values())


def _evaluate_retention_deletion_permission(
    request: AuditRetentionDeletionRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=[RETENTION_DELETION_REQUIRED_SCOPE],
            attributes={
                "operation": "audit.retention_deletion.execute",
                "retention_days": request.retention_days,
                "dry_run": request.dry_run,
                "legal_hold": request.legal_hold,
            },
        )
    )
    if not decision.allowed:
        raise AuditRetentionDeletionPermissionDenied(decision)
    return decision


def execute_audit_retention_deletion(
    repository: AxisPersistenceRepository,
    request: AuditRetentionDeletionRequest,
) -> AuditRetentionDeletionResult:
    decision = _evaluate_retention_deletion_permission(request)
    cutoff = _retention_cutoff(request.retention_days)
    candidates = repository.list_audit_events_before(
        tenant_id=request.tenant_id,
        cutoff=cutoff,
        event_type=request.event_type,
        actor_id=request.actor_filter,
        limit=request.limit,
    )
    candidate_hashes = [_event_deletion_hash(event) for event in candidates]
    matching_legal_holds = _matching_legal_holds(
        repository.list_active_audit_legal_holds(request.tenant_id),
        candidates,
    )

    if request.legal_hold or matching_legal_holds:
        hold_notes = [
            f"Active legal hold {legal_hold.hold_id} blocks matching candidate records."
            for legal_hold in matching_legal_holds
        ]
        return AuditRetentionDeletionResult(
            tenant_id=request.tenant_id,
            retention_days=request.retention_days,
            cutoff=cutoff.isoformat(),
            dry_run=request.dry_run,
            legal_hold=True,
            status="blocked_legal_hold",
            candidate_count=len(candidates),
            deleted_count=0,
            retained_count=len(candidates),
            deleted_event_hashes=[],
            permission_decision=decision,
            notes=[
                "Legal hold is active; physical retention deletion is blocked.",
                "Candidate records were counted but no rows were deleted.",
                *hold_notes,
            ],
        )

    if request.dry_run:
        return AuditRetentionDeletionResult(
            tenant_id=request.tenant_id,
            retention_days=request.retention_days,
            cutoff=cutoff.isoformat(),
            dry_run=True,
            legal_hold=False,
            status="dry_run",
            candidate_count=len(candidates),
            deleted_count=0,
            retained_count=len(candidates),
            deleted_event_hashes=[],
            permission_decision=decision,
            notes=[
                "Dry run completed; no audit rows were deleted.",
                "Run with dry_run=false to execute physical retention deletion.",
            ],
        )

    deleted_count = repository.delete_audit_events(candidates)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=RETENTION_DELETION_EVENT_TYPE,
            payload={
                "category": "audit",
                "status": "executed",
                "reason": request.reason,
                "retention_days": request.retention_days,
                "cutoff": cutoff.isoformat(),
                "candidate_count": len(candidates),
                "deleted_count": deleted_count,
                "event_type_filter": request.event_type,
                "actor_filter": request.actor_filter,
                "deleted_event_hashes": candidate_hashes,
                "permission_decision": decision.model_dump(),
                "raw_payload_exported": False,
            },
        )
    )
    return AuditRetentionDeletionResult(
        tenant_id=request.tenant_id,
        retention_days=request.retention_days,
        cutoff=cutoff.isoformat(),
        dry_run=False,
        legal_hold=False,
        status="executed",
        candidate_count=len(candidates),
        deleted_count=deleted_count,
        retained_count=0,
        deleted_event_hashes=candidate_hashes,
        permission_decision=decision,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        notes=[
            "Physical retention deletion executed for eligible tenant-scoped audit rows.",
            "Deletion evidence stores event hashes, counts and filters, not raw payloads.",
            "Retention deletion evidence events are excluded from future candidate scans.",
        ],
    )
