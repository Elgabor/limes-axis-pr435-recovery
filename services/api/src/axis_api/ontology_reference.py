from pydantic import ValidationError

from axis_api.demo import (
    ManufacturingOntology,
    ManufacturingOntologyEntityDetail,
    build_manufacturing_ontology_entity_detail,
)
from axis_api.manufacturing_empty import empty_manufacturing_ontology
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    ManufacturingTenantNotFound,
    get_manufacturing_tenant_metadata,
)
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_ONTOLOGY_REFERENCE_ID = "manufacturing-ontology"
ONTOLOGY_SURFACE = "ontology"


class OntologyReferenceRecordNotFound(LookupError):
    pass


class OntologyReferenceRecordInvalid(ValueError):
    pass


def get_persisted_manufacturing_ontology(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingOntology:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, tenant_id)
    record = repository.get_demo_reference_record(
        tenant_id=tenant_id,
        surface=ONTOLOGY_SURFACE,
        reference_id=MANUFACTURING_ONTOLOGY_REFERENCE_ID,
    )
    if record is None:
        return empty_manufacturing_ontology(tenant_id, tenant_metadata)

    try:
        ontology = ManufacturingOntology.model_validate(record.payload)
    except ValidationError as exc:
        raise OntologyReferenceRecordInvalid(
            "Manufacturing ontology reference payload is invalid"
        ) from exc

    if ontology.tenant_id != tenant_id:
        raise OntologyReferenceRecordInvalid(
            "Manufacturing ontology tenant does not match record tenant"
        )

    return ontology.model_copy(
        update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
    )


def require_persisted_manufacturing_ontology(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingOntology:
    try:
        ontology = get_persisted_manufacturing_ontology(repository, tenant_id)
    except ManufacturingTenantNotFound as exc:
        raise OntologyReferenceRecordNotFound(
            "Manufacturing ontology reference record not found"
        ) from exc
    if ontology.provenance == ManufacturingResponseProvenance.EMPTY:
        raise OntologyReferenceRecordNotFound(
            "Manufacturing ontology reference record not found"
        )
    return ontology


def get_persisted_manufacturing_ontology_entity_detail(
    repository: AxisPersistenceRepository,
    node_id: str,
    tenant_id: str,
) -> ManufacturingOntologyEntityDetail | None:
    ontology = get_persisted_manufacturing_ontology(repository, tenant_id=tenant_id)
    return build_manufacturing_ontology_entity_detail(ontology, node_id)
