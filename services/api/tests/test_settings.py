"""Compatibility fixture captured from main at 0f0ef5f before capability extraction."""

import json
import os
import runpy
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings

from axis_api.config import RuntimeConfigurationError, Settings, validate_runtime_configuration

CONTRACT = json.loads((Path(__file__).parent / "fixtures/settings_contract.json").read_text())
API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.upper().startswith("AXIS_"):
            monkeypatch.delenv(name)


def test_flat_defaults_and_aliases_remain_compatible() -> None:
    settings = Settings(_env_file=None)
    assert settings.model_dump() == {name: entry["default"] for name, entry in CONTRACT.items()}
    assert settings.model_dump(by_alias=True) == {
        entry["alias"]: entry["default"] for entry in CONTRACT.values()
    }


@pytest.mark.parametrize("name", CONTRACT)
def test_every_existing_environment_name_is_loaded(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = CONTRACT[name]
    value = entry["probe"]
    encoded = value if isinstance(value, str) else json.dumps(value)
    monkeypatch.setenv(entry["alias"], encoded)
    settings = Settings(_env_file=None)
    assert settings.model_dump()[name] == value
    assert value != entry["default"]


@pytest.mark.parametrize("name", CONTRACT)
def test_constructor_names_and_aliases_remain_compatible(name: str) -> None:
    entry = CONTRACT[name]
    for key in (name, entry["alias"]):
        assert (
            Settings(_env_file=None, **{key: entry["probe"]}).model_dump()[name] == entry["probe"]
        )


def test_environment_source_precedence_and_json_lists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        'AXIS_ENV=dotenv\nAXIS_CORS_ORIGINS=["https://console.example"]\nUNKNOWN=ok\n'
    )
    assert Settings(_env_file=dotenv).environment == "dotenv"
    monkeypatch.setenv("AXIS_ENV", "process")
    assert Settings(_env_file=dotenv).environment == "process"
    for key in ("environment", "AXIS_ENV"):
        settings = Settings(_env_file=dotenv, **{key: "constructor"})
        assert settings.environment == "constructor"
        assert settings.cors_origins == ["https://console.example"]


def test_capabilities_own_each_field_once_without_loading_environment() -> None:
    groups = [base for base in Settings.__bases__ if base is not BaseSettings]
    assert {base.__name__ for base in groups} == {
        "IdentitySettings",
        "PersistenceSettings",
        "ModelsSettings",
        "ConnectorsSettings",
        "PolicySettings",
        "ObservabilitySettings",
        "RuntimeSettings",
    }
    names = [name for base in groups for name in base.model_fields]
    assert len(names) == len(set(names)) == len(CONTRACT)
    assert set(names) == set(Settings.model_fields)
    assert all(not issubclass(base, BaseSettings) for base in groups)


def test_generated_reference_is_current_and_ignores_operator_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AXIS_POSTGRES_DSN", "do-not-publish-operator-secret")
    monkeypatch.setenv("AXIS_OIDC_CLIENT_SECRET", "do-not-publish-operator-secret")
    generator = runpy.run_path(str(API_ROOT / "scripts/export_settings_reference.py"))
    reference = generator["render_reference"]()
    assert "do-not-publish-operator-secret" not in reference
    assert "axis:axis@" not in reference
    assert reference == generator["REFERENCE"].read_text(encoding="utf-8")


def production_settings(**overrides: object) -> Settings:
    values = dict(
        environment="production",
        oidc_auth_required=True,
        api_rate_limit_enabled=True,
        api_rate_limit_paths=["*"],
        api_rate_limit_backend="redis",
        api_rate_limit_failure_mode="closed",
        redis_url="redis://redis.example:6379/0",
        tenant_admission_mode="registered_only",
    )
    return Settings(_env_file=None, **(values | overrides))


INVALID_COMBINATIONS = [
    ({"api_rate_limit_requests": 0}, "AXIS_API_RATE_LIMIT_REQUESTS"),
    ({"api_rate_limit_window_seconds": -1}, "AXIS_API_RATE_LIMIT_WINDOW_SECONDS"),
    (
        {"source_ingestion_dispatch_enabled": True, "source_ingestion_retry_base_seconds": 61},
        "AXIS_SOURCE_INGESTION_RETRY_MAX_SECONDS",
    ),
    (
        {
            "source_ingestion_dispatch_enabled": True,
            "source_ingestion_extraction_enabled": True,
            "source_ingestion_claim_timeout_seconds": 30,
        },
        "AXIS_SOURCE_INGESTION_CLAIM_TIMEOUT_SECONDS",
    ),
]


@pytest.mark.parametrize("environment", ["production", "prod", " PRODUCTION "])
@pytest.mark.parametrize(("overrides", "message"), INVALID_COMBINATIONS)
def test_production_rejects_invalid_combinations(
    environment: str,
    overrides: dict,
    message: str,
) -> None:
    with pytest.raises(RuntimeConfigurationError, match=message):
        validate_runtime_configuration(production_settings(environment=environment, **overrides))


@pytest.mark.parametrize(("overrides", "message"), INVALID_COMBINATIONS)
def test_development_configuration_remains_compatible(overrides: dict, message: str) -> None:
    validate_runtime_configuration(Settings(_env_file=None, **overrides))


def test_production_accepts_consistent_ingestion_and_ignores_disabled_extraction() -> None:
    validate_runtime_configuration(
        production_settings(
            source_ingestion_dispatch_enabled=True,
            source_ingestion_extraction_enabled=True,
            source_ingestion_retry_base_seconds=60,
            source_ingestion_retry_max_seconds=60,
            source_ingestion_claim_timeout_seconds=31,
            source_ingestion_extraction_time_budget_seconds=30,
        )
    )
    validate_runtime_configuration(
        production_settings(
            source_ingestion_dispatch_enabled=True,
            source_ingestion_extraction_enabled=False,
            source_ingestion_claim_timeout_seconds=5,
        )
    )


def test_invalid_production_configuration_fails_before_app_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import axis_api.main as api

    def unexpected_app(*args: object, **kwargs: object) -> None:
        pytest.fail("FastAPI must not be constructed for an invalid production profile")

    monkeypatch.setattr(api, "FastAPI", unexpected_app)
    with pytest.raises(RuntimeConfigurationError, match="AXIS_SOURCE_INGESTION_RETRY_MAX_SECONDS"):
        api.create_app(
            production_settings(
                source_ingestion_dispatch_enabled=True,
                source_ingestion_retry_base_seconds=61,
            )
        )
