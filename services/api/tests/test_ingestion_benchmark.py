"""Deterministic experiment contracts, never shared-runner latency assertions."""

import gzip
import hashlib
import importlib
import json
import socket
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest
from axis_sdk.connector_authoring import ConnectorError
from pydantic import ValidationError


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return tuple(
        importlib.import_module(name)
        for name in (
            "benchmark_ingestion",
            "ingestion_fixture",
            "ingestion_pipeline",
        )
    )


@pytest.fixture
def workload(modules):
    return modules[0].PROFILES["smoke"].model_copy(update={"records": 8, "page_records": 2})


@pytest.fixture
def corpus(modules, workload):
    with modules[1].corpus(workload) as value:
        yield value
    assert not value.root.exists()


@pytest.mark.parametrize("kind", ["rest", "database", "object", "document"])
def test_strategies_complete_identical_work_and_bound_memory(modules, corpus, kind, monkeypatch):
    benchmark, fixture, pipeline = modules

    def no_network(*_args, **_kwargs):
        raise AssertionError("benchmark opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setenv("AXIS_POSTGRES_DSN", "postgresql://unwanted.invalid/database")
    monkeypatch.setenv("AXIS_S3_SOURCE_INGESTION_ENABLED", "true")
    completed = []
    results = {}
    for mode in pipeline.MODES:
        result = pipeline.execute(corpus, kind, mode)
        benchmark.validate_trial(result, corpus.workload)
        assert not result["rejected"]
        assert all(row["status"] == "PASS" for row in result["samples"])
        encoded_result = json.dumps(result, ensure_ascii=False)
        assert "approved/" not in encoded_result and "é" not in encoded_result
        completed.append(
            sorted(
                (r["tenant"], r["job"], r["payload_sha256"], r["checkpoint_sha256"], r["bytes"])
                for r in result["samples"]
            )
        )
        for sample in result["samples"]:
            assert sample["payload_sha256"] == corpus.expected[kind, sample["tenant"]]
            assert sample["records"] == corpus.workload.records
        results[mode] = result
    assert all(value == completed[0] for value in completed)
    assert results["materialized-serial"]["buffered_rows_peak"] == corpus.workload.records
    assert results["streamed-serial"]["buffered_rows_peak"] == corpus.workload.page_records
    assert results["streamed-parallel"]["buffered_rows_peak"] <= (
        corpus.workload.workers * corpus.workload.page_records
    )
    assert corpus.revision == fixture.digest(corpus.workload.model_dump())


@pytest.mark.parametrize("kind", ["rest", "database", "object", "document"])
@pytest.mark.parametrize("materialize", [False, True])
def test_failed_sink_resumes_only_acknowledged_checkpoint(modules, corpus, kind, materialize):
    _benchmark, _fixture, pipeline = modules
    with corpus.source(kind, "heavy") as source:
        sink = pipeline.DigestSink(source, fail_page=1)
        meter = pipeline.BufferMeter()
        with pytest.raises(OSError):
            pipeline.consume(source, sink, materialize=materialize, meter=meter)
        assert sink.rows == corpus.workload.page_records
        assert sink.position.checkpoint is not None
        assert meter.rows == meter.bytes == 0
        sink.fail_page = None
        pipeline.consume(source, sink, materialize=materialize, meter=meter)
        assert sink.rows == corpus.workload.records
        assert sink.hash.hexdigest() == corpus.expected[kind, "heavy"]
        assert meter.rows == meter.bytes == 0


@pytest.mark.parametrize("materialize", [False, True])
def test_partial_read_preserves_commit_boundary(modules, corpus, materialize, monkeypatch):
    _benchmark, _fixture, pipeline = modules
    with corpus.source("object", "heavy") as source:
        original = source.read
        calls = 0

        def broken(position):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("fixture source interrupted")
            return original(position)

        monkeypatch.setattr(source, "read", broken)
        sink, meter = pipeline.DigestSink(source), pipeline.BufferMeter()
        with pytest.raises(OSError):
            pipeline.consume(source, sink, materialize=materialize, meter=meter)
        assert sink.rows == (0 if materialize else corpus.workload.page_records)
        assert meter.rows == meter.bytes == 0
        monkeypatch.setattr(source, "read", original)
        pipeline.consume(source, sink, materialize=materialize, meter=meter)
        assert sink.hash.hexdigest() == corpus.expected["object", "heavy"]


@pytest.mark.parametrize("kind", ["rest", "database", "object", "document"])
def test_duplicate_delivery_and_conflicting_replay(modules, corpus, kind):
    _benchmark, fixture, pipeline = modules
    with corpus.source(kind, "heavy") as source:
        batch, candidate = source.read(fixture.Position())
        sink = pipeline.DigestSink(source)
        sink.commit(batch, candidate)
        before = sink.hash.hexdigest(), sink.rows, sink.pages
        sink.commit(batch, candidate)
        assert (sink.hash.hexdigest(), sink.rows, sink.pages) == before
        changed = deepcopy(batch.records)
        changed[0]["text"] = "different fixture"
        with pytest.raises(ValueError, match="conflicting replay"):
            sink.commit(batch.model_copy(update={"records": changed}), candidate)
        assert (sink.hash.hexdigest(), sink.rows, sink.pages) == before
        with corpus.source(kind, "light-a") as other:
            with pytest.raises(ConnectorError, match="invalid_checkpoint"):
                pipeline.DigestSink(other).commit(batch, candidate)
            with pytest.raises(ValidationError, match="Checkpoint does not match"):
                other.read(candidate)


def test_page_byte_row_and_timeout_limits_fail_without_false_completion(
    modules, corpus, monkeypatch
):
    _benchmark, fixture, pipeline = modules
    with corpus.source("rest", "heavy") as source:
        sink, meter = pipeline.DigestSink(source), pipeline.BufferMeter()
        source.limits = source.limits.model_copy(update={"max_bytes": 10})
        with pytest.raises(ConnectorError, match="limit_exceeded"):
            pipeline.consume(source, sink, materialize=False, meter=meter)
        assert sink.rows == 0 and sink.position.checkpoint is None
    with corpus.source("rest", "heavy") as source:
        source.workload = source.workload.model_copy(update={"max_pages": 1})
        sink, meter = pipeline.DigestSink(source), pipeline.BufferMeter()
        with pytest.raises(ValueError, match="page limit"):
            pipeline.consume(source, sink, materialize=True, meter=meter)
        assert sink.rows == 0 and meter.rows == meter.bytes == 0
    with corpus.source("rest", "heavy") as source:
        source.workload = source.workload.model_copy(update={"job_bytes": 1})
        sink, meter = pipeline.DigestSink(source), pipeline.BufferMeter()
        with pytest.raises(ValueError, match="byte limit"):
            pipeline.consume(source, sink, materialize=False, meter=meter)
        assert sink.rows == 0 and meter.rows == meter.bytes == 0
    with corpus.source("rest", "heavy") as source:
        batch, candidate = source.read(fixture.Position())
        source.workload = source.workload.model_copy(update={"records": 1})
        monkeypatch.setattr(source, "read", lambda _position: (batch, candidate))
        sink, meter = pipeline.DigestSink(source), pipeline.BufferMeter()
        with pytest.raises(ValueError, match="row limit"):
            pipeline.consume(source, sink, materialize=False, meter=meter)
        assert sink.rows == 0 and meter.rows == meter.bytes == 0
    with corpus.source("rest", "heavy") as source:
        ticks = iter((0, 0, 31))
        monkeypatch.setattr(pipeline, "monotonic", lambda: next(ticks))
        sink, meter = pipeline.DigestSink(source), pipeline.BufferMeter()
        with pytest.raises(TimeoutError):
            pipeline.consume(source, sink, materialize=False, meter=meter)
        assert sink.rows == 0 and sink.position.checkpoint is None


def test_backpressure_rejects_explicitly_and_recovers_capacity(modules):
    _benchmark, _fixture, pipeline = modules
    queue = pipeline.BoundedQueue(3, 2, fair=False)
    assert queue.offer(pipeline.Job("heavy", 0)) is None
    assert queue.offer(pipeline.Job("heavy", 1)) is None
    assert queue.offer(pipeline.Job("heavy", 2)) == "tenant_queue_full"
    assert queue.offer(pipeline.Job("light-a", 0)) is None
    assert queue.offer(pipeline.Job("light-b", 0)) == "queue_full"
    assert len(queue.pending) == queue.peak == 3
    first = queue.take()
    assert queue.offer(pipeline.Job("heavy", 3)) is None
    queue.finish(first)
    assert len(queue.pending) == 3 and not any(queue.active.values())


def test_last_acknowledgement_cannot_hide_an_exceeded_time_budget(modules, corpus, monkeypatch):
    _benchmark, _fixture, pipeline = modules
    with corpus.source("document", "heavy") as source:
        source.limits = source.limits.model_copy(update={"max_records": corpus.workload.records})
        ticks = iter((0, 0, 0, 31))
        monkeypatch.setattr(pipeline, "monotonic", lambda: next(ticks))
        sink, meter = pipeline.DigestSink(source), pipeline.BufferMeter()
        with pytest.raises(TimeoutError):
            pipeline.consume(source, sink, materialize=False, meter=meter)
        # Acknowledged work is retained truthfully even though the timing failed.
        assert sink.rows == corpus.workload.records and sink.position.checkpoint is not None
        assert meter.rows == meter.bytes == 0


def test_fair_turns_keep_a_slow_tenant_from_taking_every_slot(modules):
    _benchmark, _fixture, pipeline = modules
    queue = pipeline.BoundedQueue(8, 6, fair=True)
    for index in range(6):
        assert queue.offer(pipeline.Job("heavy", index)) is None
    for index in range(2):
        assert queue.offer(pipeline.Job("light", index)) is None
    heavy, light = queue.take(), queue.take()
    assert (heavy.tenant, light.tenant) == ("heavy", "light")
    assert queue.take() is None  # One active job per tenant, not an executor backlog.
    queue.finish(light)
    assert queue.take() == pipeline.Job("light", 1)
    assert queue.active["heavy"] == 1


def test_executor_parallelism_is_real_and_bounded(modules, corpus):
    _benchmark, _fixture, pipeline = modules
    barrier, lock = Barrier(corpus.workload.workers), Lock()
    active = peak = calls = 0

    def process(*args):
        nonlocal active, peak, calls
        with lock:
            index = calls
            calls += 1
            active += 1
            peak = max(peak, active)
        try:
            if index < corpus.workload.workers:
                barrier.wait(timeout=5)
            return pipeline.process_job(*args)
        finally:
            with lock:
                active -= 1

    result = pipeline.execute(corpus, "rest", "streamed-parallel", process=process)
    assert peak == result["active_peak"] == corpus.workload.workers
    assert active == 0 and all(row["status"] == "PASS" for row in result["samples"])


def test_light_tenant_finishes_while_heavy_tenant_is_waiting(modules, corpus):
    _benchmark, _fixture, pipeline = modules
    light_done = Event()

    def process(*args):
        job = args[2]
        if job.tenant == "heavy" and job.ordinal == 0:
            assert light_done.wait(timeout=5)
        result = pipeline.process_job(*args)
        if job.tenant == "light-a":
            light_done.set()
        return result

    result = pipeline.execute(corpus, "rest", "streamed-fair", process=process)
    assert [r["tenant"] for r in result["dispatch_order"][:3]] == ["heavy", "light-a", "light-b"]
    assert all(row["status"] == "PASS" for row in result["samples"])


@pytest.mark.parametrize(
    "changes",
    [
        {"workers": True},
        {"workers": 1000},
        {"queue_capacity": 0},
        {"records": 1001},
        {"page_bytes": 100},
        {"page_records": 100},
        {"max_pages": 1},
        {"job_bytes": 1024},
        {"endpoint": "https://unwanted.invalid"},
    ],
)
def test_invalid_workload_is_rejected_before_creating_fixtures(modules, changes):
    with pytest.raises(ValidationError):
        modules[1].Workload.model_validate(
            {**modules[0].PROFILES["representative"].model_dump(), **changes}
        )


def test_metrics_include_failures_and_rejected_jobs(modules, corpus, monkeypatch):
    benchmark, _fixture, pipeline = modules
    corpus.workload = corpus.workload.model_copy(update={"queue_capacity": 2})

    def fail(*_args, **_kwargs):
        raise OSError("private fixture payload must not enter evidence")

    monkeypatch.setattr(pipeline.DigestSink, "commit", fail)
    result = pipeline.execute(corpus, "document", "streamed-parallel")
    benchmark.validate_trial(result, corpus.workload)
    assert len(result["samples"]) == 2 and len(result["rejected"]) == 3
    assert all(row["status"] == "FAIL" and row["error"] == "OSError" for row in result["samples"])
    assert "private fixture" not in json.dumps(result)
    assert result["buffered_rows_at_end"] == result["buffered_bytes_at_end"] == 0


def test_failure_opening_source_is_counted(modules, corpus, monkeypatch):
    benchmark, _fixture, pipeline = modules

    def unavailable(*_args):
        raise OSError("private source path")

    monkeypatch.setattr(corpus, "source", unavailable)
    result = pipeline.execute(corpus, "database", "streamed-parallel")
    benchmark.validate_trial(result, corpus.workload)
    assert len(result["samples"]) == result["offered"]
    assert all(r["status"] == "FAIL" and r["records"] == 0 for r in result["samples"])
    assert "private source" not in json.dumps(result)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_ambiguous_or_nonfinite_reports_are_rejected(modules, raw):
    with pytest.raises(ValueError):
        modules[0].read_json(raw)


@pytest.fixture
def report(modules, corpus):
    benchmark, fixture, pipeline = modules
    results = []
    files = benchmark.source_hashes()
    for kind in fixture.KINDS:
        for mode in pipeline.MODES:
            result = pipeline.execute(corpus, kind, mode)
            result.update(
                trial=0,
                source_fingerprint=fixture.digest(files),
                memory={"python_peak_bytes": 1, "process_rss_high_water_bytes": 1},
            )
            results.append(result)
    return {
        "schema_version": 1,
        "scope": "synthetic-ingestion-strategy-comparison",
        "trials": 1,
        "workload": corpus.workload.model_dump(),
        "workload_sha256": fixture.digest(corpus.workload.model_dump()),
        "provenance": {"files": files},
        "results": results,
    }


def test_summary_requires_three_trials_and_preserves_failures(modules, report):
    benchmark = modules[0]
    summary = benchmark.summarize(report)
    assert summary["validation_status"] == "PASS"
    assert summary["comparison_status"] == summary["deployment_slo_status"] == "NOT RUN"
    assert all(row["seconds"]["direction"] == "NOT RUN" for row in summary["comparisons"])
    report["results"][0]["samples"][0].update(status="FAIL", error="TimeoutError")
    summary = benchmark.summarize(report)
    assert summary["validation_status"] == summary["comparison_status"] == "FAIL"
    assert summary["rows"][0]["failures"] == 1


@pytest.mark.parametrize(
    "failure",
    [
        "missing_trial",
        "duplicate_trial",
        "wrong_fixture",
        "different_runtime",
        "fast_empty",
        "different_payload",
        "different_checkpoint",
        "missing_job",
        "unbounded_workers",
    ],
)
def test_incomparable_or_incomplete_evidence_is_rejected(modules, report, failure):
    result = report["results"][0]
    sample = result["samples"][0]
    if failure == "missing_trial":
        report["results"].pop()
    elif failure == "duplicate_trial":
        report["results"].append(deepcopy(result))
    elif failure == "wrong_fixture":
        report["workload_sha256"] = "0" * 64
    elif failure == "different_runtime":
        result["source_fingerprint"] = "0" * 64
    elif failure == "fast_empty":
        sample["records"] = 0
    elif failure == "different_payload":
        sample["payload_sha256"] = "0" * 64
    elif failure == "different_checkpoint":
        sample["checkpoint_sha256"] = "0" * 64
    elif failure == "missing_job":
        result["samples"].pop()
    else:
        result["active_peak"] = 1000
    with pytest.raises(ValueError):
        modules[0].validate_report(report)


def test_three_trial_noise_policy(modules):
    compare = modules[0].compare_values
    assert compare([100] * 2, [50] * 2)["direction"] == "NOT RUN"
    assert compare([0] * 3, [50] * 3)["direction"] == "NOT RUN"
    assert compare([100, 101, 100], [102, 103, 102])["direction"] == "within-noise"
    assert compare([90, 110, 100], [85, 85, 85])["direction"] == "within-noise"
    assert compare([100] * 3, [80] * 3)["direction"] == "lower"
    assert compare([100] * 3, [120] * 3)["direction"] == "higher"


def test_capture_refuses_to_overwrite_existing_artifacts(modules, tmp_path):
    marker = tmp_path / "preserve.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="already exists"):
        modules[0].run("smoke", 1, tmp_path)
    assert marker.read_text() == "keep"


def test_fixture_caps_do_not_raise_current_extraction_limits(modules):
    from axis_api.config import Settings

    for workload in modules[0].PROFILES.values():
        assert (
            workload.records
            <= Settings.model_fields["source_ingestion_extraction_max_rows"].default
        )
        assert (
            workload.job_bytes
            <= Settings.model_fields["source_ingestion_extraction_max_bytes"].default
        )
        assert (
            workload.page_records
            <= Settings.model_fields["source_ingestion_extraction_page_size"].default
        )
        assert (
            workload.request_seconds
            <= Settings.model_fields["source_ingestion_extraction_time_budget_seconds"].default
        )


def test_checked_capture_integrity_and_derived_summaries(modules):
    benchmark = modules[0]
    directory = Path(__file__).resolve().parents[3] / "docs/benchmarks/ingestion-v1"
    manifest = benchmark.read_json((directory / "manifest.json").read_text())
    paths = {item["path"] for item in manifest["artifacts"]}
    assert paths == {
        path.name for path in directory.iterdir() if path.name not in {"README.md", "manifest.json"}
    }
    for item in manifest["artifacts"]:
        content = (directory / item["path"]).read_bytes()
        assert len(content) == item["bytes"]
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
    for profile in ("representative", "saturation"):
        with gzip.open(directory / f"{profile}.json.gz", "rt") as stream:
            report = benchmark.read_json(stream.read())
        benchmark.validate_report(report)
        assert report["trials"] == 3
        assert report["provenance"]["head"] == manifest["captured_source_commit"]
        assert not report["provenance"]["working_tree_dirty"]
        summary = benchmark.read_json((directory / f"{profile}-summary.json").read_text())
        assert benchmark.summarize(report) == summary
        assert summary["validation_status"] == summary["comparison_status"] == "PASS"
        assert summary["deployment_slo_status"] == "NOT RUN"
        rejected = [len(result["rejected"]) for result in report["results"]]
        assert set(rejected) == ({0} if profile == "representative" else {16})


def test_cli_smoke_writes_complete_verified_artifacts(modules, tmp_path):
    benchmark = modules[0]
    output = tmp_path / "capture"
    result = subprocess.run(
        [
            sys.executable,
            benchmark.__file__,
            "run",
            "--profile",
            "smoke",
            "--trials",
            "1",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    with gzip.open(output / "report.json.gz", "rt") as stream:
        report = benchmark.read_json(stream.read())
    summary = benchmark.read_json((output / "summary.json").read_text())
    benchmark.validate_report(report)
    assert len(report["results"]) == 16
    assert benchmark.summarize(report) == summary
    assert summary["validation_status"] == "PASS"
    assert summary["comparison_status"] == "NOT RUN"
    assert not (output / "partial.json").exists()
