# ADR 0007: Model aggregate persistence behind stable facade methods

- **Status:** Accepted
- **Date:** 2026-09-06
- **Owners:** @metaforismo
- **Related:** [Issue #356](https://github.com/Limes-Labs/limes-axis/issues/356), [aggregate boundaries](../persistence-aggregates.md)

## Context

`AxisPersistenceRepository` contains 237 methods across many aggregates. Model
endpoint and invocation SQL can have a focused owner without changing the
request-level unit of work or forcing every caller to migrate simultaneously.

## Decision

`axis_api.repositories.models` owns model persistence records, explicit read/write
ports and the SQL implementation. The existing facade re-exports record types
and delegates its nine model methods to one aggregate implementation using the
same caller-supplied SQLAlchemy session. The missing-record exception has one
shared owner and remains available at the old import path.

The aggregate flushes but never commits, rolls back, opens or closes a session.
Domain services and request/session orchestration keep transaction and policy
authority. Existing query predicates, sorting, limits, constraint behavior and
record schemas are moved unchanged.

## Consequences

- Model SQL has a focused owner and can be exercised directly through its ports.
- Existing callers keep their imports, method signatures and transaction scope.
- Audit, usage, provider pre-call commits and savepoint recovery remain explicit
  in their existing owners; no generic base repository hides domain behavior.
- Nine facade delegates remain for compatibility; most aggregates still need
  extraction in subsequent reviewable slices.
- PostgreSQL contract tests become an explicit step in the existing live-API CI
  job. They create and migrate a fresh throwaway database with the job's server.

## Alternatives Considered

- **Generic base repository or dynamic method forwarding:** obscures SQL and
  makes aggregate and transaction ownership harder to inspect.
- **Aggregate opens its own session:** breaks model/audit/usage atomicity.
- **Migrate every caller and aggregate at once:** expands the review beyond one
  independently verifiable slice.

## Verification

The same contract suite exercises facade and aggregate on SQLite locally and
PostgreSQL in CI, including tenant filtering, idempotency, keyset ordering,
rollback and cross-session commit visibility with linked audit writes.
Structural comparison proves all nine moved SQL methods and four records are
unchanged. `make verify` and OpenAPI parity protect existing caller behavior.
Exact outcomes and external-service boundaries are recorded in the PR.

## Supersession

None.
