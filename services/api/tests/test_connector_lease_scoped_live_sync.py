"""Lease-scoped secret resolution + runtime egress enforcement for live sync.

Covers the three fail-closed legs added on top of the existing governed live
sync stack:

* the ``env://`` lease-scoped secret resolver matrix (every blocked branch and
  the resolved success state, with material never leaking into evidence);
* runtime egress enforcement at connect time (the ACTUAL resolved target must
  match the pinned profile hash and the egress-policy evidence);
* full-loop persistence scans proving no secret material lands in any
  persisted run, checkpoint, proposal or audit payload — while flags-off
  behavior stays byte-identical to the static-DSN path.
"""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_connector_live_sync import (  # noqa: E402
    APPROVED_DSN,
    EXTERNAL_DB_CONNECTOR_ID,
    EXTERNAL_DB_LEASE_ID,
    PRIVATE_ENDPOINT_REF,
    TENANT_ID,
    UNAPPROVED_DSN,
    create_dispatched_live_sync_run,
    live_capable_registry_payload,
    seed_connector_registry_reference,
    seed_external_db_egress_policy,
    seed_manifest,
    session_factory,  # noqa: F401  (fixture re-export)
    sync_execution_request,
)

from axis_api.config import Settings
from axis_api.connector_execution import (
    LEASE_SCOPED_RESOLUTION_DSN_SENTINEL,
    LIVE_SYNC_BATCH_FAILED_STATUS,
    LIVE_SYNC_BATCH_READ_STATUS,
    RUNTIME_EGRESS_BLOCK_REASON,
    ConnectorLiveSyncBatchRequest,
    ConnectorSyncExecutionRequest,
    DeferredConnectorLiveSyncRuntime,
    ExternalPostgresLiveQueryProfile,
    SelfHostedConnectorLiveSyncRuntime,
    SelfHostedConnectorSyncExecutionRuntime,
    _secret_retrieval_decision,
    connector_live_sync_runtime_from_settings,
    external_postgres_live_query_profile_from_settings,
    postgres_endpoint_target_sha256,
    runtime_egress_target_block_reason,
)
from axis_api.connector_runs import (
    _sync_checkpoint_result_is_public_safe,
    execute_demo_connector_sync,
)
from axis_api.connector_secret_resolution import (
    RESOLVED_LEASE_SCOPED_SECRET_DECISION,
    SECRET_RESOLUTION_ENV_SECRET_NOT_CONFIGURED,
    SECRET_RESOLUTION_LEASE_NOT_ACTIVE,
    SECRET_RESOLUTION_LEASE_REF_MISSING,
    SECRET_RESOLUTION_MALFORMED_SECRET_REF,
    SECRET_RESOLUTION_PROVIDER_NOT_IMPLEMENTED,
    SECRET_RESOLUTION_RESOLVER_NOT_CONFIGURED,
    SECRET_RESOLUTION_SECRET_MATERIAL_RETURNED,
    SECRET_RESOLUTION_UNKNOWN_PROVIDER,
    SECRET_RESOLUTION_UNSUPPORTED_ACCESS_MODE,
    EnvLeaseScopedSecretResolver,
    SecretResolutionError,
    SecretResolutionRequest,
)
from axis_api.db import session_scope
from axis_api.models import AuditEvent, utc_now
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialHandleCreate,
    ConnectorCredentialLeaseCreate,
)

ENV_SECRET_VAR = "AXIS_TEST_LIVE_SYNC_DSN"
SECRET_DSN = "postgresql://axis_live:sup3r-secret-material@readonly.local:5432/axis_external"
UNAPPROVED_SECRET_DSN = (
    "postgresql://axis_live:sup3r-secret-material@unapproved.local:5432/axis_external"
)
SECRET_MARKERS = ("sup3r-secret-material", "postgresql://", "axis_live:")
EXTERNAL_DB_INPUT_SUMMARY = {
    "live_sync_requested": "true",
    "connection_profile_id": "profile_postgres_ops_readonly",
    "schema_name": "operations",
    "table_name": "production_orders",
    "selected_columns": "order_id,asset_id,work_center,status,risk_level",
    "query_mode": "read_only_snapshot",
    "egress_policy_id": "egress_policy_private_endpoint_ops",
    "egress_boundary": "approved_private_endpoint",
    "credential_access_mode": "lease_scoped_secret_ref",
}


