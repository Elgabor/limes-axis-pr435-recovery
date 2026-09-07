"""Bounded measurement helpers; SQL values and frame locals are never collected."""

import hashlib
import html
import math
import sys
import threading
from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from sqlalchemy import event


@dataclass
class RequestMetrics:
    statements: int = 0
    sql_ms: float = 0


REQUEST_METRICS = ContextVar("performance_request_metrics", default=None)


def percentile(values, percent):
    """Nearest-rank estimator, with no interpolation or fabricated empty zero."""
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * percent / 100) - 1)]


def distribution(values):
    return {
        "count": len(values),
        **{f"p{percent}": percentile(values, percent) for percent in (50, 95, 99)},
        "max": max(values) if values else None,
    }


class DatabaseMetrics:
    def __init__(self, engine):
        self.engine = engine
        self.lock = threading.Lock()
        self.checked_out = {}
        self.peak = 0
        self.connection_seconds = 0
        self.queries = {}
        self.listeners = [
            ("checkout", self.checkout),
            ("checkin", self.checkin),
            ("before_cursor_execute", self.before),
            ("after_cursor_execute", self.after),
            ("handle_error", self.error),
        ]

    def __enter__(self):
        for name, callback in self.listeners:
            event.listen(self.engine, name, callback)
        return self

    def __exit__(self, *_exc):
        for name, callback in self.listeners:
            event.remove(self.engine, name, callback)

    def checkout(self, _connection, record, _proxy):
        with self.lock:
            self.checked_out[id(record)] = perf_counter()
            self.peak = max(self.peak, len(self.checked_out))

    def checkin(self, _connection, record):
        with self.lock:
            started = self.checked_out.pop(id(record), None)
            if started is not None:
                self.connection_seconds += perf_counter() - started

    def before(self, _connection, _cursor, statement, _parameters, context, _many):
        context._performance_start = perf_counter()
        context._performance_fingerprint = hashlib.sha256(statement.encode()).hexdigest()[:16]
        context._performance_operation = statement.split(maxsplit=1)[0].upper()
        request = REQUEST_METRICS.get()
        if request is not None:
            request.statements += 1

    def finish_query(self, context):
        started = getattr(context, "_performance_start", None)
        if started is None:
            return
        context._performance_start = None
        elapsed = (perf_counter() - started) * 1000
        request = REQUEST_METRICS.get()
        if request is not None:
            request.sql_ms += elapsed
        with self.lock:
            key = context._performance_fingerprint
            stats = self.queries.setdefault(
                key,
                {
                    "fingerprint": key,
                    "operation": context._performance_operation,
                    "count": 0,
                    "total_ms": 0,
                    "max_ms": 0,
                },
            )
            stats["count"] += 1
            stats["total_ms"] += elapsed
            stats["max_ms"] = max(stats["max_ms"], elapsed)

    def after(self, _connection, _cursor, _statement, _parameters, context, _many):
        self.finish_query(context)

    def error(self, context):
        if context.execution_context is not None:
            self.finish_query(context.execution_context)

    def snapshot(self, seconds):
        with self.lock:
            now = perf_counter()
            held = self.connection_seconds + sum(now - start for start in self.checked_out.values())
            return {
                "pool_peak": self.peak,
                "pool_at_end": len(self.checked_out),
                "pool_connection_seconds": held,
                "pool_mean_occupied": held / seconds,
                "query_fingerprints": sorted(
                    self.queries.values(),
                    key=lambda item: item["total_ms"],
                    reverse=True,
                ),
            }


class StackSampler:
    """Sample Python wall stacks containing API frames, including sync workers.

    This observes Python frames, not native CPU stacks or async causal ancestry.
    Waiting outside an API frame is excluded, so widths are shares of collected
    stacks, not percentages of total CPU utilization or end-to-end latency.
    """

    def __init__(self, root: Path, interval=0.01):
        self.root = str(root) + "/"
        self.interval = interval
        self.stacks = Counter()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, name="performance-sampler", daemon=True)

    def sample(self):
        while not self.stop.wait(self.interval):
            for thread_id, frame in sys._current_frames().items():
                if thread_id == self.thread.ident:
                    continue
                stack = []
                has_api = False
                while frame is not None:
                    filename = frame.f_code.co_filename
                    has_api |= "/axis_api/" in filename
                    filename = filename.removeprefix(self.root)
                    if filename.startswith("/"):
                        filename = Path(filename).name
                    label = f"{filename}:{frame.f_code.co_name}:{frame.f_lineno}"
                    stack.append(label.replace(";", ":").replace("\n", " "))
                    frame = frame.f_back
                if has_api:
                    key = tuple(reversed(stack))
                    if key not in self.stacks and len(self.stacks) >= 4096:
                        key = ("stack-cardinality-limit",)
                    self.stacks[key] += 1

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.stop.set()
        self.thread.join(timeout=2)

    def write(self, prefix: Path):
        prefix.with_suffix(".folded").write_text(
            "".join(f"{';'.join(stack)} {count}\n" for stack, count in sorted(self.stacks.items()))
        )
        prefix.with_suffix(".svg").write_text(flamegraph(self.stacks))


def flamegraph(stacks):
    tree = {"count": 0, "children": {}}
    depth = 0
    for stack, count in stacks.items():
        depth = max(depth, len(stack))
        node = tree
        node["count"] += count
        for label in stack:
            node = node["children"].setdefault(label, {"count": 0, "children": {}})
            node["count"] += count
    height = 70 + depth * 20
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" '
        f'viewBox="0 0 1200 {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="10" y="20" font-family="sans-serif" font-size="14">'
        "Axis Python wall-stack samples — hover for frames (not CPU utilization)</text>",
        f'<text x="10" y="40" font-family="sans-serif" font-size="12">'
        f"{tree['count']} collected stacks; waiting without API frames excluded</text>",
    ]

    def draw(node, x, level, width):
        position = x
        for label, child in sorted(node["children"].items()):
            child_width = width * child["count"] / node["count"]
            y = height - 20 * (level + 1)
            color = int(hashlib.sha256(label.encode()).hexdigest()[:2], 16)
            parts.append(
                f"<g><title>{html.escape(label)} ({child['count']} samples)</title>"
                f'<rect x="{position:.3f}" y="{y}" width="{child_width:.3f}" height="19" '
                f'fill="rgb(245,{120 + color // 2},80)" stroke="white" stroke-width="0.3"/>'
            )
            if child_width > 65:
                fields = label.split(":")
                short = (fields[-2] if len(fields) > 1 else label)[: int(child_width / 7)]
                parts.append(
                    f'<text x="{position + 3:.3f}" y="{y + 14}" '
                    f'font-family="monospace" font-size="11">{html.escape(short)}</text>'
                )
            parts.append("</g>")
            draw(child, position, level + 1, child_width)
            position += child_width

    if tree["count"]:
        draw(tree, 0, 0, 1200)
    parts.append("</svg>")
    return "\n".join(parts)
