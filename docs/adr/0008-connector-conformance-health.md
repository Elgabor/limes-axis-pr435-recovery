# ADR 0008: Connector conformance and health in the authoring SDK

- **Status:** Accepted
- **Date:** 2026-09-06
- **Owners:** @metaforismo
- **Related:** [Issue #342](https://github.com/Limes-Labs/limes-axis/issues/342), [conformance and health](../connector-conformance.md)

## Context

The source authoring protocol defines port shapes and bounded batches, but
adapter authors lack a reusable fixture report and a shared model for operational
freshness, lag, checkpoints, errors and retries. A green reference test must not
be mistaken for another adapter's readiness or a new execution permission.

## Decision

The existing `axis_sdk.connector_authoring` namespace owns a fixture-driven
conformance harness, reference fault fixtures and a pure operational health
projection. The harness tests version negotiation, discovery, health, bounded
complete reads/golden data and four explicit failure cases. Missing evidence
remains NOT RUN. Reports contain fixed reasons and metadata only.

The health model consumes scoped host observations and explicit operator budgets.
Unknown evidence stays unknown; source lag compares observed head with committed
watermark so an idle source is not assumed behind. Checkpoint applicability is
explicit. The model observes retry state but never schedules work.

Preview/supported certification is a documented maintainer release-review policy
requiring exact adapter/source/host evidence. The harness does not assign levels,
register sources, grant access or persist health. Production adoption retains
existing identity, credentials, egress, activation, claims, payload and audit
owners. Protocol 1.0 and package runtime dependencies remain unchanged.

## Consequences

- Authors reuse one test surface and metadata vocabulary without importing API
  or worker packages at runtime.
- Healthy fixtures and synthetic failure readers can run offline in normal SDK CI.
- Supported status still needs declared real-source versions, host integration,
  operational budgets/runbooks and accountable review.
- A synchronous test harness cannot sandbox adapter code or preempt blocked
  drivers. Real-source deadlines and cancellation remain adapter responsibilities.
- Existing live adapters are not automatically migrated or certified.

## Alternatives Considered

- **Put source health in the API only:** prevents offline partner authoring and
  couples tests to deployment/persistence dependencies.
- **Let a passing reference suite certify every adapter:** confuses harness
  verification with source and host-boundary evidence.
- **Add another retry or credential layer:** duplicates the current trust and
  execution owners instead of observing their decisions.

## Verification

SDK tests exercise complete/partial/malformed reads, golden values, bounded
pagination, checkpoint cycles, fault fixtures, metadata-only error reporting and
health state transitions. The executable offline example is tested. Full local
verification and exact-head CI evidence are recorded in the PR. Real providers,
production adoption and support certification remain separate review boundaries.

## Supersession

None.
