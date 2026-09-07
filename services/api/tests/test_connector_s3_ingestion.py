"""S3 host transitions, with real SQL owners and an isolated payload store."""

import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from test_connector_s3_source import MemoryS3, s3_profile  # noqa: F401

from axis_api.config import Settings
from axis_api.connector_postgres_discovery import (
    SOURCE_DISCOVERY_SCOPE,
    ConnectorSourceDiscoveryRequest,
    record_connector_source_discovery,
)
from axis_api.connector_s3_ingestion import S3IngestionRuntime, SourceDiscoveryRouter
from axis_api.connector_secret_resolution import EnvLeaseScopedSecretResolver
from axis_api.connector_source_activation import (
    SOURCE_ACTIVATION_SCOPE,
    ConnectorSourceActivationRequest,
    record_connector_source_activation,
)
from axis_api.connector_source_ingestion import (
    SOURCE_INGESTION_SCOPE,
    ConnectorSourceIngestionSubmission,
    ObservationFreshnessIngestionRuntime,
    SourceIngestionOutboxDispatcher,
    record_connector_source_ingestion_request,
)
from axis_api.db import session_scope
from axis_api.models import Base, ConnectorSourceExtractionBatch
from axis_api.object_storage import LocalObjectStore
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialHandleCreate,
    ConnectorCredentialLeaseCreate,
    ConnectorEgressPolicyCreate,
    ConnectorManifestCreate,
    TenantCreate,
)


