# Platform Observability (OpenTelemetry)

The observability slice adds OpenTelemetry (OTel) distributed tracing and metrics
to the API (`services/api`) and the Temporal worker (`services/worker`). Before
it, the platform emitted a rich append-only audit ledger but had no distributed
tracing: there was no way to follow a single request across the API and into a
signalled workflow on the worker, and no request/operation latency or throughput
signals beyond logs.

The entire subsystem is **off by default** and gated by a single master flag
(`AXIS_OTEL_ENABLED`, default `false`). When disabled, no provider is installed,
the tracer/meter are the OTel process-global no-ops, and every instrumented code
path creates non-recording spans and no-op metric instruments — negligible
overhead and no behavior change for existing deployments or the default test
suite.

## Architecture

Each service owns a small telemetry bootstrap module; the two services do not
import each other's app code, but the worker depends on the API package (through
the local path source in `services/worker/pyproject.toml`), so the shared,
service-agnostic pieces live in `axis_api.telemetry` and are reused by
`axis_worker.telemetry`.

- `axis_api.telemetry.configure_api_telemetry(settings)` returns a
  `TelemetryRuntime` (tracer, meter, provider handles, metric instruments). When
  `otel_enabled` is false it returns a no-op runtime; otherwise it builds an
  **app-scoped** `TracerProvider` and `MeterProvider` (never the OTel global
  providers, so multiple app instances and tests stay isolated) with a `Resource`
  describing `service.name`, `service.version` and `deployment.environment`, and
  an OTLP/HTTP exporter.
- `axis_worker.telemetry.configure_worker_telemetry(settings)` mirrors it with a
  `limes-axis-worker` resource and a scheduled-job counter, reusing the shared
  provider builder and propagation helpers.
- The runtime is stored on `app.state.telemetry` (API) and passed into
  `MaintenanceActivities` (worker). FastAPI/ASGI auto-instrumentation is attached
  with `FastAPIInstrumentor.instrument_app(app, tracer_provider=..., meter_provider=...)`
  using the app-scoped providers.

```text
HTTP request
  -> FastAPI/ASGI auto-instrumentation span (method, route, status)
    -> manual operation span (axis.action_run.create, axis.approval.decide, ...)
      -> W3C traceparent injected into the Temporal signal payload
        --------------------------------------------------------------- API | worker
        -> worker activity span continues the trace (scheduled jobs are roots)
```

## What is traced

**API — automatic (per request):** the FastAPI instrumentation produces one
server span per request with the standard HTTP attributes (`http.method`,
`http.route`, `http.status_code`, ...). The client IP that the ASGI middleware
would normally attach (`net.peer.ip` / `client.address`) is **stripped** before
export by a privacy-filtering exporter (see Privacy below).

**API — manual operation spans** wrap the meaningful governed operations:

| Span | Endpoint | Key attributes |
| --- | --- | --- |
| `axis.action_run.create` | `POST /demo/manufacturing/actions/{id}/runs` | `axis.action_id`, `axis.tenant_id`, `axis.actor_id`, `axis.outcome` |
| `axis.approval.decide` | `POST /demo/manufacturing/approvals/{id}/decision` | `axis.approval_id`, `axis.decision`, `axis.tenant_id`, `axis.actor_id` |
| `axis.connector_sync.execute` | `POST /demo/manufacturing/connectors/runs/{id}/execute-sync` | `axis.connector_id`, `axis.tenant_id`, `axis.outcome` |
| `axis.audit.export` | `GET /demo/manufacturing/audit/export` | `axis.tenant_id`, `axis.export_format`, `axis.actor_id` |

Tenant and actor ids are additionally attached to the active request span by the
shared principal resolver (`oidc_principal`) once identity is verified, so every
authenticated request span carries `axis.tenant_id` and `axis.actor_id`.

**Worker — activity/job spans:** each scheduled maintenance activity runs inside
a span (`axis.scheduled_job.audit_retention_deletion`,
`axis.scheduled_job.orphaned_session_sweep`,
`axis.scheduled_job.tenant_state_reconciliation`) carrying `axis.job` and
`axis.outcome`. Scheduled jobs have no inbound trace context, so these are root
spans. `WorkerTelemetryRuntime.activity_span(name, carrier=...)` extracts a
propagated W3C context when one is supplied, so a signalled workflow/activity can
continue its originating trace.

## Metrics

Request count and latency come for free from the FastAPI instrumentation
(`http.server.*`). A small set of real, honest counters is emitted on top (no
fabricated gauges):

- API: `axis.action_runs{outcome}`, `axis.approval_decisions{decision}`,
  `axis.connector_sync_rows{connector_id,status}`, `axis.audit_exports{format}`.
- Worker: `axis.scheduled_job_runs{job,status}`.

The API also emits `axis.api.deprecated_requests` for the legacy manufacturing
namespace, labelled only by registered route template (or `unmatched`), bounded
HTTP method and response status. See [API compatibility](api-compatibility.md)
for the migration date, collection requirements and zero-usage removal gate.

