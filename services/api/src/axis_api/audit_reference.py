from pydantic import ValidationError

from axis_api.demo import ManufacturingAuditExplorer
from axis_api.manufacturing_empty import empty_manufacturing_audit_explorer
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    get_manufacturing_tenant_metadata,
)
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_AUDIT_EXPLORER_REFERENCE_ID = "manufacturing-audit-explorer"
AUDIT_EXPLORER_SURFACE = "audit"


class AuditReferenceRecordNotFound(LookupError):
    pass


class AuditReferenceRecordInvalid(ValueError):
    pass


def get_persisted_manufacturing_audit_explorer(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingAuditExplorer:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, tenant_id)
    record = repository.get_demo_reference_record(
        tenant_id=tenant_id,
        surface=AUDIT_EXPLORER_SURFACE,
        reference_id=MANUFACTURING_AUDIT_EXPLORER_REFERENCE_ID,
    )
    if record is None:
        return empty_manufacturing_audit_explorer(tenant_id, tenant_metadata)

    try:
        explorer = ManufacturingAuditExplorer.model_validate(record.payload)
    except ValidationError as exc:
        raise AuditReferenceRecordInvalid(
            "Manufacturing audit explorer reference payload is invalid"
        ) from exc

    if explorer.tenant_id != tenant_id:
        raise AuditReferenceRecordInvalid(
            "Manufacturing audit explorer tenant does not match record tenant"
        )

    return explorer.model_copy(
        update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
    )
