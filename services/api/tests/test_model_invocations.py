import asyncio
import json
import math
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.model_endpoints import (
    MODEL_ENDPOINT_ADMIN_SCOPE,
    ModelEndpointCreateRequest,
    model_endpoint_record,
    record_model_endpoint,
)
from axis_api.model_invocations import (
    IN_FLIGHT_REPLAY_NOTE,
    MODEL_INVOCATION_REQUESTED_STATUS,
    MODEL_INVOKE_SCOPE,
    ModelEgressBlocked,
    ModelInvocationIdempotencyConflict,
    ModelInvocationNotFound,
    ModelInvocationPermissionDenied,
    ModelInvocationPreviewRequest,
    ModelInvocationRequest,
    ModelInvocationValidationError,
    build_model_routing_telemetry,
    decide_model_route,
    get_model_invocation_result,
    invoke_model,
    preview_model_invocation,
)
from axis_api.model_providers import (
    DeferredModelInvocationRuntime,
    ModelInvocationRuntimeResult,
    ModelProviderInvocationError,
)
from axis_api.models import (
    AuditEvent,
    Base,
    ModelInvocation,
    TenantUsageEvent,
    TenantUsageRecord,
)
from axis_api.persistence import AxisPersistenceRepository, PlatformPolicyCreate
from axis_api.platform_policies import PlatformPolicyEnforcementDenied

TENANT_ID = "tenant_demo_manufacturing"
PROMPT = "Summarize the packaging line risk posture for the morning shift."
VALID_EGRESS_EVIDENCE = {
    "egress_policy_evidence_status": "validated",
    "egress_policy_result_status": "egress_policy_approved",
    "egress_policy_mode": "approved_private_endpoint",
    "egress_policy_id": "egress_models_private",
}


class RecordingModelInvocationRuntime:
    adapter_name = "axis-test-model-invocation-adapter"

    def __init__(self) -> None:
        self.requests: list[object] = []

    async def invoke(self, request) -> ModelInvocationRuntimeResult:
        self.requests.append(request)
        return ModelInvocationRuntimeResult(
            adapter=self.adapter_name,
            status="model_invocation_completed",
            output_text="Line 2 packaging risk is contained; expedite review at 14:00.",
            input_tokens=120,
            output_tokens=45,
            latency_ms=87,
            provider_request_ref="chatcmpl-test-001",
            notes=["Test runtime completed the invocation."],
        )

    def describe(self) -> dict[str, str]:
        return {"adapter": self.adapter_name, "execution_mode": "test"}


class FailingModelInvocationRuntime:
    adapter_name = "axis-test-failing-model-invocation-adapter"

    def __init__(self) -> None:
        self.requests: list[object] = []

    async def invoke(self, request) -> ModelInvocationRuntimeResult:
        self.requests.append(request)
        raise ModelProviderInvocationError(
            "The model provider endpoint could not be reached.",
            "provider_unreachable",
            latency_ms=12,
        )

    def describe(self) -> dict[str, str]:
        return {"adapter": self.adapter_name, "execution_mode": "test_failing"}


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


def seed_endpoint(repository: AxisPersistenceRepository, **overrides) -> None:
    payload = {
        "tenant_id": TENANT_ID,
        "endpoint_id": "vllm_plant_local",
        "display_name": "Plant-local vLLM",
        "provider_type": "openai_compatible",
        "hosting_boundary": "self_hosted",
        "base_url": "http://vllm.axis-models.svc.cluster.local:8000",
        "default_model": "mistral-7b-instruct",
        "task_types": ["summarize", "classify"],
        "cost_input_per_1k": Decimal("0.5"),
        "cost_output_per_1k": Decimal("1.5"),
        "created_by": "platform-admin",
        "actor_scopes": [MODEL_ENDPOINT_ADMIN_SCOPE],
    }
    payload.update(overrides)
    record_model_endpoint(repository, ModelEndpointCreateRequest(**payload))


def seed_external_endpoint(repository: AxisPersistenceRepository, **overrides) -> None:
    payload = {
        "endpoint_id": "external_hosted_llm",
        "display_name": "External hosted LLM",
        "hosting_boundary": "approved_private_endpoint",
        "base_url": "https://models.private-link.example.eu",
        "default_model": "hosted-large",
        "task_types": ["summarize"],
        "egress_policy_id": "egress_models_private",
    }
    payload.update(overrides)
    seed_endpoint(repository, **payload)


def invocation_request(**overrides) -> ModelInvocationRequest:
    payload = {
        "tenant_id": TENANT_ID,
        "actor_id": "agent_daily_brief",
        "actor_scopes": [MODEL_INVOKE_SCOPE],
        "idempotency_key": "daily-brief-2026-07-10",
        "task_type": "summarize",
        "prompt": PROMPT,
    }
    payload.update(overrides)
    return ModelInvocationRequest(**payload)


def seed_deny_policy(repository: AxisPersistenceRepository, conditions: dict) -> None:
    repository.create_platform_policy(
        PlatformPolicyCreate(
            tenant_id=TENANT_ID,
            policy_id="deny-model-routing",
            revision_number=1,
            policy_version="2026-07",
            display_name="Deny model routing",
            description="Blocks governed model invocations for this tenant.",
            scope="model_invocation",
            effect="deny",
            conditions=conditions,
            status="active",
            created_by="platform-admin",
            required_authoring_scope="platform:policy:author",
            permission_decision={"allowed": True, "reason": "allowed"},
            audit_event_type="platform.policy.authored",
            notes=[],
        )
    )


