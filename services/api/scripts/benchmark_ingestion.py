"""Run bounded ingestion strategy experiments in fresh processes.

The report compares candidates in this harness, not revisions of the production
dispatcher. Inputs are immutable synthetic fixtures and output contains only
timing, resource counts, fixture aliases and hashes.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import platform
import resource
import sqlite3
import subprocess
import sys
import tracemalloc
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from statistics import median

from ingestion_fixture import KINDS, PROVENANCE, Workload, canonical, corpus, digest
from ingestion_pipeline import MODES, execute, offered_jobs
from performance_metrics import distribution

ROOT = Path(__file__).resolve().parents[3]
PROFILES = {
    "smoke": Workload(
        records=16,
        text_bytes=128,
        page_records=4,
        heavy_jobs=3,
        light_jobs=1,
        source_delay_ms=0,
        sink_delay_ms=0,
    ),
    "representative": Workload(),
    "saturation": Workload(
        records=32,
        text_bytes=512,
        page_records=8,
        heavy_jobs=24,
        light_jobs=4,
        queue_capacity=16,
        tenant_queue_capacity=8,
    ),
}
SOURCE_FILES = (
    "services/api/scripts/benchmark_ingestion.py",
    "services/api/scripts/ingestion_fixture.py",
    "services/api/scripts/ingestion_pipeline.py",
    "services/api/scripts/performance_metrics.py",
    "services/api/src/axis_api/connector_s3_source.py",
    "services/api/src/axis_api/s3_source_profile.py",
    "packages/sdk-python/src/axis_sdk/connector_authoring/contracts.py",
    "services/api/uv.lock",
    "packages/sdk-python/uv.lock",
)


def read_json(content: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("nonfinite JSON value")

    return json.loads(content, object_pairs_hook=pairs, parse_constant=nonfinite)


def rss_high_water_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def trial(workload: Workload, kind: str, mode: str):
    files = source_hashes()
    # Fixture construction is excluded from timed/traced work, but remains in
    # the process RSS high-water mark. Every real trial uses a fresh process.
    with corpus(workload) as fixture:
        before = rss_high_water_bytes()
        tracemalloc.start()
        try:
            result = execute(fixture, kind, mode)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        result["memory"] = {
            "python_peak_bytes": peak,
            "process_rss_high_water_bytes": rss_high_water_bytes(),
            "process_rss_before_high_water_bytes": before,
        }
    if files != source_hashes():
        raise ValueError("benchmark source changed during trial")
    result["source_fingerprint"] = digest(files)
    validate_trial(result, workload)
    return result


def validate_trial(result, workload: Workload):
    if result["source"] not in KINDS or result["mode"] not in MODES:
        raise ValueError("unknown source/strategy")
    expected = {(job.tenant, job.ordinal) for job in offered_jobs(workload)}
    completed = [(row["tenant"], row["job"]) for row in result["samples"]]
    rejected = [(row["tenant"], row["job"]) for row in result["rejected"]]
    if len(set(completed + rejected)) != len(expected) or set(completed + rejected) != expected:
        raise ValueError("offered job accounting mismatch")
    if len(completed) + len(rejected) != result["offered"] or result["offered"] != len(expected):
        raise ValueError("duplicate or missing job")
    order = [(row["tenant"], row["job"]) for row in result["dispatch_order"]]
    if sorted(order) != sorted(completed):
        raise ValueError("dispatch accounting mismatch")
    workers = workload.workers if result["mode"] in {"streamed-parallel", "streamed-fair"} else 1
    if (
        not 1 <= result["active_peak"] <= workers
        or not 1 <= result["queue_peak"] <= workload.queue_capacity
    ):
        raise ValueError("queue/concurrency bound violated")
    tenant_limit = 1 if result["mode"] == "streamed-fair" else workers
    if any(not 1 <= peak <= tenant_limit for peak in result["tenant_active_peak"].values()):
        raise ValueError("tenant concurrency bound violated")
    if result["buffered_rows_at_end"] != 0 or result["buffered_bytes_at_end"] != 0:
        raise ValueError("retained payload after completion")
    rows_per_worker = (
        workload.records if result["mode"] == "materialized-serial" else workload.page_records
    )
    if result["buffered_rows_peak"] > rows_per_worker * workers:
        raise ValueError("retained row bound violated")
    bytes_per_worker = (
        workload.job_bytes if result["mode"] == "materialized-serial" else workload.page_bytes
    )
    if not 0 <= result["buffered_bytes_peak"] <= bytes_per_worker * workers:
        raise ValueError("retained byte bound violated")
    if result["seconds"] <= 0:
        raise ValueError("missing elapsed work")
    for row in result["samples"]:
        if any(not math.isfinite(row[key]) for key in ("queue_ms", "duration_ms")):
            raise ValueError("nonfinite timing")
        if row["status"] not in {"PASS", "FAIL"} or row["duration_ms"] < 0 or row["queue_ms"] < 0:
            raise ValueError("invalid completion status/timing")
        if row["status"] == "PASS" and (
            row["records"] != workload.records
            or row["error"] is not None
            or not 1 <= row["pages"] <= workload.max_pages
            or row["checkpoint_sha256"] is None
        ):
            raise ValueError("success without completed fixture work")


def validate_report(report):
    if (
        report["schema_version"] != 1
        or report["scope"] != "synthetic-ingestion-strategy-comparison"
    ):
        raise ValueError("unknown report contract")
    workload = Workload.model_validate(report["workload"])
    if report["workload_sha256"] != digest(workload.model_dump()):
        raise ValueError("workload digest mismatch")
    trials = report["trials"]
    if type(trials) is not int or not 1 <= trials <= 5:
        raise ValueError("invalid trial count")
    seen = set()
    completions = {}
    rejections = {}
    for result in report["results"]:
        validate_trial(result, workload)
        if result["source_fingerprint"] != digest(report["provenance"]["files"]):
            raise ValueError("incomparable source fingerprint")
        identity = result["source"], result["mode"], result["trial"]
        if identity in seen or not 0 <= result["trial"] < trials:
            raise ValueError("duplicate/invalid trial")
        seen.add(identity)
        rejected = sorted((r["tenant"], r["job"], r["reason"]) for r in result["rejected"])
        if rejections.setdefault(result["source"], rejected) != rejected:
            raise ValueError("strategies admitted different work")
        for row in result["samples"]:
            if row["status"] != "PASS":
                continue  # Failures are retained, never compared as fast successes.
            key = result["source"], row["tenant"], row["job"]
            value = tuple(
                row[field]
                for field in (
                    "records",
                    "bytes",
                    "pages",
                    "payload_sha256",
                    "checkpoint_sha256",
                )
            )
            if completions.setdefault(key, value) != value:
                raise ValueError("strategy/replay completion mismatch")
    if seen != {(kind, mode, index) for kind in KINDS for mode in MODES for index in range(trials)}:
        raise ValueError("incomplete experiment matrix")


def compare_values(before, after):
    if len(before) < 3 or len(after) < 3 or median(before) <= 0:
        return {"direction": "NOT RUN", "delta_percent": None}
    base, candidate = median(before), median(after)
    noise = max(base * 0.05, max(before) - min(before), max(after) - min(after))
    delta = candidate - base
    return {
        "direction": "within-noise"
        if abs(delta) <= noise
        else ("lower" if delta < 0 else "higher"),
        "delta_percent": delta / base * 100,
        "noise_allowance": noise,
    }


def summarize(report):
    validate_report(report)
    rows = []
    for kind in KINDS:
        for mode in MODES:
            trials = [r for r in report["results"] if r["source"] == kind and r["mode"] == mode]
            samples = [sample for result in trials for sample in result["samples"]]
            failures = sum(row["status"] != "PASS" for row in samples)
            rows.append(
                {
                    "source": kind,
                    "mode": mode,
                    "failures": failures,
                    "rejected_per_trial": [len(r["rejected"]) for r in trials],
                    "median_seconds": median(r["seconds"] for r in trials),
                    "median_python_peak_bytes": median(
                        r["memory"]["python_peak_bytes"] for r in trials
                    ),
                    "median_rss_high_water_bytes": median(
                        r["memory"]["process_rss_high_water_bytes"] for r in trials
                    ),
                    "max_buffered_bytes": max(r["buffered_bytes_peak"] for r in trials),
                    "max_active_jobs": max(r["active_peak"] for r in trials),
                    "queue_ms_by_tenant": {
                        tenant: distribution(
                            [r["queue_ms"] for r in samples if r["tenant"] == tenant]
                        )
                        for tenant in ("heavy", "light-a", "light-b")
                    },
                }
            )
    valid = all(r["failures"] == 0 for r in rows)
    comparisons = []
    for kind in KINDS:
        for before, after, factor in (
            ("materialized-serial", "streamed-serial", "streaming"),
            ("streamed-serial", "streamed-parallel", "parallelism"),
            ("streamed-parallel", "streamed-fair", "tenant-turns"),
        ):
            first = [r for r in report["results"] if r["source"] == kind and r["mode"] == before]
            second = [r for r in report["results"] if r["source"] == kind and r["mode"] == after]
            comparisons.append(
                {
                    "source": kind,
                    "factor": factor,
                    "before": before,
                    "after": after,
                    "seconds": compare_values(
                        [r["seconds"] for r in first], [r["seconds"] for r in second]
                    )
                    if valid
                    else {"direction": "FAIL"},
                    "python_peak_bytes": compare_values(
                        [r["memory"]["python_peak_bytes"] for r in first],
                        [r["memory"]["python_peak_bytes"] for r in second],
                    )
                    if valid
                    else {"direction": "FAIL"},
                }
            )
    return {
        "scope": report["scope"],
        "trials": report["trials"],
        "validation_status": "PASS" if valid else "FAIL",
        "comparison_status": "FAIL"
        if not valid
        else ("PASS" if report["trials"] >= 3 else "NOT RUN"),
        "deployment_slo_status": "NOT RUN",
        "rows": rows,
        "comparisons": comparisons,
    }


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def provenance():
    return {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                text=True,
            ).strip()
        ),
        "files": source_hashes(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "dependencies": {name: version(name) for name in ("httpx", "minio", "pydantic")},
    }


def run(profile: str, trials: int, output: Path):
    if not 1 <= trials <= 5:
        raise ValueError("trials must be between one and five")
    if output.exists():
        raise ValueError("output directory already exists; choose a fresh path")
    workload = PROFILES[profile]
    report = {
        "schema_version": 1,
        "scope": "synthetic-ingestion-strategy-comparison",
        "captured_at": datetime.now(UTC).isoformat(),
        "profile": profile,
        "trials": trials,
        "workload": workload.model_dump(),
        "workload_sha256": digest(workload.model_dump()),
        "provenance": provenance(),
        "sources": PROVENANCE,
        "results": [],
        "not_run": [
            "production outbox scheduling or tenant fairness",
            "live REST/PG/S3/document providers",
            "durable sink and database checkpoint transaction",
            "multi-worker deployment capacity/SLO",
        ],
    }
    output.mkdir(parents=True)
    for index in range(trials):
        # Rotate strategy order each trial to reduce consistent warm-cache bias.
        modes = MODES[index % len(MODES) :] + MODES[: index % len(MODES)]
        for kind in KINDS:
            for mode in modes:
                completed = subprocess.run(
                    [sys.executable, __file__, "_trial", kind, mode],
                    input=canonical(workload.model_dump()),
                    capture_output=True,
                    timeout=(workload.heavy_jobs + 2 * workload.light_jobs)
                    * workload.request_seconds
                    + 30,
                    check=True,
                )
                result = read_json(completed.stdout.decode())
                if result["source_fingerprint"] != digest(report["provenance"]["files"]):
                    raise ValueError("benchmark source changed between trials")
                result["trial"] = index
                report["results"].append(result)
                (output / "partial.json").write_bytes(canonical(report) + b"\n")
                print(
                    f"trial {index + 1}/{trials} {kind} {mode}: {len(result['samples'])} jobs",
                    flush=True,
                )
    summary = summarize(report)
    with gzip.GzipFile(filename=str(output / "report.json.gz"), mode="wb", mtime=0) as stream:
        stream.write(canonical(report) + b"\n")
    (output / "summary.json").write_bytes(canonical(summary) + b"\n")
    # Only the partial checkpoint created by this run is removed after success.
    (output / "partial.json").unlink()
    return summary["validation_status"] == "PASS"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--profile", choices=PROFILES, default="representative")
    run_parser.add_argument("--trials", type=int, default=3)
    run_parser.add_argument("--output", type=Path, required=True)
    child = commands.add_parser("_trial", help=argparse.SUPPRESS)
    child.add_argument("source", choices=KINDS)
    child.add_argument("mode", choices=MODES)
    args = parser.parse_args()
    if args.command == "_trial":
        workload = Workload.model_validate(read_json(sys.stdin.read()))
        print(canonical(trial(workload, args.source, args.mode)).decode())
        return 0
    return 0 if run(args.profile, args.trials, args.output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
