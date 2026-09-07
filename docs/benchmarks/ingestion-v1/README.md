# Ingestion strategy evidence, version 1

**PASS:** both experiment matrices completed with identical expected payloads and
checkpoint outcomes across all strategies and repeats. This is a synthetic
strategy evaluation for [#365](https://github.com/Limes-Labs/limes-axis/issues/365),
not a production throughput or tenant-fairness certification. The
[experiment contract](../../ingestion-performance.md) defines fixtures, limits,
metrics, comparison policy and reproduction commands.

## Capture

- Runtime/harness commit: `8f2c0a5a4befcf9bf3937a9020572070a25817b3`, clean at both
  capture starts, 2026-09-07 at 19:00:06 and 19:02:50 UTC.
- Host: macOS 26.5.2, ARM64; Python 3.12.6; SQLite 3.45.3. Each trial ran in a
  fresh process. Relevant source/lockfile hashes and dependency versions are
  retained in the reports.
- Four source shapes × four strategies × three repeats for each profile. Local
  component test suites and builds were not run concurrently with capture.
- Representative profile: **864 offered, 864 completed, zero rejected/failed**.
  Saturation profile: **1,536 offered, 768 completed, 768 rejected, zero failed**.
  Every rejection is retained as admission evidence.

## Representative results

Each cell is median elapsed seconds / median traced Python peak KiB across three
trials. One case processes 18 jobs, each with 128 records containing 2,048 UTF-8
text bytes. The sink is a digest/acknowledgement fixture. Read and sink delays are
two milliseconds per batch; they are configured fixture delays, not observed
provider latency.

| Source fixture | Materialized serial | Streamed serial | Streamed parallel | Streamed tenant turns |
| --- | --- | --- | --- | --- |
| REST / in-process HTTP | 1.238 / 1,434.9 | 1.204 / 1,484.5 | 0.425 / 1,643.4 | 0.787 / 1,634.5 |
| Database / SQLite | 1.198 / 307.8 | 1.169 / 162.1 | 0.258 / 276.0 | 0.696 / 229.4 |
| Object / S3 reader with file provider | 1.788 / 772.8 | 1.786 / 388.3 | 1.187 / 1,076.4 | 1.513 / 857.0 |
| Document / UTF-8 files | 1.223 / 312.2 | 1.136 / 159.6 | 0.323 / 296.4 | 0.735 / 226.4 |

Streaming serially reduces traced peak memory by **47.3%, 49.8% and 48.9%** for
the database, object and document fixtures. Those differences exceed the local
noise allowance. REST's **+3.5%** difference remains within noise, despite retained
batch rows falling from 128 to 16. This shows why a smaller retained payload
cannot be treated as a guaranteed reduction in total Python allocations.

Moving from serial streaming to four-worker FIFO reduces elapsed time by
**64.7%, 77.9%, 33.6% and 71.6%**, respectively, with traced peak increases of
**10.7%, 70.2%, 177.2% and 85.7%**. These are workload/fixture observations, not
predictions for real REST, PostgreSQL, MinIO or document services. In particular,
the object reader still retains a bounded full listing and checkpoint inventory;
batch streaming does not remove those structures.

Process RSS high-water marks include imports and fixture preparation and remain
86.8–91.3 MiB in these captures. The traced-heap differences above do not
establish an equivalent RSS reduction.

## Queue delay and the cost of tenant turns

The fair candidate permits one active job per tenant, with up to four globally.
It lets admitted light-tenant jobs complete while heavy-tenant work remains.
After the two light tenants drain, only one worker processes the heavy tenant.

The table uses light tenant B's descriptive queue p95, pooled across nine jobs
from three trials. This small sample is not an SLO acceptance result.

| Source fixture | FIFO parallel queue p95 | Tenant-turn queue p95 | Total elapsed change, turns vs FIFO |
| --- | --- | --- | --- |
| REST | 396.7 ms | 150.8 ms | +85.3% |
| Database | 220.4 ms | 109.0 ms | +169.4% |
| Object | 1,263.1 ms | 475.5 ms | +27.5% (within noise) |
| Document | 295.4 ms | 124.2 ms | +127.9% |

This candidate trades total drain time for lower waiting time for light tenants.
It is evidence for evaluating per-tenant concurrency separately from a global
worker count; it is not a recommendation to ship a universal one-job limit.
The current production outbox keeps its existing serial/FIFO behavior.

## Saturation and recovery

Each saturation case offers 24 heavy jobs followed by four from each light
tenant. The global waiting cap is 16 and the tenant waiting cap is eight.
Every strategy admits eight heavy and all eight light jobs and explicitly rejects
sixteen heavy jobs. The maximum observed waiting queue is **16**, maximum active
count **4**, and retained batch counters return to zero after every case.

The fair strategy's recorded per-tenant active peak is one. Admission remains
arrival-ordered: these caps do not reserve space for an arbitrary later tenant
once a queue is already full. Deterministic tests additionally verify capacity
recovery, bounded executor submission, failed-source/failed-sink acknowledgement
boundaries, resumed content equality, duplicate replay and conflicting or foreign
checkpoints. They do not use wall-clock thresholds to claim fairness.

## Decision and remaining evidence

Keep the existing production limits and default scheduling. The experiment
supports bounded batch consumption as a useful implementation target, while
showing that worker count, adapter overhead and tenant concurrency need separate
budgets. Production adoption must use the existing host's claim fencing,
checkpoint/audit transaction and policy owners; the benchmark's in-memory sink
and scheduler are not substitutes for those boundaries.

**NOT RUN:** live-provider performance, PostgreSQL driver capacity, durable sink
timing, production outbox fairness/backpressure, multi-worker deployment behavior,
SSO/private-network operation and hosted throughput/SLO acceptance. The original
S3/MinIO host tests remain separate functional evidence. REST and document source
adapters remain their own existing issue scopes.

## Artifacts

[`manifest.json`](manifest.json) records SHA-256 and byte sizes for all four data
artifacts. CI runs a fresh CLI smoke matrix, validates the checked experiment
matrices and regenerates each summary in memory to check equality; it does not
gate machine latency.

| Profile | Complete samples and provenance | Derived summary |
| --- | --- | --- |
| Representative | [report](representative.json.gz) | [summary](representative-summary.json) |
| Saturation | [report](saturation.json.gz) | [summary](saturation-summary.json) |

The source revision identifies the capture, while file hashes permit checking
that later documentation/artifact commits retain the measured implementation.
Historical evidence remains historical if the implementation changes later;
rerun the experiment before claiming a new revision's performance.
