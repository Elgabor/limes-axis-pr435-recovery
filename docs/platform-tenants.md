# Platform Tenant Lifecycle and Quotas

The tenant lifecycle slice turns persisted tenant rows into governed platform
resources. It adds operator-driven provisioning, suspension
and reactivation, a per-tenant quota store, and real enforcement wiring for
suspended tenants and quota overrides. This is the entry gate to the
multi-tenant SaaS reference in the Enterprise track.

## Current Scope

- `POST /platform/tenants` provisions a tenant with an idempotency key,
  optional bootstrap admin actor and `platform.tenant.provisioned` audit
  evidence. Provisioning requires the `platform:tenant:operator` and
  `platform:tenant:provision` scopes.
- `GET /platform/tenants` lists tenants with an optional lifecycle status
  filter. Authenticated reads require the `platform:tenant:operator` and
  `platform:tenant:read` scopes.
- `POST /platform/tenants/{tenant_id}/suspend` and
  `POST /platform/tenants/{tenant_id}/reactivate` transition the lifecycle
  status with `platform.tenant.suspended` / `platform.tenant.reactivated`
  audit evidence. Both require the `platform:tenant:operator` and
  `platform:tenant:suspend` scopes.
- `GET /platform/tenants/{tenant_id}/quotas` and
  `PUT /platform/tenants/{tenant_id}/quotas` read and replace the typed
  per-tenant quota set. Updates require the `platform:tenant:operator` and
  `platform:tenant:quota` scopes; reads require the operator and read scopes.

## Operator Authorization Model

Tenant lifecycle is a platform-operator surface, not a tenant surface. No
cross-tenant admin convention existed before this slice, so it introduces one:
every operation requires the dedicated `platform:tenant:operator` scope in
addition to the action scope, and the usual principal-tenant match check is
deliberately absent — the operator authenticates under their own tenant and
acts on other tenants. Actor impersonation is still rejected: when an OIDC
principal is present, `requested_by` is bound to the verified actor and the
verified token scopes replace self-asserted ones.

The demo-mode caveat applies as everywhere: in unauthenticated local demo mode
(`AXIS_OIDC_AUTH_REQUIRED` disabled and no bearer token attached), actor and
scopes are self-asserted in the request body. The routes are only truly
OIDC-bound when authentication is present or required.

### First-tenant bootstrap

