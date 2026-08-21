from pydantic import ValidationError

from axis_api.demo import ManufacturingAgentRegistry
from axis_api.manufacturing_empty import empty_manufacturing_agent_registry
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    ManufacturingTenantNotFound,
    get_manufacturing_tenant_metadata,
)
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_AGENT_REGISTRY_REFERENCE_ID = "manufacturing-agent-registry"
AGENT_REGISTRY_SURFACE = "agents"


class AgentReferenceRecordNotFound(LookupError):
    pass


class AgentReferenceRecordInvalid(ValueError):
    pass


def get_persisted_manufacturing_agent_registry(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingAgentRegistry:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, tenant_id)
    record = repository.get_demo_reference_record(
        tenant_id=tenant_id,
        surface=AGENT_REGISTRY_SURFACE,
        reference_id=MANUFACTURING_AGENT_REGISTRY_REFERENCE_ID,
    )
    if record is None:
        return empty_manufacturing_agent_registry(tenant_id, tenant_metadata)

    try:
        registry = ManufacturingAgentRegistry.model_validate(record.payload)
    except ValidationError as exc:
        raise AgentReferenceRecordInvalid(
            "Manufacturing agent registry reference payload is invalid"
        ) from exc

    if registry.tenant_id != tenant_id:
        raise AgentReferenceRecordInvalid(
            "Manufacturing agent registry tenant does not match record tenant"
        )

    return registry.model_copy(
        update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
    )


def require_persisted_manufacturing_agent_registry(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingAgentRegistry:
    try:
        registry = get_persisted_manufacturing_agent_registry(repository, tenant_id)
    except ManufacturingTenantNotFound as exc:
        raise AgentReferenceRecordNotFound(
            "Manufacturing agent registry reference record not found"
        ) from exc
    if registry.provenance == ManufacturingResponseProvenance.EMPTY:
        raise AgentReferenceRecordNotFound(
            "Manufacturing agent registry reference record not found"
        )
    return registry
