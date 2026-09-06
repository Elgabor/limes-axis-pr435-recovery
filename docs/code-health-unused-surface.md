# Unused surface and compatibility decisions

[Issue #357](https://github.com/Limes-Labs/limes-axis/issues/357) was checked
against base `a75422330f3a88b2b49c829d6c2f1ac3d887a41a` on 2026-09-06. Its static
candidate list predates [PR #400](https://github.com/Limes-Labs/limes-axis/pull/400),
merged as `681a67596b2f22d837d7f720d070a12b7f688ef9`. The decisions below account
for that delivered work instead of deleting additional code to satisfy an old list.

## Consumer evidence and decisions

| Candidate | Verified evidence | Decision |
| --- | --- | --- |
| `axis_api.auth` | PR #400 removed the 28-line development claims parser. No remaining imports, module-name strings or symbol callers in API, worker, SDK, schemas, CI or deployment files. Identity is composed through `identity.py`, `identity_session.py`, `oidc_code_flow.py` and the principal resolver in `main.py`. | Keep removed; do not wire an unverified claims parser into authentication. |
| `axis_api.tenant` | PR #400 removed the unused 8-line `TenantContext`. No remaining imports or symbol callers in those same surfaces. Current tenant binding and admission are owned by the principal resolver and `tenant_admission.py`. | Keep removed; preserve the current tenant owners. |
| `WorkflowRuntimePort` | PR #400 removed this unused worker protocol and its test-only placeholder. Concrete workflow request/state DTOs remain consumed by `temporal_adapter.py` and its unit/live-runtime tests. | Keep the unused protocol removed; retain the consumed DTOs. |
| Other runtime ports | `WorkflowSignalRuntime`, ontology query/mutation ports, source ingestion and connector execution ports have concrete implementations and composition/dispatcher consumers. They enforce configuration, tenant, lease, permission or execution boundaries. | Retain; a protocol without direct instantiation is not dead code. |
| Worker compatibility entry point | `axis_worker.__main__` imports and invokes `runtime.main`; it contains no independent worker setup. Make and the worker Docker image invoke `python -m axis_worker`; Helm/Compose use that image entry point. | Retain the thin entry point. The added executable test proves it delegates exactly once without opening a Temporal connection. |
| Temporal client adapter | `TemporalWorkflowRuntime` starts/signals/cancels workflows; `runtime.py` registers and polls workers. They have different responsibilities. Adapter request/state contracts, legacy boolean approval signals and governed approval signals have unit/live-integration consumers. | Retain the client and rolling-upgrade contract; do not merge it with the polling runtime or silently remove signal compatibility. |
| TypeScript unused symbols | PR #400 enabled `noUnusedLocals` and `noUnusedParameters`. The current `**/*.ts` / `**/*.tsx` includes cover production, unit tests and E2E files; CI invokes that same `tsc --noEmit` command. | Keep strict checks enabled for both production and tests. |
| `/demo/manufacturing/` | 103 deprecated operations were still served without a runtime removal notice or dedicated usage counter. Bootstrap still had live console and CI callers and no replacement URL. | Preserve aliases, add metadata-only telemetry and a dated migration policy; move bootstrap clients to `/demo/bootstrap`. |

The package manifests, Docker build contexts, Make targets, Helm/Compose
entry points and repository dynamic-import/entry-point declarations were checked,
in addition to textual callers. API packaging exports only the existing
`axis-bootstrap-first-tenant` command; no plugin entry point names the removed
modules. Worker packaging installs `axis_worker`; its package entry point is a
real deployment consumer. The separately supported Python SDK does not import
the removed API modules or worker protocol.

Repository evidence cannot inventory private downstream imports or unregistered
plugins. This PR makes **no further Python module, protocol, REST alias or
Temporal signal removal**. Unknown external consumers are a reason to keep the
remaining compatibility paths and require deployment evidence at removal time.

## Verification and measurements

The API tests compare all 103 legacy method/path contracts with their canonical
replacements, ignoring only generated schema titles that embed the URL. Runtime
tests cover response/error headers, bounded metric labels, denied requests,
unknown requests, telemetry failures, and durable bootstrap replay across URLs.
The [API compatibility policy](api-compatibility.md) defines the removal gate.

The TypeScript negative probe placed an unused local, unused function and unused
parameter in both a production `.ts` file and a `.test.ts` file. The normal
`pnpm --filter @limes-axis/web typecheck` command rejected all six with TS6133
(exit 2). Only those two temporary probes were then removed and the normal
typecheck passed. No compiler suppression or excluded test directory was added.

Local HTTP comparison on 2026-09-06 used the base `main.py` composition loaded
from the base Git object and the changed composition, sharing the same locked
dependencies. Each phase used three fresh apps, SQLite in memory, metrics off,
three warmups and 25 timed TestClient requests per path per app (75 samples).
No suite or build ran concurrently. These are client-inclusive medians, not
database or production latency measurements:

| Probe | Base, ms | Changed, ms |
| --- | ---: | ---: |
| First `/health` request, median of three fresh apps | 3.605 | 2.566 |
| Warm `/health` | 1.273 | 1.272 |
| Warm `/operations/overview`, expected 422 without tenant | 1.555 | 1.597 |
| Warm legacy overview, expected 422 without tenant | 1.706 | 1.727 |

The small warm differences are within local timing noise; no speedup is claimed.
The middleware uses the resolved route template and does not generate OpenAPI,
scan route tables, open a database session or install a telemetry exporter.
Contract count changes from 250 to 251 only for the canonical bootstrap; all
pre-existing OpenAPI operations and schemas compare identically with the base.

Verification commands:

```sh
make test-api PYTEST_ARGS='tests/test_api_compatibility.py tests/test_demo_bootstrap.py -q'
make test-worker PYTEST_ARGS='tests/test_runtime.py tests/test_temporal_adapter.py tests/test_approval_workflow.py -q'
pnpm --filter @limes-axis/web typecheck
make openapi-check route-inventory-check docs-check
make verify NEXT_PUBLIC_AXIS_API_BASE_URL=http://127.0.0.1:65534
```

Exact measurements, final full-suite counts and CI results are recorded in the
implementation PR. Before/after route and compiler evidence is local evidence,
not production usage or a performance SLO. Remaining external-service tests,
real Temporal rolling upgrades, downstream-client inventory and alias-removal
observation windows must be reported separately as NOT RUN where unavailable.
