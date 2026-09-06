"""One contract suite for the model aggregate and the stable persistence facade.

Default runs use a temporary SQLite file. The PostgreSQL CI target explicitly
selects PostgreSQL, creates/migrates a fresh random database, and drops only that
database on exit. Missing PostgreSQL configuration is an error in that lane.
"""

import os
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic.command import upgrade
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from axis_api.audit import AuditEventCreate
from axis_api.db import session_scope
from axis_api.models import AuditEvent, Base, ModelInvocation
from axis_api.persistence import AxisPersistenceRepository, PersistenceRecordNotFound
from axis_api.repositories.models import (
    ModelEndpointCreate,
    ModelEndpointStatusUpdate,
    ModelInvocationCreate,
    ModelInvocationResultRecord,
    ModelRepository,
)


@pytest.fixture(scope="module")
def contract_engine(tmp_path_factory):
    if os.getenv("AXIS_MODEL_CONTRACT_BACKEND", "sqlite") == "sqlite":
        database = tmp_path_factory.mktemp("model-contract") / "contract.sqlite"
        engine = create_engine(f"sqlite+pysqlite:///{database}")
        Base.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()
        return

    assert os.environ["AXIS_MODEL_CONTRACT_BACKEND"] == "postgresql"
    database_url = make_url(os.environ["AXIS_MODEL_CONTRACT_POSTGRES_DSN"])
    assert database_url.get_backend_name() == "postgresql"
    database_name = f"axis_model_contract_{uuid4().hex}"
    admin = create_engine(database_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    created = False
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        created = True
        temporary_url = database_url.set(database=database_name)
        # Alembic intentionally prioritizes AXIS_POSTGRES_DSN over config values.
        # Override it only in this process while migrating the fresh database.
        with patch.dict(
            os.environ,
            {
                "AXIS_POSTGRES_DSN": temporary_url.render_as_string(hide_password=False),
            },
        ):
            upgrade(Config("alembic.ini"), "head")
        engine = create_engine(temporary_url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        try:
            if created:
                with admin.connect() as connection:
                    connection.execute(text(f'DROP DATABASE "{database_name}"'))
        finally:
            admin.dispose()


@pytest.fixture
def factory(contract_engine):
    return sessionmaker(bind=contract_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(params=[AxisPersistenceRepository, ModelRepository], ids=["facade", "aggregate"])
def repository_type(request):
    return request.param


@pytest.fixture
def tenant_id():
    return f"model_contract_{uuid4().hex}"


def endpoint(tenant_id, endpoint_id="endpoint", **changes):
    values = dict(
        tenant_id=tenant_id,
        endpoint_id=endpoint_id,
        display_name="Contract model",
        provider_type="self_hosted_openai_compatible",
        hosting_boundary="self_hosted",
        base_url="http://127.0.0.1:65534/v1",
        default_model="contract-model",
        task_types=["summarization"],
        created_by="contract-actor",
        cost_input_per_1k=Decimal("0.123456"),
        cost_output_per_1k=Decimal("0.654321"),
        notes=["Registered by the contract suite."],
    )
    return ModelEndpointCreate(**(values | changes))


def invocation(tenant_id, key="invocation", **changes):
    values = dict(
        tenant_id=tenant_id,
        idempotency_key=key,
        task_type="summarization",
        requested_by="contract-actor",
        egress_decision="self_hosted",
        prompt_sha256="a" * 64,
        route_decision={"endpoint_id": "endpoint"},
        permission_decision={"allowed": True},
        notes=["Requested."],
    )
    return ModelInvocationCreate(**(values | changes))


def audit(tenant_id):
    return AuditEventCreate(
        tenant_id=tenant_id,
        actor_id="contract-actor",
        event_type="model.contract",
        payload={"source": "model-persistence-contract"},
    )


def test_endpoint_reads_are_tenant_scoped_ordered_and_filtered(factory, repository_type, tenant_id):
    other = tenant_id + "_other"
    with session_scope(factory) as session:
        repository = repository_type(session)
        repository.create_model_endpoint(endpoint(tenant_id, "z-endpoint"))
        repository.create_model_endpoint(endpoint(tenant_id, "a-endpoint", status="disabled"))
        repository.create_model_endpoint(endpoint(other, "a-endpoint"))
    with factory() as session:
        repository = repository_type(session)
        rows = repository.list_model_endpoints(tenant_id)
        assert [row.endpoint_id for row in rows] == ["a-endpoint", "z-endpoint"]
        assert all(row.tenant_id == tenant_id for row in rows)
        assert [
            row.endpoint_id
            for row in repository.list_model_endpoints(
                tenant_id,
                status="enabled",
                limit=1,
            )
        ] == ["z-endpoint"]
        assert repository.list_model_endpoints(tenant_id, limit=1)[0].endpoint_id == "a-endpoint"
        record = repository.get_model_endpoint(tenant_id, "z-endpoint")
        assert record.cost_input_per_1k == Decimal("0.123456")
        assert record.cost_output_per_1k == Decimal("0.654321")
        assert record.task_types == ["summarization"]
        assert repository.get_model_endpoint(other, "z-endpoint") is None


def test_status_update_preserves_notes_and_refuses_other_tenant(
    factory, repository_type, tenant_id
):
    with session_scope(factory) as session:
        repository = repository_type(session)
        repository.create_model_endpoint(endpoint(tenant_id))
        event = AxisPersistenceRepository(session).append_audit_event(audit(tenant_id))
        result = repository.update_model_endpoint_status(
            ModelEndpointStatusUpdate(
                tenant_id=tenant_id,
                endpoint_id="endpoint",
                status="disabled",
                audit_event_id=event.id,
                note="Disabled by contract.",
            )
        )
        assert result.status == "disabled"
        assert result.notes == ["Registered by the contract suite.", "Disabled by contract."]
        assert result.audit_event_id == event.id
        with pytest.raises(PersistenceRecordNotFound, match="Model endpoint not found"):
            repository.update_model_endpoint_status(
                ModelEndpointStatusUpdate(
                    tenant_id=tenant_id + "_other",
                    endpoint_id="endpoint",
                    status="enabled",
                    note="Must not cross tenant scope.",
                )
            )
    with factory() as session:
        assert (
            repository_type(session).get_model_endpoint(tenant_id, "endpoint").status == "disabled"
        )


def test_model_and_audit_writes_share_visibility_and_commit(factory, repository_type, tenant_id):
    with factory() as writer, factory() as observer:
        repository = repository_type(writer)
        endpoint_record = repository.create_model_endpoint(endpoint(tenant_id))
        invocation_record = repository.create_model_invocation(invocation(tenant_id))
        event = AxisPersistenceRepository(writer).append_audit_event(audit(tenant_id))
        other_repository = repository_type(observer)
        assert other_repository.get_model_endpoint(tenant_id, "endpoint") is None
        assert other_repository.get_model_invocation(tenant_id, invocation_record.id) is None
        assert observer.get(AuditEvent, event.id) is None
        observer.rollback()
        writer.commit()
        assert other_repository.get_model_endpoint(tenant_id, "endpoint").id == endpoint_record.id
        assert other_repository.get_model_invocation(tenant_id, invocation_record.id) is not None
        assert observer.get(AuditEvent, event.id) is not None


def test_model_and_audit_writes_roll_back_together(factory, repository_type, tenant_id):
    with pytest.raises(RuntimeError, match="caller cancelled"), session_scope(factory) as session:
        repository = repository_type(session)
        repository.create_model_endpoint(endpoint(tenant_id))
        repository.create_model_invocation(invocation(tenant_id))
        AxisPersistenceRepository(session).append_audit_event(audit(tenant_id))
        raise RuntimeError("caller cancelled")
    with factory() as session:
        repository = repository_type(session)
        assert repository.list_model_endpoints(tenant_id) == []
        assert repository.list_model_invocations(tenant_id) == []
        assert session.scalar(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)) is None


def test_idempotency_is_tenant_scoped_and_savepoint_failure_preserves_audit(
    factory,
    repository_type,
    tenant_id,
):
    with session_scope(factory) as session:
        repository = repository_type(session)
        first = repository.create_model_invocation(invocation(tenant_id))
        other = repository.create_model_invocation(invocation(tenant_id + "_other"))
        event = AxisPersistenceRepository(session).append_audit_event(audit(tenant_id))
        with pytest.raises(IntegrityError), session.begin_nested():
            repository.create_model_invocation(invocation(tenant_id))
        assert (
            repository.get_model_invocation_by_idempotency_key(tenant_id, "invocation").id
            == first.id
        )
        assert repository.get_model_invocation(tenant_id, other.id) is None
        assert repository.get_model_invocation_by_idempotency_key(tenant_id, "missing") is None
    with factory() as session:
        assert session.get(AuditEvent, event.id) is not None
        assert len(repository_type(session).list_model_invocations(tenant_id)) == 1


def test_keyset_continuation_orders_timestamp_ties_without_crossing_tenants(
    factory,
    repository_type,
    tenant_id,
):
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    with session_scope(factory) as session:
        repository = repository_type(session)
        records = []
        for index in (1, 3, 2):
            record = repository.create_model_invocation(invocation(tenant_id, key=f"key-{index}"))
            record.created_at = timestamp
            records.append(record)
        outsider = repository.create_model_invocation(invocation(tenant_id + "_other"))
        outsider.created_at = timestamp
    expected = sorted([record.id for record in records], reverse=True)
    with factory() as session:
        repository = repository_type(session)
        first = repository.list_model_invocations(tenant_id, limit=2)
        assert [row.id for row in first] == expected[:2]
        continuation = repository.list_model_invocations(
            tenant_id,
            cursor_created_at=first[-1].created_at,
            cursor_row_id=first[-1].id,
            limit=2,
        )
        assert [row.id for row in continuation] == expected[2:]
        assert (
            repository.list_model_invocations(
                tenant_id,
                cursor_created_at=continuation[-1].created_at,
                cursor_row_id=continuation[-1].id,
            )
            == []
        )


def test_result_update_roundtrips_and_keeps_optional_notes(factory, repository_type, tenant_id):
    with session_scope(factory) as session:
        repository = repository_type(session)
        record = repository.create_model_invocation(invocation(tenant_id))
        result = repository.record_model_invocation_result(
            ModelInvocationResultRecord(
                tenant_id=tenant_id,
                invocation_id=record.id,
                status="completed",
                input_tokens=20,
                output_tokens=12,
                latency_ms=25,
                estimated_cost_eur=Decimal("0.000123"),
                response_sha256="b" * 64,
                provider_request_ref="contract:request",
                notes=["Completed."],
            )
        )
        assert result.notes == ["Completed."]
        repository.record_model_invocation_result(
            ModelInvocationResultRecord(
                tenant_id=tenant_id,
                invocation_id=record.id,
                status="completed",
                input_tokens=20,
                output_tokens=12,
                latency_ms=25,
                estimated_cost_eur=Decimal("0.000123"),
                response_sha256="b" * 64,
                provider_request_ref="contract:request",
            )
        )
        with pytest.raises(PersistenceRecordNotFound, match="Model invocation not found"):
            repository.record_model_invocation_result(
                ModelInvocationResultRecord(
                    tenant_id=tenant_id + "_other",
                    invocation_id=record.id,
                    status="completed",
                )
            )
    with factory() as session:
        persisted = repository_type(session).get_model_invocation(tenant_id, record.id)
        assert (persisted.input_tokens, persisted.output_tokens, persisted.latency_ms) == (
            20,
            12,
            25,
        )
        assert persisted.estimated_cost_eur == Decimal("0.000123")
        assert persisted.notes == ["Completed."]
        assert persisted.response_sha256 == "b" * 64
        assert persisted.provider_request_ref == "contract:request"
        assert persisted.route_decision == {"endpoint_id": "endpoint"}
        assert persisted.permission_decision == {"allowed": True}


def test_result_mutation_remains_rollbackable(factory, repository_type, tenant_id):
    with session_scope(factory) as session:
        record = repository_type(session).create_model_invocation(invocation(tenant_id))
    with factory() as session:
        repository_type(session).record_model_invocation_result(
            ModelInvocationResultRecord(
                tenant_id=tenant_id,
                invocation_id=record.id,
                status="completed",
                input_tokens=100,
            )
        )
        session.rollback()
    with factory() as session:
        result = session.get(ModelInvocation, record.id)
        assert result.status == "requested"
        assert result.input_tokens == 0
