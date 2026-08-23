from collections.abc import Sequence
from datetime import datetime

from pydantic import ValidationError

from axis_api.demo import (
    ApprovalDecisionHistoryEntry,
    ApprovalInboxItem,
    ManufacturingApprovalInbox,
    OverviewStatus,
)
from axis_api.manufacturing_empty import empty_manufacturing_approval_inbox
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    ManufacturingTenantNotFound,
    get_manufacturing_tenant_metadata,
)
from axis_api.models import ApprovalRecord
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_APPROVAL_INBOX_REFERENCE_ID = "manufacturing-approval-inbox"
APPROVAL_INBOX_SURFACE = "approvals"

DECIDED_STATUS = "decided"
HIGH_RISK_LEVEL = "high"


class ApprovalReferenceRecordNotFound(LookupError):
    pass


class ApprovalReferenceRecordInvalid(ValueError):
    pass


def get_persisted_manufacturing_approval_inbox(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingApprovalInbox:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, tenant_id)
    record = repository.get_demo_reference_record(
        tenant_id=tenant_id,
        surface=APPROVAL_INBOX_SURFACE,
        reference_id=MANUFACTURING_APPROVAL_INBOX_REFERENCE_ID,
    )
    if record is None:
        return empty_manufacturing_approval_inbox(tenant_id, tenant_metadata)

    try:
        inbox = ManufacturingApprovalInbox.model_validate(record.payload)
    except ValidationError as exc:
        raise ApprovalReferenceRecordInvalid(
            "Manufacturing approval inbox reference payload is invalid"
        ) from exc

    if inbox.tenant_id != tenant_id:
        raise ApprovalReferenceRecordInvalid(
            "Manufacturing approval inbox tenant does not match record tenant"
        )

    reconciled = reconcile_inbox_with_decision_records(repository, tenant_id, inbox)
    return reconciled.model_copy(
        update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
    )


def derived_queue_status(items: list[ApprovalInboxItem]) -> OverviewStatus:
    """Derive queue health from the reconciled items."""
    pending = [item for item in items if item.status != DECIDED_STATUS]
    if any(item.risk_level == HIGH_RISK_LEVEL for item in pending):
        return OverviewStatus.ACTION_REQUIRED
    if pending:
        return OverviewStatus.WATCH
    return OverviewStatus.READY


def reconcile_inbox_with_decision_records(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    inbox: ManufacturingApprovalInbox,
) -> ManufacturingApprovalInbox:
    """Overlay persisted terminal decisions on the static reference inbox."""
    records = [
        record
        for record in repository.list_approval_records(tenant_id)
        if record.decision is not None
    ]
    decided_ids = {record.approval_id for record in records}
    reconciled_items = [
        item.model_copy(update={"status": DECIDED_STATUS})
        if item.approval_id in decided_ids
        else item
        for item in inbox.approvals
    ]
    return inbox.model_copy(
        update={
            "approvals": reconciled_items,
            "queue_status": derived_queue_status(reconciled_items),
            "decision_history": build_decision_history(records, reconciled_items),
        }
    )


def build_decision_history(
    records: Sequence[ApprovalRecord],
    reconciled_items: list[ApprovalInboxItem],
) -> list[ApprovalDecisionHistoryEntry]:
    """Derive terminal decision history from persisted approval records."""
    items_by_id = {item.approval_id: item for item in reconciled_items}
    entries: list[tuple[datetime | None, datetime, ApprovalDecisionHistoryEntry]] = []
    for record in records:
        snapshot = (
            record.payload.get("decision_result") if isinstance(record.payload, dict) else None
        )
        if not isinstance(snapshot, dict):
            snapshot = {}
        item = items_by_id.get(record.approval_id)
        audit_event_id = snapshot.get("audit_event_id")
        entries.append(
            (
                record.decided_at,
                record.created_at,
                ApprovalDecisionHistoryEntry(
                    approval_id=record.approval_id,
                    action=item.action if item is not None else record.action_id,
                    risk_level=item.risk_level if item is not None else record.risk_level,
                    status=record.status,
                    domain=item.domain if item is not None else None,
                    workflow_id=(
                        item.workflow_id
                        if item is not None and item.workflow_id
                        else record.workflow_id
                    ),
                    decision=str(snapshot.get("decision") or record.decision or ""),
                    decided_by=(
                        str(snapshot.get("actor_id"))
                        if snapshot.get("actor_id") is not None
                        else record.decision_actor_id
                    ),
                    decided_at=_as_iso(record.decided_at),
                    rationale=record.decision_note,
                    audit_event_id=(str(audit_event_id) if audit_event_id is not None else None),
                    follow_through_status=snapshot.get("workflow_signal_status"),
                ),
            )
        )
    entries.sort(
        key=lambda entry: (entry[0] or entry[1], entry[1]),
        reverse=True,
    )
    return [entry for _, _, entry in entries]


def _as_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def require_persisted_manufacturing_approval_inbox(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingApprovalInbox:
    try:
        inbox = get_persisted_manufacturing_approval_inbox(repository, tenant_id)
    except ManufacturingTenantNotFound as exc:
        raise ApprovalReferenceRecordNotFound(
            "Manufacturing approval inbox reference record not found"
        ) from exc
    if inbox.provenance == ManufacturingResponseProvenance.EMPTY:
        raise ApprovalReferenceRecordNotFound(
            "Manufacturing approval inbox reference record not found"
        )
    return inbox