def resolution_request(**overrides) -> SecretResolutionRequest:
    payload = {
        "connector_id": EXTERNAL_DB_CONNECTOR_ID,
        "connection_profile_id": "profile_postgres_ops_readonly",
        "credential_access_mode": "lease_scoped_secret_ref",
        "secret_provider": "env_dev",
        "secret_ref": f"env://{ENV_SECRET_VAR}",
        "lease_status": "lease_executed",
        "lease_ref": f"env://axis/leases/{TENANT_ID}/{EXTERNAL_DB_LEASE_ID}",
        "secret_material_returned": "false",
    }
    payload.update(overrides)
    return SecretResolutionRequest(**payload)


def env_resolver(value: str | None = SECRET_DSN) -> EnvLeaseScopedSecretResolver:
    environ = {} if value is None else {ENV_SECRET_VAR: value}
    return EnvLeaseScopedSecretResolver(environ=environ)


def lease_scoped_profile(
    *,
    approved_dsn: str = APPROVED_DSN,
    row_limit: int = 10,
) -> ExternalPostgresLiveQueryProfile:
    return ExternalPostgresLiveQueryProfile(
        profile_id="profile_postgres_ops_readonly",
        dsn=LEASE_SCOPED_RESOLUTION_DSN_SENTINEL,
        schema_name="operations",
        table_name="production_orders",
        allowed_columns=["order_id", "asset_id", "work_center", "status", "risk_level"],
        private_endpoint_ref=PRIVATE_ENDPOINT_REF,
        endpoint_target_sha256=postgres_endpoint_target_sha256(approved_dsn),
        row_limit=row_limit,
    )


def approved_egress_evidence(approved_dsn: str = APPROVED_DSN) -> dict[str, str]:
    return {
        "egress_policy_evidence_status": "validated",
        "egress_policy_result_status": "egress_policy_approved",
        "egress_policy_mode": "approved_private_endpoint",
        "egress_policy_private_endpoint_ref": PRIVATE_ENDPOINT_REF,
        "egress_policy_endpoint_target_sha256": postgres_endpoint_target_sha256(approved_dsn),
    }


def lease_result_evidence() -> dict:
    return {
        "status": "lease_executed",
        "provider_lease_ref": f"env://axis/leases/{TENANT_ID}/{EXTERNAL_DB_LEASE_ID}",
        "secret_material_returned": "false",
    }


def lease_scoped_live_sync_runtime(
    *,
    resolver: EnvLeaseScopedSecretResolver | None,
    resolution_enabled: bool = True,
    enforcement_enabled: bool = True,
    profile: ExternalPostgresLiveQueryProfile | None = None,
) -> SelfHostedConnectorLiveSyncRuntime:
    return SelfHostedConnectorLiveSyncRuntime(
        external_db_live_sync_enabled=True,
        external_postgres_profile=profile or lease_scoped_profile(),
        external_db_batch_size=2,
        lease_scoped_secret_resolution_enabled=resolution_enabled,
        runtime_egress_enforcement_enabled=enforcement_enabled,
        secret_resolver=resolver,
    )


def external_db_batch_request(
    *,
    offset: int = 0,
    secret_provider: str = "env_dev",
    secret_ref: str = f"env://{ENV_SECRET_VAR}",
    lease_result: dict | None = None,
    egress_policy_evidence: dict[str, str] | None = None,
) -> ConnectorLiveSyncBatchRequest:
    from axis_api.connector_execution import ConnectorLiveSyncFieldMapping

    return ConnectorLiveSyncBatchRequest(
        tenant_id=TENANT_ID,
        connector_id=EXTERNAL_DB_CONNECTOR_ID,
        run_id="run_external_db_lease_scoped",
        execution_id="sync_exec_external_db_lease_scoped",
        offset=offset,
        batch_size=2,
        field_mappings=[
            ConnectorLiveSyncFieldMapping(
                source_column="order_id",
                target_field="node_id",
                ontology_target="production_order",
            ),
        ],
        credential_lease_result=(
            lease_result_evidence() if lease_result is None else lease_result
        ),
        credential_secret_provider=secret_provider,
        credential_secret_ref=secret_ref,
        egress_policy_evidence=(
            approved_egress_evidence()
            if egress_policy_evidence is None
            else egress_policy_evidence
        ),
        input_summary=EXTERNAL_DB_INPUT_SUMMARY,
    )


