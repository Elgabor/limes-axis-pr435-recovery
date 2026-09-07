# Initial performance baseline — 2026-09-07

This report establishes the [versioned workload contract](../../performance-baseline.md) for issue [#361](https://github.com/Limes-Labs/limes-axis/issues/361). It records successful work and failures from the same unchanged application code. It does not claim an optimization, production capacity or deployed SLO acceptance.

## Result

- **PASS — measurement and artifact integrity:** completed load batches for both shapes, two five-minute soaks, and separate stack profiles retain individual samples, SQL timing, pool occupancy, resources and provenance.
- **FAIL — some local workload budgets:** late scheduled arrivals occur in the load captures below. No dropped arrival is hidden or counted as successful work.
- **NOT RUN — accepted regression comparison:** both comparisons refuse the failed baseline batches. The machine also had concurrent Python/system workloads; no idle-machine or statistically certified tail result is claimed.
- **NOT RUN — deployment SLOs and search:** this is local ASGI/SQLite with synthetic identity and external ports. Search, real provider/Temporal latency, PostgreSQL contention, browser rendering, full ingestion, HA/TLS and multi-hour soak remain outside this evidence.

## Retained load batches

Each batch contains three trials of four journeys, 60 seconds per journey. The API source digest is identical before and after. Imports, seeding and three warmup requests are excluded from request timing. The process is reused between phases; process memory is a lifetime high-water mark.

| Batch | Offered | Successful | Dropped / failed | Local phases passing | Artifact |
| --- | ---: | ---: | ---: | ---: | --- |
| before-sme | 2,880 | 2,879 | 1 | 11/12 | [Full samples](before-sme.json.gz) |
| after-sme | 2,880 | 2,880 | 0 | 12/12 | [Full samples](after-sme.json.gz) |
| before-enterprise | 5,760 | 5,516 | 244 | 7/12 | [Full samples](before-enterprise.json.gz) |
| after-enterprise | 5,760 | 5,521 | 239 | 9/12 | [Full samples](after-enterprise.json.gz) |

The recorded failures are generator-late drops. The archived samples identify their scheduled arrival and measured lag. All connections were returned at phase end. Concurrent Python processes and system indexing/media work were observed; this is an execution-condition observation, not proof of the cause of any individual delay.

## Latency and query observations

Values below are **medians of the three per-trial p95 values**, in milliseconds, for successful responses. They are descriptive observations only: the failed arrivals prevent these numbers from serving as an accepted regression comparison. SQL is the maximum statement count per successful request across the batch.

| Shape / journey | Before p95 | After p95 | Before / after SQL max |
| --- | ---: | ---: | ---: |
| sme / console | 19.72 | 22.13 | 32 / 32 |
| sme / ingestion-preview | 8.98 | 20.70 | 10 / 10 |
| sme / workflow-signal | 30.42 | 42.00 | 11 / 11 |
| sme / model-invocation | 60.91 | 72.96 | 9 / 9 |
| enterprise / console | 152.53 | 132.52 | 32 / 32 |
| enterprise / ingestion-preview | 168.53 | 159.24 | 10 / 10 |
| enterprise / workflow-signal | 38.60 | 33.38 | 11 / 11 |
| enterprise / model-invocation | 72.94 | 61.90 | 9 / 9 |

Admission-cache cold starts/expiry explain the additional tenant-admission statements included in the maxima. Query fingerprints and cursor timings are retained in each report; commit and ORM/serialization costs are included in total request latency, not cursor timing. The data alone does not establish that SQL is the limiting resource.

The actual comparator outcomes are retained for [SME](comparison-sme.json) and [enterprise](comparison-enterprise.json). Both report `NOT RUN` because failed work cannot be an accepted baseline; there is no claimed speedup.

## Duration evidence

| Capture | Duration | Successful / offered | p95 / p99 ms | Peak / final checked-out connections | Local budget |
| --- | ---: | ---: | ---: | ---: | --- |
| [soak-sme-console](soak-sme-console.json.gz) | 300 s | 3,000 / 3,000 | 22.81 / 24.84 | 1 / 0 | PASS |
| [soak-enterprise-model](soak-enterprise-model.json.gz) | 300 s | 1,200 / 1,200 | 73.89 / 75.61 | 1 / 0 | PASS |

These are one console soak and one model-invocation soak. The other journey/profile soak combinations and multi-hour runs are **NOT RUN**, although the same bounded runner supports them. Thirty-second windows and resource samples are retained, including expected append-only database growth. This is not a heap-leak, recovery or distributed durability certification.

## Stack profiles

Profiled runs use ten seconds per journey and do not receive a latency-budget PASS. The Python sampler observes wall stacks containing API frames, including synchronous worker threads. Native execution, suspended async ancestry and waits without API frames are absent. Width is a fraction of collected stacks, not CPU utilization.

| Shape | Console / preview / workflow / model collected stacks | Full profile report | All SVG and folded stacks |
| --- | --- | --- | --- |
| sme | 76 / 15 / 11 / 12 | [Report](profile-sme.json.gz) | [Archive](profiles-sme.tar.gz) |
| enterprise | 195 / 43 / 16 / 32 | [Report](profile-enterprise.json.gz) | [Archive](profiles-enterprise.tar.gz) |

The console flamegraphs can also be viewed directly: [SME](console-sme.svg) and [enterprise](console-enterprise.svg). Hover a frame for its source location and sample count. No SQL parameters, request bodies, response bodies or frame locals are included.

## Provenance and reproduction

The load captures use the measurement code committed at [`2590464`](https://github.com/Limes-Labs/limes-axis/commit/25904642ec3e3cf3c329c4b87fc5223a07052f50). The before batches identify application base `4781573`; the after batches identify `2590464`. The before working tree is explicitly marked dirty because the new harness had not yet been committed. Source hashes identify the actual inputs; no application source was changed.

The later review tightened report validation and refusal messages. Acquisition, metric and budget functions were checked unchanged by AST comparison. The soak/profile artifacts identify their own harness revision and digest. Do not compare different harness digests just because the application source is unchanged. For a new runtime PR, execute both sides using the same measurement files and environment.

- Runtime source SHA-256: `8f5e63fe12bd99a54b8ee8669a025de54ce37c2449837f97f32489f58f03bed1`.
- Load harness SHA-256: `9ed605b190d36a8b3f53597f7d01737a8def628094ac52d274068ec793b27e9d`.
- Dataset SHA-256: `14ad5c79edd3617d433a8267063d75567f69ae11b66e99d959b87e65206cf31d`.
- Environment: Darwin 25.5.0, arm64, 8 logical CPUs, Python 3.12.6, SQLite 3.45.3.
- Dependency-lock digest, full profile parameters, revision and dirty state are embedded in every report.
- Artifact byte sizes and SHA-256 values are in the [manifest](manifest.json). Gzip headers use a fixed timestamp and contain no local filename.

From an installed isolated worktree, reproduce each load batch with `make benchmark-performance BENCHMARK_ARGS='run --profile sme-single-node --repeat 3 --output /tmp/axis-sme-new'`, replacing the profile/output for enterprise. Use `--mode soak --journey console` or `--mode soak --journey model-invocation` for the corresponding duration capture, and `--mode profile --seconds 10` for profiles. Full commands, target budgets and evidence limits are in the [runbook](../../performance-baseline.md). Keep output directories distinct and use an idle, unchanged machine for an accepted comparison.
