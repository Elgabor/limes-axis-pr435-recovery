from pydantic import ValidationError

from axis_api.demo import ManufacturingModelRouting
from axis_api.manufacturing_empty import empty_manufacturing_model_routing
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    get_manufacturing_tenant_metadata,
)
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_MODEL_ROUTING_REFERENCE_ID = "manufacturing-model-routing"
MODEL_ROUTING_SURFACE = "model-routing"


class ModelRoutingReferenceRecordInvalid(ValueError):
    pass


def get_persisted_manufacturing_model_routing(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingModelRouting:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, tenant_id)
    record = repository.get_demo_reference_record(
        tenant_id=tenant_id,
        surface=MODEL_ROUTING_SURFACE,
        reference_id=MANUFACTURING_MODEL_ROUTING_REFERENCE_ID,
    )
    if record is None:
        return empty_manufacturing_model_routing(tenant_id, tenant_metadata)

    try:
        routing = ManufacturingModelRouting.model_validate(record.payload)
    except ValidationError as exc:
        raise ModelRoutingReferenceRecordInvalid(
            "Manufacturing model routing reference payload is invalid"
        ) from exc

    if routing.tenant_id != tenant_id:
        raise ModelRoutingReferenceRecordInvalid(
            "Manufacturing model routing tenant does not match record tenant"
        )

    return routing.model_copy(
        update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
    )