class CapturingPostgresReader:
    """Stands in for the psycopg read seam and captures the connect profile."""

    def __init__(self, rows_by_offset: dict[int, list[dict[str, str]]] | None = None) -> None:
        self.rows_by_offset = rows_by_offset or {}
        self.calls: list[dict] = []

    def read_batch_rows(self, profile, *, selected_columns, order_column, offset, batch_size,
                        session_hardening_enabled=False):
        self.calls.append(
            {
                "dsn": profile.dsn,
                "offset": offset,
                "batch_size": batch_size,
                "session_hardening_enabled": session_hardening_enabled,
            }
        )
        return self.rows_by_offset.get(offset, [])


def seed_env_secret_credentials(repository: AxisPersistenceRepository) -> None:
    """Active env:// credential handle + lease for the external DB connector."""
    now = utc_now()
    repository.create_connector_credential_handle(
        ConnectorCredentialHandleCreate(
            tenant_id=TENANT_ID,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            display_name="Read-only env-resolved live sync handle",
            status="active",
            secret_provider="env_dev",
            secret_ref=f"env://{ENV_SECRET_VAR}",
            purpose="read_only_connector_execution",
            rotation_interval_days=30,
            last_rotated_at=now,
            next_rotation_due_at=now,
            created_by="security-owner-role",
            labels={"environment": "demo"},
            notes=["Metadata-only credential handle for lease-scoped resolution."],
        )
    )
    repository.create_connector_credential_lease(
        ConnectorCredentialLeaseCreate(
            tenant_id=TENANT_ID,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=EXTERNAL_DB_LEASE_ID,
            status="active",
            lease_mode="provider_specific_vault_kms_lease",
            runtime_boundary="axis-credential-lease-broker",
            requested_by="axis-connector-runtime-role",
            lease_purpose="scheduled_connector_sync",
            secret_provider="env_dev",
            secret_ref=f"env://{ENV_SECRET_VAR}",
            vault_kms_policy={"ttl_seconds": "900", "max_ttl_seconds": "1800"},
            permission_decision={
                "allowed": True,
                "reason": "all_required_scopes_present",
            },
            lease_result={
                "adapter": "axis-provider-specific-vault-kms-lease-adapter",
                "status": "lease_executed",
                "provider_lease_ref": (
                    f"env://axis/leases/{TENANT_ID}/{EXTERNAL_DB_LEASE_ID}"
                ),
                "secret_material_returned": "false",
            },
            granted_at=now,
            expires_at=now.replace(year=now.year + 1),
            renewal_due_at=now,
            notes=["Active env-resolved lease for lease-scoped live sync tests."],
        )
    )


# ---------------------------------------------------------------------------
# Resolver fail-closed matrix
# ---------------------------------------------------------------------------


def test_env_resolver_resolves_active_lease_scoped_secret() -> None:
    resolved = env_resolver().resolve(resolution_request())

    assert resolved.dsn == SECRET_DSN
    assert resolved.provider_profile == "env"
    assert "sup3r-secret-material" not in repr(resolved)
    evidence = resolved.public_evidence()
    assert evidence["secret_retrieval_decision"] == RESOLVED_LEASE_SCOPED_SECRET_DECISION
    assert "sup3r-secret-material" not in json.dumps(evidence)


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        (
            {"credential_access_mode": "raw_secret_value"},
            SECRET_RESOLUTION_UNSUPPORTED_ACCESS_MODE,
        ),
        ({"credential_access_mode": ""}, SECRET_RESOLUTION_UNSUPPORTED_ACCESS_MODE),
        ({"lease_status": "lease_revoked"}, SECRET_RESOLUTION_LEASE_NOT_ACTIVE),
        ({"lease_status": ""}, SECRET_RESOLUTION_LEASE_NOT_ACTIVE),
        ({"lease_ref": ""}, SECRET_RESOLUTION_LEASE_REF_MISSING),
        (
            {"secret_material_returned": "true"},
            SECRET_RESOLUTION_SECRET_MATERIAL_RETURNED,
        ),
        ({"secret_provider": "mystery_provider"}, SECRET_RESOLUTION_UNKNOWN_PROVIDER),
        ({"secret_ref": "vault://axis/demo/handle"}, SECRET_RESOLUTION_MALFORMED_SECRET_REF),
        ({"secret_ref": "env://lower_case_var"}, SECRET_RESOLUTION_MALFORMED_SECRET_REF),
        ({"secret_ref": "env://"}, SECRET_RESOLUTION_MALFORMED_SECRET_REF),
        (
            {"secret_ref": "env://AXIS_OTHER_UNSET_VAR"},
            SECRET_RESOLUTION_ENV_SECRET_NOT_CONFIGURED,
        ),
    ],
)
def test_env_resolver_fails_closed(overrides: dict, expected_reason: str) -> None:
    with pytest.raises(SecretResolutionError) as exc_info:
        env_resolver().resolve(resolution_request(**overrides))

    assert exc_info.value.reason == expected_reason


