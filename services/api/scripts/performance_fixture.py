"""Disposable, network-free HTTP fixtures for the versioned performance workloads.

Only the local harness imports this module. Identity verification and external
ports are explicit fakes; the actual API authorization, domain, SQL and audit
paths remain in use. No test module or operator configuration is loaded.
"""

import asyncio
import gzip
import hashlib
import json
import math
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from runpy import run_path
from tempfile import TemporaryDirectory

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcAuthenticationError, OidcPrincipal
from axis_api.main import create_app
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
    ConnectorOntologyProposalCreate,
    ConnectorRunCreate,
    DemoReferenceRecordCreate,
    TenantCreate,
)
from axis_api.workflow_runtime import WorkflowSignalResult

ROOT = Path(__file__).resolve().parents[3]
WORKLOADS = ROOT / "services/api/benchmarks/workloads.v1.json"
JOURNEYS = ("console", "ingestion-preview", "workflow-signal", "model-invocation")
SCOPES = [
    "connectors:read",
    "connectors:file_csv:preview",
    "supply:read",
    "approvals:supply:request",
    MODEL_INVOKE_SCOPE,
]


class FixtureSettings(Settings):
    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, **_sources):
        return (init_settings,)


def read_json(path: Path):
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("Nonfinite JSON number")

    content = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return json.loads(content, object_pairs_hook=unique_fields, parse_constant=nonfinite)


def load_workloads(path: Path = WORKLOADS) -> dict:
    workload = read_json(path)
    if type(workload["schema_version"]) is not int or workload["schema_version"] != 1:
        raise ValueError("Unsupported workload schema")
    for seed in workload["seed_sources"].values():
        source = (ROOT / seed["path"]).resolve()
        if (
            not source.is_relative_to(ROOT)
            or hashlib.sha256(source.read_bytes()).hexdigest() != (seed["sha256"])
        ):
            raise ValueError("Versioned seed hash mismatch")
    for profile in workload["profiles"].values():
        for key, maximum in (
            ("tenants", 100),
            ("connectors_per_tenant", 1000),
            ("csv_rows", 500),
            ("runs_per_tenant", 1000),
            ("proposals_per_tenant", 1000),
            ("concurrency", 32),
            ("warmup_requests", 100),
            ("load_seconds", 3600),
            ("soak_seconds", 3600),
            ("model_delay_ms", 1000),
            ("workflow_delay_ms", 1000),
            ("request_timeout_seconds", 30),
        ):
            if type(profile[key]) is not int or not 1 <= profile[key] <= maximum:
                raise ValueError(f"Invalid workload bound: {key}")
        if set(profile["journeys"]) != set(JOURNEYS):
            raise ValueError("Workload must declare every implemented journey")
        for budget in profile["journeys"].values():
            for key in ("rps", "p95_ms", "p99_ms", "max_sql_statements", "max_response_bytes"):
                if type(budget[key]) is not int or budget[key] <= 0:
                    raise ValueError(f"Invalid journey budget: {key}")
            if budget["rps"] > 100 or budget["p95_ms"] > budget["p99_ms"]:
                raise ValueError("Invalid rate or latency budget")
        if set(profile["resource_budgets"]) != {
            "process_rss_mb",
            "cpu_cores",
            "max_pool_connections",
            "max_database_growth_mb_per_minute",
        } or any(
            type(value) is not int or value <= 0 for value in profile["resource_budgets"].values()
        ):
            raise ValueError("Invalid resource budget")
    return workload


