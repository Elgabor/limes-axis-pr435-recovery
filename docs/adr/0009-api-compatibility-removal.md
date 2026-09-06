# 0009 — Observe legacy API use before removal

- Status: Accepted
- Date: 2026-09-06
- Issue: #357
- Review: implementation self-review completed for shared handlers, bounded
  telemetry, consumer evidence and the separate production removal gate.

## Context

The deprecated manufacturing prefix still serves 103 operations. Bootstrap has
real console/CI consumers and no canonical alternative. Static absence of other
repository callers cannot prove that a deployed alias or Temporal compatibility
contract is unused.

## Decision

Keep the existing handlers and governance owners. Add `/demo/bootstrap` as a
second registration of the same demo handler, and migrate shipped bootstrap
clients. The HTTP composition root owns deprecation response headers; the
existing optional app-scoped OTel runtime owns a bounded usage counter. Neither
performs identity resolution, reads a request body, authorizes an operation,
redirects clients or disables routes.

Publish a planned 2027-01-01 removal with at least 90 days of deployment notice,
30 days of complete zero-use evidence, client-owner confirmation and a separate
maintainer-reviewed removal release. Missing telemetry is unknown usage. If the
gate is unmet, retain compatibility and publish a revised date. Details and
operator responsibilities live in [the policy](../api-compatibility.md).

Keep the consumed worker package entry point, client DTOs and rolling-upgrade
signals; do not remove them based on the old static audit. Retain TypeScript's
existing strict unused-symbol checks for production and tests.

## Alternatives

- Immediate alias or wrapper deletion would break known bootstrap/worker
  consumers and lacks private-deployment evidence.
- OpenAPI-only deprecation does not inform runtime clients or measure migration.
- A separate telemetry collector, persistent usage table or access decision
  would duplicate existing owners without helping this migration.

## Consequences and verification

No runtime dependency, credential, tenant, audit, transaction or execution owner
changes. Headers describe the namespace even when a request is refused before
routing; those requests use a fixed `unmatched` metric label. Collection remains
opt-in. Dates are release policy, not a timer in the request path.

Tests compare all legacy/canonical contracts and exercise headers, denials,
redacted/bounded labels, failures and cross-URL bootstrap replay. The worker
entry point is executed with its runtime replaced by a recording callable.
TypeScript negative probes verify production and test enforcement. Full local
verification, exact-head CI and remaining NOT RUN boundaries belong in the PR.