def test_env_resolver_fails_closed_on_empty_env_value() -> None:
    with pytest.raises(SecretResolutionError) as exc_info:
        env_resolver(value="").resolve(resolution_request())

    assert exc_info.value.reason == SECRET_RESOLUTION_ENV_SECRET_NOT_CONFIGURED


@pytest.mark.parametrize(
    ("secret_provider", "expected_profile"),
    [
        ("vault-dev", "hashicorp_vault"),
        ("hashicorp_vault", "hashicorp_vault"),
        ("aws-secrets-manager", "aws_secrets_manager"),
        ("gcp_secret_manager", "gcp_secret_manager"),
        ("azure-key-vault", "azure_key_vault"),
    ],
)
def test_env_resolver_fails_closed_for_not_implemented_providers(
    secret_provider: str,
    expected_profile: str,
) -> None:
    with pytest.raises(SecretResolutionError) as exc_info:
        env_resolver().resolve(resolution_request(secret_provider=secret_provider))

    assert exc_info.value.reason == SECRET_RESOLUTION_PROVIDER_NOT_IMPLEMENTED
    assert exc_info.value.provider_profile == expected_profile


def test_secret_retrieval_decision_taxonomy_includes_resolved_state() -> None:
    decision = _secret_retrieval_decision(
        preflight_enabled=True,
        policy_preflight_passed=True,
        secret_reference_evidence_valid=True,
        lease_evidence_valid=True,
        secret_material_returned="false",
        lease_scoped_secret_resolution=RESOLVED_LEASE_SCOPED_SECRET_DECISION,
    )
    assert decision == RESOLVED_LEASE_SCOPED_SECRET_DECISION
    # Empty resolution outcome preserves today's reference-only decision.
    assert (
        _secret_retrieval_decision(
            preflight_enabled=True,
            policy_preflight_passed=True,
            secret_reference_evidence_valid=True,
            lease_evidence_valid=True,
            secret_material_returned="false",
        )
        == "lease_scoped_reference_only"
    )


# ---------------------------------------------------------------------------
# Batch runtime: resolution + runtime egress enforcement at the connect seam
# ---------------------------------------------------------------------------


def test_batch_read_uses_resolved_dsn_and_hardened_session(monkeypatch) -> None:
    reader = CapturingPostgresReader({0: [{"order_id": "po-1"}]})
    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_batch_rows",
        reader.read_batch_rows,
    )
    runtime = lease_scoped_live_sync_runtime(resolver=env_resolver())

    batch = runtime.read_batch(external_db_batch_request())

    assert batch.status == LIVE_SYNC_BATCH_READ_STATUS
    assert reader.calls[0]["dsn"] == SECRET_DSN
    assert reader.calls[0]["session_hardening_enabled"] is True
    assert batch.evidence_summary["secret_retrieval_decision"] == (
        RESOLVED_LEASE_SCOPED_SECRET_DECISION
    )
    assert batch.evidence_summary["runtime_egress_enforcement"] == "enforced_target_match"
    assert "sup3r-secret-material" not in json.dumps(batch.model_dump(mode="json"))


def test_batch_read_flags_off_uses_static_profile_dsn(monkeypatch) -> None:
    reader = CapturingPostgresReader({0: [{"order_id": "po-1"}]})
    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_batch_rows",
        reader.read_batch_rows,
    )
    static_profile = lease_scoped_profile().model_copy(update={"dsn": APPROVED_DSN})
    runtime = lease_scoped_live_sync_runtime(
        resolver=None,
        resolution_enabled=False,
        enforcement_enabled=False,
        profile=static_profile,
    )

    batch = runtime.read_batch(external_db_batch_request())

    assert batch.status == LIVE_SYNC_BATCH_READ_STATUS
    assert reader.calls[0]["dsn"] == APPROVED_DSN
    assert reader.calls[0]["session_hardening_enabled"] is False
    assert batch.evidence_summary == {}


