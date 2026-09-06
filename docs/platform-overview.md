# Platform Overview

The first Platform slice turns the governance console overview into an
API-backed operational demo surface.

## Demo Scope

The manufacturing overview reference is API-owned, public-safe and persisted as
a tenant-scoped bootstrap record. It uses roles, system IDs and demo tenant IDs
rather than personal names or customer data. The browser does not carry local
overview records, and the API no longer defines the overview as a runtime seed
function.

It models the first Plant Operations Cockpit scenario:

- workflow load;
- pending approvals;
- governed agents;
- audit evidence;
- supplier, quality and maintenance risk signals.

## API Contract

The FastAPI service exposes:

```text
GET /demo/manufacturing/overview
```

The endpoint reads the active `demo_reference_records` row for
`tenant_demo_manufacturing`, `surface=overview` and
`reference_id=manufacturing-overview`, then returns a typed overview for the
demo tenant:

- summary metrics;
- risk signals;
- active workflow summaries;
- approval queue summaries;
- governed agent summaries;
- recent audit evidence.

The schema is included in `docs/openapi.json` and checked by CI through
`make openapi-check`. The endpoint returns 404 when the persisted reference
record is missing and 422 when the persisted payload fails the overview
contract.

## Persistence Boundary

Alembic migration `0022_demo_reference_records` creates the
`demo_reference_records` table and inserts the public-safe manufacturing
overview bootstrap record. The table is tenant-scoped, keyed by surface and
reference id, and designed for future extraction of demo/reference content out
of runtime code without moving browser fallback data back into the console.

## Console Behavior

The Next.js overview page loads the demo endpoint from
`NEXT_PUBLIC_AXIS_API_BASE_URL`. If the API is unavailable, the console shows an
API-required state and does not render local overview records.

The overview also uses the public Axis console shell: dark Axis Black and
Graphite surfaces, Signal Blue state emphasis, Teal Pulse success emphasis and
compact operational cards. The visual layer is tested separately from the data
contract so that brand changes do not reintroduce browser-local records.
Laptop-width dashboard checks keep the operations KPI cards above the readable
minimum and move the side rail below the primary workflow surface before the
main console becomes compressed. This keeps SME and enterprise feedback
sessions usable on ordinary meeting-room displays without changing the
API-required data contract.

The API also exposes:

```text
GET /demo/manufacturing/demo-readiness
```

The readiness report is computed from the persisted manufacturing operations
snapshot. It exposes SME feedback and enterprise evaluation tracks, evidence
checks, explicit production-readiness limitations and next actions. It does not
generate artifacts, query source systems, run connectors or rely on
browser-local mock data. The redesigned overview no longer renders this report
as a first-screen panel; the endpoint remains an API surface for readiness
checks.

## Redesigned Control Room

The console redesign rebuilds the overview page as an action-first control
room: a slim hero with live counts, a needs-attention strip with inline
approval decisions, five posture cards, one audit evidence feed, the governed
artifact panel and a system-health side rail. Each section reads its own
endpoint, so a failing endpoint degrades only the section that reads from it.

On a tenant whose overview answers 404 (never bootstrapped) while the API is
otherwise healthy, the page renders a guided onboarding checklist instead of an
error: five steps (connect a system, import ontology entities, define a
policy, register an agent, run a governed workflow) whose done-state derives
from the live registry counts. Its "Explore with demo data" CTA calls:

```text
POST /demo/bootstrap
```

The endpoint copies the canonical demo scenario records into the target tenant
behind the `demo:scenario:bootstrap` scope, answers 201 on first bootstrap and
200 with `idempotent_replay: true` on replays, never overwrites existing tenant
surface records, and writes a `demo.scenario.bootstrapped` audit event. When a
tenant's overview identifies the demo scenario, the console topbar shows a
"Demo" badge.

The console shell notification panel also uses:

```text
GET /demo/manufacturing/notifications
POST /demo/manufacturing/notifications/{notification_id}/acknowledgement
```

The endpoint derives a notification read model from the persisted operations
snapshot rather than from browser-local state. It surfaces operation-domain
attention, pending approvals, blocked workflow signals and recent audit
evidence with stable notification ids, routes and evidence references. When an
actor is known through OIDC or the demo actor query, Axis overlays persisted
read/ack state from `platform_notification_acknowledgements`.

The acknowledgement endpoint enforces `notifications:acknowledge`, writes
`platform.notification.acknowledged` or `platform.notification.read` audit
evidence, and persists the actor-scoped state without storing bearer token
material or relying on browser-local fallback data.

The account popover uses:

```text
GET /identity/session
```

The endpoint returns a public-safe identity session read model. With a bearer
token it reports the API-validated actor, tenant, scopes, expiry and OIDC
posture. Without a token it reports public-evaluation state when OIDC auth is
optional, or `401` when the environment requires authentication. The response
does not include bearer token material, secrets, passwords or raw JWKS content.
It is an identity posture surface, not a full production login flow.

The Operations page also exposes an API-backed artifact runtime:

```text
POST /demo/manufacturing/operations/daily-brief
POST /demo/manufacturing/operations/risk-scenarios/quality
POST /demo/manufacturing/operations/risk-scenarios/maintenance
POST /demo/manufacturing/operations/risk-scenarios/supplier-delay
```

The browser builds these requests only from the API-validated identity session.
It does not manufacture a demo actor or local scopes. If `/identity/session`
does not return an authenticated actor, or if the actor lacks the required
scopes for the selected artifact, the action remains disabled. On the API side,
an attached OIDC principal is bound to `requested_by`, `actor_scopes` and the
tenant before the existing permission checks run, rejecting actor or tenant
impersonation. Successful submissions persist the artifact, write audit
evidence and trigger a fresh read of the operations snapshot.

This is an API reference path, not a production data loading path. Future
Platform work will replace remaining bootstrap records with tenant-scoped,
authenticated API surfaces backed by Postgres, TypeDB and workflow state.

## Verification

Covered by:

- API unit tests for the manufacturing overview reference endpoint;
- repository tests for tenant-scoped demo reference records;
- migration payload validation against the `ManufacturingOverview` contract;
- generated OpenAPI drift check;
- web unit tests for the API response contract;
- web unit tests for the Axis brand tokens;
- Playwright smoke tests for API-required overview behavior, Axis shell tokens
  and no horizontal overflow on desktop and mobile.
- API and Playwright coverage for the API-backed notification panel, persisted
  acknowledgement state and no-fallback behavior.
- API and Playwright coverage for the API-validated account/session popover.
- Web unit coverage for the Operations artifact request contract, OIDC-scope
  gating and no browser-local actor/scope construction.
