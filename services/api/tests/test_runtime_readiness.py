import asyncio
import time

import pytest

from axis_api.config import RuntimeConfigurationError, Settings, validate_runtime_configuration
from axis_api.runtime_readiness import static_runtime_readiness_service
from axis_api.tenant_admission import TENANT_ADMISSION_REGISTERED_ONLY


async def _healthy() -> None:
    return None


async def _fail() -> None:
    raise OSError("private dependency details")


async def _slow() -> None:
    await asyncio.sleep(1)


@pytest.mark.asyncio
async def test_required_probe_failure_makes_service_not_ready() -> None:
    service = static_runtime_readiness_service(
        {"postgres": (True, _healthy), "temporal": (True, _fail)}
    )

    report = await service.check()

    assert report.status == "not_ready"
    assert report.dependencies["postgres"].status == "ready"
    assert report.dependencies["temporal"].status == "unavailable"


@pytest.mark.asyncio
async def test_disabled_probe_is_reported_without_execution() -> None:
    service = static_runtime_readiness_service({"typedb": (False, _fail)})

    report = await service.check()

    assert report.status == "ready"
    assert report.dependencies["typedb"].status == "disabled"


@pytest.mark.asyncio
async def test_probe_timeout_is_bounded_and_probes_run_concurrently() -> None:
    service = static_runtime_readiness_service(
        {"postgres": (True, _slow), "temporal": (True, _slow)},
        timeout_seconds=0.05,
    )
    started_at = time.monotonic()

    report = await service.check()

    assert time.monotonic() - started_at < 0.15
    assert report.status == "not_ready"
    assert {item.status for item in report.dependencies.values()} == {"timeout"}


@pytest.mark.asyncio
async def test_timed_out_probe_is_shared_until_background_work_finishes() -> None:
    started = 0
    release = asyncio.Event()

    async def blocked() -> None:
        nonlocal started
        started += 1
        await release.wait()

    service = static_runtime_readiness_service(
        {"postgres": (True, blocked)},
        timeout_seconds=0.01,
    )

    first, second = await asyncio.gather(service.check(), service.check())

    assert first.dependencies["postgres"].status == "timeout"
    assert second.dependencies["postgres"].status == "timeout"
    assert started == 1
    release.set()
    await asyncio.sleep(0)


@pytest.mark.parametrize("environment", ["production", "prod", " PRODUCTION "])
def test_production_requires_oidc_auth(environment: str) -> None:
    with pytest.raises(RuntimeConfigurationError, match="AXIS_OIDC_AUTH_REQUIRED"):
        validate_runtime_configuration(
            Settings(environment=environment, oidc_auth_required=False)
        )


def test_production_with_auth_and_development_without_auth_are_valid() -> None:
    validate_runtime_configuration(
        Settings(
            environment="production",
            oidc_auth_required=True,
            api_rate_limit_enabled=True,
            api_rate_limit_paths=["*"],
            api_rate_limit_backend="redis",
            api_rate_limit_failure_mode="closed",
            redis_url="redis://rate-limit.internal:6379/0",
            tenant_admission_mode=TENANT_ADMISSION_REGISTERED_ONLY,
        )
    )
    validate_runtime_configuration(Settings(environment="development", oidc_auth_required=False))


def test_production_requires_registered_tenant_admission() -> None:
    with pytest.raises(RuntimeConfigurationError, match="AXIS_TENANT_ADMISSION_MODE"):
        validate_runtime_configuration(
            Settings(
                environment="production",
                oidc_auth_required=True,
                api_rate_limit_enabled=True,
                api_rate_limit_paths=["*"],
                api_rate_limit_backend="redis",
                api_rate_limit_failure_mode="closed",
                redis_url="redis://rate-limit.internal:6379/0",
            )
        )
