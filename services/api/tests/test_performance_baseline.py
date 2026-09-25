"""The measurement contract is tested; CI does not gate noisy machine latency."""

import asyncio
import hashlib
import importlib
import json
import socket
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError


@pytest.fixture
def benchmark(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("benchmark_performance")


@pytest.fixture
def workload(benchmark):
    return benchmark.load_workloads()


def test_nearest_rank_and_empty_distributions(benchmark):
    assert benchmark.distribution([]) == {
        "count": 0,
        "p50": None,
        "p95": None,
        "p99": None,
        "max": None,
    }
    assert benchmark.distribution(list(range(1, 101))) == {
        "count": 100,
        "p50": 50,
        "p95": 95,
        "p99": 99,
        "max": 100,
    }


def test_published_capture_accounting_and_profile_artifacts(benchmark):
    directory = Path(__file__).resolve().parents[3] / "docs/benchmarks/performance-v1"
    captures = list(directory.glob("*.json.gz"))
    assert len(captures) == 8
    for path in captures:
        benchmark.validate_report(benchmark.read_json(path))
    for name in ("console-sme.svg", "console-enterprise.svg"):
        assert ElementTree.parse(directory / name).getroot().tag.endswith("svg")
    manifest = benchmark.read_json(directory / "manifest.json")
    recorded = {item["path"] for item in manifest["artifacts"]}
    assert recorded == {
        path.name for path in directory.iterdir() if path.name not in {"README.md", "manifest.json"}
    }
    for item in manifest["artifacts"]:
        content = (directory / item["path"]).read_bytes()
        assert len(content) == item["bytes"]
        assert hashlib.sha256(content).hexdigest() == item["sha256"]


@pytest.mark.parametrize(
    "key,value",
    [("tenants", 0), ("csv_rows", 501), ("concurrency", True), ("soak_seconds", 100000)],
)
def test_workload_bounds_fail_before_fixture_creation(benchmark, workload, tmp_path, key, value):
    workload["profiles"]["sme-single-node"][key] = value
    path = tmp_path / "workload.json"
    path.write_text(json.dumps(workload))
    with pytest.raises(ValueError, match="Invalid workload bound"):
        benchmark.load_workloads(path)


def test_changed_seed_requires_a_versioned_manifest_update(benchmark, workload, tmp_path):
    workload["seed_sources"]["connectors"]["sha256"] = "0" * 64
    path = tmp_path / "workload.json"
    path.write_text(json.dumps(workload))
    with pytest.raises(ValueError, match="seed hash mismatch"):
        benchmark.load_workloads(path)


@pytest.mark.parametrize("profile_name", ["sme-single-node", "enterprise"])
async def test_real_journeys_preserve_identity_tenancy_and_work(
    benchmark, workload, monkeypatch, profile_name
):
    def no_network(*_args, **_kwargs):
        raise AssertionError("The local benchmark must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setenv("AXIS_POSTGRES_DSN", "postgresql://unwanted.invalid/database")
    monkeypatch.setenv("AXIS_MODEL_ROUTING_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("AXIS_WORKFLOW_SIGNALS_ENABLED", "true")
    monkeypatch.setenv("AXIS_OTEL_ENABLED", "true")
    profile = workload["profiles"][profile_name]
    with benchmark.fixture(profile, workload) as (app, engine, database, tenants):
        assert app.state.settings.postgres_dsn.startswith("sqlite+")
        assert app.state.settings.workflow_signals_enabled is False
        assert app.state.settings.otel_enabled is False
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid"
        ) as client:
            for journey in benchmark.JOURNEYS:
                method, path, kwargs = benchmark.request_spec(journey, tenants[-1], 0, profile)
                response = await client.request(method, path, **kwargs)
                benchmark.validate_response(journey, response, tenants[-1], profile)
                broken = response.json()
                field, value = {
                    "console": ("total_connectors", 0),
                    "ingestion-preview": ("accepted_record_count", 0),
                    "workflow-signal": ("workflow_signal_status", "deferred"),
                    "model-invocation": ("status", "requested"),
                }[journey]
                broken[field] = value
                with pytest.raises(ValueError, match="expected work"):
                    benchmark.validate_response(
                        journey,
                        httpx.Response(200, json=broken, request=response.request),
                        tenants[-1],
                        profile,
                    )
                unauthorized = {**kwargs, "headers": {}}
                assert (await client.request(method, path, **unauthorized)).status_code == 401
                foreign = {**kwargs, "headers": {"Authorization": f"Bearer fixture:{tenants[0]}"}}
                assert (await client.request(method, path, **foreign)).status_code == 403
            assert app.state.model_invocation_runtime.calls == 1
            assert app.state.workflow_runtime.calls == 1
            # Each write traversed a real audit append, not a static HTTP fixture.
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT COUNT(*) FROM audit_events")) > 0
    assert not database.exists()


async def test_measurement_records_real_sql_pool_release_and_samples(benchmark, workload, tmp_path):
    result = await benchmark.measure(
        workload, workload["profiles"]["sme-single-node"], "console", 0.2, "load", tmp_path, 0
    )
    assert result["summary"]["offered"] == 2
    assert result["summary"]["errors"] == {}
    assert result["summary"]["sql_statements"]["max"] > 0
    assert result["summary"]["sql_ms"]["max"] > 0
    assert result["resources"]["pool_peak"] >= 1
    assert result["resources"]["pool_at_end"] == 0
    assert result["budget"]["status"] in {"NOT RUN", "FAIL"}  # two samples cannot certify p99
    assert len(result["samples"]) == result["summary"]["offered"]
    assert result["resources"]["query_fingerprints"]
    assert "benchmark-tenant" not in json.dumps(result)


async def test_request_timeout_is_retained_as_failure_and_releases_pool(
    benchmark, workload, tmp_path
):
    profile = deepcopy(workload["profiles"]["sme-single-node"])
    profile["request_timeout_seconds"] = 0.1
    profile["model_delay_ms"] = 500
    result = await benchmark.measure(
        workload, profile, "model-invocation", 0.1, "load", tmp_path, 0
    )
    assert result["summary"]["errors"] == {"TimeoutError": 1}
    assert result["summary"]["successful"] == 0
    assert result["budget"]["status"] == "FAIL"
    assert result["resources"]["pool_at_end"] == 0


@pytest.mark.parametrize(
    "content", ['{"schema_version":1,"schema_version":1}', '{"schema_version":NaN}']
)
def test_ambiguous_or_nonfinite_json_is_rejected(benchmark, tmp_path, content):
    path = tmp_path / "invalid.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        benchmark.read_json(path)


async def test_arrivals_account_for_saturation_without_an_unbounded_queue(benchmark):
    active = 0
    peak = 0

    async def slow(index, scheduled, arrival):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.1)
        active -= 1
        return {"sequence": index, "ok": True, "dropped": False, "arrival_seconds": arrival}

    records, _ = await benchmark.arrivals(slow, seconds=0.2, rps=100, concurrency=1)
    assert len(records) == 20
    assert peak == 1
    assert any(record["dropped"] for record in records)
    assert sorted(record["sequence"] for record in records) == list(range(20))


async def test_fatal_generator_failure_is_not_lost_in_a_finished_task(benchmark):
    async def broken(*_args):
        raise RuntimeError("fixture failure")

    with pytest.raises(ExceptionGroup):
        await benchmark.arrivals(broken, seconds=0.1, rps=100, concurrency=2)


def test_sql_failure_is_counted_without_recording_query_values(benchmark):
    engine = create_engine("sqlite://")
    request = benchmark.RequestMetrics()
    token = benchmark.REQUEST_METRICS.set(request)
    try:
        with benchmark.DatabaseMetrics(engine) as metrics:
            with engine.connect() as connection, pytest.raises(OperationalError):
                connection.execute(
                    text("SELECT :secret FROM absent_table"), {"secret": "sensitive-value"}
                )
            snapshot = metrics.snapshot(1)
        assert request.statements == 1
        assert request.sql_ms > 0
        assert snapshot["pool_at_end"] == 0
        assert snapshot["query_fingerprints"][0]["count"] == 1
        serialized = json.dumps(snapshot)
        assert "sensitive-value" not in serialized
        assert "absent_table" not in serialized
    finally:
        benchmark.REQUEST_METRICS.reset(token)
        engine.dispose()


def test_svg_is_valid_and_escapes_frame_labels(benchmark):
    metrics = importlib.import_module("performance_metrics")
    result = metrics.flamegraph({("root", "<script>&:function:1"): 3, ("root", "other"): 1})
    root = ElementTree.fromstring(result)
    assert root.tag.endswith("svg")
    assert "&lt;script&gt;&amp;" in result
    assert "4 collected stacks" in result
    assert "frame locals" not in result


@pytest.fixture
def report(benchmark, workload):
    samples = [
        {
            "sequence": index,
            "arrival_seconds": index / 10,
            "ok": True,
            "error": None,
            "dropped": False,
            "latency_ms": 20,
            "service_ms": 19,
            "scheduler_lag_ms": 1,
            "sql_ms": 1,
            "statements": 30,
            "response_bytes": 6000,
        }
        for index in range(100)
    ]
    summary = benchmark.summarize(samples, 10, 10)
    resources = {
        "pool_at_end": 0,
        "pool_peak": 1,
        "pool_mean_occupied": 0.1,
        "process_peak_rss_mb": 200,
        "cpu_cores_used": 0.1,
        "database_growth_mb_per_minute": 1,
    }
    return {
        "schema_version": 1,
        "complete": True,
        "provenance": {
            "harness_sha256": "h",
            "dataset_sha256": "d",
            "environment": {},
            "profile": "sme-single-node",
            "parameters": workload["profiles"]["sme-single-node"],
            "mode": "load",
            "seconds_per_journey": 10,
            "journeys": ["console"],
            "backend": "test",
        },
        "runs": [
            {
                "trial": trial,
                "journey": "console",
                "summary": deepcopy(summary),
                "resources": deepcopy(resources),
                "samples": deepcopy(samples),
                "budget": benchmark.evaluate(
                    summary,
                    resources,
                    workload["profiles"]["sme-single-node"]["journeys"]["console"],
                    workload["profiles"]["sme-single-node"]["resource_budgets"],
                ),
            }
            for trial in range(3)
        ],
    }


def test_compatible_identical_reports_pass(benchmark, report):
    assert benchmark.compare(report, deepcopy(report))["status"] == "PASS"


@pytest.mark.parametrize(
    "key",
    [
        "dataset_sha256",
        "harness_sha256",
        "profile",
        "environment",
        "mode",
        "backend",
        "seconds_per_journey",
    ],
)
def test_incompatible_reports_never_pass(benchmark, report, key):
    changed = deepcopy(report)
    changed["provenance"][key] = "different"
    with pytest.raises((ValueError, TypeError)):
        benchmark.compare(report, changed)


def test_partial_and_tampered_evidence_cannot_pass(benchmark, report):
    partial = deepcopy(report)
    partial["complete"] = False
    with pytest.raises(ValueError, match="Incomplete"):
        benchmark.compare(report, partial)
    corrupt = deepcopy(report)
    corrupt["runs"][0]["summary"]["successful"] = 101
    with pytest.raises(ValueError, match="differs"):
        benchmark.compare(report, corrupt)
    nonfinite = deepcopy(report)
    nonfinite["runs"][0]["resources"]["cpu_cores_used"] = float("nan")
    with pytest.raises(ValueError, match="Nonfinite"):
        benchmark.compare(report, nonfinite)


def test_insufficient_repetitions_never_pass(benchmark, report):
    changed = deepcopy(report)
    changed["runs"].pop()
    with pytest.raises(ValueError, match="three trials"):
        benchmark.compare(report, changed)


def test_unequal_batches_and_false_budget_results_are_rejected(benchmark, report):
    changed = deepcopy(report)
    extra = deepcopy(changed["runs"][0])
    extra["trial"] = 3
    changed["runs"].append(extra)
    with pytest.raises(ValueError, match="same number"):
        benchmark.compare(report, changed)
    changed = deepcopy(report)
    changed["runs"][0]["budget"]["status"] = "FAIL"
    with pytest.raises(ValueError, match="Stored budget"):
        benchmark.compare(report, changed)


def test_negative_latency_cannot_be_presented_as_improved_work(benchmark, report):
    changed = deepcopy(report)
    change_latencies(benchmark, changed, [-1, -1, -1])
    with pytest.raises(ValueError, match="Invalid response timing"):
        benchmark.compare(report, changed)


def change_latencies(benchmark, report, values):
    for run, latency in zip(report["runs"], values, strict=True):
        for sample in run["samples"]:
            sample["latency_ms"] = latency
        run["summary"] = benchmark.summarize(run["samples"], 10, 10)


def test_latency_regression_and_noise_are_different_outcomes(benchmark, report):
    slower = deepcopy(report)
    change_latencies(benchmark, slower, [30, 30, 30])
    assert benchmark.compare(report, slower)["status"] == "FAIL"
    noisy = deepcopy(report)
    change_latencies(benchmark, noisy, [20, 21, 80])
    assert benchmark.compare(report, noisy)["status"] == "NOT RUN"


def test_new_queries_or_resource_growth_cannot_hide_behind_fast_latency(benchmark, report):
    increased = deepcopy(report)
    for run in increased["runs"]:
        run["resources"]["process_peak_rss_mb"] = 400
    assert benchmark.compare(report, increased)["status"] == "FAIL"
    queries = deepcopy(report)
    for run in queries["runs"]:
        for sample in run["samples"]:
            sample["statements"] = 31
        run["summary"] = benchmark.summarize(run["samples"], 10, 10)
    assert benchmark.compare(report, queries)["status"] == "FAIL"


def test_budget_failures_and_profiler_evidence_are_not_certified(benchmark, workload, report):
    run = report["runs"][0]
    profile = workload["profiles"]["sme-single-node"]
    budget = profile["journeys"]["console"]
    assert (
        benchmark.evaluate(
            run["summary"], run["resources"], budget, profile["resource_budgets"], profiled=True
        )["status"]
        == "NOT RUN"
    )
    broken = deepcopy(run["summary"])
    broken["errors"] = {"TimeoutError": 1}
    result = benchmark.evaluate(broken, run["resources"], budget, profile["resource_budgets"])
    assert result["status"] == "FAIL"
    assert "errors_or_dropped_arrivals" in result["failures"]