def test_batch_read_fails_closed_when_env_secret_missing(monkeypatch) -> None:
    reader = CapturingPostgresReader()
    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_batch_rows",
        reader.read_batch_rows,
    )
    runtime = lease_scoped_live_sync_runtime(resolver=env_resolver(value=None))

    batch = runtime.read_batch(external_db_batch_request())

    assert batch.status == LIVE_SYNC_BATCH_FAILED_STATUS
    assert batch.error_code == f"blocked_{SECRET_RESOLUTION_ENV_SECRET_NOT_CONFIGURED}"
    assert reader.calls == []


def test_batch_read_fails_closed_when_resolver_not_configured(monkeypatch) -> None:
    reader = CapturingPostgresReader()
    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_batch_rows",
        reader.read_batch_rows,
    )
    runtime = lease_scoped_live_sync_runtime(resolver=None)

    batch = runtime.read_batch(external_db_batch_request())

    assert batch.status == LIVE_SYNC_BATCH_FAILED_STATUS
    assert batch.error_code == f"blocked_{SECRET_RESOLUTION_RESOLVER_NOT_CONFIGURED}"
    assert reader.calls == []


def test_batch_read_blocks_runtime_egress_target_mismatch(monkeypatch) -> None:
    reader = CapturingPostgresReader()
    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_batch_rows",
        reader.read_batch_rows,
    )
    runtime = lease_scoped_live_sync_runtime(
        resolver=env_resolver(value=UNAPPROVED_SECRET_DSN),
    )

    batch = runtime.read_batch(external_db_batch_request())

    assert batch.status == LIVE_SYNC_BATCH_FAILED_STATUS
    assert batch.error_code == f"blocked_{RUNTIME_EGRESS_BLOCK_REASON}"
    assert batch.error_code == "blocked_runtime_egress_target_mismatch"
    # Fail closed BEFORE any connection is attempted.
    assert reader.calls == []


def test_runtime_egress_block_reason_requires_evidence_match() -> None:
    profile = lease_scoped_profile()
    assert (
        runtime_egress_target_block_reason(
            dsn=SECRET_DSN,
            profile=profile,
            egress_policy_evidence=approved_egress_evidence(),
        )
        is None
    )
    # Evidence hash pinned to a different endpoint fails closed.
    assert (
        runtime_egress_target_block_reason(
            dsn=SECRET_DSN,
            profile=profile,
            egress_policy_evidence=approved_egress_evidence(UNAPPROVED_DSN),
        )
        == RUNTIME_EGRESS_BLOCK_REASON
    )
    # Unparseable DSNs fail closed too.
    assert (
        runtime_egress_target_block_reason(
            dsn="not-a-dsn",
            profile=profile,
            egress_policy_evidence=approved_egress_evidence(),
        )
        == RUNTIME_EGRESS_BLOCK_REASON
    )


# ---------------------------------------------------------------------------
# Sync-execution live read path (preflight + live read)
# ---------------------------------------------------------------------------


