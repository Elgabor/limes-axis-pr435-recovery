# Connector workspace read model

The console loads a compact, request-scoped summary, then the selected
connector. The legacy registries remain supported. Both new operations also use the
existing router's equivalent deprecated aliases and migration notices. This slice reduces browser
fan-out and response bytes; it does not introduce a shared cache or a new
permission model.

## Contract and loading

`GET /operations/connectors/workspace?tenant_id=…&offset=0&limit=25` returns
metadata, list labels, current lifecycle status, sample row counts, latest
successful-sync observations, four counters, and pagination metadata. The
normal page contains 25 connectors; the API accepts 1–50. The response has a
64 KiB UTF-8 budget and bounded text fields. Oversized pages fail with 422;
identifiers and values are never silently truncated. Offset is bounded to
0–1,000,000. The list retains the legacy reference/manifest override ordering.

`GET /operations/connectors/workspace/detail?tenant_id=…&connector_id=…`
returns one full registry item, including schema and preview data. Selection
works outside the visible page, so an old connector or snapshot link does not
fall back to the first row. A missing connector returns 404. Persisted
connectors additionally load their authoritative manifest revision/history;
its decoder is stable across renders to avoid duplicate requests.

The initial CSV reference view requests summary and selected detail. A
persisted selection also requests manifest detail. Runs and credential leases
load on the Runs tab. Handles, leases, egress policies and evidence findings
load on Governance & Evidence. These legacy reads include the selected
`connector_id`, with their existing default limits. Snapshot history retains
its separate, permission-checked endpoint and loads only for a snapshot link.
The existing full registry is loaded for template selection only while the
Add connector wizard is open. External database discovery, binding and
ingestion panels retain their own existing, selected-source reads.

A failed summary blocks the workspace. A failed counter is `null`, shown as
“—”; a transport or validation failure of a selected detail leaves the list
available. A missing requested connector retains the explicit missing-record
panel rather than selecting a different connector. Each counter runs in
a savepoint so a failed conversion or audit append cannot poison the remaining
reads. A partial audit from a failed counter is rolled back with that counter.
A `connector.workspace_read` event records the verified actor, page coordinates,
source limit and returned list count before counter savepoints. All read audits
remain in the caller's transaction, including with SQLite's legacy transaction
behavior; a caller rollback removes the page event and every counter audit.

The connector total covers the complete registry. Other counters preserve the
legacy result-window semantics: runs and egress policies count the first 100
records; pending proposals count unpromoted entries among the first 100
proposals; evidence issues aggregate the existing checks over the first 100
records of each contributing evidence surface. `counts.source_limit` exposes
that bound, which the metric descriptions also state. They are not all-time tenant totals. Selected-tab windows are
connector-scoped and can include records outside those tenant-wide windows.

## Authorization and audit parity

Both new routes use `OidcPrincipalDependency` and `_authorize_tenant_read`
before repository reads. Enforced authentication rejects a missing identity;
a verified principal cannot select another tenant. Auth-optional demo behavior
is preserved. The API derives audit attribution from the verified principal,
never a query-string actor. No response is cached across requests/principals.

| Returned field group | Existing authorized source | Boundary retained |
| --- | --- | --- |
| Tenant, plant, scenario, provenance, registry status | Connector registry | Verified tenant read |
| Connector identifier, display name, type, status, origin | Connector registry composition | Same tenant; persisted override/order semantics |
| Persisted lifecycle status and preview row count | Current registry item | Same tenant; no revision notes or sample rows in summary |
| Latest successful sync ID, time and row count | Registry's persisted run observations | Same tenant; derived from redacted run evidence |
| Total and pagination | The authorized registry sequence | Same tenant; only one page crosses HTTP |
| Runs and pending proposal counts | Existing run/proposal builders at limit 100 | Same tenant; no new read scope or records exposed |
| Egress policy count | Existing audited policy registry read | Same tenant; existing read audit, verified actor |
| Evidence issue count | Existing audited evidence report | Same tenant; existing checks/read audit, verified actor |
| Full selected connector | Existing registry composition | Same tenant and exact connector identity |
| Generation time and fixed source limit | Server-generated metadata | No additional data authority |

