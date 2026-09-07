"""Checkpoint CAS against a freshly migrated, disposable PostgreSQL database."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.orm import sessionmaker
from test_connector_s3_ingestion import host  # noqa: F401
from test_connector_s3_source import s3_profile  # noqa: F401
from test_model_persistence_contract import contract_engine  # noqa: F401

from axis_api.db import session_scope
from axis_api.models import ConnectorSourceBinding
from axis_api.persistence import AuditEventCreate, AxisPersistenceRepository, TenantCreate

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AXIS_RUN_S3_POSTGRES") != "1", reason="isolated PostgreSQL opt-in"
    ),
]


def test_concurrent_checkpoint_commit_has_one_winner(contract_engine):  # noqa: F811
    assert contract_engine.dialect.name == "postgresql"
    factory = sessionmaker(contract_engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        repo = AxisPersistenceRepository(session)
        repo.create_tenant(
            TenantCreate(
                tenant_id="s3-cas",
                display_name="CAS fixture",
                description="Isolated",
                created_by="test",
            )
        )
        audit = repo.append_audit_event(
            AuditEventCreate(
                tenant_id="s3-cas", actor_id="test", event_type="fixture.activation", payload={}
            )
        )
        session.add(
            ConnectorSourceBinding(
                tenant_id="s3-cas",
                connector_id="s3_object_storage",
                binding_id="binding",
                asset_id="source:s3_object_storage:default",
                connection_profile_id="profile",
                resource_name="s3.objects_fixture",
                schema_fingerprint="a" * 64,
                credential_lease_id="lease",
                egress_policy_id="policy",
                status="active",
                ingestion_status="pending_ingestion",
                activated_by="test",
                activation_reason="Fixture",
                audit_event_id=audit.id,
                audit_event_type=audit.event_type,
            )
        )
    barrier = Barrier(2)

    def advance(worker):
        with session_scope(factory) as session:
            repo = AxisPersistenceRepository(session)
            initial = repo.get_connector_source_binding("s3-cas", "binding")
            assert initial.source_checkpoint_revision == 0
            assert initial.source_checkpoint is None
            barrier.wait(timeout=10)
            return repo.advance_connector_source_checkpoint(
                tenant_id="s3-cas",
                connector_id="s3_object_storage",
                binding_id="binding",
                expected_revision=0,
                checkpoint={"winner": worker},
            )

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(advance, ["first", "second"])) == [False, True]
    with session_scope(factory) as session:
        repo = AxisPersistenceRepository(session)
        binding = repo.get_connector_source_binding("s3-cas", "binding")
        assert binding.source_checkpoint_revision == 1
        assert binding.source_checkpoint["winner"] in {"first", "second"}
        assert not repo.advance_connector_source_checkpoint(
            tenant_id="different-tenant",
            connector_id="s3_object_storage",
            binding_id="binding",
            expected_revision=1,
            checkpoint={"winner": "foreign"},
        )


@pytest.fixture
def host_engine(contract_engine):  # noqa: F811
    assert contract_engine.dialect.name == "postgresql"
    return contract_engine


def test_postgres_host_failure_rolls_back_checkpoint_batch_and_completion(host, monkeypatch):  # noqa: F811
    from test_connector_s3_ingestion import dispatch, state, submit

    submit(host)
    assert dispatch(host).completed == 1
    before = state(host)
    host.client.objects["approved/private-name.json"] = b"changed"
    submit(host, "failed-commit")
    original = AxisPersistenceRepository.append_audit_event

    def fail(repo, event):
        if event.event_type == "connector.source.extraction.batch_recorded":
            raise OSError("fixture audit unavailable")
        return original(repo, event)

    monkeypatch.setattr(AxisPersistenceRepository, "append_audit_event", fail)
    assert dispatch(host).retried == 1
    after = state(host)
    assert after[:2] == before[:2]
    assert len(after[2]) == len(before[2]) == 1
