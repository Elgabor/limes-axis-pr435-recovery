# API domain route extraction

The [generated inventory](api-route-inventory.md) maps all 250 OpenAPI HTTP
operations, including 103 deprecated aliases, to their handler and owning module.
Domain labels describe the extraction plan; ownership links describe current code.
`make route-inventory` regenerates it and the API test suite rejects stale output.
The exporter matches FastAPI operation IDs to source handler declarations and
fails on missing or ambiguous owners rather than inventing a module assignment.
It covers the public OpenAPI contract, not framework documentation/static routes.

## First slice: models

[Issue #355](https://github.com/Limes-Labs/limes-axis/issues/355) requests one
reviewable domain slice. All nine model handlers now live in
[`axis_api.routes.models`](../services/api/src/axis_api/routes/models.py): endpoint
create/list/status, invocation preview/create/list/get, routing telemetry and the
manufacturing routing reference. They expose ten operations: eight under
`/platform/models`, one under `/operations/model-routing` and its deprecated
`/demo/manufacturing/model-routing` alias.

`build_model_routers` returns separate platform and operations routers.
[`create_app`](../services/api/src/axis_api/main.py) constructs and mounts these at
the previous registration positions; the existing operations router owns both
its canonical prefix and deprecated alias. Handler names, paths, schemas, status
codes, query parameters, error details and deprecation metadata are preserved.
No route path or client contract migration is required.

Measured against `1742896c460be4b7824dd0d019dba15082ff35f5`:

| Measure | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| `main.py` physical lines | 10,088 | 9,628 | 460 |
| `create_app` AST line span | 7,774 | 7,355 | 419 |
| Nested function definitions in `create_app` | 157 | 148 | 9 |
| Model handlers in `create_app` | 9 | 0 | 9 |

## Shared boundaries remain in composition

The frozen `ModelRouteDependencies` bundle passes the existing function objects;
the router does not import `main`, instantiate a repository or define substitutes
for security dependencies. `Settings` and `TelemetryRuntime` belong to the
application instance and are passed at construction, with no mutable global
router or cross-application settings state.

| Boundary | Existing owner supplied by composition | Preserved behavior |
| --- | --- | --- |
| Database session | `persistence_repository` | Request lifecycle and transaction ownership |
| Identity | `oidc_principal` | Canonical FastAPI dependency and override identity |
| Model runtime | `model_invocation_runtime` | Per-application runtime selection and test overrides |
| Body tenancy and actor | `_bind_body_tenant_actor` | Principal binding before domain execution |
| Read authorization | `_authorize_model_endpoint_read`, `_authorize_tenant_read` | Existing tenant/scope checks |
| Policy error mapping | `_platform_policy_denied_detail` | Existing public-safe denial details |

Domain services retain permissions, provider selection and invocation state.
The route keeps the same pre-provider commit, provider await and audit/usage
recording flow. External model egress still requires the existing setting and
policy evidence; extraction adds no access path. The runtime dependency in
`main` also serves agent execution and remains shared.

## Verification and next slices

The before/after OpenAPI exports are byte-identical. `make openapi-check` compares
against the committed API contract. Focused endpoint, invocation, telemetry and
tenant tests exercise the extracted handlers. A two-application regression test
interleaves denied/allowed/denied invocations with separate egress settings,
overrides all three original FastAPI dependencies, and checks provider-call count
and persisted denial audit events. Exact local and CI outcomes belong in the PR.

Most other handlers still live in `main`; `create_app` is not yet composition
only. The inventory gives the next domain owners: identity, tenants, policies,
data assets, connectors, actions, agents, approvals, audit, ontology, workflows,
simulation, remaining operations and system routes. Follow-up work under
[the code-health parent](https://github.com/Limes-Labs/limes-axis/issues/354)
should extract one domain per review, retaining the same canonical shared
functions until a separately justified boundary change is reviewed.

For each slice: retain handler names and registration order, regenerate the
inventory, prove OpenAPI parity, preserve dependency overrides, and rerun the
authorization/tenant/audit tests for that domain. Do not fold service rewrites,
new dependency frameworks or endpoint redesigns into route moves. Hosted
providers and deployment behavior require separate evidence; local component
checks do not establish those outcomes.
