from pydantic import ValidationError

from axis_api.demo import ManufacturingOverview
from axis_api.manufacturing_empty import empty_manufacturing_overview
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    get_manufacturing_tenant_metadata,
)
from axis_api.persistence import AxisPersistenceRepository

MANUFACTURING_OVERVIEW_REFERENCE_ID = "manufacturing-overview"
OVERVIEW_SURFACE = "overview"


class DemoReferenceRecordNotFound(LookupError):
    pass


class DemoReferenceRecordInvalid(ValueError):
    pass


def get_persisted_manufacturing_overview(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingOverview:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, tenant_id)
    record = repository.get_demo_reference_record(
        tenant_id=tenant_id,
        surface=OVERVIEW_SURFACE,
        reference_id=MANUFACTURING_OVERVIEW_REFERENCE_ID,
    )
    if record is None:
        return empty_manufacturing_overview(tenant_id, tenant_metadata)

    try:
        overview = ManufacturingOverview.model_validate(record.payload)
    except ValidationError as exc:
        raise DemoReferenceRecordInvalid(
            "Manufacturing overview reference payload is invalid"
        ) from exc

    if overview.tenant_id != tenant_id:
        raise DemoReferenceRecordInvalid(
            "Manufacturing overview tenant does not match record tenant"
        )

    return overview.model_copy(
        update={"provenance": ManufacturingResponseProvenance.REFERENCE_SCENARIO}
    )
