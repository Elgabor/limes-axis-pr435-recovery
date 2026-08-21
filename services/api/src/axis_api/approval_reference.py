from pydantic import ValidationError

from axis_api.demo import ManufacturingApprovalInbox
from axis_api.manufacturing_empty import empty_manufacturing_approval_inbox
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    ManufacturingTenantNotFound,
    get_manufacturing_tenant_metadata,
)
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_APPROVAL_INBOX_REFERENCE_ID = "manufacturing-approval-inbox"
APPROVAL_INBOX_SURFACE = "approvals"


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

    return inbox.model_copy(
        update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
    )


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
