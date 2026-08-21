from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from axis_api.bootstrap_tenant import BOOTSTRAP_AUDIT_NOTE, run_cli
from axis_api.config import Settings
from axis_api.models import Actor, AuditEvent, Base, Tenant
from axis_api.platform_tenants import FIRST_TENANT_BOOTSTRAPPED_AUDIT_EVENT_TYPE


def bootstrap_arguments(
    *,
    tenant_id: str = "tenant_axis_platform_ops",
    idempotency_key: str = "first-tenant-v1",
    operator_id: str = "deployment-bootstrap",
) -> list[str]:
    return [
        "--tenant-id",
        tenant_id,
        "--display-name",
        "Axis platform operators",
        "--operator-id",
        operator_id,
        "--idempotency-key",
        idempotency_key,
        "--bootstrap-admin-id",
        "platform-operator-role",
        "--bootstrap-admin-display-name",
        "Platform operator",
        "--bootstrap-admin-scope",
        "platform:tenant:operator",
        "--note",
        "Bootstrap approved in the deployment change record.",
    ]


def sqlite_settings(database_path: Path) -> Settings:
    return Settings(postgres_dsn=f"sqlite+pysqlite:///{database_path}")


def initialize_database(database_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def test_cli_bootstraps_exactly_once_and_refuses_a_later_tenant(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "axis.sqlite"
    initialize_database(database_path)
    settings = sqlite_settings(database_path)
    arguments = bootstrap_arguments()

    assert run_cli(arguments, settings=settings) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["tenant_id"] == "tenant_axis_platform_ops"
    assert created["idempotent_replay"] is False

    assert run_cli(arguments, settings=settings) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["idempotent_replay"] is True

    refused = run_cli(
        bootstrap_arguments(
            tenant_id="tenant_second_platform_ops",
            idempotency_key="first-tenant-v2",
        ),
        settings=settings,
    )
    output = capsys.readouterr()
    assert refused == 2
    assert output.out == ""
    assert "tenant_registry_already_initialized" in output.err

    engine = create_engine(settings.postgres_dsn)
    try:
        with Session(engine) as session:
            tenants = list(session.scalars(select(Tenant)))
            actors = list(session.scalars(select(Actor)))
            events = list(session.scalars(select(AuditEvent)))
    finally:
        engine.dispose()
    assert [tenant.id for tenant in tenants] == ["tenant_axis_platform_ops"]
    assert [actor.id for actor in actors] == ["platform-operator-role"]
    assert BOOTSTRAP_AUDIT_NOTE in tenants[0].notes
    events_by_type = {event.event_type: event for event in events}
    assert set(events_by_type) == {
        "platform.tenant.provisioned",
        FIRST_TENANT_BOOTSTRAPPED_AUDIT_EVENT_TYPE,
    }
    bootstrap_event = events_by_type[FIRST_TENANT_BOOTSTRAPPED_AUDIT_EVENT_TYPE]
    provision_event = events_by_type["platform.tenant.provisioned"]
    assert bootstrap_event.payload["authority"] == "direct_database"
    assert bootstrap_event.payload["provision_audit_event_id"] == str(provision_event.id)


def test_cli_requires_complete_bootstrap_admin_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = bootstrap_arguments()
    name_flag_index = arguments.index("--bootstrap-admin-display-name")
    del arguments[name_flag_index : name_flag_index + 2]

    with pytest.raises(SystemExit) as exc_info:
        run_cli(arguments)

    assert exc_info.value.code == 2
    assert "must be supplied together" in capsys.readouterr().err


def test_cli_validates_operator_id_against_audit_storage_limit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "axis.sqlite"
    initialize_database(database_path)
    settings = sqlite_settings(database_path)
    boundary_operator_id = "o" * 120

    assert run_cli(
        bootstrap_arguments(operator_id=boundary_operator_id),
        settings=settings,
    ) == 0
    capsys.readouterr()

    engine = create_engine(settings.postgres_dsn)
    try:
        with Session(engine) as session:
            provision_event = session.scalar(
                select(AuditEvent).where(AuditEvent.event_type == "platform.tenant.provisioned")
            )
            assert provision_event is not None
            assert provision_event.actor_id == boundary_operator_id
    finally:
        engine.dispose()

    assert run_cli(
        bootstrap_arguments(operator_id="o" * 121),
        settings=settings,
    ) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "input is invalid" in output.err
    assert "requested_by" in output.err


@pytest.mark.parametrize(
    ("changed_flag", "changed_value"),
    [
        ("--bootstrap-admin-display-name", "Different platform operator"),
        ("--bootstrap-admin-scope", "platform:tenant:read"),
        ("--note", "Different deployment change record."),
    ],
)
def test_cli_rejects_same_key_when_persisted_evidence_changes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    changed_flag: str,
    changed_value: str,
) -> None:
    database_path = tmp_path / "axis.sqlite"
    initialize_database(database_path)
    settings = sqlite_settings(database_path)
    original_arguments = bootstrap_arguments()
    changed_arguments = original_arguments.copy()
    changed_arguments[changed_arguments.index(changed_flag) + 1] = changed_value

    assert run_cli(original_arguments, settings=settings) == 0
    capsys.readouterr()

    assert run_cli(changed_arguments, settings=settings) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "provision_idempotency_conflict" in output.err


def test_cli_database_failure_does_not_echo_the_connection_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "missing-parent" / "axis.sqlite"

    result = run_cli(
        bootstrap_arguments(),
        settings=sqlite_settings(database_path),
    )

    output = capsys.readouterr()
    assert result == 1
    assert output.out == ""
    assert "database is unavailable or migrations are incomplete" in output.err
    assert str(database_path) not in output.err
