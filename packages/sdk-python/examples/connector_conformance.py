"""Run the offline reference suite and an illustrative metadata-only health projection."""

from datetime import UTC, datetime, timedelta

from axis_sdk.connector_authoring import OperationContext
from axis_sdk.connector_authoring.conformance import (
    ConformanceProfile,
    records_digest,
    run_conformance,
)
from axis_sdk.connector_authoring.fixtures import reference_failure_fixtures
from axis_sdk.connector_authoring.health import HealthBudgets, HealthObservation, project_health
from axis_sdk.connector_authoring.reference import ReferenceAsset, ReferenceConnector


def main() -> None:
    assets = (
        ReferenceAsset(asset_id="a", asset_name="Synthetic press"),
        ReferenceAsset(asset_id="b", asset_name="Synthetic line"),
        ReferenceAsset(asset_id="c", asset_name="Synthetic conveyor"),
    )
    source = ReferenceConnector("fixture-tenant", assets=assets)
    context = OperationContext(
        tenant_id="fixture-tenant",
        connector_id=source.descriptor.connector_id,
        actor_id="fixture-author",
        operation_id="fixture-conformance",
    )
    report = run_conformance(
        source,
        context,
        ConformanceProfile(
            resource_id="assets",
            expected_records=len(assets),
            expected_digest=records_digest(asset.model_dump() for asset in assets),
        ),
        failures=reference_failure_fixtures(context, source=source),
    )
    print(report.model_dump_json(indent=2))
    assert report.passed
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    health = project_health(
        HealthObservation(
            tenant_id=context.tenant_id,
            connector_id=context.connector_id,
            resource_id="assets",
            observed_at=observed_at,
            last_success_at=observed_at - timedelta(seconds=30),
            source_watermark_at=observed_at - timedelta(seconds=45),
            source_head_at=observed_at - timedelta(seconds=5),
            checkpoint_state="committed",
            checkpoint_committed_at=observed_at - timedelta(seconds=30),
        ),
        HealthBudgets(
            max_freshness_seconds=60,
            max_lag_seconds=90,
            max_checkpoint_age_seconds=60,
        ),
    )
    print(health.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
