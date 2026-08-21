import asyncio

import pytest
from fastapi.testclient import TestClient

from axis_api.config import RuntimeConfigurationError, Settings, validate_runtime_configuration
from axis_api.main import create_app
from axis_api.rate_limit import (
    InMemoryRateLimiter,
    RateLimitBackendError,
    RedisRateLimiter,
)


class _UnavailableBackend:
    async def check(self, key: str, *, limit: int):
        raise RateLimitBackendError("backend unavailable")

    async def close(self) -> None:
        return None


class _FakeRedis:
    def __init__(self, result: list[int]) -> None:
        self.result = result
        self.calls: list[tuple] = []

    async def eval(self, *args):
        self.calls.append(args)
        return self.result

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_in_memory_backend_is_atomic_with_concurrent_callers() -> None:
    limiter = InMemoryRateLimiter(limit=10, window_seconds=60)

    decisions = await asyncio.gather(
        *(limiter.check("shared-key", limit=10) for _ in range(50))
    )

    assert sum(decision.allowed for decision in decisions) == 10


@pytest.mark.asyncio
async def test_redis_backend_hashes_keys_and_interprets_atomic_script_result() -> None:
    redis = _FakeRedis([3, 42_500])
    limiter = RedisRateLimiter(redis, window_seconds=60)  # type: ignore[arg-type]

    decision = await limiter.check("tenant:customer-secret:/route", limit=2)

    assert decision.allowed is False
    assert decision.remaining == 0
    assert decision.retry_after_seconds == 43
    assert len(redis.calls) == 1
    assert "customer-secret" not in str(redis.calls[0])


def test_rate_limit_backend_failure_is_closed_when_configured() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                api_rate_limit_enabled=True,
                api_rate_limit_failure_mode="closed",
                api_rate_limit_paths=["/identity/oidc/readiness"],
            ),
            rate_limit_backend=_UnavailableBackend(),
        )
    )

    response = client.get("/identity/oidc/readiness")

    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "rate_limit_backend_unavailable"


def test_rate_limit_backend_failure_can_be_open_only_when_explicit() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                api_rate_limit_enabled=True,
                api_rate_limit_failure_mode="open",
                api_rate_limit_paths=["/identity/oidc/readiness"],
            ),
            rate_limit_backend=_UnavailableBackend(),
        )
    )

    assert client.get("/identity/oidc/readiness").status_code == 200


def test_health_is_never_rate_limited_or_redis_dependent() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                api_rate_limit_enabled=True,
                api_rate_limit_failure_mode="closed",
                api_rate_limit_paths=["*"],
            ),
            rate_limit_backend=_UnavailableBackend(),
        )
    )

    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    ("overrides", "expected_setting"),
    [
        (
            {"api_rate_limit_enabled": False},
            "AXIS_API_RATE_LIMIT_ENABLED",
        ),
        (
            {"api_rate_limit_paths": ["/health"]},
            "AXIS_API_RATE_LIMIT_PATHS",
        ),
        ({"api_rate_limit_backend": "memory"}, "AXIS_API_RATE_LIMIT_BACKEND"),
        (
            {"api_rate_limit_backend": "redis", "api_rate_limit_failure_mode": "open"},
            "AXIS_API_RATE_LIMIT_FAILURE_MODE",
        ),
        (
            {
                "api_rate_limit_backend": "redis",
                "api_rate_limit_failure_mode": "closed",
            },
            "AXIS_REDIS_URL",
        ),
    ],
)
def test_production_rate_limiting_requires_shared_fail_closed_backend(
    overrides: dict[str, object],
    expected_setting: str,
) -> None:
    values: dict[str, object] = {
        "environment": "production",
        "oidc_auth_required": True,
        "api_rate_limit_enabled": True,
        "api_rate_limit_paths": ["*"],
    }
    values.update(overrides)
    with pytest.raises(RuntimeConfigurationError, match=expected_setting):
        validate_runtime_configuration(Settings(**values))


def test_production_rate_limiting_accepts_complete_redis_configuration() -> None:
    validate_runtime_configuration(
        Settings(
            environment="production",
            oidc_auth_required=True,
            api_rate_limit_enabled=True,
            api_rate_limit_paths=["*"],
            api_rate_limit_backend="redis",
            api_rate_limit_failure_mode="closed",
            redis_url="redis://rate-limit.internal:6379/0",
            tenant_admission_mode="registered_only",
        )
    )


def test_production_usage_metering_requires_fail_closed_admission() -> None:
    with pytest.raises(RuntimeConfigurationError, match="AXIS_USAGE_METERING_FAILURE_MODE"):
        validate_runtime_configuration(
            Settings(
                environment="production",
                oidc_auth_required=True,
                api_rate_limit_enabled=True,
                api_rate_limit_paths=["*"],
                api_rate_limit_backend="redis",
                api_rate_limit_failure_mode="closed",
                redis_url="redis://rate-limit.internal:6379/0",
                usage_metering_enabled=True,
                usage_metering_failure_mode="open",
            )
        )