def live_read_sync_execution_request(**overrides) -> ConnectorSyncExecutionRequest:
    payload = {
        "tenant_id": TENANT_ID,
        "connector_id": EXTERNAL_DB_CONNECTOR_ID,
        "run_id": "run_external_db_live_read_lease_scoped",
        "execution_id": "sync_exec_external_db_live_read_lease_scoped",
        "runtime_boundary": "axis-connector-sandbox",
        "executed_by": "axis-sync-worker-role",
        "credential_handle_ids": ["cred_external_db_readonly"],
        "credential_lease_id": EXTERNAL_DB_LEASE_ID,
        "credential_lease_mode": "provider_specific_vault_kms_lease",
        "credential_lease_runtime_boundary": "axis-credential-lease-broker",
        "credential_lease_result": lease_result_evidence(),
        "credential_secret_provider": "env_dev",
        "credential_secret_ref": f"env://{ENV_SECRET_VAR}",
        "egress_policy_evidence": {
            **approved_egress_evidence(),
            "egress_policy_runtime_boundary": "axis-egress-policy-enforcer",
            "egress_policy_ref": (
                f"self-hosted-egress-policy://{TENANT_ID}/egress_policy_private_endpoint_ops"
            ),
            "egress_policy_scope": (
                f"{EXTERNAL_DB_CONNECTOR_ID}:profile_postgres_ops_readonly"
            ),
        },
        "schedule_id": "schedule_external_db_orders_hourly",
        "schedule_ref": f"deferred-sync://{TENANT_ID}/schedule",
        "dispatch_id": "dispatch_external_db_live_read_lease_scoped",
        "dispatch_ref": "deferred-sync-dispatch://tenant/run/dispatch",
        "idempotency_key": "idem_sync_exec_external_db_live_read_lease_scoped",
        "input_summary": {
            **EXTERNAL_DB_INPUT_SUMMARY,
            "live_query_requested": "true",
            "live_query_execute": "true",
        },
    }
    payload.update(overrides)
    return ConnectorSyncExecutionRequest(**payload)


def lease_scoped_sync_execution_runtime(
    *,
    resolver: EnvLeaseScopedSecretResolver | None,
) -> SelfHostedConnectorSyncExecutionRuntime:
    return SelfHostedConnectorSyncExecutionRuntime(
        external_db_sync_enabled=True,
        external_db_live_query_preflight_enabled=True,
        external_db_live_query_execution_enabled=True,
        external_postgres_live_query_profile=lease_scoped_profile(),
        lease_scoped_secret_resolution_enabled=True,
        runtime_egress_enforcement_enabled=True,
        secret_resolver=resolver,
    )


def test_live_read_resolves_secret_and_enforces_egress(monkeypatch) -> None:
    captured: dict = {}

    def fake_read_rows(profile, *, selected_columns, session_hardening_enabled=False):
        captured["dsn"] = profile.dsn
        captured["session_hardening_enabled"] = session_hardening_enabled
        return 3

    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_rows",
        fake_read_rows,
    )
    runtime = lease_scoped_sync_execution_runtime(resolver=env_resolver())

    result = runtime.execute(live_read_sync_execution_request())

    assert result.status == "sync_execution_completed"
    assert captured["dsn"] == SECRET_DSN
    assert captured["session_hardening_enabled"] is True
    summary = result.result_summary
    assert summary["secret_retrieval_decision"] == RESOLVED_LEASE_SCOPED_SECRET_DECISION
    assert summary["runtime_egress_enforcement"] == "enforced_target_match"
    assert summary["credential_material_returned"] == "false"
    assert _sync_checkpoint_result_is_public_safe(summary)
    assert "sup3r-secret-material" not in json.dumps(result.model_dump(mode="json"))


def test_live_read_blocks_when_secret_resolution_fails(monkeypatch) -> None:
    def unexpected_read(*args, **kwargs):
        raise AssertionError("No external query may start after a resolution block.")

    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_rows",
        unexpected_read,
    )
    runtime = lease_scoped_sync_execution_runtime(resolver=env_resolver(value=None))

    result = runtime.execute(live_read_sync_execution_request())

    assert result.status == "sync_execution_live_query_blocked"
    summary = result.result_summary
    assert summary["live_query_execution_status"] == (
        f"blocked_{SECRET_RESOLUTION_ENV_SECRET_NOT_CONFIGURED}"
    )
    assert summary["secret_retrieval_decision"] == (
        f"blocked_{SECRET_RESOLUTION_ENV_SECRET_NOT_CONFIGURED}"
    )
    assert summary["external_query_started"] == "false"


def test_live_read_blocks_runtime_egress_target_mismatch(monkeypatch) -> None:
    def unexpected_read(*args, **kwargs):
        raise AssertionError("No external query may start after an egress block.")

    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_rows",
        unexpected_read,
    )
    runtime = lease_scoped_sync_execution_runtime(
        resolver=env_resolver(value=UNAPPROVED_SECRET_DSN),
    )

    result = runtime.execute(live_read_sync_execution_request())

    assert result.status == "sync_execution_live_query_blocked"
    summary = result.result_summary
    assert summary["live_query_execution_status"] == (
        "blocked_runtime_egress_target_mismatch"
    )
    assert summary["runtime_egress_enforcement"] == (
        "blocked_runtime_egress_target_mismatch"
    )
    assert summary["external_query_started"] == "false"


