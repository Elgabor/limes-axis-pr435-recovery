from pydantic import ValidationError

from axis_api.demo import ManufacturingWorkflowConsole
from axis_api.manufacturing_empty import empty_manufacturing_workflow_console
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    get_manufacturing_tenant_metadata,
)
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_WORKFLOW_CONSOLE_REFERENCE_ID = "manufacturing-workflow-console"
WORKFLOW_CONSOLE_SURFACE = "workflows"


class WorkflowReferenceRecordNotFound(LookupError):
    pass


class WorkflowReferenceRecordInvalid(ValueError):
    pass


def get_persisted_manufacturing_workflow_console(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingWorkflowConsole:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, tenant_id)
    record = repository.get_demo_reference_record(
        tenant_id=tenant_id,
        surface=WORKFLOW_CONSOLE_SURFACE,
        reference_id=MANUFACTURING_WORKFLOW_CONSOLE_REFERENCE_ID,
    )
    if record is None:
        return empty_manufacturing_workflow_console(tenant_id, tenant_metadata)

    try:
        console = ManufacturingWorkflowConsole.model_validate(record.payload)
    except ValidationError as exc:
        raise WorkflowReferenceRecordInvalid(
            "Manufacturing workflow console reference payload is invalid"
        ) from exc

    if console.tenant_id != tenant_id:
        raise WorkflowReferenceRecordInvalid(
            "Manufacturing workflow console tenant does not match record tenant"
        )

    return console.model_copy(
        update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
    )
