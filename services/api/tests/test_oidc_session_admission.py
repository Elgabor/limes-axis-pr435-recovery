from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from axis_api.persistence import AxisPersistenceRepository


def _repository_for_dialect(dialect_name: str) -> tuple[AxisPersistenceRepository, Mock]:
    session = Mock(spec=Session)
    session.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name=dialect_name)
    )
    return AxisPersistenceRepository(session), session


def test_postgres_oidc_session_admission_uses_transaction_advisory_lock() -> None:
    repository, session = _repository_for_dialect("postgresql")

    repository.acquire_oidc_session_admission_lock(
        tenant_id="tenant_acme",
        actor_id="operator@example.com",
    )

    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "pg_advisory_xact_lock" in sql
    assert "hashtextextended" in sql
    assert any("tenant_acme" in str(value) for value in compiled.params.values())
    assert any("operator@example.com" in str(value) for value in compiled.params.values())


def test_postgres_approval_decision_uses_transaction_advisory_lock() -> None:
    repository, session = _repository_for_dialect("postgresql")
    repository.acquire_approval_decision_lock("tenant_acme", "approval_42")

    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "pg_advisory_xact_lock" in sql
    assert "hashtextextended" in sql
    assert any("tenant_acme" in str(value) for value in compiled.params.values())
    assert any("approval_42" in str(value) for value in compiled.params.values())


def test_postgres_notification_acknowledgement_uses_transaction_advisory_lock() -> None:
    repository, session = _repository_for_dialect("postgresql")

    repository.acquire_platform_notification_acknowledgement_lock(
        tenant_id="tenant_acme",
        notification_id="notification_42",
        actor_id="operator@example.com",
    )

    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "pg_advisory_xact_lock" in sql
    assert "hashtextextended" in sql
    assert any("tenant_acme" in str(value) for value in compiled.params.values())
    assert any("notification_42" in str(value) for value in compiled.params.values())
    assert any("operator@example.com" in str(value) for value in compiled.params.values())


def test_sqlite_oidc_session_admission_relies_on_database_write_serialization() -> None:
    repository, session = _repository_for_dialect("sqlite")

    repository.acquire_oidc_session_admission_lock(
        tenant_id="tenant_demo_manufacturing",
        actor_id="plant-operations-owner-role",
    )

    session.execute.assert_not_called()


def test_sqlite_approval_decision_relies_on_database_write_serialization() -> None:
    repository, session = _repository_for_dialect("sqlite")
    repository.acquire_approval_decision_lock(
        "tenant_demo_manufacturing", "appr_expedite_supplier_batch"
    )
    session.execute.assert_not_called()


def test_unsupported_oidc_session_admission_dialect_fails_closed() -> None:
    repository, session = _repository_for_dialect("mysql")

    with pytest.raises(NotImplementedError, match="mysql"):
        repository.acquire_oidc_session_admission_lock(
            tenant_id="tenant_acme",
            actor_id="operator@example.com",
        )

    session.execute.assert_not_called()


def test_reference_session_lookup_locks_row_for_revocation() -> None:
    repository, session = _repository_for_dialect("postgresql")

    repository.get_oidc_browser_session_for_update(
        tenant_id="tenant_acme",
        session_ref=UUID("11111111-1111-4111-8111-111111111111"),
    )

    statement = session.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert "oidc_browser_sessions.tenant_id" in sql
    assert "oidc_browser_sessions.id" in sql
