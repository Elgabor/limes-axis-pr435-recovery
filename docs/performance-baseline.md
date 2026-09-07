# Performance workloads and baseline

Issue [#361](https://github.com/Limes-Labs/limes-axis/issues/361) establishes
versioned workloads, measurement artifacts and a regression policy. The
[initial report](benchmarks/performance-v1/README.md) records the measured
runtime revision and the evidence boundaries. This change adds measurement
tooling; it does not optimize product code or establish production capacity.

## Workload definitions

The executable source of truth is
[`workloads.v1.json`](../services/api/benchmarks/workloads.v1.json).
The profiles are initial engineering test contracts, not observed customer
usage or contractual SLAs. Product and deployment owners must revise them with
customer evidence before making capacity commitments.

| Dimension | SME single-node | Enterprise |
| --- | --- | --- |
| Deployment planning assumption | One customer installation, 4 vCPU / 8 GiB application host; colocated services need separate headroom | Three API replicas, 4 vCPU / 8 GiB each; separately provisioned Postgres, worker and stores |
| Fixture tenants / workspaces | 2 | 20 |
| Connectors per tenant | 25 | 200 |
| Historical connector runs per tenant | 50 | 250 |
| Pending proposals per tenant | 20 | 150 |
| CSV rows per preview | 100 | 500 |
| Future search corpus per tenant | 10,000 documents | 1,000,000 documents |
| Maximum concurrent in-process requests | 4 | 8 |
| Model / workflow simulated wait | 50 ms / 20 ms | 50 ms / 20 ms |
| Default load / soak per journey | 60 s / 300 s | 60 s / 300 s |

The local harness executes **both data shapes on one process and SQLite**.
It does not create the deployment topology in this table. The enterprise shape
exercises tenant/cardinality growth in current API code; it is not evidence for
three-replica throughput, production database contention, HA or horizontal scaling.

Seed templates come from three committed reference migrations, with their file
hashes pinned in the manifest. The harness reads their constants without applying
migrations, clones tenant-scoped metadata, and generates deterministic connector,
run, proposal and CSV identifiers. Historical timestamps are fixed. Request keys
are unique within a trial; repeated requests do real work instead of replaying a
cached idempotency result. Each journey/trial owns a new temporary database.
Changing seed content, cardinality, rates or delays changes the dataset digest
and requires an explicit baseline update. Schema initialization uses SQLAlchemy
metadata; PostgreSQL migration correctness belongs to its existing CI lane.

## Critical journeys and budgets

Latency runs from **scheduled arrival to validated HTTP response**. SQL counts
include request authorization and audit work; SQL execution time is measured
around cursor execution and excludes transaction commit latency. Total request
latency includes commits. Payload budgets count uncompressed response-body bytes.
The same latency and per-request budgets apply to both initial profiles; the
enterprise profile offers more work over larger tenant data.

| Journey | Current measured work | SME / enterprise requests per second | p95 / p99 budget | SQL / response byte limit |
| --- | --- | --- | --- | --- |
| Console | First page of `GET /operations/connectors/workspace`, including four non-null counters, identity and read audit | 10 / 20 | 500 / 1,000 ms | 60 statements / 65,536 bytes |
| Ingestion preview | `POST /operations/connectors/file-csv/preview`, full CSV parsing, accepted-row validation and schema observation persistence | 2 / 4 | 1,000 / 2,000 ms | 20 statements / 1,000,000 bytes |
| Workflow signal | `POST /operations/actions/request_supplier_expedite/runs`, governed persistence and an awaited synthetic signal acknowledgement | 2 / 4 | 500 / 1,000 ms | 50 statements / 32,000 bytes |
| Model invocation | `POST /platform/models/invocations`, permission/policy routing, prepare/finalize, audit and token metadata with a synthetic provider response | 2 / 4 | 1,000 / 2,000 ms | 80 statements / 32,000 bytes |
| Search — planned | Permission-safe full-text query, first 20 results, 60 s index freshness target | 10 / 25 | 500 / 1,000 ms | 65,536 bytes; SQL budget must follow the implementation plan |

Search is explicitly `NOT RUN` until [#343](https://github.com/Limes-Labs/limes-axis/issues/343)
implements its corpus and endpoint. Returning health checks or in-memory string
matches would not constitute search evidence. Its corpus size and budgets are
recorded under `planned_search` in each profile. New search implementation must
add a real journey, deterministic content/permission fixtures and freshness
observations before producing a baseline.

All implemented journeys also require zero errors/dropped arrivals, at least
95% of offered throughput after draining, no connections still checked out,
and the following process budgets:

| Resource budget, applied to every journey | SME | Enterprise local shape |
| --- | --- | --- |
| Process peak resident memory | 1,024 MiB | 1,024 MiB |
| Mean CPU cores consumed | 4 | 8 |
| Peak checked-out connections | 4 | 8 |
| Database growth | 100 MiB/min | 100 MiB/min |

CPU and peak memory include the in-process client and measurement hooks.
Memory is the operating system's process lifetime high-water mark, including
imports/seeding and earlier trials; it is not current RSS or a heap-leak proof.
Database growth includes expected append-only evidence and page allocation. The
soak report retains 30-second latency windows and CPU/memory/database samples
to expose drift. A reviewer should inspect trends and evidence growth rather
than expect a write-heavy database to plateau. The pool metric integrates
checked-out connection time; it is neither active transaction count nor server
CPU time. The mean uses measured elapsed time including the drain.

## Running locally

Install the committed dependencies in the intended worktree with `make install`.
No new benchmark dependency is required. Use an idle machine without concurrent
builds, tests or other benchmarks, and retain the same power/thermal settings.
The runner records OS, architecture, CPU count, Python, SQLite, dependency lock,
dataset, harness and runtime-source hashes. Operators must additionally ensure
the same physical machine/resource limits; those metadata alone do not prove it.

```sh
make benchmark-performance BENCHMARK_ARGS='run --profile sme-single-node --repeat 3 --output /tmp/axis-sme-before'
make benchmark-performance BENCHMARK_ARGS='run --profile enterprise --repeat 3 --output /tmp/axis-enterprise-before'
make benchmark-performance BENCHMARK_ARGS='run --profile sme-single-node --mode soak --journey console --output /tmp/axis-sme-soak'
make benchmark-performance BENCHMARK_ARGS='run --profile enterprise --mode soak --journey model-invocation --output /tmp/axis-enterprise-model-soak'
make benchmark-performance BENCHMARK_ARGS='run --profile sme-single-node --mode profile --seconds 10 --output /tmp/axis-profiles'
```

Omitting `--journey` executes all four journeys **sequentially**, with independent
datasets. This isolates their costs; it is not a mixed-traffic capacity run.
The process is reused across phases and garbage collection stays enabled.
`--seconds` overrides a phase duration up to one hour. `--repeat` is bounded at
10 and the entire report at 100,000 offered arrivals. Output directories must
not exist, preserving earlier evidence. Interrupted reports keep `complete=false`
and cannot be accepted by the comparison command.

The generator schedules fixed-rate arrivals independently of response completion.
It permits at most the profile's concurrency limit. Saturated arrivals are
recorded as drops; arrivals more than one interval late are also dropped rather
than replayed as a burst. Each offered arrival is retained in the report. A stall
can still affect the in-process generator, but its lag/drops remain visible and
fail the budget instead of reducing the apparent offered load.

Imports, database creation, seeding and three warmup requests are excluded from
request timing. Warmup follows the tenant rotation; additional enterprise tenants
can still have cold admission caches in the measured window. Each request uses
the production request/session dependency; ORM sessions are not reused across
requests. All rows, prompt text and replies are synthetic. Environment variables
and `.env` files cannot enable a real database, IdP, exporter or external adapter.
No target URL, external DSN or real credentials are accepted.

The HTTP boundary retains tenant binding, registered-tenant admission, permissions,
policy, idempotency and audit behavior. Only identity verification and external
runtime ports are fakes. Rate limiting is explicitly disabled to measure accepted
work. Tests prove that missing identity and foreign tenants are denied and that
no socket connection occurs. This is not IdP verification or rate-limiter capacity
evidence. ASGI lifespan/background jobs are not started. Optional request usage
metering and its periodic projector retain their disabled defaults; persisted
invocation token metadata is measured, billing projections are not.
SQLite and synchronous work may delay cooperative asyncio deadlines;
a request timeout is not a hard wall-clock bound on native database calls.

## Reports and profiles

`report.json` includes individual samples, p50/p95/p99/max latency, service time,
generator lag, SQL execution time/counts, bytes, errors, throughput, pool occupancy,
resource use, 30-second windows and provenance. Quantiles use nearest rank. A p99
with 100 samples is only a first engineering observation, not a statistically
certified production tail or availability SLO. Fewer than 100 successful samples
cannot pass the timing budget. Failed, empty, deferred or tenant-mismatched replies
never enter the successful latency distribution; their errors still fail the run.

`run` exits 0 when local budgets pass, 1 for failures and 2 for insufficient tail
samples or invalid input. Profile mode exits 0 for successfully captured work,
while explicitly leaving timing budgets `NOT RUN` because sampling adds overhead.
Deployment SLO status always remains `NOT RUN` for this harness.

Profile mode emits `.folded` stacks and a standalone `.svg` flamegraph per
journey/trial. It samples Python stacks containing API frames every 10 ms,
including synchronous worker threads. The graph's widths are proportions of
collected stacks, **not CPU percentages**. Native frames, suspended coroutine
ancestry and waits without API frames are absent. The report records the number
of collected stacks, including zero. Open the SVG locally and hover a frame for
its name/count. No frame locals, SQL parameters, prompts or HTTP bodies are saved
by the profiler. SQL fingerprints retain only statement hashes, operation, count
and timing, which can guide a subsequent focused query investigation.

## Regression policy

For a runtime change, run three trials before and three after using the **same
harness and workload**, duration, dependency lock, machine and backend. Copy the
measurement files into a disposable worktree of the earlier runtime if it predates
the harness; report its dirty state and source hashes honestly. Do not modify
production code merely to manufacture a baseline.

```sh
make benchmark-performance BENCHMARK_ARGS='compare /tmp/axis-sme-before/report.json /tmp/axis-sme-after/report.json'
```

The comparison also reads gzip-compressed JSON. It rejects incomplete reports,
incompatible provenance, missing/duplicate request samples, changed summaries or
budget outcomes, negative timings/counts, duplicate or unequal trial batches,
fewer than three trials, fewer than 100 successful samples,
errors, leaked connections and profiler runs.

For p95/p99, compare the median across trials. The allowed increase is the largest
of 5 ms, 15% of the prior median, or three times the largest absolute deviation
from that median. If either batch's deviation itself exceeds the larger of 5 ms
and 15% of its median, the result is inconclusive (`NOT RUN`); rerun on an idle machine rather
than silently widening tolerances. SQL statement and response-byte maxima cannot
increase without a reviewed contract change. Throughput may decline by at most
5%. CPU, peak RSS, pool occupancy and database growth allow 15% increases, with
absolute floors of 0.05 cores, 32 MiB, 0.05 connections and 1 MiB/min respectively.
Absolute workload budgets still apply. Any regression yields `FAIL`; otherwise
any inconclusive comparison prevents `PASS`.

CI runs deterministic harness/fixture/failure tests and existing product gates.
It does not turn shared-runner wall time into a merge gate. Performance-changing
PRs must attach compatible reports, inspect query/pool/resource evidence, and
document any consciously accepted budget change in review. A changed dataset,
backend or measurement method requires a fresh baseline, not a green comparison
against incompatible numbers. The [decision](adr/0016-performance-measurement-contract.md)
records ownership and alternatives.

## Remaining deployment evidence

Browser click-to-render performance, real search/index freshness, complete
source-to-object-store ingestion, Temporal execution/recovery, model-provider
latency, PostgreSQL locking/pool saturation, mixed traffic, sustained multi-hour
soaks and enterprise HA/TLS/load need their own environment-specific reports.
The existing [deployment load rehearsal](deployment-load-rehearsal.md) remains
an operator-selected reachability/load tool; its health URLs are not substitutes
for these application journeys. Existing [lineage](development.md#performance-measurement)
and [connector waterfall](connector-workspace.md#measured-evidence-and-reproduction)
measurements remain separate evidence. The harness does not resolve or change
the remaining [external-await transaction boundaries](performance-external-await-boundaries.md).