@pytest.fixture
def host_engine(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'host.sqlite'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def host(tmp_path, s3_profile, host_engine, request):  # noqa: F811
    engine = host_engine
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    profile = s3_profile.model_copy(
        update={"bucket": f"host-{uuid4().hex}", "tenant_id": f"s3-{uuid4().hex}"}
    )
    tenant = profile.tenant_id
    binding_id = getattr(request, "param", {}).get("binding_id", "binding")
    connector = "s3_object_storage"
    settings = Settings(
        connector_sync_execution_enabled=True,
        source_ingestion_dispatch_enabled=True,
        source_ingestion_extraction_enabled=True,
        s3_source_ingestion_enabled=True,
        s3_source_profiles=[profile],
    )
    client = MemoryS3({"approved/private-name.json": b'{"private-data":"fixture"}'})

    @contextmanager
    def clients(_profile, _credentials):
        # Payload reads must never borrow a SQL connection during network I/O.
        assert engine.pool.checkedout() == 0
        yield client
        assert engine.pool.checkedout() == 0

    store = LocalObjectStore(tmp_path / "payloads")
    runtime = S3IngestionRuntime(
        settings,
        store,
        client_factory=clients,
        resolver=EnvLeaseScopedSecretResolver(
            {
                "AXIS_S3_FIXTURE_CREDENTIALS": json.dumps(
                    {"access_key": "fixture-access", "secret_key": "fixture-private-secret"}
                )
            }
        ),
    )
    with session_scope(factory) as session:
        repo = AxisPersistenceRepository(session)
        repo.create_tenant(
            TenantCreate(
                tenant_id=tenant,
                display_name="S3 fixture",
                description="Isolated",
                created_by="test",
            )
        )
        repo.create_connector_manifest(
            ConnectorManifestCreate(
                tenant_id=tenant,
                connector_id=connector,
                revision_number=1,
                display_name="S3 fixture",
                connector_type="object_storage",
                source_type="s3",
                version="1.0",
                status="active_live",
                registered_by="test",
                runtime_policy={"allowed_operations": ["live_query", "external_egress"]},
            )
        )
        repo.create_connector_credential_handle(
            ConnectorCredentialHandleCreate(
                tenant_id=tenant,
                connector_id=connector,
                handle_id="handle",
                display_name="Fixture",
                secret_provider="env",
                secret_ref=profile.credential_secret_ref,
                purpose="source_ingestion",
                rotation_interval_days=1,
                created_by="test",
            )
        )
        now = datetime.now(UTC)
        repo.create_connector_credential_lease(
            ConnectorCredentialLeaseCreate(
                tenant_id=tenant,
                connector_id=connector,
                handle_id="handle",
                lease_id="lease",
                requested_by="test",
                lease_purpose="source_ingestion",
                secret_provider="env",
                secret_ref=profile.credential_secret_ref,
                permission_decision={"allowed": True, "reason": "fixture"},
                lease_result={
                    "status": "lease_executed",
                    "provider_lease_ref": "fixture://lease",
                    "secret_material_returned": "false",
                },
                granted_at=now,
                expires_at=now + timedelta(hours=1),
                renewal_due_at=now + timedelta(minutes=30),
            )
        )
        repo.create_connector_egress_policy(
            ConnectorEgressPolicyCreate(
                tenant_id=tenant,
                connector_id=connector,
                policy_id="policy",
                display_name="Fixture",
                connection_profile_id=profile.profile_id,
                egress_boundary="approved_private_endpoint",
                policy_mode="approved_private_endpoint",
                runtime_boundary="axis-egress-policy-enforcer",
                private_endpoint_ref=profile.private_endpoint_ref,
                created_by="test",
                policy_document={"approved_endpoint_target_sha256": profile.endpoint_target_sha256},
            )
        )

    # Discovery does metadata I/O in its existing owner; the payload client
    # asserts no checked-out connection only during extraction below.
    @contextmanager
    def discovery_client(_profile, _credentials):
        yield client

    runtime.client_factory = discovery_client
    common = dict(
        tenant_id=tenant,
        connector_id=connector,
        requested_by="test",
        connection_profile_id=profile.profile_id,
        credential_lease_id="lease",
        egress_policy_id="policy",
    )
    with session_scope(factory) as session:
        repo = AxisPersistenceRepository(session)
        found = record_connector_source_discovery(
            repo,
            runtime=SourceDiscoveryRouter(settings, s3=runtime),
            request=ConnectorSourceDiscoveryRequest(
                **common, discovery_id="discover", schema_name="s3"
            ),
            principal_scopes=[SOURCE_DISCOVERY_SCOPE],
        )
        assert found.result.status == "discovery_completed"
        record_connector_source_activation(
            repo,
            request=ConnectorSourceActivationRequest(
                **common,
                activation_id="activate",
                activation_reason="Read fixture prefix",
                selections=[
                    {
                        "binding_id": binding_id,
                        "resource_name": profile.resource_name,
                        "expected_schema_fingerprint": found.result.tables[0].column_fingerprint,
                    }
                ],
            ),
            principal_scopes=[SOURCE_ACTIVATION_SCOPE],
            max_selections=20,
        )
    runtime.client_factory = clients
    value = SimpleNamespace(
        factory=factory,
        engine=engine,
        settings=settings,
        runtime=runtime,
        client=client,
        store=store,
        profile=profile,
        binding_id=binding_id,
    )
    yield value


def submit(host, request_id="request"):
    with session_scope(host.factory) as session:
        return record_connector_source_ingestion_request(
            AxisPersistenceRepository(session),
            submission=ConnectorSourceIngestionSubmission(
                tenant_id=host.profile.tenant_id,
                connector_id="s3_object_storage",
                request_id=request_id,
                requested_by="test",
                reason="Incremental fixture read",
                stage="extract",
                selections=[{"binding_id": host.binding_id}],
            ),
            principal_scopes=[SOURCE_INGESTION_SCOPE],
            max_selections=20,
            settings=host.settings,
        )


def dispatch(host):
    return asyncio.run(
        SourceIngestionOutboxDispatcher(
            settings=host.settings,
            session_factory=host.factory,
            runtime=ObservationFreshnessIngestionRuntime(),
            s3_runtime=host.runtime,
            random_uniform=lambda low, high: low,
        ).run_once()
    )


def state(host):
    with session_scope(host.factory) as session:
        repo = AxisPersistenceRepository(session)
        binding = repo.get_connector_source_binding(host.profile.tenant_id, host.binding_id)
        batches = list(session.scalars(select(ConnectorSourceExtractionBatch)).all())
        return binding.source_checkpoint_revision, binding.source_checkpoint, batches


def test_discover_activate_extract_incremental_replay_and_absence(host):
    submit(host)
    assert dispatch(host).completed == 1
    revision, checkpoint, batches = state(host)
    assert revision == 1 and len(batches) == 1 and batches[0].row_count == 1
    assert "private" not in json.dumps(checkpoint)
    submit(host)  # Same id is a replay, not another read or checkpoint advance.
    assert dispatch(host).claimed == 0
    assert state(host)[0] == 1
    submit(host, "unchanged")
    assert dispatch(host).completed == 1
    assert len(host.client.gets) == 1
    assert state(host)[2][-1].row_count == 0
    host.client.objects.clear()
    submit(host, "absence")
    assert dispatch(host).completed == 1
    assert state(host)[0] == 3
    assert state(host)[1]["inventory"] == {}
    payloads = [json.loads(p.read_text()) for p in host.store.root.rglob("*.json")]
    assert any(p["rows"] and p["rows"][0]["kind"] == "observed_absent" for p in payloads)


@pytest.mark.parametrize(
    "failure",
    [
        "partial",
        "store",
        "audit",
        "revoked",
        "claim",
        "claim_expiry",
        "checkpoint",
        "policy_target",
    ],
)
def test_failures_never_commit_checkpoint_or_batch(host, monkeypatch, failure):
    submit(host)
    if failure == "partial":
        host.client.partial = True
    elif failure == "store":

        def fail(*args):
            assert host.engine.pool.checkedout() == 0
            raise OSError("private-store-details")

        monkeypatch.setattr(host.store, "put_json", fail)
    elif failure == "audit":
        original = AxisPersistenceRepository.append_audit_event

        def fail(repo, event):
            if event.event_type == "connector.source.extraction.batch_recorded":
                raise OSError("private-audit-details")
            return original(repo, event)

        monkeypatch.setattr(AxisPersistenceRepository, "append_audit_event", fail)
    else:
        original = host.store.put_json

        def mutate(key, payload):
            assert host.engine.pool.checkedout() == 0
            with session_scope(host.factory) as session:
                repo = AxisPersistenceRepository(session)
                if failure == "revoked":
                    repo.get_connector_credential_lease(
                        host.profile.tenant_id, "lease"
                    ).status = "revoked"
                elif failure == "checkpoint":
                    repo.get_connector_source_binding(
                        host.profile.tenant_id, "binding"
                    ).source_checkpoint_revision = 5
                elif failure == "policy_target":
                    repo.get_connector_egress_policy(
                        host.profile.tenant_id, "policy"
                    ).policy_document = {"approved_endpoint_target_sha256": "f" * 64}
                else:
                    from axis_api.models import ConnectorSourceIngestionRequest

                    row = session.scalar(select(ConnectorSourceIngestionRequest))
                    if failure == "claim_expiry":
                        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    else:
                        row.claim_token = "different-worker"
            return original(key, payload)

        monkeypatch.setattr(host.store, "put_json", mutate)
    assert dispatch(host).completed == 0
    revision, checkpoint, batches = state(host)
    assert revision == (5 if failure == "checkpoint" else 0)
    assert checkpoint is None and batches == []
    if failure not in {"claim", "claim_expiry"}:
        with session_scope(host.factory) as session:
            row = AxisPersistenceRepository(session).get_connector_source_ingestion_request(
                host.profile.tenant_id, "request"
            )
            assert row.evidence["source_dial_performed"] is True
            assert row.evidence["extraction_performed"] is True
            assert "batches" not in row.evidence


@pytest.mark.parametrize("gate", ["disabled", "tenant", "expired", "policy", "manifest"])
def test_current_authorization_checked_before_payload_read(host, gate):
    submit(host)
    with session_scope(host.factory) as session:
        repo = AxisPersistenceRepository(session)
        tenant = host.profile.tenant_id
        if gate == "disabled":
            host.settings.s3_source_ingestion_enabled = False
        elif gate == "tenant":
            host.settings.s3_source_profiles = [
                host.profile.model_copy(update={"tenant_id": "other"})
            ]
        elif gate == "expired":
            repo.get_connector_credential_lease(tenant, "lease").expires_at = datetime.now(
                UTC
            ) - timedelta(seconds=1)
        elif gate == "policy":
            repo.get_connector_egress_policy(tenant, "policy").status = "revoked"
        else:
            repo.get_connector_manifest(tenant, "s3_object_storage").status = "suspended"
    assert dispatch(host).completed == 0
    assert host.client.gets == []
    assert state(host) == (0, None, [])


def test_operational_retry_reads_again_but_commits_one_payload(host):
    submit(host)
    host.client.partial = True
    assert dispatch(host).retried == 1
    assert state(host) == (0, None, [])
    host.client.partial = False
    with session_scope(host.factory) as session:
        row = AxisPersistenceRepository(session).get_connector_source_ingestion_request(
            host.profile.tenant_id, "request"
        )
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    assert dispatch(host).completed == 1
    assert state(host)[0] == 1 and len(state(host)[2]) == 1
    assert len(host.client.gets) == 2
    persisted = host.engine.url.database
    from pathlib import Path

    database_bytes = Path(persisted).read_bytes()
    for private_value in (b"private-name.json", b"private-data", b"fixture-private-secret"):
        assert private_value not in database_bytes


@pytest.mark.parametrize("host", [{"binding_id": "b" * 180}], indirect=True)
def test_maximum_request_and_binding_ids_produce_bounded_batch_identity(host):
    submit(host, "r" * 180)
    assert dispatch(host).completed == 1
    batch = state(host)[2][0]
    assert len(batch.batch_key) <= 240
    assert batch.binding_id == "b" * 180
    assert batch.request_id == "r" * 180


def test_batch_identity_frames_ids_instead_of_joining_delimiters(host):
    from dataclasses import replace

    from axis_api.connector_s3_ingestion import CompletedS3Extraction
    from axis_api.connector_s3_source import OBJECT_SCHEMA_FINGERPRINT

    with session_scope(host.factory) as session:
        prepared = host.runtime.prepare_selection(
            AxisPersistenceRepository(session),
            tenant_id=host.profile.tenant_id,
            connector_id="s3_object_storage",
            request_id="a:b",
            binding_id=host.binding_id,
            resource_name=host.profile.resource_name,
            pinned_schema_fingerprint=OBJECT_SCHEMA_FINGERPRINT,
            executed_by="test",
        )
    result = host.runtime.extract_prepared(prepared)
    first = CompletedS3Extraction(
        replace(prepared, binding_id="c"), result.outcome, result.checkpoint_state
    )
    second = CompletedS3Extraction(
        replace(prepared, request_id="a", binding_id="b:c"), result.outcome, result.checkpoint_state
    )
    assert first.batch_key != second.batch_key
    assert first.batch_key == replace(first).batch_key
