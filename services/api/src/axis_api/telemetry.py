"""OpenTelemetry bootstrap for the Axis API (off by default).

The whole subsystem is gated by :attr:`Settings.otel_enabled` (``AXIS_OTEL_ENABLED``,
default ``false``). When disabled, :func:`configure_api_telemetry` returns a
:class:`TelemetryRuntime` whose tracer/meter are the process-global *no-op*
providers, so instrumented code paths create non-recording spans and no-op metric
instruments — zero exporters installed, negligible overhead, and no behavior
change for existing deployments or the default test suite.

When enabled we build an app-scoped :class:`~opentelemetry.sdk.trace.TracerProvider`
and :class:`~opentelemetry.sdk.metrics.MeterProvider` (never mutating the OTel
global providers, so multiple app instances and tests stay isolated) with a
``Resource`` describing ``service.name`` / ``service.version`` /
``deployment.environment`` and an OTLP/HTTP exporter pointed at
``AXIS_OTEL_EXPORTER_OTLP_ENDPOINT``.

Privacy: span attributes and metric labels follow the same rule as audit
payloads — only stable, non-sensitive identifiers (tenant id, actor id, resource
ids, outcomes). Never record tokens, secrets, client IPs, or raw payload values.
See :data:`SENSITIVE_ATTRIBUTE_FORBIDDEN_SUBSTRINGS`.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Mapping
from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Meter, MeterProvider
from opentelemetry.propagators.textmap import CarrierT
from opentelemetry.trace import Span, Tracer, TracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from axis_api.config import Settings

DEFAULT_SERVICE_NAME = "limes-axis-api"
SERVICE_VERSION = "0.0.0"
_INSTRUMENTATION_SCOPE = "axis_api"

# Non-sensitive span attribute / metric label keys. These mirror the identifiers
# already surfaced in audit payloads.
ATTR_TENANT_ID = "axis.tenant_id"
ATTR_ACTOR_ID = "axis.actor_id"
ATTR_ACTION_ID = "axis.action_id"
ATTR_ACTION_RUN_ID = "axis.action_run_id"
ATTR_APPROVAL_ID = "axis.approval_id"
ATTR_CONNECTOR_ID = "axis.connector_id"
ATTR_EXECUTION_MODE = "axis.execution_mode"
ATTR_OUTCOME = "axis.outcome"
ATTR_WORKFLOW_ID = "axis.workflow_id"
ATTR_SIGNAL_NAME = "axis.signal_name"
ATTR_SIGNAL_STATUS = "axis.signal_status"
ATTR_DECISION = "axis.decision"
ATTR_EXPORT_FORMAT = "axis.export_format"
ATTR_JOB = "axis.job"
ATTR_MODEL_PROVIDER_ID = "axis.model.provider_id"
ATTR_MODEL_ID = "axis.model.model_id"
ATTR_MODEL_LATENCY_MS = "axis.model.latency_ms"
ATTR_MODEL_INPUT_TOKENS = "axis.model.input_tokens"
ATTR_MODEL_OUTPUT_TOKENS = "axis.model.output_tokens"

# Defence-in-depth guard: attribute keys containing any of these substrings must
# never be attached to a span. Callers are expected to only pass the curated keys
# above; this is a belt-and-braces filter enforced by ``set_span_attributes``.
# Substrings are matched with word boundaries (see ``_is_sensitive_attribute_key``)
# so e.g. "token" matches "id_token" but a benign key like "axis.recipe_id" is not
# stripped just because it contains "ip"/"id".
SENSITIVE_ATTRIBUTE_FORBIDDEN_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "credential",
    "api_key",
    "apikey",
)

# Client-IP attributes emitted by the ASGI/HTTP instrumentation. Matched exactly
# (not by the bare substring "ip", which would strip benign keys like
# "axis.pipeline_id"). Covers both the legacy and stable HTTP semantic conventions.
SENSITIVE_IP_ATTRIBUTE_KEYS = frozenset(
    {
        "net.peer.ip",
        "net.sock.peer.addr",
        "net.host.ip",
        "client.address",
        "client.socket.address",
        "http.client_ip",
    }
)

# URL attributes whose value carries the raw query string (which may contain
# cursors, filters, or — defensively — a token in a query param). The path is
# kept; everything from "?" onward is scrubbed before export.
URL_QUERY_ATTRIBUTE_KEYS = frozenset({"http.url", "http.target", "url.full", "url.query"})

_SENSITIVE_WORD_BOUNDARY_PATTERNS = tuple(
    re.compile(rf"(?:^|[^a-z0-9])({re.escape(term)})(?:[^a-z0-9]|$)")
    for term in SENSITIVE_ATTRIBUTE_FORBIDDEN_SUBSTRINGS
)

_W3C_PROPAGATOR = TraceContextTextMapPropagator()


def _is_sensitive_attribute_key(key: str) -> bool:
    lowered = key.casefold()
    if lowered in SENSITIVE_IP_ATTRIBUTE_KEYS:
        return True
    return any(pattern.search(lowered) for pattern in _SENSITIVE_WORD_BOUNDARY_PATTERNS)


def _scrub_query_from_url(value: object) -> object:
    """Strip the query string from a URL-bearing attribute value.

    ``url.query`` holds only the query, so scrubbing it yields an empty string.
    ``http.url`` / ``http.target`` keep scheme/host/path.
    """
    if isinstance(value, str) and "?" in value:
        return value.split("?", 1)[0]
    return value


def set_span_attributes(span: Span, attributes: Mapping[str, object]) -> None:
    """Attach non-null, non-sensitive attributes to ``span``.

    Silently drops ``None`` values (so callers can pass optional ids uniformly)
    and any key that trips the sensitive-substring guard.
    """

    for key, value in attributes.items():
        if value is None:
            continue
        if _is_sensitive_attribute_key(key):
            continue
        span.set_attribute(key, value)


def annotate_current_span(attributes: Mapping[str, object]) -> None:
    """Attach attributes to whatever span is active in the current context.

    Used by the principal resolver to tag the auto-instrumentation request span
    with tenant/actor once identity is known. A no-op when no span is recording.
    """

    span = trace.get_current_span()
    if not span.is_recording():
        return
    set_span_attributes(span, attributes)


def inject_trace_context(carrier: CarrierT | None = None) -> dict[str, str]:
    """Serialise the active W3C trace context into a carrier dict.

    Returns an empty dict when no span is recording (telemetry disabled or no
    active span), so the outbound signal payload is unchanged in that case.
    """

    target: dict[str, str] = {} if carrier is None else carrier  # type: ignore[assignment]
    _W3C_PROPAGATOR.inject(target)
    return target


def extract_trace_context(carrier: CarrierT):
    """Rebuild an OTel context from a carrier produced by :func:`inject_trace_context`."""

    return _W3C_PROPAGATOR.extract(carrier)


@dataclass(frozen=True)
class TelemetryRuntime:
    """Handle to the tracer, meter, and metric instruments for one service.

    When ``enabled`` is ``False`` the tracer/meter are the OTel no-op globals and
    all instruments are no-ops, so instrumented code stays branch-free.
    """

    enabled: bool
    tracer: Tracer
    meter: Meter
    tracer_provider: TracerProvider | None
    meter_provider: MeterProvider | None
    action_run_counter: Counter
    connector_sync_rows_counter: Counter
    approval_decision_counter: Counter
    audit_export_counter: Counter
    deprecated_request_counter: Counter

    @property
    def metrics_enabled(self) -> bool:
        return self.meter_provider is not None


def _noop_runtime() -> TelemetryRuntime:
    tracer = trace.get_tracer(_INSTRUMENTATION_SCOPE, SERVICE_VERSION)
    meter = metrics.get_meter(_INSTRUMENTATION_SCOPE, SERVICE_VERSION)
    return _build_runtime(
        enabled=False,
        tracer=tracer,
        meter=meter,
        tracer_provider=None,
        meter_provider=None,
    )


def _build_runtime(
    *,
    enabled: bool,
    tracer: Tracer,
    meter: Meter,
    tracer_provider: TracerProvider | None,
    meter_provider: MeterProvider | None,
) -> TelemetryRuntime:
    return TelemetryRuntime(
        enabled=enabled,
        tracer=tracer,
        meter=meter,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        action_run_counter=meter.create_counter(
            "axis.action_runs",
            unit="1",
            description="Persisted manufacturing action runs by outcome.",
        ),
        connector_sync_rows_counter=meter.create_counter(
            "axis.connector_sync_rows",
            unit="1",
            description="Rows ingested by connector sync execution.",
        ),
        approval_decision_counter=meter.create_counter(
            "axis.approval_decisions",
            unit="1",
            description="Recorded approval decisions by decision value.",
        ),
        audit_export_counter=meter.create_counter(
            "axis.audit_exports",
            unit="1",
            description="Audit evidence export operations.",
        ),
        deprecated_request_counter=meter.create_counter(
            "axis.api.deprecated_requests",
            unit="1",
            description="Legacy API responses by registered route, method and status.",
        ),
    )


def scrub_span_attributes(attributes: Mapping[str, object]) -> dict[str, object] | None:
    """Return a privacy-scrubbed copy of ``attributes``, or ``None`` if unchanged.

    Enforces the audit-grade privacy rules on the raw attributes recorded by the
    framework instrumentation (which we do not control directly):

    - drop any attribute whose key is a client-IP key or trips the sensitive-key
      guard (tokens, secrets, cookies, ...);
    - scrub the query string from URL-bearing attributes (``http.url`` /
      ``http.target`` / ``url.full`` / ``url.query``) so cursors, filters, or a
      token planted in a query param are never exported — the path is kept.
    """

    scrubbed: dict[str, object] = {}
    changed = False
    for key, value in attributes.items():
        if _is_sensitive_attribute_key(key):
            changed = True
            continue
        if key.casefold() in URL_QUERY_ATTRIBUTE_KEYS:
            cleaned = _scrub_query_from_url(value)
            if cleaned != value:
                changed = True
            scrubbed[key] = cleaned
            continue
        scrubbed[key] = value
    return scrubbed if changed else None


class _PrivacyFilteringSpanExporter:
    """Wrap a span exporter and privacy-scrub every span before export.

    The FastAPI/ASGI auto-instrumentation records standard HTTP attributes that
    include the client IP (``net.peer.ip`` / ``client.address``) and the full
    request URL with its query string. Axis follows the same privacy rules as its
    audit payloads — no IPs, tokens, secrets, or raw query strings — so every span
    is scrubbed here regardless of which exporter is configured.
    """

    def __init__(self, wrapped) -> None:
        self._wrapped = wrapped

    def export(self, spans):
        for span in spans:
            attributes = span.attributes
            if not attributes:
                continue
            scrubbed = scrub_span_attributes(attributes)
            if scrubbed is not None:
                span._attributes = scrubbed
        return self._wrapped.export(spans)

    def shutdown(self):
        return self._wrapped.shutdown()

    def force_flush(self, timeout_millis: int = 30_000):
        return self._wrapped.force_flush(timeout_millis)


def shutdown_providers(tracer_provider, meter_provider) -> None:
    """Flush and shut down app-scoped providers (no-op when none installed).

    Ensures BatchSpanProcessor-buffered spans are exported and the exporter
    threads are torn down on API/worker shutdown. Guards each call so a failing
    exporter never breaks graceful shutdown.
    """

    for provider in (tracer_provider, meter_provider):
        if provider is None:
            continue
        for method in ("force_flush", "shutdown"):
            hook = getattr(provider, method, None)
            if hook is None:
                continue
            # Shutdown must never raise and break graceful teardown.
            with contextlib.suppress(Exception):
                hook()


def build_resource(settings: Settings, *, service_name: str, service_version: str):
    """Build an OTel ``Resource`` from settings (imported lazily to stay light)."""

    from opentelemetry.sdk.resources import Resource

    return Resource.create(
        {
            "service.name": settings.otel_service_name or service_name,
            "service.version": service_version,
            "deployment.environment": settings.environment,
        }
    )


def build_sdk_providers(
    settings: Settings,
    *,
    service_name: str,
    service_version: str,
    span_exporter=None,
    metric_reader=None,
):
    """Build app-scoped tracer/meter providers + tracer/meter for one service.

    Shared by the API and worker bootstraps. Never touches the OTel global
    providers, so each caller (and each test) stays isolated. Returns
    ``(tracer_provider, meter_provider_or_none, tracer, meter)``.
    """

    from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    resource = build_resource(
        settings,
        service_name=service_name,
        service_version=service_version,
    )
    tracer_provider = SdkTracerProvider(resource=resource)
    if span_exporter is not None:
        tracer_provider.add_span_processor(
            SimpleSpanProcessor(_PrivacyFilteringSpanExporter(span_exporter))
        )
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                _PrivacyFilteringSpanExporter(
                    OTLPSpanExporter(endpoint=_traces_endpoint(settings))
                )
            )
        )
    tracer = tracer_provider.get_tracer(_INSTRUMENTATION_SCOPE, service_version)

    meter_provider = None
    if settings.otel_metrics_enabled or metric_reader is not None:
        from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider

        reader = metric_reader or _otlp_metric_reader(settings)
        meter_provider = SdkMeterProvider(resource=resource, metric_readers=[reader])
        meter = meter_provider.get_meter(_INSTRUMENTATION_SCOPE, service_version)
    else:
        meter = metrics.get_meter(_INSTRUMENTATION_SCOPE, service_version)

    return tracer_provider, meter_provider, tracer, meter


def configure_api_telemetry(
    settings: Settings,
    *,
    span_exporter=None,
    metric_reader=None,
) -> TelemetryRuntime:
    """Bootstrap tracing/metrics for the API.

    ``span_exporter`` / ``metric_reader`` are injection points for tests (e.g. an
    in-memory span exporter); in production they are ``None`` and an OTLP/HTTP
    exporter is built from settings. Returns a no-op runtime when disabled.
    """

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


def instrument_fastapi_app(app, runtime: TelemetryRuntime) -> None:
    """Attach FastAPI/ASGI auto-instrumentation using the app-scoped providers."""

    if not runtime.enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=runtime.tracer_provider,
        meter_provider=runtime.meter_provider,
    )


def _traces_endpoint(settings: Settings) -> str:
    return settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"


def _metrics_endpoint(settings: Settings) -> str:
    return settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/metrics"


def _otlp_metric_reader(settings: Settings):
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    return PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=_metrics_endpoint(settings)),
    )


def observability_posture(settings: Settings) -> dict[str, object]:
    """Return the observability readiness posture surfaced by the readiness report."""

    return {
        "otel_enabled": settings.otel_enabled,
        "otel_metrics_enabled": settings.otel_enabled and settings.otel_metrics_enabled,
        "otel_exporter_endpoint_configured": bool(
            settings.otel_exporter_otlp_endpoint.strip()
        ),
        "otel_traces_endpoint": _traces_endpoint(settings) if settings.otel_enabled else None,
    }
