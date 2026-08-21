# Product audit and hardening checklist — 2026-07-22

This checklist records the repository-wide product review requested on 2026-07-22. It prioritizes product trust, tenant isolation, truthful data presentation, and repeatable verification over decorative UI changes.

## P0 — Tenant and identity correctness

- [x] Scope every core console route to the API-verified tenant: workflows, agents, ontology, connectors, model routing, policies, audit, simulation, and command search.
- [x] Disable tenant-scoped requests until `/identity/session` resolves successfully.
- [x] Reject mismatched response tenants in the Web runtime layer.
- [x] Cover authenticated non-demo and explicitly unauthenticated demo sessions in tests.

## P1 — Data fidelity and operational correctness

- [x] Do not replace valid empty persisted datasets with reference/demo records.
- [x] Distinguish live, reference-scenario, stale-after-refresh-failure, empty, and unavailable sources.
- [x] Replace proxy or invented overview metrics with values backed by the named dataset.
- [x] Treat a zero-artifact replay response as an empty state, not an API error.
- [x] Reconcile the connector live-sync Temporal schedule when the feature is disabled.
- [x] Remove wall-clock expiry from fixed-date API tests so the full suite is deterministic.
- [x] Rename overview shortcuts that only navigate to read-only pages.

## P1 — External side-effect integrity (follow-up architecture)

- [ ] Extend the durable outbox/state-machine boundary beyond approval decisions to action signals, connector export signals, object writes, and paid model calls.
- [ ] Decide when the approval decision outbox becomes the default deployment mode.
- [ ] Build, scan, approve, sign, and publish the same immutable container digest.

## P2 — UX, navigation, and accessibility

- [x] Provide a skip link and a stable main-content target; remove nested `main` landmarks.
- [x] Give mobile navigation an explicit navigation landmark and a discoverable
      overflow/menu pattern.
- [x] Give loading regions accessible status text while keeping the skeleton visual concise.
- [x] Expose status and sparkbar values without relying on color or pointer-only
      `title` text.
- [x] Add route-level loading, error, and not-found boundaries and route-specific metadata.
- [x] Keep selected filters, records, and deep links synchronized with the URL. Record
      selection, high-risk filters, ontology traversal, policy tabs and Settings tabs are
      URL-backed; discrete tab changes push browser history while comparison-only policy
      state replaces the current entry.
- [ ] Replace implementation-oriented tenant copy with operator-facing language.

## P2 — Runtime and deployment follow-ups

- [ ] Add worker/outbox health and backlog-age evidence to deployment readiness.
- [ ] Resolve registered model credential handles during provider invocation.
- [ ] Make model endpoint and invocation idempotency race-safe.
- [x] Implement the documented `X-Request-Id` correlation boundary, including validation,
      request state, response echo, CORS exposure, and generic-500 correlation evidence.
- [x] Make notification acknowledgement audit idempotency race-safe for simultaneous
      writers. PostgreSQL uses a transaction-scoped advisory lock, SQLite acquires write
      intent immediately before the authoritative read, identical retries replay one
      audit event, and acknowledgement state cannot regress.
- [x] Decide whether production admits valid identity claims for unknown tenant records.
      Local development can opt into `claims_only`; production readiness requires
      `registered_only`, which rejects unknown tenants consistently across bearer, cookie,
      login and refresh flows and records a denial audit event.
- [ ] Expand the Python SDK beyond the current demo-manufacturing surface.

## P3 — Component and code consistency

- [x] Use semantic source/status badges instead of unconditional green source pills.
- [x] Use semantic connector governance tones and the defined danger token for failed agent runs.
- [x] Correct singular/plural operational copy.
- [ ] Consolidate repeated cards, tables, and action styles onto shared primitives.
- [ ] Split the API composition root into bounded route modules without weakening cross-cutting controls.

## Verification gates

- [x] Web unit tests, lint, typecheck, and production build.
- [x] API, worker, SDK, schema, OpenAPI, deployment, and container contract checks.
- [x] Desktop, mobile, tablet, and small-laptop browser sweeps with overflow checks.
- [x] Keyboard focus, dialogs, drawers, filters, empty/loading/error states, refreshes, and repeated submissions.
- [x] Authenticated non-demo tenant contract test across all tenant-scoped routes.
- [ ] Live Postgres, Temporal, TypeDB, object-store, and OIDC checks when Docker is healthy.
- [x] Second-pass product review after implementation.

### Verification evidence

- Web: 827 unit/component tests in 91 files; lint, typecheck, and production Next.js
  builds for both the live-API and fail-closed profiles passed.
- Browser: 69 mocked Chromium smoke tests passed across desktop, Pixel 7, and iPad
  profiles; 21 read-only live-API scenarios passed across the same three profiles
  and 2 state-mutating scenarios passed once, serially, in Chromium.
- In-app browser: the real production build and API were inspected at 390×844 with the
  mobile drawer closed and open. The route retained one `main` landmark, had no horizontal
  overflow or console errors, exposed the current Settings destination, locked body scroll
  while open, closed on Escape, and restored focus to the menu trigger.
- Persisted product sweep: 12 console routes rendered with one `main` landmark and no
  horizontal overflow; audit filtering/reset and truthful empty workflow/replay states
  were exercised.
- Services: API 1,530 passed / 14 infrastructure-gated skipped; worker 51 passed / 3
  infrastructure-gated skipped; Python SDK 104 passed. Ruff passed for all three Python
  packages.
- Contracts: OpenAPI export, all six schema lint/compile checks, deployment package, all
  three Helm profiles, container-image, and container-release checks passed.

## Current environment boundary

The Docker daemon was not running during the final review. The persisted browser pass
therefore used a temporary SQLite database created from the current ORM schema, populated
with the canonical migration reference payloads, and bootstrapped through the real API.
The 23 live-profile browser scenarios exercised the real FastAPI application and production
Next.js build; the other 69 scenarios intentionally exercised the fail-closed/mock profile.
Neither set is evidence that the distributed stack or Postgres migrations work in this
environment. Live Postgres, Temporal, TypeDB, MinIO and Keycloak claims remain unverified
until Docker is available.
