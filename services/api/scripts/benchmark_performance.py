"""Run bounded, isolated ASGI load/soak measurements or compare compatible reports.

No target URL or operator database is accepted. The workload runs through a
real in-process API against disposable SQLite with explicit identity/runtime
fixtures. Deployment SLOs, browser rendering and external services are separate.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import resource
import sqlite3
import statistics
import subprocess
from collections import Counter
from contextlib import nullcontext, suppress
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, process_time

import httpx
from performance_fixture import (
    JOURNEYS,
    ROOT,
    WORKLOADS,
    fixture,
    load_workloads,
    read_json,
    request_spec,
    require_finite_numbers,
    validate_response,
)
from performance_metrics import (
    REQUEST_METRICS,
    DatabaseMetrics,
    RequestMetrics,
    StackSampler,
    distribution,
)


def fingerprint(paths):
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def provenance(workload, profile, mode, seconds, journeys):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()

    sources = list((ROOT / "services/api/src").rglob("*.py"))
    measurement_sources = [
        WORKLOADS,
        *(
            ROOT / "services/api/scripts" / name
            for name in (
                "benchmark_performance.py",
                "performance_fixture.py",
                "performance_metrics.py",
            )
        ),
    ]
    environment = {
        "python": platform.python_version(),
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "sqlite": sqlite3.sqlite_version,
        "api_lock_sha256": fingerprint([ROOT / "services/api/uv.lock"]),
    }
    return {
        "revision": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "runtime_source_sha256": fingerprint(sources),
        "harness_sha256": fingerprint(measurement_sources),
        "dataset_version": workload["dataset_version"],
        "dataset_sha256": fingerprint(
            [WORKLOADS, *(ROOT / seed["path"] for seed in workload["seed_sources"].values())]
        ),
        "environment": environment,
        "profile": profile,
        "parameters": workload["profiles"][profile],
        "mode": mode,
        "seconds_per_journey": seconds,
        "journeys": list(journeys),
        "backend": "in-process ASGI / disposable SQLite / synthetic external ports",
    }


def rss_mb():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024 if platform.system() == "Darwin" else 1024)


async def arrivals(invoke, *, seconds, rps, concurrency):
    """Fixed-rate offered load with bounded in-flight work and explicit drops.

    Latency starts at the scheduled arrival, so generator delay is included.
    There is no unbounded queue and no compensating burst after an event-loop
    stall: arrivals more than one interval late are recorded as drops.
    """
    started = perf_counter()
    pending = set()
    records = []
    offered = math.ceil(seconds * rps)

    async def execute(index, scheduled):
        records.append(await invoke(index, scheduled, scheduled - started))

    async with asyncio.TaskGroup() as group:
        for index in range(offered):
            scheduled = started + index / rps
            await asyncio.sleep(max(0, scheduled - perf_counter()))
            completed = {task for task in pending if task.done()}
            for task in completed:
                task.result()
            pending -= completed
            late = perf_counter() - scheduled
            if late > 1 / rps or len(pending) >= concurrency:
                records.append(
                    {
                        "sequence": index,
                        "arrival_seconds": index / rps,
                        "ok": False,
                        "error": "generator_late" if late > 1 / rps else "concurrency_limit",
                        "dropped": True,
                        "latency_ms": None,
                        "service_ms": None,
                        "scheduler_lag_ms": late * 1000,
                        "sql_ms": 0,
                        "statements": 0,
                        "response_bytes": 0,
                    }
                )
            else:
                pending.add(group.create_task(execute(index, scheduled)))
    await asyncio.sleep(max(0, started + seconds - perf_counter()))
    return sorted(records, key=lambda record: record["sequence"]), perf_counter() - started


def summarize(records, seconds, elapsed):
    successful = [record for record in records if record["ok"]]
    return {
        "offered": len(records),
        "completed": sum(not record["dropped"] for record in records),
        "successful": len(successful),
        "errors": dict(Counter(record["error"] for record in records if not record["ok"])),
        "success_per_second": len(successful) / elapsed,
        "offered_per_second": len(records) / seconds,
        "elapsed_seconds_including_drain": elapsed,
        "latency_ms": distribution([record["latency_ms"] for record in successful]),
        "service_ms": distribution([record["service_ms"] for record in successful]),
        "scheduler_lag_ms": distribution([record["scheduler_lag_ms"] for record in records]),
        "sql_ms": distribution([record["sql_ms"] for record in successful]),
        "sql_statements": distribution([record["statements"] for record in successful]),
        "response_bytes": distribution([record["response_bytes"] for record in successful]),
    }


def evaluate(summary, resources, budget, resource_budget, *, profiled=False):
    failures = []
    if summary["errors"]:
        failures.append("errors_or_dropped_arrivals")
    if resources["pool_at_end"]:
        failures.append("pool_not_released")
    if not profiled and summary["successful"]:
        for metric, quantile, limit in (
            ("latency_ms", "p95", budget["p95_ms"]),
            ("latency_ms", "p99", budget["p99_ms"]),
            ("sql_statements", "max", budget["max_sql_statements"]),
            ("response_bytes", "max", budget["max_response_bytes"]),
        ):
            if summary[metric][quantile] > limit:
                failures.append(f"{metric}.{quantile}")
        if summary["success_per_second"] < budget["rps"] * 0.95:
            failures.append("throughput")
        for metric, limit in (
            ("process_peak_rss_mb", resource_budget["process_rss_mb"]),
            ("cpu_cores_used", resource_budget["cpu_cores"]),
            ("pool_peak", resource_budget["max_pool_connections"]),
            ("database_growth_mb_per_minute", resource_budget["max_database_growth_mb_per_minute"]),
        ):
            if resources[metric] > limit:
                failures.append(metric)
    status = (
        "FAIL" if failures else ("NOT RUN" if profiled or summary["successful"] < 100 else "PASS")
    )
    return {
        "status": status,
        "failures": failures,
        "minimum_tail_samples": 100,
        "profiled": profiled,
    }


async def measure(workload, profile, journey, seconds, mode, output, trial):
    with fixture(profile, workload) as (app, engine, database, tenants):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://fixture.invalid",
            trust_env=False,
        ) as client:

            async def request(sequence):
                tenant = tenants[sequence % len(tenants)]
                method, path, kwargs = request_spec(journey, tenant, sequence, profile)
                response = await client.request(method, path, **kwargs)
                validate_response(journey, response, tenant, profile)
                return response

            for index in range(profile["warmup_requests"]):
                await request(-index - 1)

            async def invoke(sequence, scheduled, arrival):
                metrics = RequestMetrics()
                token = REQUEST_METRICS.set(metrics)
                started = perf_counter()
                record = {
                    "sequence": sequence,
                    "arrival_seconds": arrival,
                    "dropped": False,
                    "response_bytes": 0,
                    "ok": False,
                    "error": None,
                }
                try:
                    async with asyncio.timeout(profile["request_timeout_seconds"]):
                        response = await request(sequence)
                    record.update(ok=True, response_bytes=len(response.content))
                except Exception as exc:
                    # Neither exception messages nor response bodies enter evidence.
                    record["error"] = type(exc).__name__
                finally:
                    record.update(
                        latency_ms=(perf_counter() - scheduled) * 1000,
                        service_ms=(perf_counter() - started) * 1000,
                        scheduler_lag_ms=(started - scheduled) * 1000,
                        statements=metrics.statements,
                        sql_ms=metrics.sql_ms,
                    )
                    REQUEST_METRICS.reset(token)
                return record

            initial_bytes = database.stat().st_size
            cpu_started = process_time()
            sampler = StackSampler(ROOT) if mode == "profile" else None
            resource_samples = []
            monitor_stop = asyncio.Event()
            monitor_started = perf_counter()

            def sample_resources():
                resource_samples.append(
                    {
                        "elapsed_seconds": perf_counter() - monitor_started,
                        "process_cpu_seconds": process_time() - cpu_started,
                        "process_peak_rss_mb": rss_mb(),
                        "database_bytes": database.stat().st_size,
                    }
                )

            async def monitor():
                while not monitor_stop.is_set():
                    sample_resources()
                    with suppress(TimeoutError):
                        await asyncio.wait_for(monitor_stop.wait(), timeout=30)

            with DatabaseMetrics(engine) as database_metrics, sampler or nullcontext():
                monitoring = asyncio.create_task(monitor())
                try:
                    records, elapsed = await arrivals(
                        invoke,
                        seconds=seconds,
                        rps=profile["journeys"][journey]["rps"],
                        concurrency=profile["concurrency"],
                    )
                finally:
                    monitor_stop.set()
                    await monitoring
                    sample_resources()
                resources = database_metrics.snapshot(elapsed)
            resources.update(
                process_peak_rss_mb=rss_mb(),
                cpu_cores_used=(process_time() - cpu_started) / elapsed,
                database_bytes=database.stat().st_size,
                database_growth_mb_per_minute=(database.stat().st_size - initial_bytes)
                / 1024
                / 1024
                / elapsed
                * 60,
            )
            if sampler:
                sampler.write(output / f"{journey}-{trial}")
            resources["python_stack_samples"] = sum(sampler.stacks.values()) if sampler else None
            summary = summarize(records, seconds, elapsed)
            windows = []
            for start in range(0, math.ceil(seconds), 30):
                selected = [
                    record for record in records if start <= record["arrival_seconds"] < start + 30
                ]
                windows.append(
                    {
                        "start_seconds": start,
                        "successful": sum(r["ok"] for r in selected),
                        "latency_ms": distribution([r["latency_ms"] for r in selected if r["ok"]]),
                    }
                )
            return {
                "trial": trial,
                "journey": journey,
                "summary": summary,
                "resources": resources,
                "resource_samples": resource_samples,
                "windows": windows,
                "budget": evaluate(
                    summary,
                    resources,
                    profile["journeys"][journey],
                    profile["resource_budgets"],
                    profiled=bool(sampler),
                ),
                "samples": records,
            }


def compare(before, after):
    """Three-run medians; incompatible or undersampled reports cannot pass."""
    for report in (before, after):
        validate_report(report)
    compatibility = (
        "harness_sha256",
        "dataset_sha256",
        "environment",
        "profile",
        "parameters",
        "mode",
        "seconds_per_journey",
        "journeys",
        "backend",
    )
    for key in compatibility:
        if before["provenance"][key] != after["provenance"][key]:
            raise ValueError(f"Incompatible reports: {key}")
    if before["provenance"]["mode"] == "profile":
        raise ValueError("Profiler runs are not comparable latency evidence")
    changes = []
    for journey in before["provenance"]["journeys"]:
        old = [run for run in before["runs"] if run["journey"] == journey]
        new = [run for run in after["runs"] if run["journey"] == journey]
        if min(len(old), len(new)) < 3:
            raise ValueError("Comparison requires at least three trials per journey")
        if len(old) != len(new):
            raise ValueError("Comparison requires the same number of trials")
        if any(run["summary"]["successful"] < 100 for run in old + new):
            raise ValueError("Comparison requires at least 100 successful samples per trial")
        for runs in (old, new):
            if len({run["trial"] for run in runs}) != len(runs):
                raise ValueError("Duplicate trial identifiers")
        if any(run["summary"]["errors"] or run["resources"]["pool_at_end"] for run in old + new):
            raise ValueError("Failed work or leaked connections cannot be a performance baseline")
        for quantile in ("p95", "p99"):
            old_values = [run["summary"]["latency_ms"][quantile] for run in old]
            new_values = [run["summary"]["latency_ms"][quantile] for run in new]
            old_median, new_median = statistics.median(old_values), statistics.median(new_values)
            noise = max(abs(value - old_median) for value in old_values)
            new_noise = max(abs(value - new_median) for value in new_values)
            allowance = max(5, old_median * 0.15, 3 * noise)
            noisy = noise > max(5, old_median * 0.15) or new_noise > max(5, new_median * 0.15)
            changes.append(
                {
                    "journey": journey,
                    "metric": f"latency_ms.{quantile}",
                    "before": old_median,
                    "after": new_median,
                    "allowance_ms": allowance,
                    "status": "NOT RUN"
                    if noisy
                    else ("FAIL" if new_median > old_median + allowance else "PASS"),
                }
            )
        for metric, section in (("sql_statements", "summary"), ("response_bytes", "summary")):
            old_max = max(run[section][metric]["max"] for run in old)
            new_max = max(run[section][metric]["max"] for run in new)
            changes.append(
                {
                    "journey": journey,
                    "metric": metric,
                    "before": old_max,
                    "after": new_max,
                    "status": "FAIL" if new_max > old_max else "PASS",
                }
            )
        for metric in (
            "cpu_cores_used",
            "process_peak_rss_mb",
            "pool_mean_occupied",
            "database_growth_mb_per_minute",
        ):
            old_median = statistics.median(run["resources"][metric] for run in old)
            new_median = statistics.median(run["resources"][metric] for run in new)
            floor = {
                "cpu_cores_used": 0.05,
                "process_peak_rss_mb": 32,
                "pool_mean_occupied": 0.05,
                "database_growth_mb_per_minute": 1,
            }[metric]
            changes.append(
                {
                    "journey": journey,
                    "metric": metric,
                    "before": old_median,
                    "after": new_median,
                    "status": "FAIL"
                    if (new_median > old_median + max(floor, old_median * 0.15))
                    else "PASS",
                }
            )
        old_rate = statistics.median(run["summary"]["success_per_second"] for run in old)
        new_rate = statistics.median(run["summary"]["success_per_second"] for run in new)
        changes.append(
            {
                "journey": journey,
                "metric": "success_per_second",
                "before": old_rate,
                "after": new_rate,
                "status": "FAIL" if new_rate < old_rate * 0.95 else "PASS",
            }
        )
        changes.append(
            {
                "journey": journey,
                "metric": "absolute_budgets",
                "status": "FAIL"
                if any(run["budget"]["status"] == "FAIL" for run in new)
                else "PASS",
            }
        )
    statuses = {change["status"] for change in changes}
    return {
        "schema_version": 1,
        "status": "FAIL"
        if "FAIL" in statuses
        else ("NOT RUN" if "NOT RUN" in statuses else "PASS"),
        "comparisons": changes,
    }


def validate_report(report):
    require_finite_numbers(report)
    if (
        type(report["schema_version"]) is not int
        or report["schema_version"] != 1
        or report.get("complete") is not True
    ):
        raise ValueError("Incomplete or unsupported report")
    journeys = report["provenance"]["journeys"]
    if not journeys or len(set(journeys)) != len(journeys) or not set(journeys) <= set(JOURNEYS):
        raise ValueError("Invalid report journeys")
    for run in report["runs"]:
        if run["journey"] not in journeys:
            raise ValueError("Unexpected journey")
        summary = run["summary"]
        samples = run["samples"]
        seconds = report["provenance"]["seconds_per_journey"]
        rps = report["provenance"]["parameters"]["journeys"][run["journey"]]["rps"]
        if len(samples) != math.ceil(seconds * rps) or (
            summary["elapsed_seconds_including_drain"] < seconds
        ):
            raise ValueError("Missing arrivals or invalid measurement duration")
        if not samples or [r["sequence"] for r in samples] != list(range(len(samples))):
            raise ValueError("Missing or duplicated request samples")
        for sample in samples:
            if type(sample["ok"]) is not bool or type(sample["dropped"]) is not bool:
                raise ValueError("Invalid sample outcome")
            if sample["ok"] and (sample["dropped"] or sample["error"] is not None):
                raise ValueError("Successful work cannot be dropped or failed")
            if not sample["ok"] and not isinstance(sample["error"], str):
                raise ValueError("Failed work requires an error classification")
            for key in ("sequence", "statements", "response_bytes"):
                if type(sample[key]) is not int or sample[key] < 0:
                    raise ValueError("Invalid sample count")
            for key in ("arrival_seconds", "scheduler_lag_ms", "sql_ms"):
                if type(sample[key]) not in (int, float) or sample[key] < 0:
                    raise ValueError("Invalid sample timing")
            for key in ("latency_ms", "service_ms"):
                if sample["dropped"]:
                    if sample[key] is not None:
                        raise ValueError("Dropped work cannot have a response latency")
                elif type(sample[key]) not in (int, float) or sample[key] < 0:
                    raise ValueError("Invalid response timing")
        recomputed = summarize(
            samples,
            report["provenance"]["seconds_per_journey"],
            summary["elapsed_seconds_including_drain"],
        )
        if summary != recomputed:
            raise ValueError("Summary differs from retained samples")
        if summary["offered"] != summary["successful"] + sum(summary["errors"].values()):
            raise ValueError("Invalid request accounting")
        for key in (
            "pool_at_end",
            "pool_peak",
            "pool_mean_occupied",
            "process_peak_rss_mb",
            "cpu_cores_used",
            "database_growth_mb_per_minute",
        ):
            if type(run["resources"][key]) not in (int, float) or run["resources"][key] < 0:
                raise ValueError("Invalid resource measurement")
        parameters = report["provenance"]["parameters"]
        expected_budget = evaluate(
            summary,
            run["resources"],
            parameters["journeys"][run["journey"]],
            parameters["resource_budgets"],
            profiled=report["provenance"]["mode"] == "profile",
        )
        if run["budget"] != expected_budget:
            raise ValueError("Stored budget result differs from measurements")


async def run(args):
    workload = load_workloads()
    profile = workload["profiles"][args.profile]
    seconds = args.seconds or profile["soak_seconds" if args.mode == "soak" else "load_seconds"]
    journeys = [args.journey] if args.journey else JOURNEYS
    if seconds * args.repeat * sum(profile["journeys"][j]["rps"] for j in journeys) > 100_000:
        raise ValueError("A report is limited to 100000 offered arrivals")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "provenance": provenance(workload, args.profile, args.mode, seconds, journeys),
        "deployment_slo_status": "NOT RUN",
        "search_status": "NOT RUN: #343 unimplemented",
        "runs": [],
        "complete": False,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    for trial in range(args.repeat):
        for journey in journeys:
            result = await measure(
                workload, profile, journey, seconds, args.mode, args.output, trial
            )
            report["runs"].append(result)
            (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "trial": trial,
                        "journey": journey,
                        "summary": result["summary"],
                        "budget": result["budget"],
                    }
                ),
                flush=True,
            )
    report["complete"] = True
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    statuses = {result["budget"]["status"] for result in report["runs"]}
    if "FAIL" in statuses:
        return 1
    return 2 if "NOT RUN" in statuses and args.mode != "profile" else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    measure_parser = commands.add_parser("run")
    measure_parser.add_argument(
        "--profile", choices=("sme-single-node", "enterprise"), default="sme-single-node"
    )
    measure_parser.add_argument("--mode", choices=("load", "soak", "profile"), default="load")
    measure_parser.add_argument("--seconds", type=int, choices=range(1, 3601), metavar="1..3600")
    measure_parser.add_argument("--repeat", type=int, choices=range(1, 11), default=1)
    measure_parser.add_argument("--journey", choices=JOURNEYS)
    measure_parser.add_argument("--output", type=Path, required=True)
    comparison = commands.add_parser("compare")
    comparison.add_argument("before", type=Path)
    comparison.add_argument("after", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "run":
            return asyncio.run(run(args))
        result = compare(read_json(args.before), read_json(args.after))
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Validation errors contain our classifications, not HTTP bodies or SQL values.
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        parser.exit(2, f"Benchmark input/evidence error: {reason}\n")


if __name__ == "__main__":
    raise SystemExit(main())
