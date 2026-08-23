"""Scheduled connector live-sync lifecycle tests (no live Temporal).

Two layers, both on the in-memory fake pattern:

* the workflow orchestration (:func:`orchestrate_scheduled_live_sync`) driven
  by a scripted activity port — claim-conflict skip, release reasons on
  completion/failure/activity error, no release without a held claim;
* the real DB-owning activities on SQLite + a tmp-path CSV dropzone, driven by
  the same orchestrator — full claim → batches → checkpoints → release
  lifecycle, resume from a committed checkpoint, claim-conflict skip against a
  racing worker, and the failure path releasing the claim.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from runpy import run_path

import pytest
from axis_api.config import Settings
from axis_api.connector_execution import (
    ConnectorLiveSyncBatchRequest,
    ConnectorLiveSyncBatchResult,
    ConnectorLiveSyncPlan,
    ConnectorLiveSyncPlanRequest,
    ConnectorLiveSyncRecord,
)
from axis_api.connector_manifests import (
    ConnectorManifestCreateRequest,
    ConnectorManifestLifecycleRequest,
    record_demo_connector_manifest,
    transition_demo_connector_manifest_lifecycle,
)
from axis_api.connector_runs import (
    ConnectorRunCreateRequest,
    ConnectorRunDispatchRequest,
    ConnectorRunSyncExecutionRequest,
    ConnectorSyncCheckpointClaimRequest,
    claim_connector_sync_checkpoint,
    dispatch_demo_connector_sync,
    execute_demo_connector_sync,
    record_demo_connector_run,
)
from axis_api.db import session_scope
from axis_api.models import Base, utc_now
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialHandleCreate,
    ConnectorCredentialLeaseCreate,
    DemoReferenceRecordCreate,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from temporalio.exceptions import ActivityError

from axis_worker.connector_live_sync_activities import (
    CLAIM_ACTIVITY,
    EXECUTE_ACTIVITY,
    LIST_CANDIDATES_ACTIVITY,
    RELEASE_ACTIVITY,
    SCHEDULED_LIVE_SYNC_WORKER_ACTOR,
    ConnectorLiveSyncActivities,
)
from axis_worker.workflows.connector_live_sync_workflows import (
    RELEASE_REASON_COMPLETED,
    RELEASE_REASON_FAILED,
    orchestrate_scheduled_live_sync,
)

pytestmark = pytest.mark.asyncio

TENANT_ID = "tenant_demo_manufacturing"
FILE_CSV_CONNECTOR_ID = "file_csv_manufacturing_assets"
FILE_CSV_LEASE_ID = "lease_file_csv_readonly_20260710"
DROPZONE_FILE_NAME = "dropzone-assets.csv"
DROPZONE_CSV_CONTENT = (
    "asset_id,asset_name,domain,station,risk_level\n"
    "asset_press_1,Press 1,Operations,Line 1,low\n"
    "asset_press_2,Press 2,Operations,Line 1,medium\n"
    "asset_press_3,Press 3,Maintenance,Line 2,low\n"
    "asset_press_4,Press 4,Maintenance,Line 2,high\n"
    "asset_press_5,Press 5,Quality,Line 3,low\n"
)
REGISTRY_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "api"
    / "migrations"
    / "versions"
    / "0023_connector_registry_reference.py"
)


# ---------------------------------------------------------------------------
# Orchestrator unit tests with a scripted in-memory activity port
# ---------------------------------------------------------------------------


class ScriptedActivityPort:
    def __init__(self, results: dict[str, list[dict] | dict | Exception]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict | None]] = []

    async def run(self, activity_name: str, payload: dict | None = None) -> dict:
        self.calls.append((activity_name, payload))
        result = self.results[activity_name]
        if isinstance(result, list):
            result = result.pop(0)
        if isinstance(result, Exception):
            raise result
        return dict(result)

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


def _candidate() -> dict:
    return {
        "tenant_id": TENANT_ID,
        "connector_id": FILE_CSV_CONNECTOR_ID,
        "run_id": "run_scheduled_live_sync",
        "credential_lease_id": FILE_CSV_LEASE_ID,
    }


def _activity_error() -> ActivityError:
    return ActivityError(
        "activity failed after retries",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type=EXECUTE_ACTIVITY,
        activity_id="1",
        retry_state=None,
    )


async def test_orchestrator_skips_run_on_claim_conflict() -> None:
    port = ScriptedActivityPort(
        {
            LIST_CANDIDATES_ACTIVITY: {
                "status": "candidates_listed",
                "candidates": [_candidate()],
            },
            CLAIM_ACTIVITY: {
                "outcome": "skipped_claim_conflict",
                "checkpoint_id": "chk_run_scheduled_live_sync_batch_1",
                "active_claim_id": "claim_other_worker",
            },
        }
    )

    result = await orchestrate_scheduled_live_sync(port, attempt_seed="seed")

    assert result["outcomes"] == [
        {
            "run_id": "run_scheduled_live_sync",
            "outcome": "skipped_claim_conflict",
            "active_claim_id": "claim_other_worker",
        }
    ]
    # Neither execution nor release runs for a conflicted claim.
    assert port.call_names() == [LIST_CANDIDATES_ACTIVITY, CLAIM_ACTIVITY]


async def test_orchestrator_releases_claim_with_completed_reason() -> None:
    port = ScriptedActivityPort(
        {
            LIST_CANDIDATES_ACTIVITY: {
                "status": "candidates_listed",
                "candidates": [_candidate()],
            },
            CLAIM_ACTIVITY: {
                "outcome": "claimed",
                "checkpoint_id": "chk_run_scheduled_live_sync_batch_1",
                "claim_id": "claim_sched_seed_0",
                "lease_expires_at": "2026-07-10T12:00:00+00:00",
            },
            EXECUTE_ACTIVITY: {"status": "sync_execution_completed"},
            RELEASE_ACTIVITY: {"outcome": "released"},
        }
    )

    result = await orchestrate_scheduled_live_sync(port, attempt_seed="seed")

    assert result["outcomes"] == [
        {"run_id": "run_scheduled_live_sync", "outcome": "sync_execution_completed"}
    ]
    execute_payload = port.calls[2][1]
    assert execute_payload["checkpoint_claim_id"] == "claim_sched_seed_0"
    assert execute_payload["attempt_id"] == "seed_0"
    release_payload = port.calls[3][1]
    assert release_payload["release_reason"] == RELEASE_REASON_COMPLETED


async def test_orchestrator_failure_path_releases_claim() -> None:
    port = ScriptedActivityPort(
        {
            LIST_CANDIDATES_ACTIVITY: {
                "status": "candidates_listed",
                "candidates": [_candidate()],
            },
            CLAIM_ACTIVITY: {
                "outcome": "claimed",
                "checkpoint_id": "chk_run_scheduled_live_sync_batch_1",
                "claim_id": "claim_sched_seed_0",
                "lease_expires_at": "2026-07-10T12:00:00+00:00",
            },
            EXECUTE_ACTIVITY: {"status": "sync_execution_failed"},
            RELEASE_ACTIVITY: {"outcome": "released"},
        }
    )

    result = await orchestrate_scheduled_live_sync(port, attempt_seed="seed")

    assert result["outcomes"][0]["outcome"] == "sync_execution_failed"
    assert port.calls[3][1]["release_reason"] == RELEASE_REASON_FAILED


async def test_orchestrator_releases_claim_when_execute_activity_errors() -> None:
    port = ScriptedActivityPort(
        {
            LIST_CANDIDATES_ACTIVITY: {
                "status": "candidates_listed",
                "candidates": [_candidate()],
            },
            CLAIM_ACTIVITY: {
                "outcome": "claimed",
                "checkpoint_id": "chk_run_scheduled_live_sync_batch_1",
                "claim_id": "claim_sched_seed_0",
                "lease_expires_at": "2026-07-10T12:00:00+00:00",
            },
            EXECUTE_ACTIVITY: _activity_error(),
            RELEASE_ACTIVITY: {"outcome": "released"},
        }
    )

    result = await orchestrate_scheduled_live_sync(port, attempt_seed="seed")

    assert result["outcomes"][0]["outcome"] == "execution_error"
    assert port.call_names()[-1] == RELEASE_ACTIVITY
    assert port.calls[3][1]["release_reason"] == RELEASE_REASON_FAILED


async def test_orchestrator_fresh_run_executes_without_release() -> None:
    port = ScriptedActivityPort(
        {
            LIST_CANDIDATES_ACTIVITY: {
                "status": "candidates_listed",
                "candidates": [_candidate()],
            },
            CLAIM_ACTIVITY: {"outcome": "fresh_run_no_claim"},
            EXECUTE_ACTIVITY: {"status": "sync_execution_completed"},
        }
    )

    result = await orchestrate_scheduled_live_sync(port, attempt_seed="seed")

    assert result["outcomes"][0]["outcome"] == "sync_execution_completed"
    assert RELEASE_ACTIVITY not in port.call_names()


# ---------------------------------------------------------------------------
# Real activities on SQLite + tmp-path dropzone (in-process, no Temporal)
# ---------------------------------------------------------------------------


class ActivityMethodPort:
    """Dispatches orchestrator activity names to the real activity methods."""

    def __init__(self, activities: ConnectorLiveSyncActivities) -> None:
        self._methods = {
            LIST_CANDIDATES_ACTIVITY: activities.list_scheduled_live_sync_candidates,
            CLAIM_ACTIVITY: activities.claim_scheduled_live_sync_checkpoint,
            EXECUTE_ACTIVITY: activities.execute_scheduled_live_sync,
            RELEASE_ACTIVITY: activities.release_scheduled_live_sync_claim,
        }
        self.calls: list[tuple[str, dict | None]] = []

    async def run(self, activity_name: str, payload: dict | None = None) -> dict:
        self.calls.append((activity_name, payload))
        method = self._methods[activity_name]
        if payload is None:
            return await method()
        return await method(payload)

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


class FailingScriptedLiveSyncRuntime:
    """Commits one real-shaped batch then fails, to seed a resumable run."""

    adapter_name = "axis-scripted-live-sync-runtime"

    def plan(self, request: ConnectorLiveSyncPlanRequest) -> ConnectorLiveSyncPlan:
        return ConnectorLiveSyncPlan(
            adapter=self.adapter_name,
            status="live_sync_plan_ready",
            source_mode="file_csv_live_sync",
            source_ref=DROPZONE_FILE_NAME,
            batch_size=2,
            max_records=10,
            external_query_required=False,
        )

    def read_batch(
        self,
        request: ConnectorLiveSyncBatchRequest,
    ) -> ConnectorLiveSyncBatchResult:
        if request.offset == 0:
            return ConnectorLiveSyncBatchResult(
                adapter=self.adapter_name,
                status="live_sync_batch_read",
                records=[
                    ConnectorLiveSyncRecord(
                        node_id="asset_press_1",
                        node_type="asset",
                        ontology_type="manufacturing_asset",
                        field_summary={"asset_name": "Press 1"},
                    ),
                    ConnectorLiveSyncRecord(
                        node_id="asset_press_2",
                        node_type="asset",
                        ontology_type="manufacturing_asset",
                        field_summary={"asset_name": "Press 2"},
                    ),
                ],
                next_offset=2,
                source_exhausted=False,
            )
        return ConnectorLiveSyncBatchResult(
            adapter=self.adapter_name,
            status="live_sync_batch_failed",
            error_code="connector_unavailable",
        )


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "AXIS_CONNECTOR_SYNC_EXECUTION_ENABLED": "true",
        "AXIS_CONNECTOR_LIVE_SYNC_EXECUTION_ENABLED": "true",
        "AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED": "true",
        "AXIS_FILE_CSV_LIVE_SYNC_ROOT": str(tmp_path),
        "AXIS_FILE_CSV_LIVE_SYNC_BATCH_SIZE": "2",
        "AXIS_FILE_CSV_LIVE_SYNC_MAX_ROWS": "10",
    }
    values.update(overrides)
    return Settings(**values)


def _live_capable_registry_payload() -> dict:
    migration = run_path(str(REGISTRY_MIGRATION_PATH))
    payload = deepcopy(migration["CONNECTOR_REGISTRY_PAYLOAD"])
    connector = next(
        item
        for item in payload["connectors"]
        if item["manifest"]["connector_id"] == FILE_CSV_CONNECTOR_ID
    )
    connector["manifest"]["sync_modes"] = [
        *connector["manifest"]["sync_modes"],
        "live_sync",
    ]
    connector["runtime_policy"]["allowed_operations"] = [
        *connector["runtime_policy"]["allowed_operations"],
        "live_query",
        "external_egress",
    ]
    connector["runtime_policy"]["blocked_operations"] = [
        "live_write",
        "credential_capture",
    ]
    connector["runtime_policy"]["egress_policy"] = "approved-live-sync-boundary"
    return payload


def _seed_scheduled_live_sync_run(
    session_factory: sessionmaker[Session],
    *,
    run_id: str,
) -> None:
    payload = _live_capable_registry_payload()
    now = utc_now()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=TENANT_ID,
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=payload,
            )
        )
        connector = next(
            item
            for item in payload["connectors"]
            if item["manifest"]["connector_id"] == FILE_CSV_CONNECTOR_ID
        )
        record_demo_connector_manifest(
            repository,
            ConnectorManifestCreateRequest(
                tenant_id=TENANT_ID,
                registered_by="platform-connector-owner-role",
                manifest=connector["manifest"],
                runtime_policy=connector["runtime_policy"],
                preview_sample=connector["preview_sample"],
                notes=["Manifest registered for scheduled live sync worker tests."],
            ),
        )
        transition_demo_connector_manifest_lifecycle(
            repository,
            FILE_CSV_CONNECTOR_ID,
            ConnectorManifestLifecycleRequest(
                tenant_id=TENANT_ID,
                transitioned_by="platform-connector-owner-role",
                target_status="active_preview",
                actor_scopes=["connectors:manifest:lifecycle"],
                transition_reason="Validated for scheduled live sync tests.",
                evidence_refs=["approval:connector-live-sync-preview"],
            ),
        )
        transition_demo_connector_manifest_lifecycle(
            repository,
            FILE_CSV_CONNECTOR_ID,
            ConnectorManifestLifecycleRequest(
                tenant_id=TENANT_ID,
                transitioned_by="platform-connector-owner-role",
                target_status="active_live",
                actor_scopes=[
                    "connectors:manifest:lifecycle",
                    "connectors:manifest:enable_live",
                ],
                transition_reason="Governed live sync execution gate for tests.",
                evidence_refs=[
                    "approval:connector-live-sync-enable",
                    "policy:live-sync-boundary-reviewed",
                    "credential:live-sync-readonly-lease-policy",
                ],
            ),
        )
        repository.create_connector_credential_handle(
            ConnectorCredentialHandleCreate(
                tenant_id=TENANT_ID,
                connector_id=FILE_CSV_CONNECTOR_ID,
                handle_id="cred_file_csv_readonly",
                display_name="Read-only live sync handle",
                status="active",
                secret_provider="vault-dev",
                secret_ref="vault://axis/demo/cred_file_csv_readonly",
                purpose="read_only_connector_execution",
                rotation_interval_days=30,
                last_rotated_at=now,
                next_rotation_due_at=now,
                created_by="security-owner-role",
                labels={"environment": "demo"},
                notes=["Metadata-only credential handle."],
            )
        )
        repository.create_connector_credential_lease(
            ConnectorCredentialLeaseCreate(
                tenant_id=TENANT_ID,
                connector_id=FILE_CSV_CONNECTOR_ID,
                handle_id="cred_file_csv_readonly",
                lease_id=FILE_CSV_LEASE_ID,
                status="active",
                lease_mode="self_hosted_vault_kms_lease",
                runtime_boundary="axis-credential-lease-broker",
                requested_by="axis-connector-runtime-role",
                lease_purpose="scheduled_connector_sync",
                secret_provider="vault-dev",
                secret_ref="vault://axis/demo/cred_file_csv_readonly",
                vault_kms_policy={"ttl_seconds": "900", "max_ttl_seconds": "1800"},
                permission_decision={
                    "allowed": True,
                    "reason": "all_required_scopes_present",
                },
                lease_result={
                    "adapter": "axis-self-hosted-vault-kms-lease-adapter",
                    "status": "lease_executed",
                    "provider_lease_ref": (
                        f"self-hosted-vault-kms://{TENANT_ID}/{FILE_CSV_LEASE_ID}"
                    ),
                    # Persisted lease records carry the string form, matching
                    # the API's durable lease contract.
                    "secret_material_returned": "false",
                },
                granted_at=now,
                expires_at=now.replace(year=now.year + 1),
                renewal_due_at=now,
                notes=["Active lease for scheduled live sync worker tests."],
            )
        )
        record_demo_connector_run(
            repository,
            ConnectorRunCreateRequest(
                tenant_id=TENANT_ID,
                connector_id=FILE_CSV_CONNECTOR_ID,
                run_id=run_id,
                execution_mode="scheduled_sync_plan",
                requested_by="plant-operations-owner-role",
                credential_handle_ids=["cred_file_csv_readonly"],
                credential_lease_id=FILE_CSV_LEASE_ID,
                schedule_id="schedule_live_sync_hourly",
                schedule_cadence="hourly",
                schedule_timezone="Europe/Rome",
                next_run_at=datetime(2026, 7, 10, 14, 0),
                input_summary={
                    "live_sync_requested": "true",
                    "source_file_name": DROPZONE_FILE_NAME,
                },
            ),
        )
        dispatch_demo_connector_sync(
            repository,
            run_id,
            ConnectorRunDispatchRequest(
                tenant_id=TENANT_ID,
                dispatch_id=f"dispatch_{run_id}",
                dispatched_by="axis-scheduler-role",
                actor_scopes=["connectors:sync:dispatch"],
                credential_lease_id=FILE_CSV_LEASE_ID,
                idempotency_key=f"idem_dispatch_{run_id}",
            ),
        )


def _seed_failed_first_execution(
    session_factory: sessionmaker[Session],
    *,
    run_id: str,
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        failed_run = execute_demo_connector_sync(
            repository,
            run_id,
            ConnectorRunSyncExecutionRequest(
                tenant_id=TENANT_ID,
                execution_id=f"sync_exec_first_{run_id}",
                executed_by=SCHEDULED_LIVE_SYNC_WORKER_ACTOR,
                actor_scopes=["connectors:sync:execute"],
                credential_lease_id=FILE_CSV_LEASE_ID,
                idempotency_key=f"idem_sync_exec_first_{run_id}",
            ),
            live_sync_runtime=FailingScriptedLiveSyncRuntime(),
        )
        assert failed_run.status == "sync_execution_failed"


async def test_activities_full_lifecycle_fresh_run_completes(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    (tmp_path / DROPZONE_FILE_NAME).write_text(DROPZONE_CSV_CONTENT)
    _seed_scheduled_live_sync_run(session_factory, run_id="run_sched_fresh")
    activities = ConnectorLiveSyncActivities(
        _settings(tmp_path), session_factory=session_factory
    )
    port = ActivityMethodPort(activities)

    result = await orchestrate_scheduled_live_sync(port, attempt_seed="tick1")

    assert result["outcomes"] == [
        {"run_id": "run_sched_fresh", "outcome": "sync_execution_completed"}
    ]
    # Fresh runs have no resume checkpoint, so no claim and no release.
    assert RELEASE_ACTIVITY not in port.call_names()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        run = repository.get_connector_run(TENANT_ID, "run_sched_fresh")
        assert run.status == "sync_execution_completed"
        assert run.result_summary["records_read"] == "5"
        batch_checkpoints = repository.list_connector_sync_checkpoints(
            TENANT_ID,
            run_id="run_sched_fresh",
            status="sync_batch_committed",
        )
        assert len(batch_checkpoints) == 3
        proposals = repository.list_connector_ontology_proposals(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
            limit=200,
        )
        assert len(proposals) == 5


async def test_activities_resume_claims_checkpoint_and_releases_on_completion(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    (tmp_path / DROPZONE_FILE_NAME).write_text(DROPZONE_CSV_CONTENT)
    _seed_scheduled_live_sync_run(session_factory, run_id="run_sched_resume")
    _seed_failed_first_execution(session_factory, run_id="run_sched_resume")
    activities = ConnectorLiveSyncActivities(
        _settings(tmp_path), session_factory=session_factory
    )
    port = ActivityMethodPort(activities)

    result = await orchestrate_scheduled_live_sync(port, attempt_seed="tick2")

    assert result["outcomes"] == [
        {"run_id": "run_sched_resume", "outcome": "sync_execution_completed"}
    ]
    assert port.call_names() == [
        LIST_CANDIDATES_ACTIVITY,
        CLAIM_ACTIVITY,
        EXECUTE_ACTIVITY,
        RELEASE_ACTIVITY,
    ]
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        run = repository.get_connector_run(TENANT_ID, "run_sched_resume")
        assert run.status == "sync_execution_completed"
        summary = run.result_summary
        # Resume picks up at the committed offset; total covers all 5 rows.
        assert summary["resume_offset"] == "2"
        assert summary["records_read"] == "5"
        claims = repository.list_connector_sync_checkpoint_claims(
            TENANT_ID,
            checkpoint_id="chk_run_sched_resume_batch_1",
        )
        assert len(claims) == 1
        assert claims[0].claimed_by == SCHEDULED_LIVE_SYNC_WORKER_ACTOR
        assert claims[0].status == "released"
        assert claims[0].release_reason == RELEASE_REASON_COMPLETED


async def test_activities_skip_run_when_other_worker_holds_claim(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    (tmp_path / DROPZONE_FILE_NAME).write_text(DROPZONE_CSV_CONTENT)
    _seed_scheduled_live_sync_run(session_factory, run_id="run_sched_conflict")
    _seed_failed_first_execution(session_factory, run_id="run_sched_conflict")
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        claim_connector_sync_checkpoint(
            repository,
            "chk_run_sched_conflict_batch_1",
            ConnectorSyncCheckpointClaimRequest(
                tenant_id=TENANT_ID,
                claim_id="claim_other_worker",
                claimed_by="axis-other-worker-role",
                actor_scopes=["connectors:sync:checkpoint:claim"],
                idempotency_key="idem_claim_other_worker",
            ),
        )
    activities = ConnectorLiveSyncActivities(
        _settings(tmp_path), session_factory=session_factory
    )
    port = ActivityMethodPort(activities)

    result = await orchestrate_scheduled_live_sync(port, attempt_seed="tick3")

    assert result["outcomes"] == [
        {
            "run_id": "run_sched_conflict",
            "outcome": "skipped_claim_conflict",
            "active_claim_id": "claim_other_worker",
        }
    ]
    assert EXECUTE_ACTIVITY not in port.call_names()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        run = repository.get_connector_run(TENANT_ID, "run_sched_conflict")
        # The conflicted run was not executed and the foreign claim is intact.
        assert run.status == "sync_execution_failed"
        claims = repository.list_connector_sync_checkpoint_claims(
            TENANT_ID,
            checkpoint_id="chk_run_sched_conflict_batch_1",
            status="claimed",
        )
        assert [claim.claim_id for claim in claims] == ["claim_other_worker"]


async def test_activities_failure_path_releases_claim(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    dropzone_file = tmp_path / DROPZONE_FILE_NAME
    dropzone_file.write_text(DROPZONE_CSV_CONTENT)
    _seed_scheduled_live_sync_run(session_factory, run_id="run_sched_failure")
    _seed_failed_first_execution(session_factory, run_id="run_sched_failure")
    # The source disappears before the scheduled resume: the execution fails
    # closed and the worker must still release its claim.
    dropzone_file.unlink()
    activities = ConnectorLiveSyncActivities(
        _settings(tmp_path), session_factory=session_factory
    )
    port = ActivityMethodPort(activities)

    result = await orchestrate_scheduled_live_sync(port, attempt_seed="tick4")

    assert result["outcomes"] == [
        {"run_id": "run_sched_failure", "outcome": "sync_execution_failed"}
    ]
    assert port.call_names()[-1] == RELEASE_ACTIVITY
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        claims = repository.list_connector_sync_checkpoint_claims(
            TENANT_ID,
            checkpoint_id="chk_run_sched_failure_batch_1",
        )
        assert len(claims) == 1
        assert claims[0].status == "released"
        assert claims[0].release_reason == RELEASE_REASON_FAILED


async def test_list_candidates_disabled_without_worker_flag(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    (tmp_path / DROPZONE_FILE_NAME).write_text(DROPZONE_CSV_CONTENT)
    _seed_scheduled_live_sync_run(session_factory, run_id="run_sched_disabled")
    activities = ConnectorLiveSyncActivities(
        _settings(tmp_path, AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED="false"),
        session_factory=session_factory,
    )

    listing = await activities.list_scheduled_live_sync_candidates()

    assert listing == {"status": "scheduled_live_sync_disabled", "candidates": []}
    # And the run stays untouched.
    with session_scope(session_factory) as session:
        run = AxisPersistenceRepository(session).get_connector_run(
            TENANT_ID, "run_sched_disabled"
        )
        assert run.status == "sync_dispatch_deferred"
