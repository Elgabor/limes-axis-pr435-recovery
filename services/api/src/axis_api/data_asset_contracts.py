"""Declared data contracts evaluated against observed evidence.

A contract states what must be true about one asset's observed evidence: a
resource that must exist, the schema fingerprint it must carry, and freshness
thresholds for its last observation. Evaluation is derived from real
observations at read time — never stored verdicts — and an undeclared or
unobserved asset is ``unknown``, never green.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from axis_api.identity import resolve_declared_actor
from axis_api.persistence import (
    AuditEventCreate,
    AxisPersistenceRepository,
    DataAssetContractCreate,
)

CHECK_PRESENCE = "presence"
CHECK_SCHEMA = "schema"
CHECK_FRESHNESS = "freshness"


class DataContractState(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


class DataAssetContractConflict(ValueError):
    def __init__(
        self,
        asset_id: str,
        reason: str,
        *,
        current_revision_number: int | None = None,
    ) -> None:
        super().__init__(f"Data asset contract conflict: {reason}")
        self.asset_id = asset_id
        self.reason = reason
        self.current_revision_number = current_revision_number


class DataAssetContractDeclarationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_resource_name: str = Field(min_length=1, max_length=240)
    expected_schema_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    freshness_warn_hours: int | None = Field(default=None, ge=1)
    freshness_fail_hours: int | None = Field(default=None, ge=1)
    notes: list[str] = Field(default_factory=list)
    expected_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    declared_by: str | None = Field(default=None, min_length=1)


class DataAssetContractRecord(BaseModel):
    expected_resource_name: str = Field(min_length=1)
    expected_schema_fingerprint: str | None
    freshness_warn_hours: int | None
    freshness_fail_hours: int | None
    notes: list[str]
    revision_number: int = Field(ge=1)
    declared_by: str = Field(min_length=1)
    declared_at: datetime


class DataAssetContractView(BaseModel):
    tenant_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    contract: DataAssetContractRecord | None


class ContractCheck(BaseModel):
    kind: str = Field(pattern="^(presence|schema|freshness)$")
    state: DataContractState
    detail: str = Field(min_length=1)


class DataAssetContractEvaluationView(BaseModel):
    tenant_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    status: DataContractState
    checks: list[ContractCheck]
    evaluated_at: datetime


def _contract_view(record) -> DataAssetContractRecord:
    return DataAssetContractRecord(
        expected_resource_name=record.expected_resource_name,
        expected_schema_fingerprint=record.expected_schema_fingerprint,
        freshness_warn_hours=record.freshness_warn_hours,
        freshness_fail_hours=record.freshness_fail_hours,
        notes=list(record.notes),
        revision_number=record.revision_number,
        declared_by=record.declared_by,
        declared_at=record.created_at,
    )


def _fingerprint(request: DataAssetContractDeclarationRequest) -> tuple:
    return (
        request.expected_resource_name,
        request.expected_schema_fingerprint,
        request.freshness_warn_hours,
        request.freshness_fail_hours,
        list(request.notes),
    )


def _fingerprint_of_record(record) -> tuple:
    return (
        record.expected_resource_name,
        record.expected_schema_fingerprint,
        record.freshness_warn_hours,
        record.freshness_fail_hours,
        list(record.notes),
    )


def declare_data_asset_contract(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    asset_id: str,
    request: DataAssetContractDeclarationRequest,
    principal_actor_id: str | None,
) -> tuple[DataAssetContractRecord, str]:
    """Declare or update a data contract for one catalogued asset.

    Returns the current record and one of ``created`` (first declaration),
    ``updated`` (new revision), ``unchanged`` (identical current declaration)
    or ``replayed`` (same idempotency key).
    """
    repository.acquire_data_asset_contract_lock(
        tenant_id=tenant_id,
        asset_id=asset_id,
    )

    submitted_fingerprint = _fingerprint(request)
    existing_replay = repository.get_data_asset_contract_by_revision_idempotency_key(
        tenant_id,
        request.idempotency_key,
    )
    if existing_replay is not None:
        if existing_replay.asset_id != asset_id or _fingerprint_of_record(
            existing_replay
        ) != submitted_fingerprint:
            raise DataAssetContractConflict(asset_id, "revision_idempotency_conflict")
        return _contract_view(existing_replay), "replayed"

    current = repository.get_current_data_asset_contract(tenant_id, asset_id)
    declared_by = resolve_declared_actor(request.declared_by, principal_actor_id)

    if current is not None:
        if (
            request.expected_revision is None
            or request.expected_revision != current.revision_number
        ):
            raise DataAssetContractConflict(
                asset_id,
                "expected_revision_mismatch",
                current_revision_number=current.revision_number,
            )
        if _fingerprint_of_record(current) == submitted_fingerprint:
            return _contract_view(current), "unchanged"

    is_first_declaration = current is None
    revision_number = 1 if is_first_declaration else current.revision_number + 1
    audit_event_type = (
        "data.contract.declared" if is_first_declaration else "data.contract.updated"
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=declared_by,
            event_type=audit_event_type,
            payload={
                "asset_id": asset_id,
                "expected_resource_name": request.expected_resource_name,
                "revision_number": revision_number,
                "revises_revision_number": (
                    None if is_first_declaration else current.revision_number
                ),
                "idempotency_key": request.idempotency_key,
            },
        )
    )
    record_payload = DataAssetContractCreate(
        tenant_id=tenant_id,
        asset_id=asset_id,
        revision_number=revision_number,
        expected_resource_name=request.expected_resource_name,
        expected_schema_fingerprint=request.expected_schema_fingerprint,
        freshness_warn_hours=request.freshness_warn_hours,
        freshness_fail_hours=request.freshness_fail_hours,
        notes=list(request.notes),
        declared_by=declared_by,
        audit_event_type=audit_event_type,
        revises_revision_number=(
            None if is_first_declaration else current.revision_number
        ),
        replaced_by_revision_number=None,
        revision_idempotency_key=request.idempotency_key,
    )
    if is_first_declaration:
        record = repository.create_data_asset_contract_record(record_payload)
    else:
        record = repository.append_data_asset_contract_revision(current, record_payload)
    return _contract_view(record), "created" if is_first_declaration else "updated"


def get_data_asset_contract_view(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    asset_id: str,
) -> DataAssetContractView:
    record = repository.get_current_data_asset_contract(tenant_id, asset_id)
    return DataAssetContractView(
        tenant_id=tenant_id,
        asset_id=asset_id,
        contract=_contract_view(record) if record is not None else None,
    )


def evaluate_data_asset_contract(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    asset_id: str,
    now: datetime | None = None,
) -> DataAssetContractEvaluationView:
    """Derive the contract verdict from persisted evidence at read time."""
    evaluated_at = now or datetime.now(UTC)
    contract_record = repository.get_current_data_asset_contract(tenant_id, asset_id)
    if contract_record is None:
        return DataAssetContractEvaluationView(
            tenant_id=tenant_id,
            asset_id=asset_id,
            status=DataContractState.UNKNOWN,
            checks=[],
            evaluated_at=evaluated_at,
        )

    observation = repository.get_data_resource_observation_for_asset(
        tenant_id,
        asset_id,
        contract_record.expected_resource_name,
    )
    checks: list[ContractCheck] = []

    if observation is None:
        checks.append(
            ContractCheck(
                kind=CHECK_PRESENCE,
                state=DataContractState.FAIL,
                detail=(
                    f"Resource {contract_record.expected_resource_name!r} has "
                    "never been observed."
                ),
            )
        )
    else:
        checks.append(
            ContractCheck(
                kind=CHECK_PRESENCE,
                state=DataContractState.PASS,
                detail=(
                    f"Resource {contract_record.expected_resource_name!r} was "
                    f"last seen {observation.last_seen_at.isoformat()}."
                ),
            )
        )
        checks.extend(
            [
                _schema_check(contract_record, observation),
                _freshness_check(contract_record, observation, evaluated_at),
            ],
        )

    return DataAssetContractEvaluationView(
        tenant_id=tenant_id,
        asset_id=asset_id,
        status=_overall_status(checks),
        checks=checks,
        evaluated_at=evaluated_at,
    )


def _schema_check(contract_record, observation) -> ContractCheck:
    if contract_record.expected_schema_fingerprint is None:
        return ContractCheck(
            kind=CHECK_SCHEMA,
            state=DataContractState.UNKNOWN,
            detail="The contract does not declare an expected schema fingerprint.",
        )
    if observation.schema_fingerprint is None:
        return ContractCheck(
            kind=CHECK_SCHEMA,
            state=DataContractState.UNKNOWN,
            detail="The last observation carried no schema fingerprint.",
        )
    if observation.schema_fingerprint == contract_record.expected_schema_fingerprint:
        return ContractCheck(
            kind=CHECK_SCHEMA,
            state=DataContractState.PASS,
            detail="The observed schema fingerprint matches the contract.",
        )
    return ContractCheck(
        kind=CHECK_SCHEMA,
        state=DataContractState.FAIL,
        detail=(
            "The observed schema fingerprint differs from the declared "
            "expectation; compare drift on the resource before re-declaring."
        ),
    )


def _as_utc(value: datetime) -> datetime:
    # SQLite (local/test profiles) stores naive datetimes even for
    # timezone-aware columns; normalize before arithmetic.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _freshness_check(contract_record, observation, evaluated_at: datetime) -> ContractCheck:
    if (
        contract_record.freshness_warn_hours is None
        and contract_record.freshness_fail_hours is None
    ):
        return ContractCheck(
            kind=CHECK_FRESHNESS,
            state=DataContractState.UNKNOWN,
            detail="The contract declares no freshness thresholds.",
        )

    hours_since_seen = (
        evaluated_at - _as_utc(observation.last_seen_at)
    ).total_seconds() / 3600
    warn_hours = contract_record.freshness_warn_hours
    fail_hours = contract_record.freshness_fail_hours
    if fail_hours is not None and hours_since_seen > fail_hours:
        return ContractCheck(
            kind=CHECK_FRESHNESS,
            state=DataContractState.FAIL,
            detail=(
                f"Last observation is {hours_since_seen:.1f}h old, beyond the "
                f"{fail_hours}h fail threshold."
            ),
        )
    if warn_hours is not None and hours_since_seen > warn_hours:
        return ContractCheck(
            kind=CHECK_FRESHNESS,
            state=DataContractState.WARN,
            detail=(
                f"Last observation is {hours_since_seen:.1f}h old, within the "
                f"{fail_hours}h fail threshold but beyond the {warn_hours}h "
                "warn threshold."
            ),
        )
    return ContractCheck(
        kind=CHECK_FRESHNESS,
        state=DataContractState.PASS,
        detail=f"Last observation is {hours_since_seen:.1f}h old.",
    )


def _overall_status(checks: list[ContractCheck]) -> DataContractState:
    states = {check.state for check in checks}
    for degraded in (DataContractState.FAIL, DataContractState.WARN, DataContractState.UNKNOWN):
        if degraded in states:
            return degraded
    return DataContractState.PASS
