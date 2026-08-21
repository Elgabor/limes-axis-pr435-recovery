from pydantic import ValidationError

from axis_api.demo import ManufacturingActionRegistry
from axis_api.manufacturing_empty import empty_manufacturing_action_registry
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    ManufacturingTenantNotFound,
    get_manufacturing_tenant_metadata,
)
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_ACTION_REGISTRY_REFERENCE_ID = "manufacturing-action-registry"
ACTION_REGISTRY_SURFACE = "actions"


class ActionReferenceRecordNotFound(LookupError):
    pass


class ActionReferenceRecordInvalid(ValueError):
    pass


def get_persisted_manufacturing_action_registry(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingActionRegistry:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, tenant_id)
    record = repository.get_demo_reference_record(
        tenant_id=tenant_id,
        surface=ACTION_REGISTRY_SURFACE,
        reference_id=MANUFACTURING_ACTION_REGISTRY_REFERENCE_ID,
    )
    if record is None:
        return empty_manufacturing_action_registry(tenant_id, tenant_metadata)

    try:
        registry = ManufacturingActionRegistry.model_validate(record.payload)
    except ValidationError as exc:
        raise ActionReferenceRecordInvalid(
            "Manufacturing action registry reference payload is invalid"
        ) from exc

    if registry.tenant_id != tenant_id:
        raise ActionReferenceRecordInvalid(
            "Manufacturing action registry tenant does not match record tenant"
        )

    return registry.model_copy(
        update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
    )


def require_persisted_manufacturing_action_registry(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingActionRegistry:
    try:
        registry = get_persisted_manufacturing_action_registry(repository, tenant_id)
    except ManufacturingTenantNotFound as exc:
        raise ActionReferenceRecordNotFound(
            "Manufacturing action registry reference record not found"
        ) from exc
    if registry.provenance == ManufacturingResponseProvenance.EMPTY:
        raise ActionReferenceRecordNotFound(
            "Manufacturing action registry reference record not found"
        )
    return registry
