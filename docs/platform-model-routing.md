# Platform Model Routing And Cost Observability

The model routing surface has two parts: the read-only reference telemetry
view described below, and a flag-gated execution slice.

The execution slice registers tenant-scoped model endpoints through
`GET/POST /platform/models/endpoints` (openai-compatible providers;
`self_hosted`, `approved_private_endpoint` and `external` hosting boundaries;
scope `platform:model:endpoint:admin`) and runs governed invocations through
`POST /platform/models/invocations` (scope `models:invoke`), with routing
telemetry at `GET /platform/models/routing/telemetry`. Execution requires
`AXIS_MODEL_ROUTING_EXECUTION_ENABLED=true` (default `false`; disabled
invocations record an honest deferred status) and the selected endpoint's
exact base URL must appear in the operator-owned
`AXIS_MODEL_INVOCATION_ALLOWED_BASE_URLS` list. The allowlist is checked again
immediately before the provider request, so a tenant cannot register a model
endpoint that turns the API into a generic server-side request proxy.
Invocation records are
metadata-only — token counts, latency, status and audit evidence; prompt text
is excerpted only up to `AXIS_MODEL_INVOCATION_PROMPT_EXCERPT_CHARS` (default
`0`) — and feed per-tenant usage metering. Non-self-hosted egress stays
separately blocked while `AXIS_EXTERNAL_MODEL_EGRESS_ENABLED=false`.

The reference telemetry view is read-only. The endpoint reads a persisted
tenant-scoped bootstrap record instead of a route-owned runtime seed. It does
not call a live model provider, does not send prompts outside the demo tenant
boundary and does not enforce production budgets yet.

The API module no longer defines a model routing runtime seed factory. Contract
tests validate the Alembic bootstrap payload directly against the public API
schema.

## API

```text
GET /demo/manufacturing/model-routing
```

The endpoint reads the active `demo_reference_records` row for
`surface=model-routing` and `reference_id=manufacturing-model-routing`, then
returns:

- tenant, plant, scenario and timestamp metadata;
- top-level metrics for route decisions, blocked egress, estimated spend and
  agent coverage;
- provider options with hosting boundary, egress mode, cost basis and allowed
  policies;
- route telemetry for each demo agent;
- model policy, prompt classification, token estimates and cost estimates;
- decision reason, required permissions, evidence references and audit event ID;
- budget and observability notes.

Missing persisted reference records return 404. Invalid or tenant-mismatched
payloads return 422.

## Invocation Durability

`POST /platform/models/invocations` runs in three phases: it commits the
requested invocation row, then calls the provider, then records the outcome in
a new transaction. Committing first makes the idempotency key durable before
any external call and keeps a provider timeout from occupying a database
connection. The phase contract and the inventory of the other external-await
paths are in
[external-await transaction boundaries](./performance-external-await-boundaries.md)
and [ADR 0003](./adr/0003-external-await-transaction-boundary.md).

A process can stop after the claim is committed but before the provider is
called. This guarantees at-most-once dispatch, not exactly-once execution or
automatic recovery.

Two consequences are part of the endpoint contract:

- At most one provider call is issued per tenant and idempotency key. A
  duplicate delivery that arrives while the first call is in flight replays the
  stored record instead of calling the provider again.
- A replayed record whose outcome has not been written yet is returned with
  status `requested` and a note stating that no result is available and that no
  second call was issued. `requested` is not a failure status, and the record
  is never re-invoked automatically: the outcome of the first provider call is
  unknown, and Axis does not fabricate one. Clearing a record left `requested`
  by an interrupted process is operator work.

## Console

The `/model-routing` page shows:

- route telemetry filters for domain, provider and egress decision;
- selected route detail with provider, model, token count, latency and
  estimated cost;
- policy posture for external egress requested/allowed;
- required permissions, evidence refs and observability event names;
- provider boundary metadata;
- budget and OpenTelemetry-first observability notes.

## Current Scope

Delivered:

- read-only reference route telemetry;
- persisted bootstrap record for the reference route telemetry;
- runtime seed factory removed from the API module;
- blocked external route visibility;
- local and approved-provider route examples;
- token and cost estimates;
- API response contracts;
- Playwright smoke coverage for API-required behavior;
- flag-gated model endpoint registration and governed invocations
  (`AXIS_MODEL_ROUTING_EXECUTION_ENABLED`, off by default) with the
  openai-compatible provider adapter;
- metadata-only persisted invocation records with audit ledger evidence and
  per-tenant usage metering;
- model-routed agent proposals through the governed agent run slice;
- committed-before-provider-call invocation durability with single-call
  duplicate delivery.

Still Platform work:

- additional provider adapters beyond openai-compatible endpoints;
- provider-specific billing ingestion;
- tenant-scoped budget enforcement;
- policy-managed exception workflow for external model egress;
- recovery or expiry of invocation records left `requested` by an interrupted
  process.
