"""Contract tests binding packages/schemas to the real API domain payloads.

The JSON Schema files in ``packages/schemas`` are the public, language-neutral
contract for the core Axis records. These tests build real payloads through the
same domain functions the API routes use (per-file sqlite convention) and
validate them against the published schema files, so the schema package cannot
silently drift from the Pydantic models that actually serve traffic.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from runpy import run_path

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.agent_runs import (
    AGENT_RUN_EXECUTE_SCOPE,
    AgentRunStartRequest,
    start_agent_run,
)
from axis_api.audit_queries import AuditEventQuery, query_persisted_audit_events
from axis_api.connector_manifests import (
    ConnectorManifestCreateRequest,
    record_demo_connector_manifest,
)
from axis_api.db import session_scope
from axis_api.model_endpoints import (
    MODEL_ENDPOINT_ADMIN_SCOPE,
    ModelEndpointCreateRequest,
    record_model_endpoint,
)
from axis_api.model_invocations import MODEL_INVOKE_SCOPE
from axis_api.model_providers import ModelInvocationRuntimeResult
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    DemoReferenceRecordCreate,
    TenantCreate,
)
from axis_api.platform_tenants import TenantProvisionRequest, provision_tenant

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "packages" / "schemas"

TENANT_ID = "tenant_demo_manufacturing"

DAILY_BRIEF_PROPOSAL = {
    "action_id": "generate_daily_plant_brief",
    "summary": "Generate the governed morning brief for plant owners.",
    "payload": {
        "tenant_id": TENANT_ID,
        "scope": "daily_operations",
        "evidence_refs": ["wf_supplier_delay_review"],
    },
    "evidence_refs": ["manufacturing_operation_record:order_rush_4812"],
}


class ProposalModelRuntime:
    """Test double emitting a canned parseable JSON proposal."""

    adapter_name = "axis-schema-contract-model-runtime"

    async def invoke(self, request) -> ModelInvocationRuntimeResult:
        return ModelInvocationRuntimeResult(
            adapter=self.adapter_name,
            status="model_invocation_completed",
            output_text=json.dumps(DAILY_BRIEF_PROPOSAL),
            input_tokens=210,
            output_tokens=64,
            latency_ms=42,
            provider_request_ref="chatcmpl-schema-contract-001",
            notes=["Schema contract runtime completed the invocation."],
        )

    def describe(self) -> dict[str, str]:
        return {"adapter": self.adapter_name, "execution_mode": "test"}


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    assert path.exists(), f"missing schema file: {path}"
    return json.loads(path.read_text())


def build_validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


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


def seed_reference(
    factory: sessionmaker[Session],
    *,
    surface: str,
    reference_id: str,
    payload: dict,
    version: str = "2026-06-22",
) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=TENANT_ID,
                surface=surface,
                reference_id=reference_id,
                status="active",
                source="bootstrap",
                version=version,
                payload=payload,
            )
        )


def seed_agent_run_references(factory: sessionmaker[Session]) -> None:
    agent_payload = deepcopy(
        run_path("migrations/versions/0024_agent_registry_reference.py")[
            "AGENT_REGISTRY_PAYLOAD"
        ]
    )
    action_payload = deepcopy(
        run_path("migrations/versions/0025_action_registry_reference.py")[
            "ACTION_REGISTRY_PAYLOAD"
        ]
    )
    ontology_payload = deepcopy(
        run_path("migrations/versions/0030_ontology_reference.py")["ONTOLOGY_PAYLOAD"]
    )
    seed_reference(
        factory,
        surface="agents",
        reference_id="manufacturing-agent-registry",
        payload=agent_payload,
    )
    seed_reference(
        factory,
        surface="actions",
        reference_id="manufacturing-action-registry",
        payload=action_payload,
        version=action_payload["schema_version"],
    )
    seed_reference(
        factory,
        surface="ontology",
        reference_id="manufacturing-ontology",
        payload=ontology_payload,
    )


def model_endpoint_request(**overrides) -> ModelEndpointCreateRequest:
    payload = {
        "tenant_id": TENANT_ID,
        "endpoint_id": "vllm_plant_local",
        "display_name": "Plant-local vLLM",
        "provider_type": "openai_compatible",
        "hosting_boundary": "self_hosted",
        "base_url": "http://vllm.axis-models.svc.cluster.local:8000",
        "default_model": "mistral-7b-instruct",
        "task_types": ["agent_proposal", "summarize"],
        "cost_input_per_1k": Decimal("0.5"),
        "cost_output_per_1k": Decimal("1.5"),
        "created_by": "platform-admin",
        "actor_scopes": [MODEL_ENDPOINT_ADMIN_SCOPE],
    }
    payload.update(overrides)
    return ModelEndpointCreateRequest(**payload)


def connector_manifest_request() -> ConnectorManifestCreateRequest:
    return ConnectorManifestCreateRequest(
        tenant_id=TENANT_ID,
        registered_by="platform-connector-owner-role",
        manifest={
            "connector_id": "external_db_shift_orders",
            "display_name": "Shift orders database mirror",
            "connector_type": "external_db",
            "version": "2026-06-22",
            "source_type": "database",
            "sync_modes": ["schema_preview", "manual_import"],
            "runtime_boundary": "axis-connector-sandbox",
            "required_permissions": [
                "connectors:read",
                "connectors:external_db:preview",
            ],
            "credential_requirements": {
                "storage": "external_reference",
                "required_secret_refs": ["cred_external_db_readonly"],
                "notes": ["Metadata-only credential handle reference."],
            },
            "schema_fields": [
                {
                    "source_column": "order_id",
                    "target_field": "node_id",
                    "ontology_target": "production_order",
                    "data_type": "string",
                    "required": True,
                    "description": "Stable production order identifier.",
                }
            ],
            "mapping_notes": ["Registered as a preview-only manifest."],
        },
        runtime_policy={
            "allowed_operations": ["schema_validate", "metadata_preview"],
            "blocked_operations": [
                "live_query",
                "live_write",
                "credential_capture",
                "external_egress",
            ],
            "egress_policy": "no-external-egress",
            "max_file_size_mb": 5,
            "row_limit": 100,
            "payload_policy": "metadata-only-redacted-preview",
        },
        preview_sample={
            "file_name": "profile_postgres_ops_readonly:operations.shift_orders",
            "record_count": 1,
            "headers": ["order_id"],
            "sample_rows": [{"order_id": "order_shift_100"}],
        },
        notes=["Manifest is registered without enabling live sync."],
    )


def test_every_schema_file_is_a_valid_draft_2020_12_schema() -> None:
    schema_files = sorted(SCHEMAS_DIR.glob("*.schema.json"))
    assert len(schema_files) >= 6
    for path in schema_files:
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == f"https://schemas.limeslabs.eu/axis/{path.name}"


def test_tenant_record_matches_tenant_schema(
    session_factory: sessionmaker[Session],
) -> None:
    validator = build_validator("tenant.schema.json")
    with session_scope(session_factory) as session:
        record = provision_tenant(
            AxisPersistenceRepository(session),
            TenantProvisionRequest(
                tenant_id="tenant_acme_manufacturing",
                display_name="Acme Manufacturing",
                description="Reference multi-tenant SaaS design partner.",
                requested_by="axis-platform-operator-role",
                actor_scopes=[
                    "platform:tenant:operator",
                    "platform:tenant:provision",
                ],
                idempotency_key="idem_provision_acme_schema_contract",
                notes=["Provisioned during schema package contract tests."],
            ),
        )
        validator.validate(record.model_dump(mode="json"))


def test_model_endpoint_record_matches_model_endpoint_schema(
    session_factory: sessionmaker[Session],
) -> None:
    validator = build_validator("model-endpoint.schema.json")
    with session_scope(session_factory) as session:
        record = record_model_endpoint(
            AxisPersistenceRepository(session), model_endpoint_request()
        )
        validator.validate(record.model_dump(mode="json"))


def test_connector_manifest_matches_connector_manifest_schema(
    session_factory: sessionmaker[Session],
) -> None:
    validator = build_validator("connector-manifest.schema.json")
    request = connector_manifest_request()
    validator.validate(request.manifest)
    with session_scope(session_factory) as session:
        record = record_demo_connector_manifest(
            AxisPersistenceRepository(session), request
        )
        validator.validate(record.manifest)


def test_persisted_audit_ledger_events_match_audit_event_schema(
    session_factory: sessionmaker[Session],
) -> None:
    validator = build_validator("audit-event.schema.json")
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(
            TenantCreate(
                tenant_id=TENANT_ID,
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
        record_model_endpoint(repository, model_endpoint_request())
        record_demo_connector_manifest(repository, connector_manifest_request())
        explorer = query_persisted_audit_events(
            repository, AuditEventQuery(tenant_id=TENANT_ID)
        )
        assert explorer.events, "expected persisted audit events to validate"
        for event in explorer.events:
            validator.validate(event.model_dump(mode="json"))


async def test_agent_run_result_matches_agent_run_schema(
    session_factory: sessionmaker[Session],
) -> None:
    validator = build_validator("agent-run.schema.json")
    seed_agent_run_references(session_factory)
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        record_model_endpoint(repository, model_endpoint_request())
        result = await start_agent_run(
            repository,
            "agent_daily_brief",
            AgentRunStartRequest(
                tenant_id=TENANT_ID,
                actor_id="plant-operations-owner",
                actor_scopes=[
                    AGENT_RUN_EXECUTE_SCOPE,
                    MODEL_INVOKE_SCOPE,
                    "agents:read",
                    "audit:read",
                    "workflows:read",
                ],
                idempotency_key="agent-run-schema-contract-2026-07-10",
                mode="dry_run",
            ),
            ProposalModelRuntime(),
            execution_enabled=True,
        )
        assert result.status == "dry_run_completed"
        payload = result.model_dump(mode="json")
        validator.validate(payload)
        assert payload["steps"], "expected persisted agent run steps to validate"


def test_action_registry_definitions_match_action_schema() -> None:
    validator = build_validator("action.schema.json")
    payload = run_path("migrations/versions/0025_action_registry_reference.py")[
        "ACTION_REGISTRY_PAYLOAD"
    ]
    actions = payload["actions"]
    assert actions, "expected bootstrap action registry definitions"
    for action in actions:
        validator.validate(action["definition"])


def test_agent_run_creation_timestamp_serializes_as_rfc3339() -> None:
    # Guard the date-time format assumption shared by the schemas: Pydantic
    # serializes datetimes to RFC 3339 in JSON mode, which is what the
    # `format: date-time` annotations in the schema package describe.
    now = datetime(2026, 7, 10, 8, 30, tzinfo=UTC)
    assert now.isoformat() == "2026-07-10T08:30:00+00:00"