def endpoint_records(repository: AxisPersistenceRepository):
    return [
        model_endpoint_record(record)
        for record in repository.list_model_endpoints(TENANT_ID, limit=200)
    ]


def test_decide_model_route_is_deterministic_and_prefers_self_hosted(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_external_endpoint(repository)
        seed_endpoint(repository, endpoint_id="vllm_plant_b")
        seed_endpoint(repository)
        endpoints = endpoint_records(repository)

        first = decide_model_route(endpoints, task_type="summarize")
        second = decide_model_route(endpoints, task_type="summarize")
        assert first == second
        assert first.status == "routed"
        # Self-hosted candidates outrank the private-endpoint one; the
        # lexicographically smallest endpoint_id wins the tie.
        assert first.endpoint_id == "vllm_plant_b"
        assert first.model_id == "mistral-7b-instruct"
        assert first.candidate_endpoint_ids == [
            "vllm_plant_b",
            "vllm_plant_local",
            "external_hosted_llm",
        ]


def test_decide_model_route_honors_model_and_endpoint_pins(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        seed_external_endpoint(repository)
        seed_endpoint(
            repository,
            endpoint_id="vllm_disabled",
            status="disabled",
            default_model="hosted-large",
        )
        endpoints = endpoint_records(repository)

        pinned_model = decide_model_route(
            endpoints, task_type="summarize", requested_model="hosted-large"
        )
        assert pinned_model.endpoint_id == "external_hosted_llm"
        assert pinned_model.model_id == "hosted-large"

        pinned_endpoint = decide_model_route(
            endpoints,
            task_type="summarize",
            requested_endpoint_id="external_hosted_llm",
        )
        assert pinned_endpoint.endpoint_id == "external_hosted_llm"

        unknown_task = decide_model_route(endpoints, task_type="translate")
        assert unknown_task.status == "blocked"
        assert unknown_task.reason == "no_matching_endpoint"
        assert unknown_task.endpoint_id is None

        disabled_only = decide_model_route(
            endpoints,
            task_type="summarize",
            requested_endpoint_id="vllm_disabled",
        )
        assert disabled_only.status == "blocked"


async def test_invoke_model_requires_invoke_scope(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        with pytest.raises(ModelInvocationPermissionDenied) as excinfo:
            await invoke_model(
                repository,
                invocation_request(actor_scopes=["actions:read"]),
                RecordingModelInvocationRuntime(),
            )

        assert excinfo.value.required_permission == MODEL_INVOKE_SCOPE
        assert excinfo.value.decision.reason == f"missing_scope:{MODEL_INVOKE_SCOPE}"


async def test_invoke_model_records_result_audit_and_metering(
    session_factory: sessionmaker[Session],
) -> None:
    runtime = RecordingModelInvocationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        result = await invoke_model(
            repository,
            invocation_request(),
            runtime,
            usage_metering_enabled=True,
        )

        assert result.status == "completed"
        assert result.endpoint_id == "vllm_plant_local"
        assert result.model_id == "mistral-7b-instruct"
        assert result.hosting_boundary == "self_hosted"
        assert result.egress_decision == "allowed_self_hosted"
        assert result.output_text.startswith("Line 2 packaging risk")
        assert result.input_tokens == 120
        assert result.output_tokens == 45
        assert result.latency_ms == 87
        # 120 * 0.5/1k + 45 * 1.5/1k = 0.06 + 0.0675
        assert result.estimated_cost_eur == pytest.approx(0.1275)
        assert result.cost_basis == "estimated_from_endpoint_rates"
        assert result.provider_request_ref == "chatcmpl-test-001"
        assert result.idempotent_replay is False
        assert result.persisted is True
        assert len(result.prompt_sha256) == 64
        assert result.response_sha256 is not None
        assert result.audit_event_id is not None
        assert len(runtime.requests) == 1
        assert runtime.requests[0].base_url == (
            "http://vllm.axis-models.svc.cluster.local:8000"
        )

        stored = session.scalars(select(ModelInvocation)).one()
        assert stored.status == "completed"
        assert stored.prompt_excerpt is None
        assert stored.response_excerpt is None

        audit_events = {
            event.event_type: event for event in session.scalars(select(AuditEvent))
        }
        recorded = audit_events["model.invocation.recorded"]
        assert recorded.payload["prompt_sha256"] == result.prompt_sha256
        assert recorded.payload["response_sha256"] == result.response_sha256
        assert recorded.payload["input_tokens"] == 120
        assert recorded.payload["output_tokens"] == 45
        serialized = json.dumps(recorded.payload)
        assert PROMPT not in serialized
        assert "Line 2 packaging risk" not in serialized

        usage_rows = {
            row.metric_key: row for row in session.scalars(select(TenantUsageRecord))
        }
        assert usage_rows["model_invocations"].quantity == 1
        assert usage_rows["model_input_tokens"].quantity == 120
        assert usage_rows["model_output_tokens"].quantity == 45
        assert usage_rows["model_invocations"].dimensions == {}
        usage_events = {
            event.metric_key: event
            for event in session.scalars(select(TenantUsageEvent))
        }
        assert usage_events["model_invocations"].dimensions == {
            "provider_id": "vllm_plant_local",
            "model_id": "mistral-7b-instruct",
        }


async def test_invoke_model_stores_bounded_excerpt_only_when_configured(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        await invoke_model(
            repository,
            invocation_request(),
            RecordingModelInvocationRuntime(),
            prompt_excerpt_chars=16,
        )

        stored = session.scalars(select(ModelInvocation)).one()
        assert stored.prompt_excerpt == PROMPT[:16]
        assert stored.response_excerpt == "Line 2 packaging"


async def test_invoke_model_idempotent_replay_returns_same_record(
    session_factory: sessionmaker[Session],
) -> None:
    runtime = RecordingModelInvocationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        first = await invoke_model(repository, invocation_request(), runtime)
        second = await invoke_model(repository, invocation_request(), runtime)

        assert first.invocation_id == second.invocation_id
        assert first.idempotent_replay is False
        assert second.idempotent_replay is True
        assert second.status == "completed"
        assert second.input_tokens == 120
        # Response bodies are never persisted, so the replay carries no output.
        assert second.output_text == ""
        assert len(runtime.requests) == 1


async def test_invoke_model_idempotency_payload_conflict(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        first = await invoke_model(
            repository, invocation_request(), RecordingModelInvocationRuntime()
        )
        with pytest.raises(ModelInvocationIdempotencyConflict) as excinfo:
            await invoke_model(
                repository,
                invocation_request(prompt="A different prompt body entirely."),
                RecordingModelInvocationRuntime(),
            )

        assert excinfo.value.invocation_id == first.invocation_id


async def test_invoke_model_platform_policy_deny_fails_closed(
    session_factory: sessionmaker[Session],
) -> None:
    runtime = RecordingModelInvocationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        seed_deny_policy(repository, {"action_domains": ["model_routing"]})
        with pytest.raises(PlatformPolicyEnforcementDenied) as excinfo:
            await invoke_model(repository, invocation_request(), runtime)

        assert excinfo.value.decision.effect == "deny"
        assert excinfo.value.audit_event_type == "platform.policy.enforcement.denied"
        assert runtime.requests == []
        assert session.scalars(select(ModelInvocation)).all() == []


async def test_invoke_model_policy_deny_fails_closed_on_malformed_context(
    session_factory: sessionmaker[Session],
) -> None:
    runtime = RecordingModelInvocationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        # The deny policy conditions do not match the (degraded) context; the
        # malformed task type must still fail closed against any deny policy.
        seed_deny_policy(repository, {"risk_levels": ["high"]})
        malformed = invocation_request().model_copy(update={"task_type": ""})
        with pytest.raises(PlatformPolicyEnforcementDenied) as excinfo:
            await invoke_model(repository, malformed, runtime)

        assert excinfo.value.decision.effect == "deny"
        assert excinfo.value.decision.evidence["fail_closed"] is True
        assert runtime.requests == []


async def test_external_endpoint_blocked_when_egress_flag_off(
    session_factory: sessionmaker[Session],
) -> None:
    runtime = RecordingModelInvocationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_external_endpoint(repository)
        with pytest.raises(ModelEgressBlocked) as excinfo:
            await invoke_model(
                repository,
                invocation_request(egress_policy_evidence=dict(VALID_EGRESS_EVIDENCE)),
                runtime,
                external_model_egress_enabled=False,
            )

        assert excinfo.value.egress_decision == "blocked_external_egress_disabled"
        assert excinfo.value.audit_event_type == "model.invocation.blocked"
        assert runtime.requests == []
        assert session.scalars(select(ModelInvocation)).all() == []

        blocked_event = session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == "model.invocation.blocked")
        ).one()
        assert blocked_event.payload["egress_decision"] == (
            "blocked_external_egress_disabled"
        )
        assert blocked_event.payload["provider_call_started"] is False


async def test_external_endpoint_blocked_without_valid_egress_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    runtime = RecordingModelInvocationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_external_endpoint(repository)

        with pytest.raises(ModelEgressBlocked) as missing:
            await invoke_model(
                repository,
                invocation_request(),
                runtime,
                external_model_egress_enabled=True,
            )
        assert missing.value.egress_decision == "blocked_egress_policy_evidence_missing"

        tampered = dict(VALID_EGRESS_EVIDENCE, egress_policy_id="egress_other_policy")
        with pytest.raises(ModelEgressBlocked) as invalid:
            await invoke_model(
                repository,
                invocation_request(
                    idempotency_key="daily-brief-tampered",
                    egress_policy_evidence=tampered,
                ),
                runtime,
                external_model_egress_enabled=True,
            )
        assert invalid.value.egress_decision == "blocked_egress_policy_evidence_invalid"
        assert runtime.requests == []


async def test_external_endpoint_allowed_with_flag_and_valid_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_external_endpoint(repository)
        result = await invoke_model(
            repository,
            invocation_request(egress_policy_evidence=dict(VALID_EGRESS_EVIDENCE)),
            RecordingModelInvocationRuntime(),
            external_model_egress_enabled=True,
        )

        assert result.status == "completed"
        assert result.endpoint_id == "external_hosted_llm"
        assert result.egress_decision == "allowed_with_egress_policy_evidence"


async def test_self_hosted_route_allowed_without_external_egress_flag(
    session_factory: sessionmaker[Session],
) -> None:
    # Ports the historic ModelRouter guarantee: local routes never require the
    # external egress flag.
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        result = await invoke_model(
            repository,
            invocation_request(),
            RecordingModelInvocationRuntime(),
            external_model_egress_enabled=False,
        )

        assert result.status == "completed"
        assert result.egress_decision == "allowed_self_hosted"


async def test_invoke_model_returns_deferred_result_when_execution_disabled(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        result = await invoke_model(
            repository,
            invocation_request(),
            DeferredModelInvocationRuntime(),
            usage_metering_enabled=True,
        )

        assert result.status == "model_invocation_deferred"
        assert result.output_text == ""
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.estimated_cost_eur == 0
        assert "deferred" in " ".join(result.notes).lower()
        # Deferred invocations consume nothing, so nothing is metered.
        assert session.scalars(select(TenantUsageRecord)).all() == []

        stored = session.scalars(select(ModelInvocation)).one()
        assert stored.status == "model_invocation_deferred"


async def test_failed_runtime_records_failed_status_and_audit(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        result = await invoke_model(
            repository,
            invocation_request(),
            FailingModelInvocationRuntime(),
            usage_metering_enabled=True,
        )

        assert result.status == "failed"
        assert result.error_code == "provider_unreachable"
        assert result.output_text == ""
        assert result.response_sha256 is None
        assert result.latency_ms == 12

        stored = session.scalars(select(ModelInvocation)).one()
        assert stored.status == "failed"
        assert stored.error_code == "provider_unreachable"

        recorded = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "model.invocation.recorded"
            )
        ).one()
        assert recorded.payload["status"] == "failed"
        assert recorded.payload["error_code"] == "provider_unreachable"

        usage_rows = {
            row.metric_key: row for row in session.scalars(select(TenantUsageRecord))
        }
        assert usage_rows["model_invocations"].quantity == 1
        assert "model_input_tokens" not in usage_rows
        assert "model_output_tokens" not in usage_rows


async def test_invoke_model_fails_closed_when_no_endpoint_matches(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        with pytest.raises(ModelInvocationValidationError) as excinfo:
            await invoke_model(
                repository,
                invocation_request(task_type="translate"),
                RecordingModelInvocationRuntime(),
            )

        assert excinfo.value.reason == "no_matching_endpoint"
        assert session.scalars(select(ModelInvocation)).all() == []


def test_preview_model_invocation_estimates_cost_without_provider_call(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        preview = preview_model_invocation(
            repository,
            ModelInvocationPreviewRequest(
                tenant_id=TENANT_ID,
                actor_id="agent_daily_brief",
                actor_scopes=[MODEL_INVOKE_SCOPE],
                task_type="summarize",
                prompt=PROMPT,
                max_output_tokens=100,
            ),
        )

        expected_input_tokens = math.ceil(len(PROMPT) / 4)
        assert preview.status == "preview_ready"
        assert preview.route_decision.endpoint_id == "vllm_plant_local"
        assert preview.egress_decision == "allowed_self_hosted"
        assert preview.estimated_input_tokens == expected_input_tokens
        assert preview.estimated_output_tokens == 100
        assert preview.estimated_cost_eur == pytest.approx(
            expected_input_tokens * 0.5 / 1000 + 100 * 1.5 / 1000
        )
        assert preview.cost_basis == "estimated_from_endpoint_rates"
        assert preview.audit_event_type == "model.invocation.previewed"

        # No invocation was persisted and no provider was called.
        assert session.scalars(select(ModelInvocation)).all() == []
        audit_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "model.invocation.previewed"
            )
        ).one()
        assert audit_event.payload["provider_call_started"] is False
        assert PROMPT not in json.dumps(audit_event.payload)


def test_preview_model_invocation_reports_blocked_routes(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_external_endpoint(repository)
        preview = preview_model_invocation(
            repository,
            ModelInvocationPreviewRequest(
                tenant_id=TENANT_ID,
                actor_id="agent_daily_brief",
                actor_scopes=[MODEL_INVOKE_SCOPE],
                task_type="summarize",
                prompt=PROMPT,
            ),
            external_model_egress_enabled=False,
        )

        assert preview.status == "preview_blocked"
        assert preview.egress_decision == "blocked_external_egress_disabled"

        no_route = preview_model_invocation(
            repository,
            ModelInvocationPreviewRequest(
                tenant_id=TENANT_ID,
                actor_id="agent_daily_brief",
                actor_scopes=[MODEL_INVOKE_SCOPE],
                task_type="translate",
                prompt=PROMPT,
            ),
        )
        assert no_route.status == "preview_blocked"
        assert no_route.route_decision.reason == "no_matching_endpoint"
        assert no_route.egress_decision == "blocked_no_matching_endpoint"


async def test_get_model_invocation_result_and_not_found(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        created = await invoke_model(
            repository, invocation_request(), RecordingModelInvocationRuntime()
        )

        fetched = get_model_invocation_result(
            repository, TENANT_ID, created.invocation_id
        )
        assert fetched.invocation_id == created.invocation_id
        assert fetched.status == "completed"
        assert fetched.output_text == ""

        with pytest.raises(ModelInvocationNotFound):
            get_model_invocation_result(repository, TENANT_ID, "not-a-uuid")
        with pytest.raises(ModelInvocationNotFound):
            get_model_invocation_result(
                repository,
                "tenant_other",
                created.invocation_id,
            )


async def test_telemetry_projection_reflects_persisted_invocations(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        completed = await invoke_model(
            repository, invocation_request(), RecordingModelInvocationRuntime()
        )
        failed = await invoke_model(
            repository,
            invocation_request(idempotency_key="daily-brief-failed"),
            FailingModelInvocationRuntime(),
        )

        projection = build_model_routing_telemetry(repository, TENANT_ID)
        assert projection.route_count == 2
        routes = {route.route_id: route for route in projection.routes}

        completed_route = routes[str(completed.invocation_id)]
        assert completed_route.provider_id == "vllm_plant_local"
        assert completed_route.model == "mistral-7b-instruct"
        assert completed_route.input_tokens == 120
        assert completed_route.output_tokens == 45
        assert completed_route.latency_ms == 87
        assert completed_route.estimated_cost_eur == pytest.approx(0.1275)
        assert completed_route.egress_decision == "allowed_self_hosted"
        assert completed_route.external_egress_requested is False
        assert completed_route.route_status.value == "ready"
        assert completed_route.audit_event_id == str(completed.audit_event_id)

        failed_route = routes[str(failed.invocation_id)]
        assert failed_route.route_status.value == "action_required"
        assert failed_route.input_tokens == 0


def test_invocation_routes_invoke_replay_and_deferred_flag_off(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    runtime = RecordingModelInvocationRuntime()
    app.state.model_invocation_runtime = runtime
    client = TestClient(app)
    client.post(
        "/platform/models/endpoints",
        json={
            "tenant_id": TENANT_ID,
            "endpoint_id": "vllm_plant_local",
            "display_name": "Plant-local vLLM",
            "provider_type": "openai_compatible",
            "hosting_boundary": "self_hosted",
            "base_url": "http://vllm.axis-models.svc.cluster.local:8000",
            "default_model": "mistral-7b-instruct",
            "task_types": ["summarize"],
            "cost_input_per_1k": "0.5",
            "cost_output_per_1k": "1.5",
            "created_by": "platform-admin",
            "actor_scopes": [MODEL_ENDPOINT_ADMIN_SCOPE],
        },
    ).raise_for_status()
    payload = invocation_request().model_dump(mode="json")

    first = client.post("/platform/models/invocations", json=payload)
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["status"] == "completed"
    assert first_body["output_text"].startswith("Line 2 packaging risk")

    replay = client.post("/platform/models/invocations", json=payload)
    assert replay.status_code == 200
    assert replay.json()["invocation_id"] == first_body["invocation_id"]
    assert replay.json()["idempotent_replay"] is True
    assert len(runtime.requests) == 1

    conflict = client.post(
        "/platform/models/invocations",
        json={**payload, "prompt": "A different prompt body."},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "CONFLICT"

    # A fresh app without an injected runtime defaults to the deferred adapter
    # because AXIS_MODEL_ROUTING_EXECUTION_ENABLED is off.
    deferred_app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    deferred_app.state.session_factory = session_factory
    assert isinstance(
        deferred_app.state.model_invocation_runtime, DeferredModelInvocationRuntime
    )
    deferred_client = TestClient(deferred_app)
    deferred = deferred_client.post(
        "/platform/models/invocations",
        json={**payload, "idempotency_key": "daily-brief-deferred"},
    )
    assert deferred.status_code == 200
    assert deferred.json()["status"] == "model_invocation_deferred"


def test_invocation_route_translates_egress_block_to_model_provider_blocked(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.model_invocation_runtime = RecordingModelInvocationRuntime()
    client = TestClient(app)
    with session_scope(session_factory) as session:
        seed_external_endpoint(AxisPersistenceRepository(session))

    response = client.post(
        "/platform/models/invocations",
        json=invocation_request(
            egress_policy_evidence=dict(VALID_EGRESS_EVIDENCE)
        ).model_dump(mode="json"),
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "MODEL_PROVIDER_BLOCKED"
    assert detail["reason"] == "blocked_external_egress_disabled"
    assert detail["endpoint_id"] == "external_hosted_llm"
    assert detail["audit_event_id"] is not None

    # The blocked audit event was committed despite the 403.
    with session_factory() as session:
        blocked = session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == "model.invocation.blocked")
        ).one()
        assert blocked.payload["hosting_boundary"] == "approved_private_endpoint"


def test_invocation_route_permission_and_validation_errors(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.model_invocation_runtime = RecordingModelInvocationRuntime()
    client = TestClient(app)
    with session_scope(session_factory) as session:
        seed_endpoint(AxisPersistenceRepository(session))

    denied = client.post(
        "/platform/models/invocations",
        json=invocation_request(actor_scopes=[]).model_dump(mode="json"),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"
    assert denied.json()["detail"]["required_permission"] == MODEL_INVOKE_SCOPE

    unroutable = client.post(
        "/platform/models/invocations",
        json=invocation_request(task_type="translate").model_dump(mode="json"),
    )
    assert unroutable.status_code == 422
    assert unroutable.json()["detail"]["reason"] == "no_matching_endpoint"

    missing_key = invocation_request().model_dump(mode="json")
    missing_key.pop("idempotency_key")
    rejected = client.post("/platform/models/invocations", json=missing_key)
    assert rejected.status_code == 422


def test_invocation_route_policy_deny_returns_policy_violation(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.model_invocation_runtime = RecordingModelInvocationRuntime()
    client = TestClient(app)
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_endpoint(repository)
        seed_deny_policy(repository, {"action_domains": ["model_routing"]})

    response = client.post(
        "/platform/models/invocations",
        json=invocation_request().model_dump(mode="json"),
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "POLICY_VIOLATION"
    assert detail["reason"] == "platform_policy_denied"
    assert detail["policy_id"] == "deny-model-routing"

    with session_factory() as session:
        denied_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "platform.policy.enforcement.denied"
            )
        ).one()
        assert denied_event.payload["enforcement_point"] == "model_invocation"


def test_invocation_list_route_paginates_with_cursor(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.model_invocation_runtime = RecordingModelInvocationRuntime()
    client = TestClient(app)
    with session_scope(session_factory) as session:
        seed_endpoint(AxisPersistenceRepository(session))

    created_ids = []
    for index in range(5):
        response = client.post(
            "/platform/models/invocations",
            json=invocation_request(
                idempotency_key=f"daily-brief-{index}"
            ).model_dump(mode="json"),
        )
        assert response.status_code == 201
        created_ids.append(response.json()["invocation_id"])

    collected: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params = {"tenant_id": TENANT_ID, "page_size": 2}
        if cursor is not None:
            params["cursor"] = cursor
        page = client.get("/platform/models/invocations", params=params)
        assert page.status_code == 200
        body = page.json()
        collected.extend(item["invocation_id"] for item in body["invocations"])
        pages += 1
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        cursor = body["next_cursor"]
        assert cursor is not None

    assert pages == 3
    assert len(collected) == 5
    assert set(collected) == set(created_ids)

    invalid_cursor = client.get(
        "/platform/models/invocations",
        params={"tenant_id": TENANT_ID, "cursor": "not-a-cursor"},
    )
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["detail"]["reason"] == (
        "invalid_model_invocation_cursor"
    )

    detail = client.get(
        f"/platform/models/invocations/{created_ids[0]}",
        params={"tenant_id": TENANT_ID},
    )
    assert detail.status_code == 200
    assert detail.json()["invocation_id"] == created_ids[0]

    missing = client.get(
        "/platform/models/invocations/00000000-0000-0000-0000-000000000000",
        params={"tenant_id": TENANT_ID},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "NOT_FOUND"


def test_telemetry_route_projects_real_invocations(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.model_invocation_runtime = RecordingModelInvocationRuntime()
    client = TestClient(app)
    with session_scope(session_factory) as session:
        seed_endpoint(AxisPersistenceRepository(session))

    invoked = client.post(
        "/platform/models/invocations",
        json=invocation_request().model_dump(mode="json"),
    )
    assert invoked.status_code == 201
    invocation_id = invoked.json()["invocation_id"]

    telemetry = client.get(
        "/platform/models/routing/telemetry",
        params={"tenant_id": TENANT_ID},
    )
    assert telemetry.status_code == 200
    body = telemetry.json()
    assert body["route_count"] == 1
    route = body["routes"][0]
    assert route["route_id"] == invocation_id
    assert route["input_tokens"] == 120
    assert route["output_tokens"] == 45
    assert route["latency_ms"] == 87
    assert route["egress_decision"] == "allowed_self_hosted"
    assert route["audit_event_id"] == invoked.json()["audit_event_id"]

    # Preview works regardless of the execution flag and never persists rows.
    preview = client.post(
        "/platform/models/invocations/preview",
        json={
            "tenant_id": TENANT_ID,
            "actor_id": "agent_daily_brief",
            "actor_scopes": [MODEL_INVOKE_SCOPE],
            "task_type": "summarize",
            "prompt": PROMPT,
        },
    )
    assert preview.status_code == 200
    assert preview.json()["status"] == "preview_ready"


# --- Transaction boundary around the external provider call (issue #362) ---


class TransactionProbeRuntime:
    """Records whether a database transaction is open during the provider call."""

    adapter_name = "axis-test-transaction-probe-runtime"

    def __init__(self, session: Session) -> None:
        self._session = session
        self.transaction_open_during_call: list[bool] = []

    async def invoke(self, request) -> ModelInvocationRuntimeResult:
        self.transaction_open_during_call.append(self._session.in_transaction())
        return ModelInvocationRuntimeResult(
            adapter=self.adapter_name,
            status="model_invocation_completed",
            output_text="Probed.",
            input_tokens=10,
            output_tokens=5,
            latency_ms=3,
        )

    def describe(self) -> dict[str, str]:
        return {"adapter": self.adapter_name, "execution_mode": "test"}


class PoolProbeRuntime:
    """Records pooled connections checked out while the provider call runs."""

    adapter_name = "axis-test-pool-probe-runtime"

    def __init__(self, engine) -> None:
        self._engine = engine
        self.checked_out_during_call: list[int] = []

    async def invoke(self, request) -> ModelInvocationRuntimeResult:
        self.checked_out_during_call.append(self._engine.pool.checkedout())
        return ModelInvocationRuntimeResult(
            adapter=self.adapter_name,
            status="model_invocation_completed",
            output_text="Probed.",
            input_tokens=10,
            output_tokens=5,
            latency_ms=3,
        )

    def describe(self) -> dict[str, str]:
        return {"adapter": self.adapter_name, "execution_mode": "test"}


class InterruptedModelInvocationRuntime:
    """Fails the way a killed process or a client timeout does.

    ``ModelProviderInvocationError`` is a governed provider failure that the
    pipeline records; this raises through it instead, so the surrounding
    session rolls back exactly as an interrupted request would.
    """

    adapter_name = "axis-test-interrupted-model-invocation-adapter"

    def __init__(self) -> None:
        self.requests: list[object] = []

    async def invoke(self, request) -> ModelInvocationRuntimeResult:
        self.requests.append(request)
        raise RuntimeError("The process was interrupted during the provider call.")

    def describe(self) -> dict[str, str]:
        return {"adapter": self.adapter_name, "execution_mode": "test_interrupted"}


def seed_committed_endpoint(session_factory: sessionmaker[Session]) -> None:
    with session_scope(session_factory) as session:
        seed_endpoint(AxisPersistenceRepository(session))


async def test_invoke_model_holds_no_transaction_across_the_provider_call(
    session_factory: sessionmaker[Session],
) -> None:
    seed_committed_endpoint(session_factory)
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        runtime = TransactionProbeRuntime(session)

        result = await invoke_model(
            repository,
            invocation_request(),
            runtime,
            commit_before_provider_call=True,
        )

        assert result.status == "completed"
        # The prepared row is committed first, so the provider timeout cannot
        # occupy a pooled database connection.
        assert runtime.transaction_open_during_call == [False]


async def test_invoke_model_keeps_the_caller_transaction_when_not_the_owner(
    session_factory: sessionmaker[Session],
) -> None:
    """Callers that embed an invocation keep their own transaction semantics."""

    seed_committed_endpoint(session_factory)
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        runtime = TransactionProbeRuntime(session)

        result = await invoke_model(repository, invocation_request(), runtime)

        assert result.status == "completed"
        assert runtime.transaction_open_during_call == [True]


async def test_interrupted_provider_call_keeps_the_requested_row_durable(
    session_factory: sessionmaker[Session],
) -> None:
    seed_committed_endpoint(session_factory)
    runtime = InterruptedModelInvocationRuntime()

    with pytest.raises(RuntimeError), session_scope(session_factory) as session:
        await invoke_model(
            AxisPersistenceRepository(session),
            invocation_request(),
            runtime,
            commit_before_provider_call=True,
        )

    with session_scope(session_factory) as session:
        stored = session.scalars(select(ModelInvocation)).all()
        assert len(stored) == 1
        assert stored[0].idempotency_key == "daily-brief-2026-07-10"
        assert stored[0].status == MODEL_INVOCATION_REQUESTED_STATUS
        assert len(runtime.requests) == 1


async def test_retry_after_an_interrupted_call_does_not_call_the_provider_again(
    session_factory: sessionmaker[Session],
) -> None:
    seed_committed_endpoint(session_factory)
    with pytest.raises(RuntimeError), session_scope(session_factory) as session:
        await invoke_model(
            AxisPersistenceRepository(session),
            invocation_request(),
            InterruptedModelInvocationRuntime(),
            commit_before_provider_call=True,
        )

    retry_runtime = RecordingModelInvocationRuntime()
    with session_scope(session_factory) as session:
        replay = await invoke_model(
            AxisPersistenceRepository(session),
            invocation_request(),
            retry_runtime,
            commit_before_provider_call=True,
        )

    # The outcome of the first provider call is unknown, so the retry replays
    # the durable record instead of risking a second billable call.
    assert replay.idempotent_replay is True
    assert replay.status == MODEL_INVOCATION_REQUESTED_STATUS
    assert replay.output_text == ""
    assert IN_FLIGHT_REPLAY_NOTE in replay.notes
    assert retry_runtime.requests == []


def _lose_the_idempotency_race(repository: AxisPersistenceRepository) -> None:
    """Make the first key lookup miss, as a concurrent duplicate would.

    Two deliveries can both read before either commits; the loser then reaches
    the unique constraint on tenant and idempotency key.
    """

    real_lookup = repository.get_model_invocation_by_idempotency_key
    seen: list[int] = []

    def racing_lookup(tenant_id: str, idempotency_key: str):
        seen.append(1)
        if len(seen) == 1:
            return None
        return real_lookup(tenant_id, idempotency_key)

    repository.get_model_invocation_by_idempotency_key = racing_lookup


async def test_concurrent_duplicate_delivery_replays_instead_of_failing(
    session_factory: sessionmaker[Session],
) -> None:
    seed_committed_endpoint(session_factory)
    with session_scope(session_factory) as session:
        winner = await invoke_model(
            AxisPersistenceRepository(session),
            invocation_request(),
            RecordingModelInvocationRuntime(),
            commit_before_provider_call=True,
        )

    duplicate_runtime = RecordingModelInvocationRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        _lose_the_idempotency_race(repository)

        duplicate = await invoke_model(
            repository,
            invocation_request(),
            duplicate_runtime,
            commit_before_provider_call=True,
        )

    assert duplicate.invocation_id == winner.invocation_id
    assert duplicate.idempotent_replay is True
    assert duplicate_runtime.requests == []
    with session_scope(session_factory) as session:
        assert len(session.scalars(select(ModelInvocation)).all()) == 1


async def test_concurrent_duplicate_with_a_different_payload_still_conflicts(
    session_factory: sessionmaker[Session],
) -> None:
    seed_committed_endpoint(session_factory)
    with session_scope(session_factory) as session:
        await invoke_model(
            AxisPersistenceRepository(session),
            invocation_request(),
            RecordingModelInvocationRuntime(),
            commit_before_provider_call=True,
        )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        _lose_the_idempotency_race(repository)

        with pytest.raises(ModelInvocationIdempotencyConflict):
            await invoke_model(
                repository,
                invocation_request(prompt="A different prompt body entirely."),
                RecordingModelInvocationRuntime(),
                commit_before_provider_call=True,
            )


@pytest.fixture
def pooled_engine(tmp_path):
    """A file-backed engine, so pool checkouts are observable per session."""

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'axis-pool-probe.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


async def test_provider_call_occupies_no_pooled_connection(pooled_engine) -> None:
    factory = sessionmaker(bind=pooled_engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        seed_endpoint(AxisPersistenceRepository(session))

    runtime = PoolProbeRuntime(pooled_engine)
    with session_scope(factory) as session:
        await invoke_model(
            AxisPersistenceRepository(session),
            invocation_request(),
            runtime,
            commit_before_provider_call=True,
        )

    # Pool occupancy during the external await, measured at the pool itself.
    assert runtime.checked_out_during_call == [0]


async def test_provider_call_occupies_a_pooled_connection_for_embedded_callers(
    pooled_engine,
) -> None:
    factory = sessionmaker(bind=pooled_engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        seed_endpoint(AxisPersistenceRepository(session))

    runtime = PoolProbeRuntime(pooled_engine)
    with session_scope(factory) as session:
        await invoke_model(AxisPersistenceRepository(session), invocation_request(), runtime)

    # The measured baseline this change removes for the request handler, and
    # the behaviour embedded callers still have until their own slice lands.
    assert runtime.checked_out_during_call == [1]


def test_http_invocation_releases_pool_before_provider(pooled_engine) -> None:
    factory = sessionmaker(bind=pooled_engine, autoflush=False, expire_on_commit=False)
    seed_committed_endpoint(factory)
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    runtime = PoolProbeRuntime(pooled_engine)
    app.state.model_invocation_runtime = runtime
    with TestClient(app) as client:
        response = client.post(
            "/platform/models/invocations",
            json=invocation_request().model_dump(mode="json"),
        )
    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    assert runtime.checked_out_during_call == [0]


async def test_overlapping_deliveries_replay_the_committed_in_flight_claim(
    pooled_engine,
) -> None:
    factory = sessionmaker(bind=pooled_engine, autoflush=False, expire_on_commit=False)
    seed_committed_endpoint(factory)
    entered = asyncio.Event()
    release = asyncio.Event()

    class PausedRuntime(RecordingModelInvocationRuntime):
        async def invoke(self, request):
            entered.set()
            await release.wait()
            return await super().invoke(request)

    runtime = PausedRuntime()

    async def first_delivery():
        with session_scope(factory) as session:
            return await invoke_model(
                AxisPersistenceRepository(session), invocation_request(), runtime,
                commit_before_provider_call=True, usage_metering_enabled=True,
            )

    task = asyncio.create_task(first_delivery())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert pooled_engine.pool.checkedout() == 0
        duplicate_runtime = RecordingModelInvocationRuntime()
        with session_scope(factory) as session:
            replay = await invoke_model(
                AxisPersistenceRepository(session), invocation_request(), duplicate_runtime,
                commit_before_provider_call=True, usage_metering_enabled=True,
            )
        assert replay.status == MODEL_INVOCATION_REQUESTED_STATUS
        assert replay.idempotent_replay is True
        assert IN_FLIGHT_REPLAY_NOTE in replay.notes
        assert duplicate_runtime.requests == []
        release.set()
        completed = await asyncio.wait_for(task, timeout=5)
        assert completed.invocation_id == replay.invocation_id
        assert completed.status == "completed"
        assert len(runtime.requests) == 1
        with session_scope(factory) as session:
            assert len(session.scalars(select(ModelInvocation)).all()) == 1
            assert len(session.scalars(select(TenantUsageEvent)).all()) == 3
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("failure_phase", ["prepare", "finalize"])
async def test_commit_failure_never_reissues_a_provider_call(
    pooled_engine, monkeypatch, failure_phase,
) -> None:
    factory = sessionmaker(bind=pooled_engine, autoflush=False, expire_on_commit=False)
    seed_committed_endpoint(factory)
    runtime = RecordingModelInvocationRuntime()
    with pytest.raises(RuntimeError, match="commit failed"), session_scope(factory) as session:
        real_commit = session.commit
        calls = 0

        def fail_commit():
            nonlocal calls
            calls += 1
            if calls == (1 if failure_phase == "prepare" else 2):
                raise RuntimeError("commit failed")
            real_commit()

        monkeypatch.setattr(session, "commit", fail_commit)
        await invoke_model(
            AxisPersistenceRepository(session), invocation_request(), runtime,
            commit_before_provider_call=True, usage_metering_enabled=True,
        )
    with session_scope(factory) as session:
        records = session.scalars(select(ModelInvocation)).all()
        assert session.scalars(select(TenantUsageEvent)).all() == []
        if failure_phase == "prepare":
            assert records == []
            assert runtime.requests == []
        else:
            assert len(records) == 1
            assert records[0].status == MODEL_INVOCATION_REQUESTED_STATUS
            assert len(runtime.requests) == 1
            replay_runtime = RecordingModelInvocationRuntime()
            replay = await invoke_model(
                AxisPersistenceRepository(session), invocation_request(), replay_runtime,
                commit_before_provider_call=True,
            )
            assert replay.idempotent_replay is True
            assert replay_runtime.requests == []