The summary omits credentials, secret/endpoint references, policy documents,
source rows, schema fields, revision history, snapshot/export contents and
write decisions. Snapshot permissions, credential gates, lifecycle transitions
and governed mutations continue to execute through their existing endpoints.
Tests compare every returned list field and counter to the legacy reads under
a principal with no extra scopes, test missing identity/foreign-tenant denials,
and check audit attribution and savepoint rollback.

## Freshness and invalidation

Summary and selected-detail responses send `Cache-Control: private, no-store`.
There is no TTL, cross-component data cache or tenant-only cache. The shared
`useAxisQuery` still cancels superseded requests and masks data when the path,
tenant or bearer actor changes. The workspace also remounts when the
API-verified cookie principal changes, clearing queries and action drafts.

Global refresh and successful governed mutations refetch the summary and only
the currently enabled detail reads. Same-principal refresh retains the previous
summary until its replacement arrives; failures retain the existing stale
source indicator. The displayed time is the last successful summary's server
`generated_at`, not the attempted refresh time. Switching connector/page drops
the old detail while loading; switching away from a tab disables its queries.
Reopening a tab or the wizard fetches again. An unresolved or failed identity
check disables every connector query.

## Measured evidence and reproduction

The [captured waterfall and byte counts](benchmarks/connector-workspace.json)
compare baseline `269a96f7613e345fe1392633fd3f8604d43b5c85` with this change.
The fixture contains 60 synthetic reference connectors, empty side registries,
and the CSV reference selected. Both captures use the real API on an isolated
SQLite database, a production Next.js build and Chromium 151 / Playwright
1.62.1 at 1440×1000. Connector HTTP response bodies only are counted; identity,
health, readiness and static resources are outside this measurement.

| Initial connector load | Before | After |
| --- | ---: | ---: |
| HTTP requests | 7 | 2 |
| Response body bytes | 161,020 | 9,587 |
| Main registry/summary bytes | 156,014 | 6,935 |
| JavaScript page errors | 0 | 0 |

The baseline launches seven registry reads together. The updated page receives
the summary, then requests the selected 2,652-byte detail. This is a 94.0%
reduction in response bytes for this fixture. The timestamps are observations
from one browser capture per revision, not latency assertions or production
capacity evidence. The reference selection has no persisted-manifest history
request. Readiness can remain degraded because unrelated services are absent.

Use unused local ports. From `services/api`, start the
[isolated fixture factory](../services/api/scripts/benchmark_connector_workspace.py):

```sh
PYTHONPATH=src:scripts uv run uvicorn benchmark_connector_workspace:create_benchmark_app \
  --factory --host 127.0.0.1 --port 8364
```

From the repository root, build and start the console in another terminal:

```sh
NEXT_PUBLIC_AXIS_API_BASE_URL=http://127.0.0.1:8364 pnpm --filter @limes-axis/web build
pnpm --filter @limes-axis/web exec next start --hostname 127.0.0.1 --port 3364
```

From `apps/web`, use the locked browser version to capture responses and a
viewport screenshot. The script waits for connector reads, not unrelated
readiness probes:

```sh
pnpm exec playwright install chromium
node scripts/measure-connector-workspace.mjs http://127.0.0.1:3364 /tmp/connector-workspace.json
```

For a baseline comparison, build/run the baseline revision in a separate
checkout with its own installed environments and point this same capture
script at it. The fixture's seed comes from the unchanged connector reference
migration; it appends 58 copies with distinct synthetic CSV identifiers. The
factory creates a fresh temporary database for every process and never uses a
shared database.

The summary still composes the complete registry internally before projecting
its page, preserving existing reference and persisted-override behavior. This
change bounds the HTTP summary, not server memory or SQL work for arbitrarily
large tenants. A storage-level paged projection requires separate measurement.
SQLite observations do not establish PostgreSQL capacity or hosted latency.
