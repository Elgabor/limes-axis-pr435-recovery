# Ingestion streaming, concurrency and backpressure experiments

This is the reproducible evaluation for [#365](https://github.com/Limes-Labs/limes-axis/issues/365).
The runner compares four ingestion strategies on identical synthetic work and
checks their completed content and checkpoints. It measures the cost of buffering
multiple batches, bounded concurrency and tenant turn scheduling before any change
to the production outbox is considered.

The [version 1 capture](benchmarks/ingestion-v1/README.md) records three-trial
representative and saturation results, with complete samples and provenance.

## Current runtime and the experiment boundary

The production [PostgreSQL reader](../services/api/src/axis_api/connector_source_extraction.py)
uses bounded keyset queries where a single-column primary key exists, then returns
the selection's rows in one materialized envelope. A cursor watermark describes
that read; it is not a durable cross-request incremental checkpoint. The
[S3 reader](s3-source-ingestion.md) returns a bounded SDK batch and candidate
inventory, and the host commits binding checkpoints with the request and audit
metadata. The current [outbox dispatcher](../services/api/src/axis_api/connector_source_ingestion.py)
claims a bounded batch and processes requests serially. Its claim query is ordered
by availability/creation/ID; it does not promise tenant turn scheduling.

A benchmark job drains one bounded immutable corpus across SDK-sized batches.
It is not a production outbox request. Here, **streaming** means acknowledging and
discarding each batch before reading the next; individual records, documents and
objects still fit in memory. The materialized comparison stages all the job's
batches before acknowledging them. Neither strategy changes a production port.

| Source shape | What executes | Evidence boundary |
| --- | --- | --- |
| REST | `httpx` request/status/JSON handling with a paginated `MockTransport` | In-process HTTP fixture; generic REST ingestion remains tracked in #336 |
| Database | Read-only SQLite keyset cursor over a real temporary database | Local SQL/decoding shape; not PostgreSQL driver, network or capacity evidence |
| Object | Production `S3ObjectSource`, including enumeration, conditional read contract, content hashes and inventory checkpoints | File-backed provider double; not MinIO/S3 transport or host authorization evidence |
| Document | Separate UTF-8 text files and metadata records | Document payload shape; Microsoft 365/Google Workspace adapters remain tracked in #338 |

Fixtures use three generated tenant aliases and multibyte text. They cannot accept
an operator database, URL, credentials or existing source directory. Every run
creates its own files/database and removes only that temporary corpus. The sink
acknowledges into an in-memory digest and checkpoint after a fixed fixture delay.
It does not prove durable object storage, audit transactions, lease/policy
enforcement or deployment tenant isolation. Existing source/host tests own those
contracts.

## Workloads and strategies

The versioned strict workload model and profiles live in
[`ingestion_fixture.py`](../services/api/scripts/ingestion_fixture.py) and
[`benchmark_ingestion.py`](../services/api/scripts/benchmark_ingestion.py). Their
content hashes are included in each capture.

| Profile | Records/job; text bytes/record | Offered jobs: heavy / light A / light B | Global / tenant queue capacity | Batch rows | Fixture read / sink delay |
| --- | --- | --- | --- | --- | --- |
| `smoke` | 16; 128 | 3 / 1 / 1 | 24 / 12 | 4 | 0 / 0 ms |
| `representative` | 128; 2,048 | 12 / 3 / 3 | 24 / 12 | 16 | 2 / 2 ms per batch |
| `saturation` | 32; 512 | 24 / 4 / 4 | 16 / 8 | 8 | 2 / 2 ms per batch |

All jobs are offered as a burst, with the heavy tenant first. Rejected work is
retained with `tenant_queue_full` or `queue_full`; it never disappears from the
denominator or counts as a completed request. The saturation fixture admits eight
heavy and four jobs from each light tenant, rejecting sixteen heavy jobs. This
tests finite admission under a known skew, not a sustained arrival-rate SLO.

| Strategy | Retention | Maximum active jobs | Selection |
| --- | --- | --- | --- |
| `materialized-serial` | All batches of one bounded job | 1 | FIFO |
| `streamed-serial` | One batch | 1 | FIFO |
| `streamed-parallel` | One batch per active job | 4 | FIFO |
| `streamed-fair` | One batch per active job | 4 globally, 1 per tenant | Tenant rotation |

The coordinator submits only available worker slots, so the executor cannot hide
an unbounded waiting queue. Queue capacity and per-tenant admission caps apply to
every strategy. Tenant rotation protects **admitted jobs** from another tenant
taking every slot; it does not reserve admission for future tenants or provide
byte-weighted, cost-weighted or distributed fairness. With three tenants the fair
candidate can use at most three slots, and when only the heavy tenant remains it
uses one. That throughput tradeoff is part of the experiment.

The experiment retains strict limits: at most 1,000 records/job, 100 records/batch,
1 MiB/batch, 5,000,000 canonical batch bytes/job, 1,000 batches/job and a 30-second
cooperative job budget. Published profiles use smaller values where shown above.
Each read also validates the SDK row/byte/checkpoint contract. Queue and worker
limits are capped at 64 waiting jobs, 32 per tenant and eight workers. Invalid or
incomplete fixture shapes fail before any corpus is created. The parent also
enforces a process timeout; fixture filesystem calls are not evidence of vendor
timeout behavior.

## Run and inspect

Run without other test suites/builds competing for resources:

```sh
make install
make test-api PYTEST_ARGS='tests/test_ingestion_benchmark.py -q'
make benchmark-ingestion BENCHMARK_ARGS='run --profile smoke --trials 1 --output /tmp/axis-ingestion-smoke'
make benchmark-ingestion BENCHMARK_ARGS='run --profile representative --trials 3 --output /tmp/axis-ingestion-representative'
make benchmark-ingestion BENCHMARK_ARGS='run --profile saturation --trials 3 --output /tmp/axis-ingestion-saturation'
```

Use a new output directory each time; existing artifacts are never overwritten.
`report.json.gz` retains every completed/rejected job, dispatch order, queue delay,
processing time, acknowledged rows/bytes/pages, content and checkpoint hashes,
active/retained peaks and source/runtime provenance. `summary.json` aggregates the
same samples. If the experiment is interrupted, `partial.json` retains completed
trials and fails complete-matrix validation. A failing job remains in the report
and makes validation fail; the CLI returns nonzero.

Every source/strategy/trial runs in a fresh Python process, with strategy order
rotated between trials. Fixture generation happens before timing and tracing;
the fixture's files have already been written, so cold storage is not measured.
The parent and child compare source fingerprints to reject edits during a run.
The report binds the workload, relevant runtime/harness files, lockfiles, Git
revision, dirty status, Python/SQLite/library versions and host platform.

## Measurements and comparison policy

- `queue_ms` runs from burst admission to the actual start in a worker, including
  any executor startup delay. `duration_ms` includes source creation, reads, sink
  acknowledgement and source closure. Rejections have no fabricated latency.
- `python_peak_bytes` is peak allocation traced during execution, including
  Python-side adapter/scheduler overhead. `process_rss_high_water_bytes` is the
  fresh process's lifetime RSS high-water mark, **including imports and fixture
  preparation**. The earlier RSS high-water mark is also retained. These are
  different measures; subtracting them does not yield exact ingestion RSS.
- `buffered_rows_peak` and `buffered_bytes_peak` account for retained batches;
  the bytes are canonical JSON size, not Python object size. S3 inventory,
  decoder allocations and executor overhead appear in traced memory separately.
- Completed work must match expected fixture rows and independently constructed
  content hashes. All strategies/trials must agree on acknowledged bytes/pages,
  content and final checkpoint. Faster failures, missing jobs, changed admission,
  changed sources or different work cannot become an improvement.
- A comparison needs three trials. Each factor changes one strategy dimension:
  materialization → streaming, serial → parallel, FIFO → tenant turns. Median
  differences within the larger of 5% of the baseline or either trial range are
  `within-noise`. This is a local screening rule, not statistical significance.
  Small per-tenant p95/p99 samples are descriptive; deployment SLOs remain
  `NOT RUN` regardless of the local result.

## Acceptance and verification

| Issue criterion | Evidence |
| --- | --- |
| Representative REST/database/object/document sources | Four explicit fixture adapters, with current S3 reader adoption and transport limits above |
| Peak memory and queue delay | Fresh-process traced heap/RSS plus retained batch and per-job queue accounting |
| Streaming/materialization and bounded parallelism | Four controlled strategies, content/checkpoint equality and three-trial comparison |
| Backpressure and tenant fairness | Saturation workload, explicit rejections, bounded executor tests and a light tenant completing while a heavy tenant waits |
| Deterministic checkpoints and replay | Failed-read/failed-sink resumption, duplicate acknowledgement, conflicting replay and cross-tenant checkpoint rejection tests |

The deterministic suite also covers byte/row/page/time limits, source-opening
failures, artifact overwrite protection, report corruption, missing work,
runtime drift and the comparison noise rule. It does not gate CI on machine
latency. This measurement slice introduces no production concurrency setting,
scheduler, connector registration, storage behavior or public API change.