def require_finite_numbers(value):
    if isinstance(value, dict):
        for item in value.values():
            require_finite_numbers(item)
    elif isinstance(value, list):
        for item in value:
            require_finite_numbers(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite measurement")


class FixtureIdentity:
    def __init__(self, tenants):
        self.tenants = tenants

    def verify_authorization_header(self, authorization):
        # Tokens are fixture selectors, never JWTs or usable credentials.
        prefix = "Bearer fixture:"
        if not authorization or not authorization.startswith(prefix):
            raise OidcAuthenticationError("invalid_fixture_identity")
        tenant = authorization[len(prefix) :]
        if tenant not in self.tenants:
            raise OidcAuthenticationError("unknown_fixture_tenant")
        return OidcPrincipal(actor_id="benchmark", tenant_id=tenant, scopes=SCOPES)


class FixtureModels:
    def __init__(self, delay_ms):
        self.delay_ms = delay_ms
        self.calls = 0

    async def invoke(self, request):
        self.calls += 1
        await asyncio.sleep(self.delay_ms / 1000)
        return ModelInvocationRuntimeResult(
            adapter="axis-performance-fixture",
            status="model_invocation_completed",
            output_text="Synthetic benchmark result.",
            input_tokens=20,
            output_tokens=5,
            latency_ms=self.delay_ms,
        )


class FixtureWorkflows:
    def __init__(self, delay_ms):
        self.delay_ms = delay_ms
        self.calls = 0

    async def signal_action_run(self, request):
        self.calls += 1
        await asyncio.sleep(self.delay_ms / 1000)
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="action_signal_requested",
            adapter="axis-performance-fixture",
            signal_name=request.signal_name,
        )


@contextmanager
def fixture(profile: dict, workload: dict):
    with TemporaryDirectory(prefix="axis-performance-") as directory:
        database = Path(directory) / "fixture.sqlite"
        app = create_app(
            FixtureSettings(
                postgres_dsn=f"sqlite+pysqlite:///{database}",
                oidc_auth_required=True,
                tenant_admission_mode="registered_only",
                api_rate_limit_enabled=False,
                workflow_signals_enabled=False,
                model_routing_execution_enabled=False,
                otel_enabled=False,
            )
        )
        engine = app.state.session_factory.kw["bind"]
        Base.metadata.create_all(engine)
        tenants = [f"benchmark-tenant-{index:03}" for index in range(profile["tenants"])]
        app.state.identity_verifier = FixtureIdentity(tenants)
        app.state.model_invocation_runtime = FixtureModels(profile["model_delay_ms"])
        app.state.workflow_runtime = FixtureWorkflows(profile["workflow_delay_ms"])
        seeds = {
            key: run_path(str(ROOT / seed["path"]))[seed["symbol"]]
            for key, seed in workload["seed_sources"].items()
        }
        try:
            with session_scope(app.state.session_factory) as session:
                repository = AxisPersistenceRepository(session)
                for tenant in tenants:
                    repository.create_tenant(
                        TenantCreate(
                            tenant_id=tenant,
                            display_name=tenant,
                            created_by="benchmark",
                        )
                    )
                    for key, original in seeds.items():
                        payload = deepcopy(original)
                        payload["tenant_id"] = tenant
                        if key == "connectors":
                            template = payload["connectors"][0]
                            payload["connectors"] = [deepcopy(template)]
                            for index in range(1, profile["connectors_per_tenant"]):
                                connector = deepcopy(template)
                                connector["manifest"]["connector_id"] = f"fixture-{index:04}"
                                connector["manifest"]["display_name"] = f"Fixture {index:04}"
                                payload["connectors"].append(connector)
                        seed = workload["seed_sources"][key]
                        repository.upsert_demo_reference_record(
                            DemoReferenceRecordCreate(
                                tenant_id=tenant,
                                surface=seed["surface"],
                                reference_id=seed["reference_id"],
                                status="active",
                                source="performance-fixture",
                                version=workload["dataset_version"],
                                payload=payload,
                            )
                        )
                    record_model_endpoint(
                        repository,
                        ModelEndpointCreateRequest(
                            tenant_id=tenant,
                            endpoint_id="fixture-model",
                            display_name="Fixture",
                            provider_type="openai_compatible",
                            hosting_boundary="self_hosted",
                            base_url="http://fixture.invalid",
                            default_model="synthetic",
                            task_types=["summarize"],
                            created_by="benchmark",
                            actor_scopes=[MODEL_ENDPOINT_ADMIN_SCOPE],
                        ),
                    )
                    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
                    for index in range(profile["runs_per_tenant"]):
                        run = repository.create_connector_run(
                            ConnectorRunCreate(
                                tenant_id=tenant,
                                connector_id="file_csv_manufacturing_assets",
                                run_id=f"fixture-run-{index:04}",
                                requested_by="benchmark",
                                status="sync_execution_completed",
                                result_summary={"records_read": "10"},
                            )
                        )
                        run.created_at = timestamp + timedelta(seconds=index)
                    for index in range(profile["proposals_per_tenant"]):
                        proposal = repository.create_connector_ontology_proposal(
                            ConnectorOntologyProposalCreate(
                                tenant_id=tenant,
                                connector_id="file_csv_manufacturing_assets",
                                proposal_id=f"fixture-proposal-{index:04}",
                                proposed_by="benchmark",
                                source_file_name="fixture.csv",
                                mapping_profile="benchmark",
                                node_id=f"fixture-{index}",
                                node_type="asset",
                                ontology_type="manufacturing_asset",
                            )
                        )
                        proposal.created_at = timestamp + timedelta(seconds=index)
            yield app, engine, database, tenants
        finally:
            engine.dispose()


