# ADR 0011: Request-scoped connector workspace projection

- **Status:** Accepted
- **Date:** 2026-09-06
- **Owners:** @metaforismo
- **Related:** [Issue #364](https://github.com/Limes-Labs/limes-axis/issues/364), [workspace contract](../connector-workspace.md)

## Context

The connector console eagerly reads seven registries, plus a manifest history
for a persisted selection. Most response fields are unused until an operator
opens a detail tab. Tenant binding, audit evidence, stale-data labels and links
to records outside the first page must remain correct.

## Decision

`axis_api.connector_workspace` owns a compact page and counter projection over
the existing registry builders. The HTTP composition root verifies the request
principal and tenant before calling it and derives the audit actor from that
principal. The summary has a page limit, bounded text and a 64 KiB response
budget. The existing operations router exposes `/operations/connectors/workspace`
and its selected-detail route with equivalent deprecated aliases, preserving
the repository's shared-handler compatibility contract.

The console reads the summary, then its selected connector. Tab-specific reads
include that connector's ID and run only while needed. Snapshot history retains
its separate permission check; wizard templates load only while the wizard is
open. Existing full registries and their legacy aliases remain available.

The page admission and existing counter-read audits share the caller's
transaction. Counter failures roll back to savepoints and return unavailable
values without committing independently. No server/shared HTTP cache is added.
The browser invalidates on query identity changes, remounts on a changed verified
cookie principal, and refreshes currently enabled queries after mutations.

## Consequences

- The measured 60-connector fixture falls from seven initial reads to two and
  from 161,020 response bytes to 9,587. Details remain independently loadable.
- Existing first-100 counter semantics remain explicit. They are not all-time
  totals; failed counters are unknown, not zero.
- Registry composition still materializes all tenant manifests internally.
  HTTP pagination does not establish bounded SQL work, memory or hosted capacity.
- The new page audit records read scope before counter savepoints, also ensuring
  SQLite's legacy driver does not commit their audits ahead of the caller.

## Alternatives Considered

- **Aggregate full registry responses into one endpoint:** reduces the request
  count but retains an unbounded, mostly unused response and coupled failures.
- **Tenant-only or shared cache:** adds principal invalidation, audit and freshness
  risks before a measured need for caching exists.
- **Rewrite persistence pagination now:** enlarges the slice and changes reference
  overlay/order behavior without separate storage measurements.

## Verification

HTTP tests compare every projected field and counter to authorized legacy reads,
check tenant/authentication denials, payload bounds, audit attribution, savepoint
failure and caller rollback. Browser-query tests cover lazy loading, cancellation,
principal changes and refresh. The [measurement guide](../connector-workspace.md)
includes the reproducible fixture and real desktop/mobile browser checks.
`make verify` and the existing CI lanes gate merge. Hosted capacity is not proved.

## Supersession

None.