# ---------------------------------------------------------------------------
# Full governed loop: persistence + stage audit scans
# ---------------------------------------------------------------------------


def _scan_persisted_payloads_for_markers(session: Session) -> list[str]:
    leaks: list[str] = []
    repository = AxisPersistenceRepository(session)
    for event in session.scalars(select(AuditEvent)):
        serialized = json.dumps(event.payload, default=str)
        for marker in SECRET_MARKERS:
            if marker in serialized:
                leaks.append(f"audit:{event.event_type}:{marker}")
    for run in repository.list_connector_runs(TENANT_ID, limit=200):
        serialized = json.dumps(run.result_summary, default=str) + json.dumps(
            run.input_summary, default=str
        )
        for marker in SECRET_MARKERS:
            if marker in serialized:
                leaks.append(f"run:{run.run_id}:{marker}")
    for checkpoint in repository.list_connector_sync_checkpoints(TENANT_ID):
        serialized = json.dumps(checkpoint.result_summary, default=str) + json.dumps(
            checkpoint.cursor, default=str
        )
        for marker in SECRET_MARKERS:
            if marker in serialized:
                leaks.append(f"checkpoint:{checkpoint.checkpoint_id}:{marker}")
    for proposal in repository.list_connector_ontology_proposals(
        tenant_id=TENANT_ID,
        connector_id=EXTERNAL_DB_CONNECTOR_ID,
        limit=200,
    ):
        serialized = json.dumps(proposal.field_summary, default=str)
        for marker in SECRET_MARKERS:
            if marker in serialized:
                leaks.append(f"proposal:{proposal.proposal_id}:{marker}")
    return leaks


def _external_rows(offset: int) -> list[dict[str, str]]:
    all_rows = [
        {"order_id": f"po-100{index}"} for index in range(3)
    ]
    return all_rows[offset : offset + 2]


def test_execute_live_sync_resolves_env_secret_without_persisting_material(
    session_factory: sessionmaker[Session],  # noqa: F811
    monkeypatch,
) -> None:
    payload = live_capable_registry_payload(EXTERNAL_DB_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    reader = CapturingPostgresReader({0: _external_rows(0), 2: _external_rows(2)})
    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_batch_rows",
        reader.read_batch_rows,
    )
    runtime = lease_scoped_live_sync_runtime(resolver=env_resolver())

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, EXTERNAL_DB_CONNECTOR_ID, payload)
        seed_env_secret_credentials(repository)
        seed_external_db_egress_policy(repository)
        create_dispatched_live_sync_run(
            repository,
            run_id="run_external_db_lease_scoped",
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=EXTERNAL_DB_LEASE_ID,
            input_summary=EXTERNAL_DB_INPUT_SUMMARY,
        )

        run = execute_demo_connector_sync(
            repository,
            "run_external_db_lease_scoped",
            sync_execution_request(
                execution_id="sync_exec_lease_scoped",
                idempotency_key="idem_sync_exec_lease_scoped",
                lease_id=EXTERNAL_DB_LEASE_ID,
            ),
            live_sync_runtime=runtime,
        )
        checkpoints = repository.list_connector_sync_checkpoints(
            TENANT_ID,
            run_id="run_external_db_lease_scoped",
            status="sync_batch_committed",
        )
        leaks = _scan_persisted_payloads_for_markers(session)

    assert run.status == "sync_execution_completed"
    summary = run.sync_execution_result.result_summary
    assert summary["records_read"] == "3"
    assert summary["secret_retrieval_decision"] == RESOLVED_LEASE_SCOPED_SECRET_DECISION
    assert summary["runtime_egress_enforcement"] == "enforced_target_match"
    # The resolver saw the real DSN at the connect seam...
    assert all(call["dsn"] == SECRET_DSN for call in reader.calls)
    assert all(call["session_hardening_enabled"] for call in reader.calls)
    # ...but zero secret material reached any persisted or audited payload.
    assert leaks == []
    assert len(checkpoints) == 2
    for checkpoint in checkpoints:
        assert _sync_checkpoint_result_is_public_safe(checkpoint.result_summary)
        assert checkpoint.result_summary["secret_retrieval_decision"] == (
            RESOLVED_LEASE_SCOPED_SECRET_DECISION
        )


