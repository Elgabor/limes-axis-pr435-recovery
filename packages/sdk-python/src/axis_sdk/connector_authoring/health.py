"""Pure metadata projection; observations never authorize source calls or retries."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from axis_sdk.connector_authoring.contracts import ContractModel, Identifier


class OperationalError(StrEnum):
    CREDENTIALS = "credentials"
    SCHEMA_DRIFT = "schema_drift"
    THROTTLED = "throttled"
    PARTIAL_DATA = "partial_data"
    SOURCE_UNAVAILABLE = "source_unavailable"
    INVALID_CHECKPOINT = "invalid_checkpoint"
    UNKNOWN = "unknown_error"


class HealthObservation(ContractModel):
    tenant_id: Identifier
    connector_id: Identifier
    resource_id: Identifier
    observed_at: AwareDatetime
    last_success_at: AwareDatetime | None = None
    source_watermark_at: AwareDatetime | None = None
    source_head_at: AwareDatetime | None = None
    checkpoint_state: Literal["unknown", "absent", "not_applicable", "committed", "invalid"] = (
        "unknown"
    )
    checkpoint_committed_at: AwareDatetime | None = None
    last_error: OperationalError | None = None
    last_error_at: AwareDatetime | None = None
    retry_state: Literal["idle", "scheduled", "in_progress", "exhausted"] = "idle"
    attempt_count: int = Field(default=0, ge=0, strict=True)
    next_retry_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def coherent_observation(self):
        for timestamp in (
            self.last_success_at,
            self.source_watermark_at,
            self.source_head_at,
            self.checkpoint_committed_at,
            self.last_error_at,
        ):
            if timestamp is not None and timestamp > self.observed_at:
                raise ValueError("Observed history cannot be in the future")
        if (
            self.source_head_at is not None
            and self.source_watermark_at is not None
            and self.source_watermark_at > self.source_head_at
        ):
            raise ValueError("Committed watermark cannot be ahead of the observed source head")
        if (self.last_error is None) != (self.last_error_at is None):
            raise ValueError("Error category and timestamp must be supplied together")
        if self.checkpoint_state == "committed" and self.checkpoint_committed_at is None:
            raise ValueError("Committed checkpoint requires its commit time")
        if (
            self.checkpoint_state in {"unknown", "absent", "not_applicable"}
            and self.checkpoint_committed_at
        ):
            raise ValueError("Unknown or absent checkpoint cannot carry a commit time")
        if (self.retry_state == "scheduled") != (self.next_retry_at is not None):
            raise ValueError("Only a scheduled retry carries its next attempt time")
        if self.retry_state != "idle" and (self.attempt_count == 0 or self.active_error is None):
            raise ValueError("Retry state requires an attempt and an unresolved error")
        return self

    @property
    def active_error(self) -> OperationalError | None:
        if self.last_error_at is not None and (
            self.last_success_at is None or self.last_error_at >= self.last_success_at
        ):
            return self.last_error
        return None


class HealthBudgets(ContractModel):
    """Operator-supplied resource budgets, not SDK defaults or service guarantees."""

    max_freshness_seconds: int = Field(ge=1, strict=True)
    max_lag_seconds: int = Field(ge=1, strict=True)
    max_checkpoint_age_seconds: int = Field(ge=1, strict=True)


class OperationalHealth(ContractModel):
    observation: HealthObservation
    budgets: HealthBudgets
    status: Literal["ready", "degraded", "unavailable", "unknown"]
    freshness_seconds: float | None
    lag_seconds: float | None
    checkpoint_age_seconds: float | None
    reasons: tuple[
        Literal[
            "credentials",
            "schema_drift",
            "throttled",
            "partial_data",
            "source_unavailable",
            "invalid_checkpoint",
            "unknown_error",
            "retry_scheduled",
            "retry_in_progress",
            "retry_exhausted",
            "retry_overdue",
            "freshness_unknown",
            "stale",
            "lag_unknown",
            "lagging",
            "checkpoint_unknown",
            "checkpoint_stale",
        ],
        ...,
    ]


def project_health(observation: HealthObservation, budgets: HealthBudgets) -> OperationalHealth:
    """Derive health at the supplied observation time; never substitute zero for unknown."""

    observation = HealthObservation.model_validate(observation.model_dump())
    budgets = HealthBudgets.model_validate(budgets.model_dump())

    def age(timestamp: datetime | None) -> float | None:
        return None if timestamp is None else (observation.observed_at - timestamp).total_seconds()

    freshness = age(observation.last_success_at)
    lag = (
        None
        if observation.source_head_at is None or observation.source_watermark_at is None
        else (observation.source_head_at - observation.source_watermark_at).total_seconds()
    )
    checkpoint_age = age(observation.checkpoint_committed_at)
    reasons = []
    unavailable = False
    degraded = False
    unknown = False
    error = observation.active_error
    if error is not None:
        reasons.append(error.value)
        unavailable = error in {
            OperationalError.CREDENTIALS,
            OperationalError.SCHEMA_DRIFT,
            OperationalError.SOURCE_UNAVAILABLE,
            OperationalError.INVALID_CHECKPOINT,
        }
        degraded = True
    if observation.retry_state != "idle":
        reasons.append("retry_" + observation.retry_state)
        degraded = True
        unavailable |= observation.retry_state == "exhausted"
        if (
            observation.next_retry_at is not None
            and observation.next_retry_at < observation.observed_at
        ):
            reasons.append("retry_overdue")
    for value, budget, missing, exceeded in (
        (freshness, budgets.max_freshness_seconds, "freshness_unknown", "stale"),
        (lag, budgets.max_lag_seconds, "lag_unknown", "lagging"),
        (
            checkpoint_age,
            budgets.max_checkpoint_age_seconds,
            "checkpoint_unknown",
            "checkpoint_stale",
        ),
    ):
        if missing == "checkpoint_unknown" and observation.checkpoint_state == "not_applicable":
            continue
        if value is None:
            reasons.append(missing)
            unknown = True
        elif value > budget:
            reasons.append(exceeded)
            degraded = True
    if observation.checkpoint_state == "invalid":
        if "invalid_checkpoint" not in reasons:
            reasons.append("invalid_checkpoint")
        unavailable = True
    if unavailable:
        status = "unavailable"
    elif degraded:
        status = "degraded"
    elif unknown:
        status = "unknown"
    else:
        status = "ready"
    return OperationalHealth(
        observation=observation,
        budgets=budgets,
        status=status,
        freshness_seconds=freshness,
        lag_seconds=lag,
        checkpoint_age_seconds=checkpoint_age,
        reasons=tuple(reasons),
    )
