from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from axis_sdk.connector_authoring.health import (
    HealthBudgets,
    HealthObservation,
    OperationalError,
    project_health,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
BUDGETS = HealthBudgets(
    max_freshness_seconds=60,
    max_lag_seconds=120,
    max_checkpoint_age_seconds=60,
)


def observation(**changes):
    values = dict(
        tenant_id="tenant-a",
        connector_id="connector-a",
        resource_id="resource-a",
        observed_at=NOW,
        last_success_at=NOW - timedelta(seconds=30),
        source_watermark_at=NOW - timedelta(seconds=60),
        source_head_at=NOW - timedelta(seconds=10),
        checkpoint_state="committed",
        checkpoint_committed_at=NOW - timedelta(seconds=30),
    )
    return HealthObservation(**(values | changes))


def test_freshness_lag_and_checkpoint_age_are_distinct_and_serializable():
    result = project_health(observation(), BUDGETS)
    assert result.status == "ready"
    assert (result.freshness_seconds, result.lag_seconds, result.checkpoint_age_seconds) == (
        30,
        50,
        30,
    )
    assert result.reasons == ()
    assert type(result).model_validate_json(result.model_dump_json()) == result


def test_missing_history_is_unknown_instead_of_zero_or_ready():
    result = project_health(
        HealthObservation(
            tenant_id="tenant-a",
            connector_id="connector-a",
            resource_id="resource-a",
            observed_at=NOW,
        ),
        BUDGETS,
    )
    assert result.status == "unknown"
    assert result.freshness_seconds is None
    assert result.lag_seconds is None
    assert result.checkpoint_age_seconds is None
    assert set(result.reasons) == {"freshness_unknown", "lag_unknown", "checkpoint_unknown"}


@pytest.mark.parametrize(
    "field,seconds,reason",
    [
        ("last_success_at", 61, "stale"),
        ("source_watermark_at", 131, "lagging"),
        ("checkpoint_committed_at", 61, "checkpoint_stale"),
    ],
)
def test_independent_budget_breaches_degrade_health(field, seconds, reason):
    result = project_health(observation(**{field: NOW - timedelta(seconds=seconds)}), BUDGETS)
    assert result.status == "degraded"
    assert reason in result.reasons


def test_exact_budget_is_allowed_and_invalid_checkpoint_is_unavailable():
    exact = observation(last_success_at=NOW - timedelta(seconds=60))
    assert project_health(exact, BUDGETS).status == "ready"
    result = project_health(observation(checkpoint_state="invalid"), BUDGETS)
    assert result.status == "unavailable"
    assert "invalid_checkpoint" in result.reasons


@pytest.mark.parametrize(
    "error,status",
    [
        (OperationalError.CREDENTIALS, "unavailable"),
        (OperationalError.SCHEMA_DRIFT, "unavailable"),
        (OperationalError.THROTTLED, "degraded"),
        (OperationalError.PARTIAL_DATA, "degraded"),
        (OperationalError.SOURCE_UNAVAILABLE, "unavailable"),
        (OperationalError.INVALID_CHECKPOINT, "unavailable"),
        (OperationalError.UNKNOWN, "degraded"),
    ],
)
def test_failure_categories_have_fixed_metadata_only_health(error, status):
    result = project_health(observation(last_error=error, last_error_at=NOW), BUDGETS)
    assert result.status == status
    assert result.reasons == (error.value,)
    assert result.observation.tenant_id == "tenant-a"
    assert "cursor" not in result.model_dump_json()


def test_retry_schedule_and_exhaustion_are_observations_not_actions():
    scheduled = observation(
        last_error=OperationalError.THROTTLED,
        last_error_at=NOW - timedelta(seconds=10),
        retry_state="scheduled",
        attempt_count=2,
        next_retry_at=NOW - timedelta(seconds=1),
    )
    result = project_health(scheduled, BUDGETS)
    assert result.status == "degraded"
    assert result.reasons == ("throttled", "retry_scheduled", "retry_overdue")
    assert result.observation == scheduled
    exhausted = observation(
        last_error=OperationalError.THROTTLED,
        last_error_at=NOW,
        retry_state="exhausted",
        attempt_count=5,
    )
    assert project_health(exhausted, BUDGETS).status == "unavailable"


def test_later_complete_success_resolves_historical_error():
    recovered = observation(
        last_error=OperationalError.CREDENTIALS,
        last_error_at=NOW - timedelta(seconds=40),
        attempt_count=2,
    )
    result = project_health(recovered, BUDGETS)
    assert result.status == "ready"
    assert result.reasons == ()
    assert result.observation.last_error == OperationalError.CREDENTIALS


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_at": NOW.replace(tzinfo=None)},
        {"last_success_at": NOW + timedelta(seconds=1)},
        {"source_watermark_at": NOW + timedelta(seconds=1)},
        {"last_error": OperationalError.THROTTLED},
        {"last_error_at": NOW},
        {"checkpoint_state": "absent"},
        {"checkpoint_committed_at": None},
        {"retry_state": "scheduled"},
        {"next_retry_at": NOW},
        {"retry_state": "exhausted", "attempt_count": 1},
        {"attempt_count": -1},
        {"provider_message": "private-password"},
        {"checkpoint_cursor": "private-cursor"},
    ],
)
def test_inconsistent_future_or_sensitive_input_is_rejected(changes):
    with pytest.raises(ValidationError):
        observation(**changes)


def test_revalidation_prevents_mutated_models_from_claiming_healthy_future_success():
    forged = observation().model_copy(update={"last_success_at": NOW + timedelta(seconds=1)})
    with pytest.raises(ValidationError):
        project_health(forged, BUDGETS)


@pytest.mark.parametrize("budget", [0, -1, True])
def test_budgets_must_be_explicit_positive_seconds(budget):
    with pytest.raises(ValidationError):
        HealthBudgets(
            max_freshness_seconds=budget, max_lag_seconds=10, max_checkpoint_age_seconds=10
        )


def test_idle_source_has_zero_backlog_even_when_its_latest_event_is_old():
    old = NOW - timedelta(days=1)
    result = project_health(observation(source_head_at=old, source_watermark_at=old), BUDGETS)
    assert result.lag_seconds == 0
    assert result.status == "ready"


def test_nonresumable_source_marks_checkpoint_not_applicable_explicitly():
    result = project_health(
        observation(
            checkpoint_state="not_applicable",
            checkpoint_committed_at=None,
        ),
        BUDGETS,
    )
    assert result.status == "ready"
    assert result.checkpoint_age_seconds is None
    assert "checkpoint_unknown" not in result.reasons


def test_a_watermark_without_source_head_does_not_claim_zero_lag():
    result = project_health(observation(source_head_at=None), BUDGETS)
    assert result.status == "unknown"
    assert result.lag_seconds is None
    assert "lag_unknown" in result.reasons


def test_watermark_ahead_of_source_head_is_rejected():
    with pytest.raises(ValidationError):
        observation(source_head_at=NOW - timedelta(seconds=120))