def request_spec(journey, tenant, sequence, profile):
    headers = {"Authorization": f"Bearer fixture:{tenant}"}
    common = {"headers": headers}
    if journey == "console":
        return (
            "GET",
            "/operations/connectors/workspace",
            {
                **common,
                "params": {"tenant_id": tenant, "limit": 25},
            },
        )
    if journey == "ingestion-preview":
        csv = "asset_id,asset_name,domain,station,risk_level\n" + "".join(
            f"fixture-{index},Asset {index},Operations,Line 1,low\n"
            for index in range(profile["csv_rows"])
        )
        return (
            "POST",
            "/operations/connectors/file-csv/preview",
            {
                **common,
                "json": {"tenant_id": tenant, "file_name": "fixture.csv", "csv_content": csv},
            },
        )
    payload = {
        "actor_id": "benchmark",
        "actor_scopes": SCOPES,
        "idempotency_key": f"{journey}-{sequence}",
    }
    if journey == "workflow-signal":
        return (
            "POST",
            "/operations/actions/request_supplier_expedite/runs",
            {
                **common,
                "params": {"tenant_id": tenant},
                "json": {
                    **payload,
                    "payload": {
                        "supplier_batch_id": "asset_motors_batch",
                        "target_arrival": "2026-06-22T08:00:00+02:00",
                        "reason": "Synthetic benchmark",
                        "cost_ceiling_eur": "1200",
                    },
                },
            },
        )
    if journey == "model-invocation":
        return (
            "POST",
            "/platform/models/invocations",
            {
                **common,
                "json": {
                    **payload,
                    "tenant_id": tenant,
                    "task_type": "summarize",
                    "prompt": "Synthetic benchmark.",
                },
            },
        )
    raise ValueError(f"Unknown journey: {journey}")


def validate_response(journey, response, tenant, profile):
    """A fast HTTP error or empty/deferred answer must never improve a baseline."""
    response.raise_for_status()
    body = response.json()
    if body["tenant_id"] != tenant:
        raise ValueError("Response tenant mismatch")
    if journey == "console":
        valid = (
            body["total_connectors"] == profile["connectors_per_tenant"]
            and len(body["connectors"]) == min(25, profile["connectors_per_tenant"])
            and body["counts"]["runs"] == min(100, profile["runs_per_tenant"])
            and body["counts"]["pending_proposals"] == min(100, profile["proposals_per_tenant"])
            and all(value is not None for value in body["counts"].values())
        )
    elif journey == "ingestion-preview":
        valid = body["preview_status"] == "ready" and (
            body["accepted_record_count"] == profile["csv_rows"]
        )
    elif journey == "workflow-signal":
        valid = body["persisted"] and body["workflow_signal_status"] == "action_signal_requested"
    else:
        valid = body["status"] == "completed" and not body["idempotent_replay"]
    if not valid:
        raise ValueError("Journey did not complete its expected work")
