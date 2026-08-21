from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from axis_api.persistence import AxisPersistenceRepository


class ManufacturingResponseProvenance(StrEnum):
    REFERENCE_SCENARIO = "reference_scenario"
    LIVE = "live"
    EMPTY = "empty"


class ManufacturingTenantNotFound(LookupError):
    def __init__(self, tenant_id: str) -> None:
        super().__init__(f"Manufacturing tenant {tenant_id!r} is unknown")
        self.tenant_id = tenant_id


@dataclass(frozen=True)
class ManufacturingTenantMetadata:
    plant_name: str | None
    scenario: str | None
    as_of: str


def get_manufacturing_tenant_metadata(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingTenantMetadata:
    tenant = repository.get_tenant(tenant_id)
    if tenant is None:
        # A seeded tenant predating the registry still exists as far as the
        # console is concerned; only a tenant with neither a registry row nor
        # reference records is genuinely unknown.
        if repository.has_demo_reference_records(tenant_id):
            return ManufacturingTenantMetadata(
                plant_name=None,
                scenario=None,
                as_of=datetime.now(UTC).isoformat(),
            )
        raise ManufacturingTenantNotFound(tenant_id)
    return ManufacturingTenantMetadata(
        plant_name=tenant.name.strip() or None,
        scenario=tenant.description.strip() or None,
        as_of=tenant.updated_at.isoformat(),
    )


def find_manufacturing_tenant_metadata(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> ManufacturingTenantMetadata:
    tenant = repository.get_tenant(tenant_id)
    if tenant is None:
        return ManufacturingTenantMetadata(
            plant_name=None,
            scenario=None,
            as_of=datetime.now(UTC).isoformat(),
        )
    return ManufacturingTenantMetadata(
        plant_name=tenant.name.strip() or None,
        scenario=tenant.description.strip() or None,
        as_of=tenant.updated_at.isoformat(),
    )


def operational_provenance(has_records: bool) -> ManufacturingResponseProvenance:
    return (
        ManufacturingResponseProvenance.LIVE
        if has_records
        else ManufacturingResponseProvenance.EMPTY
    )