def test_execute_live_sync_blocks_runtime_egress_mismatch_with_stage_audit(
    session_factory: sessionmaker[Session],  # noqa: F811
    monkeypatch,
) -> None:
    payload = live_capable_registry_payload(EXTERNAL_DB_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    reader = CapturingPostgresReader()
    monkeypatch.setattr(
        "axis_api.connector_execution._read_external_postgres_batch_rows",
        reader.read_batch_rows,
    )
    runtime = lease_scoped_live_sync_runtime(
        resolver=env_resolver(value=UNAPPROVED_SECRET_DSN),
    )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, EXTERNAL_DB_CONNECTOR_ID, payload)
        seed_env_secret_credentials(repository)
        seed_external_db_egress_policy(repository)
        create_dispatched_live_sync_run(
            repository,
            run_id="run_external_db_egress_block",
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=EXTERNAL_DB_LEASE_ID,
            input_summary=EXTERNAL_DB_INPUT_SUMMARY,
        )

        run = execute_demo_connector_sync(
            repository,
            "run_external_db_egress_block",
            sync_execution_request(
                execution_id="sync_exec_egress_block",
                idempotency_key="idem_sync_exec_egress_block",
                lease_id=EXTERNAL_DB_LEASE_ID,
            ),
            live_sync_runtime=runtime,
        )
        failed_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_failed",
        )
        leaks = _scan_persisted_payloads_for_markers(session)

    assert run.status == "sync_execution_failed"
    summary = run.sync_execution_result.result_summary
    assert summary["sync_error_code"] == "blocked_runtime_egress_target_mismatch"
    assert summary["external_query_started"] == "false"
    # Blocked before any connection attempt and stage-audited like other blocks.
    assert reader.calls == []
    assert len(failed_events) == 1
    assert leaks == []


# ---------------------------------------------------------------------------
# Settings wiring: flags-off byte-identical construction
# ---------------------------------------------------------------------------


def test_profile_from_settings_prefers_static_dsn_fallback() -> None:
    settings = Settings(
        AXIS_EXTERNAL_DB_LIVE_QUERY_DSN=APPROVED_DSN,
        AXIS_EXTERNAL_DB_LEASE_SCOPED_SECRET_RESOLUTION_ENABLED="true",
    )
    profile = external_postgres_live_query_profile_from_settings(settings)
    assert profile is not None
    assert profile.dsn == APPROVED_DSN
    assert profile.endpoint_target_sha256 == postgres_endpoint_target_sha256(APPROVED_DSN)


def test_profile_from_settings_supports_pinned_target_without_static_dsn() -> None:
    pinned = postgres_endpoint_target_sha256(APPROVED_DSN)
    settings = Settings(
        AXIS_EXTERNAL_DB_LEASE_SCOPED_SECRET_RESOLUTION_ENABLED="true",
        AXIS_EXTERNAL_DB_LIVE_QUERY_ENDPOINT_TARGET_SHA256=pinned,
    )
    profile = external_postgres_live_query_profile_from_settings(settings)
    assert profile is not None
    assert profile.dsn == LEASE_SCOPED_RESOLUTION_DSN_SENTINEL
    assert profile.endpoint_target_sha256 == pinned
    # Without the resolution flag the pinned hash alone builds no profile.
    assert (
        external_postgres_live_query_profile_from_settings(
            Settings(AXIS_EXTERNAL_DB_LIVE_QUERY_ENDPOINT_TARGET_SHA256=pinned)
        )
        is None
    )


def test_live_sync_runtime_from_settings_flags_off_stays_deferred() -> None:
    assert isinstance(
        connector_live_sync_runtime_from_settings(Settings()),
        DeferredConnectorLiveSyncRuntime,
    )
    runtime = connector_live_sync_runtime_from_settings(
        Settings(
            AXIS_CONNECTOR_SYNC_EXECUTION_ENABLED="true",
            AXIS_CONNECTOR_LIVE_SYNC_EXECUTION_ENABLED="true",
        )
    )
    assert isinstance(runtime, SelfHostedConnectorLiveSyncRuntime)
    assert runtime.lease_scoped_secret_resolution_enabled is False
    assert runtime.runtime_egress_enforcement_enabled is False
    assert runtime.secret_resolver is None
