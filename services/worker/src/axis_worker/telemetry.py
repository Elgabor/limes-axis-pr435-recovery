"""OpenTelemetry bootstrap for the Axis worker (off by default).

Mirrors :mod:`axis_api.telemetry`: gated by ``AXIS_OTEL_ENABLED`` (default
``false``), builds an app-scoped tracer/meter provider (never the OTel globals)
with a ``limes-axis-worker`` resource and an OTLP/HTTP exporter, and is a clean
no-op when disabled. Reuses the shared provider builder and propagation helpers
from ``axis_api.telemetry`` (the worker already depends on the API package).

Scheduled maintenance activities are wrapped in a root span (they have no
inbound trace context). :func:`extract_trace_context` lets a signalled
workflow/activity that receives a propagated ``traceparent`` continue the
originating trace.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

from axis_api.config import Settings
from axis_api.telemetry import (
    ATTR_JOB,
    ATTR_OUTCOME,
    SERVICE_VERSION,
    build_sdk_providers,
    extract_trace_context,
    set_span_attributes,
)
from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Meter, MeterProvider
from opentelemetry.propagators.textmap import CarrierT
from opentelemetry.trace import Span, Tracer, TracerProvider

DEFAULT_SERVICE_NAME = "limes-axis-worker"
_INSTRUMENTATION_SCOPE = "axis_worker"


@dataclass(frozen=True)
class WorkerTelemetryRuntime:
    """Tracer/meter handle for the worker; no-ops when telemetry is disabled."""

    enabled: bool
    tracer: Tracer
    meter: Meter
    tracer_provider: TracerProvider | None
    meter_provider: MeterProvider | None
    scheduled_job_counter: Counter
    source_ingestion_stage_counter: Counter

    @contextmanager
    def activity_span(
        self,
        name: str,
        *,
        carrier: CarrierT | None = None,
        attributes: Mapping[str, object] | None = None,
    ) -> Iterator[Span]:
        """Start a span for a worker activity/workflow step.

        If ``carrier`` holds a propagated W3C context (e.g. from a signalled
        workflow payload) the span is linked as a child of the originating
        trace; otherwise it is a root span (the scheduled-job case).
        """

        context = extract_trace_context(carrier) if carrier else None
        with self.tracer.start_as_current_span(name, context=context) as span:
            if attributes:
                set_span_attributes(span, attributes)
            yield span

    def record_job_run(self, *, job: str, status: str) -> None:
        self.scheduled_job_counter.add(1, {"job": job, "status": status})


def _build_runtime(
    *,
    enabled: bool,
    tracer: Tracer,
    meter: Meter,
    tracer_provider: TracerProvider | None,
    meter_provider: MeterProvider | None,
) -> WorkerTelemetryRuntime:
    return WorkerTelemetryRuntime(
        enabled=enabled,
        tracer=tracer,
        meter=meter,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        scheduled_job_counter=meter.create_counter(
            "axis.scheduled_job_runs",
            unit="1",
            description="Scheduled maintenance job runs by job and status.",
        ),
        source_ingestion_stage_counter=meter.create_counter(
            "axis.source_ingestion_dispatch_outcomes",
            unit="1",
            description=(
                "Governed source ingestion dispatch outcomes per pass, "
                "labelled by outcome only — never request payloads."
            ),
        ),
    )


def _noop_runtime() -> WorkerTelemetryRuntime:
    tracer = trace.get_tracer(_INSTRUMENTATION_SCOPE, SERVICE_VERSION)
    meter = metrics.get_meter(_INSTRUMENTATION_SCOPE, SERVICE_VERSION)
    return _build_runtime(
        enabled=False,
        tracer=tracer,
        meter=meter,
        tracer_provider=None,
        meter_provider=None,
    )


def configure_worker_telemetry(
    settings: Settings,
    *,
    span_exporter=None,
    metric_reader=None,
) -> WorkerTelemetryRuntime:
    """Bootstrap tracing/metrics for the worker; no-op runtime when disabled."""

    if not settings.otel_enabled:
        return _noop_runtime()

    tracer_provider, meter_provider, tracer, meter = build_sdk_providers(
        settings,
        service_name=DEFAULT_SERVICE_NAME,
        service_version=SERVICE_VERSION,
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )
    return _build_runtime(
        enabled=True,
        tracer=tracer,
        meter=meter,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )


__all__ = [
    "ATTR_JOB",
    "ATTR_OUTCOME",
    "WorkerTelemetryRuntime",
    "configure_worker_telemetry",
]
