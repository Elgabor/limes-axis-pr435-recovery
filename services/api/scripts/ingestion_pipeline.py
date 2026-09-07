"""Benchmark-only strategies, not the production outbox scheduler or object store.

The bounded coordinator never submits an unbounded executor queue. The fair
candidate rotates tenants and permits one active job per tenant. Its cost when
one tenant remains is intentionally visible in the measurements.
"""

from __future__ import annotations

import hashlib
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Lock
from time import monotonic, sleep

from axis_sdk.connector_authoring import ReadRequest, batch_byte_size
from ingestion_fixture import Corpus, Position, Workload, canonical, digest

MODES = ("materialized-serial", "streamed-serial", "streamed-parallel", "streamed-fair")


@dataclass(frozen=True)
class Job:
    tenant: str
    ordinal: int


def offered_jobs(workload: Workload) -> list[Job]:
    return [
        Job(tenant, ordinal)
        for tenant, count in (
            ("heavy", workload.heavy_jobs),
            ("light-a", workload.light_jobs),
            ("light-b", workload.light_jobs),
        )
        for ordinal in range(count)
    ]


class BoundedQueue:
    """Single-coordinator admission with explicit global and tenant rejection."""

    def __init__(self, capacity: int, tenant_capacity: int, *, fair: bool):
        if capacity < 1 or tenant_capacity < 1:
            raise ValueError("queue capacities must be positive")
        self.capacity, self.tenant_capacity, self.fair = capacity, tenant_capacity, fair
        self.pending = deque()
        self.tenants = deque()
        self.counts = Counter()
        self.active = Counter()
        self.active_peak = Counter()
        self.peak = 0

    def offer(self, job: Job) -> str | None:
        if self.counts[job.tenant] >= self.tenant_capacity:
            return "tenant_queue_full"
        if len(self.pending) >= self.capacity:
            return "queue_full"
        if job.tenant not in self.tenants:
            self.tenants.append(job.tenant)
        self.pending.append(job)
        self.counts[job.tenant] += 1
        self.peak = max(self.peak, len(self.pending))
        return None

    def take(self) -> Job | None:
        selected = None
        if not self.fair and self.pending:
            selected = self.pending[0]
        elif self.fair:
            for _ in range(len(self.tenants)):
                tenant = self.tenants[0]
                self.tenants.rotate(-1)
                if self.counts[tenant] and not self.active[tenant]:
                    selected = next(job for job in self.pending if job.tenant == tenant)
                    break
        if selected is not None:
            self.pending.remove(selected)
            self.counts[selected.tenant] -= 1
            self.active[selected.tenant] += 1
            self.active_peak[selected.tenant] = max(
                self.active_peak[selected.tenant], self.active[selected.tenant]
            )
        return selected

    def finish(self, job: Job):
        if self.active[job.tenant] < 1:
            raise ValueError("job was not active")
        self.active[job.tenant] -= 1


class BufferMeter:
    """Retained canonical batch bytes, separate from traced heap and process RSS."""

    def __init__(self):
        self.lock = Lock()
        self.rows = self.bytes = self.peak_rows = self.peak_bytes = 0

    def add(self, rows: int, size: int):
        with self.lock:
            self.rows += rows
            self.bytes += size
            self.peak_rows = max(self.peak_rows, self.rows)
            self.peak_bytes = max(self.peak_bytes, self.bytes)

    def remove(self, rows: int, size: int):
        with self.lock:
            self.rows -= rows
            self.bytes -= size
            assert self.rows >= 0 and self.bytes >= 0


class DigestSink:
    """Acknowledgement fixture with replay deduplication; no durability claim."""

    def __init__(self, source, *, delay_ms=0, fail_page=None):
        self.source = source
        self.delay_ms, self.fail_page = delay_ms, fail_page
        self.position = Position()
        self.rows = self.bytes = self.pages = 0
        self.hash = hashlib.sha256()
        self.accepted = {}

    def commit(self, batch, candidate: Position):
        request = ReadRequest(
            context=self.source.context,
            resource=self.source.resource,
            checkpoint=self.position.checkpoint,
            limits=self.source.limits,
        )
        if batch.checkpoint is None or batch.checkpoint != candidate.checkpoint:
            raise ValueError("missing or mismatched candidate checkpoint")
        identity = digest(batch.checkpoint.storage_record())
        if identity in self.accepted:
            batch.validate_for(request.model_copy(update={"checkpoint": None}))
            if not batch.records and batch.completion == "complete":
                return
            if self.accepted[identity] != digest(batch.records):
                raise ValueError("conflicting replay")
            return
        batch.validate_for(request)
        sleep(self.delay_ms / 1000)
        if self.fail_page == self.pages:
            raise OSError("injected sink failure")
        # No mutation before validation/acknowledgement. Retry starts at position.
        encoded = [canonical(row) + b"\n" for row in batch.records]
        for row in encoded:
            self.hash.update(row)
        self.rows += len(batch.records)
        self.bytes += sum(map(len, encoded))
        self.pages += 1
        self.accepted[identity] = digest(batch.records)
        self.position = candidate


