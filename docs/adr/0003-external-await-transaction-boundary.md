# ADR 0003: External-Await Transaction Boundary

- **Status:** Proposed
- **Date:** 2026-09-05
- **Owners:** `@metaforismo`
- **Related:** [Issue #362](https://github.com/Limes-Labs/limes-axis/issues/362),
  [parent issue #360](https://github.com/Limes-Labs/limes-axis/issues/360)

## Context

Seven `async def` request handlers take the synchronous persistence repository,
and six of them await an external runtime — a model provider or the workflow
runtime — while the request transaction is still open. The full inventory is in
[external-await transaction boundaries](../performance-external-await-boundaries.md).

`POST /platform/models/invocations` is the sharpest case. It writes the
requested invocation row, which carries the idempotency key together with the
route, permission, platform-policy and egress decisions, and then awaits the
provider for up to the configured timeout with that row uncommitted. Two
properties follow, and neither is only about speed:

- A pooled database connection is held for the duration of a third party's
  latency.
- The idempotency key is not durable. A process that dies during the provider
  call loses the only record that the call was issued, so a retry or a
  duplicate delivery finds no key and can invoke the provider a second time.
  Concurrent duplicates likewise both call the provider, and the loser fails on
  the uniqueness constraint at the end of the request.

The repository already answers the same pressure twice, in two different
shapes. Approval decisions use a transactional outbox: the decision and its
delivery intent commit together and a dispatcher performs the signal. Browser
session refresh uses a committed claim: an atomic `active` -> `refreshing`
transition commits before the IdP token exchange, which then runs outside the
open transaction, and `run_orphaned_session_sweep_job` reaps claims left stale
by a process that died between claim and completion.

An outbox fits a fire-and-forget signal. It does not fit a model invocation,
whose caller waits for the provider response within the same request. The
committed-claim shape does fit, and this decision applies it.

## Decision

A request handler that awaits an external runtime runs in three phases:
prepare and commit, external await, idempotent finalize. The record carrying
the idempotency key and the decision evidence is committed before the external
call; the outcome is recorded afterwards in a new transaction.

The commit boundary is owned by the request handler, not by the domain
function. `invoke_model` takes an explicit `commit_before_provider_call`
argument, which the model-invocation handler sets and embedded callers leave
unset. Phase 1 commits the entire request session, so only a caller whose
session holds nothing but this invocation's own prepared work may take the
contract. An agent run, which embeds an invocation inside a larger unit of
work, keeps its existing all-or-nothing semantics until its own slice is
analysed.

The non-terminal record is the fail-closed position. A record left `requested`
by an interrupted process is replayed, never re-invoked, because the outcome of
the first provider call is unknown and Axis does not fabricate one.

This ADR applies the contract to the model-invocation handler only. The four
remaining external-await handlers keep their current boundary; each writes
state belonging to a larger unit of work and needs its own analysis of what may
become durable before the await.

## Consequences

- Provider latency no longer occupies a database connection on the governed
  model-invocation path, measured at the connection pool.
- At most one provider call is issued per tenant and idempotency key, including
  under concurrent duplicate delivery. A duplicate that previously produced a
  second billable call and a uniqueness failure now returns the stored record.
- A caller can receive a `requested` status for a key whose provider call is
  still in flight or was interrupted. This is a widened response contract:
  `requested` must not be read as failure, and the returned notes say so.
- A record left `requested` by an interrupted process is not finalized
  automatically. Recovering or expiring such records is operator work until a
  reaper is designed; that is deliberately not part of this decision.
- Audit evidence written before the provider call now survives a request that
  later fails, where it was previously rolled back. For an append-only audit
  trail this is the intended direction, but it is a change in what a failed
  request leaves behind.
- The contract is opt-in per caller, so two transaction shapes coexist until
  the remaining handlers are converted.

## Alternatives Considered

- **A transactional outbox for model invocations:** rejected because the caller
  waits for the provider response in the same request. An outbox would turn a
  synchronous governed call into an asynchronous one and change the endpoint's
  contract far beyond this decision.
- **Shipping the orphan sweep in the same change:** rejected as separate scope.
  Session refresh shows the shape a sweep would take — a staleness window and a
  maintenance job — but an invocation left `requested` cannot be resolved the
  way a stale session claim can, because the provider may or may not have run.
  What such a sweep is allowed to conclude is its own decision.
- **Committing unconditionally inside `invoke_model`:** rejected because the
  function is also called inside an agent run, where a commit would make that
  run's partial state durable without any analysis of its finalize semantics.
- **An autonomous transaction or a second session for the requested row:**
  rejected because it adds a connection rather than releasing one, and it
  splits one request's evidence across two connections with no ordering
  guarantee.
- **Leaving the boundary and shortening the provider timeout:** rejected
  because it trades a correctness property for a smaller version of the same
  exposure; the idempotency key would still be lost on an interrupted call.
- **Moving the whole path to an async database driver first:** rejected as a
  larger change that removes event-loop blocking but not the open transaction.
  The two concerns are independent and this one is fixable now.

## Verification

- Focused transaction, pool-occupancy, interruption and duplicate-delivery
  tests in `services/api/tests/test_model_invocations.py`.
- The full API test suite.
- `make docs-check`.
- `NOT RUN`: wall-clock tail-latency and pool-saturation measurement under a
  representative workload, which needs the baseline owned by
  [issue #361](https://github.com/Limes-Labs/limes-axis/issues/361).
- `NOT RUN`: the contract for the four remaining external-await handlers.
- `NOT RUN`: an independent security review of the widened response contract.

## Supersession

None.