Metrics are gated by `AXIS_OTEL_METRICS_ENABLED` (default `true`, but only ever
active when `AXIS_OTEL_ENABLED` is also true).

## Trace-context propagation (API -> worker)

The API calls the worker by signalling a Temporal workflow through
`TemporalWorkflowSignalRuntime`. For the dict-payload signals (action run,
connector manual import, evidence snapshot export) the active W3C trace context
is **injected** into the signal payload as a `traceparent` (and `tracestate`) key
via `inject_trace_context`. When telemetry is disabled the current span is
non-recording and the propagator injects nothing, so the payload is unchanged.

The **consumption** side is provided but not yet wired into the workflow signal
handlers: `WorkerTelemetryRuntime.activity_span(name, carrier=...)` calls
`extract_trace_context` to continue an originating trace from a carrier, and the
scheduled-job activities are fully span-instrumented (as root spans, since a
schedule has no inbound context). Extracting the propagated `traceparent` inside
the `ApprovalWorkflow` signal handler is deferred: workflow code runs in
Temporal's deterministic sandbox where starting OTel spans is a side effect, so
the idiomatic path is a Temporal tracing interceptor — which is incompatible with
the app-scoped (non-global) providers used here. In short, today the API
**injects** context into the outbound signal payload and the worker's activity
spans can link to a carrier, but end-to-end signal-side extraction inside the
workflow is a documented follow-up — no claim is made that a signalled workflow
currently continues the API trace automatically.

## Privacy

Span attributes and metric labels follow the **same rules as audit payloads**:
only stable, non-sensitive identifiers (tenant id, actor id, resource ids,
outcomes). Tokens, secrets, credentials, cookies, client IPs and raw query
strings are never recorded. This is enforced two ways:

1. Instrumented code only ever sets the curated `axis.*` attribute keys through
   `set_span_attributes`, which drops any key that trips the sensitive-key guard
   (word-boundary substrings such as `token`/`secret`/`cookie`, plus the exact
   client-IP keys — the bare substring `ip` is deliberately not used, so benign
   keys like `axis.pipeline_id` are kept).
2. A `_PrivacyFilteringSpanExporter` wraps every span exporter and privacy-scrubs
   every span before export, regardless of exporter: it drops sensitive
   attributes (including the framework-added client IP) and strips the query
   string from URL-bearing attributes (`http.url`, `http.target`, `url.full`,
   `url.query`) — keeping scheme/host/path — so cursors, filters, or a token
   planted in a query parameter are never exported.

## Configuration

| Setting (env) | Default | Purpose |
| --- | --- | --- |
| `AXIS_OTEL_ENABLED` | `false` | Master flag; install providers and instrument the app. |
| `AXIS_OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP/HTTP base endpoint; `/v1/traces` and `/v1/metrics` are appended. |
| `AXIS_OTEL_METRICS_ENABLED` | `true` | Emit metrics when telemetry is enabled. |
| `AXIS_OTEL_SERVICE_NAME` | unset | Override the resource `service.name` (defaults to `limes-axis-api` / `limes-axis-worker`). |

`deployment.environment` is taken from `AXIS_ENV`.

## Exporter setup — pointing at a collector

The services export OTLP over HTTP. Point them at any OTLP-compatible collector
or backend:

- **Docker Compose:** an optional `otel-collector` service is included (commented)
  in `infra/docker/docker-compose.yml`. Uncomment it, set `AXIS_OTEL_ENABLED=true`
  on the worker (and API), and the exporter posts to `http://otel-collector:4318`.
- **Helm:** set `observability.otel.enabled=true` and
  `observability.otel.exporterOtlpEndpoint` in values; the chart wires
  `AXIS_OTEL_*` into the shared ConfigMap for both the API and worker Deployments.
- **Jaeger / Tempo / Grafana Alloy:** run a collector that accepts OTLP/HTTP on
  `:4318` and forwards to your backend, then set the endpoint to that collector.

## Readiness

`GET /deployment/readiness` reports the observability posture:
`capabilities.otel_enabled`, `capabilities.otel_metrics_enabled`,
`capabilities.otel_exporter_endpoint_configured`, and a non-blocking
`observability_instrumentation` check (observability is recommended, not a
production blocker, so it never gates production readiness).

## Testing

All tests use in-memory exporters (`InMemorySpanExporter`,
`InMemoryMetricReader`); no live OTLP collector is required. `create_app` accepts
an optional `telemetry=` runtime so tests can inject an in-memory-backed runtime.
Coverage lives in `services/api/tests/test_telemetry.py` (bootstrap gating,
request spans, tenant/actor attributes with no sensitive fields, metric data
points, trace-context round-trip, readiness posture) and
`services/worker/tests/test_telemetry.py` (bootstrap gating, activity span +
metric, propagated-context linking).