def consume(source, sink: DigestSink, *, materialize: bool, meter: BufferMeter):
    """Bound both individual reads and the entire job; acknowledge before resume."""
    position = sink.position
    staged = deque()
    deadline = monotonic() + source.workload.request_seconds
    total_rows = total_bytes = 0
    try:
        for _ in range(source.workload.max_pages):
            if monotonic() >= deadline:
                raise TimeoutError("job budget exhausted")
            batch, candidate = source.read(position)
            if monotonic() >= deadline:
                raise TimeoutError("job budget exhausted")
            total_rows += len(batch.records)
            if total_rows > source.workload.records:
                raise ValueError("job row limit exceeded")
            size = batch_byte_size(batch.records)
            total_bytes += size
            if total_bytes > source.workload.job_bytes:
                raise ValueError("job byte limit exceeded")
            staged.append((batch, candidate, size))
            meter.add(len(batch.records), size)
            if not materialize:
                sink.commit(batch, candidate)
                staged.popleft()
                meter.remove(len(batch.records), size)
            # Materialized pages remain speculative until all are read. The
            # committed sink position stays unchanged if the read fails.
            position = candidate
            if batch.completion == "complete":
                break
            if batch.completion != "more":
                raise ValueError("unexpected truncated fixture")
        else:
            raise ValueError("job page limit exceeded")
        while staged:
            if monotonic() >= deadline:
                raise TimeoutError("job budget exhausted")
            batch, candidate, size = staged[0]
            sink.commit(batch, candidate)
            staged.popleft()
            meter.remove(len(batch.records), size)
        if monotonic() >= deadline:
            # A final slow acknowledgement must not turn an exceeded job budget
            # into a successful timing sample. Already acknowledged progress stays.
            raise TimeoutError("job budget exhausted")
    finally:
        for batch, _candidate, size in staged:
            meter.remove(len(batch.records), size)


def process_job(corpus: Corpus, kind: str, job: Job, mode: str, meter, offered_at: float):
    started = monotonic()
    result = {
        "tenant": job.tenant,
        "job": job.ordinal,
        "queue_ms": (started - offered_at) * 1000,
        "status": "PASS",
        "error": None,
    }
    sink = None
    try:
        with corpus.source(kind, job.tenant) as source:
            sink = DigestSink(source, delay_ms=corpus.workload.sink_delay_ms)
            consume(source, sink, materialize=mode == "materialized-serial", meter=meter)
            if (
                sink.rows != corpus.workload.records
                or sink.hash.hexdigest() != corpus.expected[kind, job.tenant]
            ):
                raise ValueError("fixture completion mismatch")
    except Exception as exc:
        # Exceptions can contain source data; retain only their type, including
        # failures opening or closing a source. All offered jobs stay accounted.
        result.update(status="FAIL", error=type(exc).__name__)
    result.update(
        records=sink.rows if sink else 0,
        bytes=sink.bytes if sink else 0,
        pages=sink.pages if sink else 0,
        payload_sha256=sink.hash.hexdigest() if sink else None,
        checkpoint_sha256=(
            digest(sink.position.checkpoint.storage_record())
            if sink and sink.position.checkpoint
            else None
        ),
    )
    result["duration_ms"] = (monotonic() - started) * 1000
    return result


def execute(corpus: Corpus, kind: str, mode: str, *, process=process_job):
    if mode not in MODES:
        raise ValueError("unknown strategy")
    workload = corpus.workload
    queue = BoundedQueue(
        workload.queue_capacity,
        workload.tenant_queue_capacity,
        fair=mode == "streamed-fair",
    )
    workers = workload.workers if mode in {"streamed-parallel", "streamed-fair"} else 1
    jobs, rejected, samples, order = offered_jobs(workload), [], [], []
    meter = BufferMeter()
    started = monotonic()
    for job in jobs:
        reason = queue.offer(job)
        if reason:
            rejected.append({"tenant": job.tenant, "job": job.ordinal, "reason": reason})
    active_peak = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        active = {}
        while queue.pending or active:
            while len(active) < workers:
                job = queue.take()
                if job is None:
                    break
                order.append({"tenant": job.tenant, "job": job.ordinal})
                future = executor.submit(process, corpus, kind, job, mode, meter, started)
                active[future] = job
                active_peak = max(active_peak, len(active))
            if not active:
                raise ValueError("queue made no progress")
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                job = active.pop(future)
                try:
                    samples.append(future.result())
                finally:
                    queue.finish(job)
    return {
        "source": kind,
        "mode": mode,
        "offered": len(jobs),
        "seconds": monotonic() - started,
        "samples": samples,
        "rejected": rejected,
        "dispatch_order": order,
        "active_peak": active_peak,
        "queue_peak": queue.peak,
        "tenant_active_peak": dict(queue.active_peak),
        "buffered_rows_peak": meter.peak_rows,
        "buffered_bytes_peak": meter.peak_bytes,
        "buffered_rows_at_end": meter.rows,
        "buffered_bytes_at_end": meter.bytes,
    }
