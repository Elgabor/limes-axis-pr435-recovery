# Legacy API migration and removal policy

The 105 deprecated HTTP operations under `/demo/manufacturing/` remain available
with their existing handlers, authorization, tenant binding, validation, response
bodies, status codes, audit and idempotency behavior. Deprecation is a notice;
this release does not remove or redirect an operation.

## Migration

| Legacy path | Canonical replacement |
| --- | --- |
| `POST /demo/manufacturing/bootstrap` | `POST /demo/bootstrap` |
| Every other registered `/demo/manufacturing/...` operation | Replace only `/demo/manufacturing` with `/operations`; retain the rest of the path, method, parameters and body |

For example, `/demo/manufacturing/overview?tenant_id=...` becomes
`/operations/overview?tenant_id=...`. Some suffixes already start with
`/operations/`; preserve that suffix rather than guessing a shorter path. The
[generated inventory](api-route-inventory.md) lists the exact operations.

Bootstrap remains a demo-only operation with `demo:scenario:bootstrap`
authorization. Both bootstrap URLs use the same handler and durable replay
record: starting through one URL and retrying through the other does not create
a second bootstrap or audit event. Console onboarding and CI now use the
canonical URL. Historical migrations and compatibility tests retain legacy names.

## Runtime notice

Responses in the `/demo/manufacturing/` namespace carry:

- `Deprecation`: **2026-09-06 00:00 UTC**, encoded as a structured date under
  [RFC 9745](https://www.rfc-editor.org/rfc/rfc9745.html).
- `Sunset`: **2027-01-01 00:00 UTC**, encoded as an HTTP date under
  [RFC 8594](https://www.rfc-editor.org/rfc/rfc8594.html).
- `Link` with `rel="deprecation"` pointing to this guide; existing links remain.

The notice covers the namespace, including unknown paths, unsupported methods,
validation/authorization/rate-limit failures and unhandled 500 responses.
Canonical endpoints do not receive it. CORS exposes these headers to allowed
browser origins, alongside the existing request ID. No clock check disables a
route when the published date arrives.

## Usage evidence

The existing optional OTel runtime emits `axis.api.deprecated_requests`, a
counter with only these attributes:

| Attribute | Values |
| --- | --- |
| `http.route` | Registered legacy path template, or `unmatched` when no compatible HTTP route was resolved before the response |
| `http.request.method` | Standard HTTP method, or `_OTHER` for an unrecognized method |
| `http.response.status_code` | Actual response status; 500 for an exception before response headers |

The counter records one response start, including a stream that subsequently
fails. A pre-response exception records one 500. Requests blocked by outer
middleware, unknown paths and unsupported methods use the bounded `unmatched`
bucket. They are not attributed to a guessed handler. Route parameters,
queries, tenant/actor IDs, cookies, credentials and payloads are never labels.
Requests outside this namespace and WebSocket/lifespan events do not increment
the counter. Counter failure does not change an operation's result.

Enable both `AXIS_OTEL_ENABLED=true` and `AXIS_OTEL_METRICS_ENABLED=true` with the
deployment's existing approved collector. Defaults and exporter destinations
are unchanged. See [observability](platform-observability.md) for configuration.
Metrics disabled, collector downtime, a missing series or an unobserved replica
mean **unknown usage**, not zero. This release does not collect deployment
evidence or enable an exporter automatically.

## Removal gate and ownership

**The planned removal date is 2027-01-01, in a separately reviewed release.**
The API maintainer owns the migration and release decision; each deployment
operator owns its client inventory and observation coverage. Before removal:

1. Publish the replacement and notice for at least 90 calendar days in the
   affected supported release/deployment; the source merge alone is not notice
   to an operator still running an older version.
2. Record 30 consecutive days of zero legacy response deltas across all
   supported instances, with verified metric collection, restart handling and
   positive control traffic. Investigate the `unmatched` bucket too. Absence of
   metrics cannot satisfy this gate.
3. Confirm migration of console, SDK/integration clients, scripts, CI and each
   deployment operator's private consumers. Preserve tenant, permission, audit,
   bootstrap replay and workflow compatibility evidence on the release SHA.
4. Attach the deployment/version coverage, dated counter reports, collection
   health, client-owner confirmations and maintainer approval to the removal PR.

If the evidence is incomplete, keep the aliases and publish a revised future
Sunset date and migration notice before the current deadline. No automatic
removal, usage-based routing or new authorization path is implemented here.

NOT RUN: production traffic collection, private-client migration, the 30-day
observation window and actual alias removal. Passing local tests does not
satisfy those release gates.