Production uses `AXIS_TENANT_ADMISSION_MODE=registered_only`, so an empty
tenant registry cannot admit an OIDC operator to call `POST /platform/tenants`.
This is a deliberate fail-closed boundary. Operators run
`axis-bootstrap-first-tenant` once, after migrations, from the packaged API
image with the deployment's database credential. The direct database authority
is not exposed as an HTTP route. It reuses the normal provisioning permission,
idempotency and audit path, appends a distinct
`platform.tenant.first_bootstrap.completed` event with
`authority=direct_database`, serializes competing attempts, permits an exact
replay without duplicate evidence, rejects same-key payload drift with
`provision_idempotency_conflict`, and refuses a different later request with
`tenant_registry_already_initialized`. Every tenant after the first is created
through the authenticated API. The full command and Kubernetes example lives
in [Deployment Baseline](deployment.md#bootstrap-the-first-registered-tenant).

## Lifecycle Model

A tenant carries a `status` (`active`, `suspended`, `pending_deletion` — the
enum is extensible), display metadata (`display_name`, `description`),
provisioning evidence (`created_by`, `provision_idempotency_key`,
`bootstrap_admin_actor_id`, audit references) and lifecycle timestamps
(`suspended_at`/`suspended_by`/`suspension_reason`, `reactivated_at`/
`reactivated_by`). Migration `0047_tenant_lifecycle` chains after
`0046_oidc_session_lifecycle`; existing seeded tenants migrate to
`status=active` through server defaults with zero behavior change.

Provisioning follows the action-run idempotency convention: replaying the same
idempotency key with the same payload returns the persisted tenant with
`idempotent_replay=true` and HTTP 200; reusing the key with a different payload
or reusing the tenant id under a new key returns a `CONFLICT`. An optional
bootstrap admin creates the actor row inside the same transaction. Scope grants
stay IdP-owned: the requested bootstrap scopes are recorded as audit evidence
only, never as a live grant.

Provision audit events created before immutable `provision_notes` evidence was
introduced can be replayed only while the tenant's latest-event pointer still
references that provisioning event. After a lifecycle transition, the original
notes are no longer provable, so those legacy same-key replays fail closed with
`provision_idempotency_conflict`; newly provisioned tenants remain replayable
because their original notes are retained in the audit ledger.

Suspension requires an active tenant and a reason; reactivation requires a
non-active tenant and clears the suspension fields (history stays in the audit
ledger). Lifecycle audit events are written in the target tenant's ledger with
the operator recorded as actor, so a tenant's own audit history shows who
suspended or reactivated it and why.

## Quota Model

`tenant_quotas` holds one row per tenant and typed quota key:

- `api_requests_per_window` — overrides the global API rate limit
  (`AXIS_API_RATE_LIMIT_REQUESTS`) for that tenant on the protected paths;
- `max_concurrent_sessions` — overrides the global concurrent browser-session
  cap (`AXIS_OIDC_SESSION_MAX_CONCURRENT`; `0` means unlimited);
- `max_connector_sync_rows_per_run` — caps the governed live-sync row limit
  per run below the connector profile bound.

Quota rows are update-in-place rather than revisioned: the `PUT` endpoint
replaces the typed quota set (a key set to a value is upserted, a key left
unset is cleared), and the append-only history lives in the
`platform.tenant.quota.updated` audit trail written for every individual key
change with previous and new values. This is the simplest existing pattern
that still audits every change; revisioned quota rows can be layered on later
if rollback bundles become necessary.

## Enforcement Points

Enforcement is wired at real choke points, not decoratively:

- **Inactive tenants fail closed.** The shared OIDC principal dependency —
  the single place where tenant scoping is resolved for every OIDC-bound
  route, covering bearer tokens and browser session cookies — rejects requests
  for suspended or pending-deletion tenants with a 403, a distinct
  `tenant_suspended` / `tenant_pending_deletion` reason and a
  `platform.tenant.suspended_request.denied` audit event in the tenant's
  ledger. Unauthenticated demo-mode requests carry no verified tenant context
  and are not covered, matching the demo-mode caveat used across the API.
  Lifecycle status is an allowlist boundary: only the exact persisted `active`
  value is admitted. Unknown, corrupt, mixed-case or future status values fail
  closed with `tenant_status_not_active` rather than becoming accidental access
  paths.
- **Suspended tenants cannot establish or rotate sessions.** Session
  establishment and rotation bypass the resource-access choke point, so they
  are guarded independently. `GET /identity/oidc/callback` (login) checks the
  tenant status after the ID token is validated and, for a non-active tenant,
  rejects the login with a 403 (`tenant_suspended` / `tenant_pending_deletion`)
  and a `platform.tenant.suspended_request.denied` audit event, writing no
  session row. `POST /identity/session/refresh` checks the tenant status in its
  precondition path and, for a non-active tenant, revokes the stored session
  with distinct audit evidence and returns a 403 — no new session cookie is
  issued and no refresh grant is attempted against the IdP. Both paths use a
  **fresh status read** (not the TTL cache): they are low-frequency security
  boundaries, so reading persisted status directly removes the staleness window
  entirely — a suspension takes effect on the very next login or refresh.
- **Per-tenant rate limits.** The API rate-limit middleware resolves the
  tenant from the HMAC-verified session cookie and applies the tenant's
  `api_requests_per_window` quota to a tenant-shared bucket, falling back to
  the global per-client limit when no tenant is resolvable or no quota exists.
  Bearer requests deliberately fall back to the global limit: the middleware
  never trusts an unverified tenant claim to select a higher limit, and full
  JWT verification belongs to the principal resolver, not the middleware.
  Rate-limited responses carry `scope: tenant_quota` or
  `scope: client_endpoint` so operators can tell which limit applied.
- **Concurrent sessions.** The OIDC callback reads the
  `max_concurrent_sessions` quota when present and revokes the oldest active
  sessions beyond the effective cap, exactly like the global setting.
- **Live-sync row caps.** Governed live-sync execution caps the plan's
  `max_records` (and per-batch read sizes) at
  `max_connector_sync_rows_per_run` when the quota is below the connector
  profile bound; the capped bound appears in the
  `connector.run.sync_execution_started` audit payload.

## Tenant State Cache

The resource-access suspension check and the per-tenant rate limit run on the
hot request path, so tenant status and quotas are read through a bounded
in-process cache (`AXIS_TENANT_STATE_CACHE_TTL_SECONDS`, default 5 seconds, at
most 1024 tenant entries). The staleness window equals the TTL: a suspension or
quota change made on another replica or process takes effect locally within at
most one TTL. Lifecycle, quota and provisioning routes invalidate the local
entry immediately after their database transaction commits, so single-process
deployments observe committed changes at once without allowing a concurrent
request to repopulate pre-commit state. A TTL of `0` disables caching and reads
fresh state on every request. If the status
lookup itself fails (for example the database is unreachable), the check defers
to the route layer, which surfaces the same persistence failure on its own
database access.

The session-establishment and refresh checks deliberately do **not** use this
cache: they read persisted tenant status directly so a suspension blocks the
next login or refresh with no staleness window, at negligible cost on those
low-frequency paths.

## Console

The governance console ships an operator surface for this API at `/tenants`
(top-level in the console navigation, alongside the other platform-operator
surfaces such as Policies, rather than nested under the operator's own
`/settings`). It is a cross-tenant fleet-administration surface, not a
tenant-scoped view.

The tenant list (`/tenants`) renders the `TenantRegistry` as a table
(`tenant_id`, display name, status pill, created-by, latest lifecycle
transition, updated timestamp), a status filter over `active` / `suspended` /
`pending_deletion`, and the API-required and empty states used across the
console (no local fallback data). The list is requested at the API maximum
`limit=200` (the `GET /platform/tenants` route caps at `le=200`, orders by
`tenant_id` and has no cursor pagination yet). When the returned rows reach
that ceiling the console renders a visible "listing cap" notice rather than
implying completeness — beyond 200 tenants an operator narrows by the status
filter to find others. A dedicated single-tenant `GET /platform/tenants/{id}`
route and server-side cursor pagination are a tracked follow-up. A provision
form on the list validates the
`tenant_id` against the server pattern `^[a-z0-9][a-z0-9_-]*$` before any
request is sent, generates a client-side `idempotency_key`, and surfaces the
`201` created, idempotent-replay `200`, `409` conflict and `422` field-mapped
outcomes distinctly. An optional bootstrap-admin block collects the actor id,
display name and requested scopes (recorded as audit evidence only).

The tenant detail (`/tenants/{tenant_id}`) shows the full `TenantRecord`, a
lifecycle timeline (provisioned / suspended / reactivated with actor, reason
and the audit event id for the latest transition), and the lifecycle actions:
suspend with a required reason when the tenant is active, reactivate when it is
suspended. Because there is no single-tenant read route, the detail derives its
record from the same `limit=200` registry read; if the tenant is not in that
page and the page is capped, the not-found state notes the tenant may exist
beyond the listing cap rather than being genuinely absent. A quota panel reads
the current `TenantQuotaSet` and edits the three
typed values with numeric inputs; a blank field clears the override (the API's
`null`-clears semantics), inputs are bound to the server `ge`/`le` limits, and
a confirmation step precedes the `PUT`, after which the panel refetches.

Every write is issued through the shared session bridge, which auto-attaches
the CSRF double-submit header. The console sends the fixed
`platform-tenant-operator-role` actor id and the operator scopes for each
action; the API rebinds `requested_by`/`actor_scopes` from the authenticated
OIDC principal and gates authority on `platform:tenant:operator` plus the
per-action scope (`:provision`, `:suspend`, `:read`, `:quota`). Operators
missing a scope receive the `403` surfaced inline on the relevant form.

## Boundaries

The slice is a foundation. It does not yet include:

- tenant deletion or data export (`pending_deletion` is modeled and blocked at
  the principal boundary, but no deletion pipeline exists);
- an approval-workflow gate on lifecycle transitions or quota changes;
- per-tenant quotas beyond the three typed keys;
- a dedicated single-tenant read route or server-side cursor pagination (the
  console lists and derives detail from the operator-scoped registry read at
  the `limit=200` API maximum, and surfaces a visible cap notice past it);
- distributed rate-limit or cache coordination across replicas (each process
  enforces from its own cache within the TTL staleness window).

Those capabilities remain Enterprise work behind the typed operator scopes,
the audited lifecycle transitions and the quota audit trail.

## Acceptance Notes

- API tests cover the provisioning happy path with bootstrap admin actor and
  audit evidence, idempotent replay, idempotency conflicts, duplicate tenants,
  duplicate bootstrap actors, invalid tenant ids and permission denials for
  each new scope.
- Lifecycle tests cover suspend → fail-closed 403 with audit evidence →
  reactivate restores access, lifecycle conflicts, unknown tenants, operator
  cross-tenant authorization and actor impersonation rejection.
- Quota tests cover typed updates, clears, per-change audit events, unchanged
  keys producing no events, validation bounds, unknown tenants and read/update
  scope enforcement.
- Enforcement tests cover the per-tenant rate limit tripping before the global
  limit, global fallback without a quota, bearer tokens never selecting a
  per-tenant limit, tampered-cookie rejection, the concurrent-session override,
  the live-sync row cap (including bounded batch reads and the audited capped
  bound) and the cache staleness window with explicit invalidation.
- Session-boundary tests cover a suspended tenant's login callback rejected
  fail-closed with no session row plus audit evidence, and a suspended tenant's
  refresh rejected with the stored session revoked and no IdP refresh grant
  attempted.
- Production identity admission is registry-backed. With
  `AXIS_TENANT_ADMISSION_MODE=registered_only`, verified bearer tokens and
  browser sessions are admitted only for persisted active tenants; unknown
  tenants are rejected with `tenant_not_registered`, login creates no session,
  and refresh revokes an existing session before any IdP grant. Local/demo
  environments keep the backward-compatible `claims_only` default. Only the
  exact persisted `active` lifecycle status is admitted. A packaged,
  direct-database first-tenant bootstrap closes the otherwise empty-registry
  deadlock without weakening the HTTP boundary; exact replay is idempotent and
  every later bootstrap is refused. Successful lifecycle and quota writes clear
  the process-local tenant-state cache only after commit; other replicas
  converge within the configured cache TTL.
- The OpenAPI contract is regenerated and checked; migration identifier tests
  cover the extended `tenants` schema and the new `tenant_quotas` table.
- Public documentation avoids customer data, personal names, contacts,
  pricing, credentials and deployment secrets.
