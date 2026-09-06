# External-Await Transaction Boundaries

This document inventories every API request path that awaits an external
runtime — a model provider or the workflow runtime — and records whether that
path holds a database transaction while it waits. It is the measurement
inventory for [issue #362](https://github.com/Limes-Labs/limes-axis/issues/362)
and the reference for the phase contract described below.

Holding a transaction across an external call couples database pool occupancy
to a third party's latency and leaves the request's own evidence uncommitted
for the whole call. The second effect matters more than the first: a record
that carries an idempotency key is not durable until it is committed, so a
process that dies mid-call loses the only proof that the call was ever issued.

## Phase Contract

A request that awaits an external runtime runs in three phases:

1. **Prepare and commit.** Evaluate permissions, policy, routing and egress,
   write the record that carries the idempotency key and the decision evidence,
   then commit. The transaction ends and the pooled connection is returned.
2. **External await.** Call the provider or workflow runtime with no open
   transaction and no lazy attribute load.
3. **Idempotent finalize.** Open a new transaction and record the outcome
   against the committed record. If this phase never commits, the record stays
   in its non-terminal state, which is the fail-closed position: a later
   delivery of the same idempotency key replays that record instead of issuing
   a second external call.

Phase 1 commits the whole request session. A caller may therefore only take
this contract when it owns the request transaction and the session holds
nothing but its own prepared work. A path that embeds an external call inside a
larger unit of work — an agent run, for example — must not commit, because it
would also commit its own partial state.

## Inventory

Seven request handlers in `services/api/src/axis_api/main.py` are `async def`
and take the synchronous `PersistenceRepository`.

| Request handler | External await | Owner | Written before the await | Phase contract |
| --- | --- | --- | --- | --- |
| `manufacturing_agent_run` | Model provider and workflow signal | `agent_runs.py` | Agent run row and context-read audit events | Not applied |
| `manufacturing_connector_evidence_invariant_snapshot_export_request_decision` | Workflow signal | `connector_evidence_invariants.py` | Approval decision record | Not applied |
| `manufacturing_connector_manual_import_decision` | Workflow signal | `connector_manual_imports.py` | Approval decision record | Not applied |
| `manufacturing_action_run` | Workflow signal | `action_runs.py` | Action run row | Not applied |
| `manufacturing_action_run_outcome` | None | `action_runs.py` | Not applicable | Not applicable |
| `manufacturing_approval_decision` | Workflow signal, unless `AXIS_APPROVAL_DECISION_OUTBOX_ENABLED` is set | `approval_decisions.py` | Decision record, and the outbox row when enabled | Superseded by the outbox |
| `platform_model_invocation_create` | Model provider | `model_invocations.py` | Requested invocation row | **Applied** |

Two entries need explanation.

`manufacturing_action_run_outcome` is `async def` for interface symmetry with
the other action-run handlers and awaits nothing external. It is listed so that
a future reader does not re-derive the same conclusion.

`manufacturing_approval_decision` already has the stronger remedy. With
`AXIS_APPROVAL_DECISION_OUTBOX_ENABLED`, the decision and its delivery
intent are written in one transaction and a dispatcher performs the signal, so
no external call happens inside the request at all. See
[the approval decision outbox](./approval-decision-outbox.md). An outbox suits
a fire-and-forget signal; it does not suit a model invocation, whose caller
waits for the provider response in the same request.

## Applied Path: Model Invocation

`POST /platform/models/invocations` commits the requested invocation before the
provider call. Two behaviours follow from that commit and are contract, not
side effects:

- A duplicate delivery that arrives while the first call is in flight now finds
  the committed record and replays it, so at most one provider call is issued
  per idempotency key. Previously both deliveries called the provider and one
  of them failed on the uniqueness constraint at the end of the request.
- A replayed record whose provider call has not yet been recorded is returned
  with status `requested` and a note stating that no result is available and
  that no second call was issued. Callers must not read `requested` as failure.

A record left in `requested` by an interrupted process is never finalized
automatically, because the outcome of the provider call is unknown and Axis
does not fabricate one. Recovering or expiring those records is operator work
today; automating it is follow-up scope, not part of this contract.

Browser session refresh already runs the same shape — it commits an atomic
`active` -> `refreshing` claim before the IdP token exchange and reaps stale
claims in `run_orphaned_session_sweep_job` — so the sweep pattern exists in the
repository. It is not reused here as-is: a stale session claim can be resolved
by revoking the session, while an invocation left `requested` cannot be
resolved without knowing whether the provider ran.

## Verification

| Property | Evidence |
| --- | --- |
| No transaction is open during the provider call | `test_invoke_model_holds_no_transaction_across_the_provider_call` |
| Pool occupancy during the provider call is 0, against a measured baseline of 1 | `test_provider_call_occupies_no_pooled_connection` and `test_provider_call_occupies_a_pooled_connection_for_embedded_callers` |
| An interrupted provider call leaves the idempotency key durable | `test_interrupted_provider_call_keeps_the_requested_row_durable` |
| A retry after an interruption issues no second provider call | `test_retry_after_an_interrupted_call_does_not_call_the_provider_again` |
| A concurrent duplicate replays instead of failing | `test_concurrent_duplicate_delivery_replays_instead_of_failing` |
| A concurrent duplicate with a different payload still conflicts | `test_concurrent_duplicate_with_a_different_payload_still_conflicts` |
| HTTP handler releases the pool before dispatch | `test_http_invocation_releases_pool_before_provider` |
| Overlapping deliveries see the committed in-flight claim | `test_overlapping_deliveries_replay_the_committed_in_flight_claim` |
| Prepare and finalize commit failures preserve dispatch and metering boundaries | `test_commit_failure_never_reissues_a_provider_call` |
| Embedded callers keep their transaction semantics | `test_invoke_model_keeps_the_caller_transaction_when_not_the_owner` |

All of the above live in `services/api/tests/test_model_invocations.py`.

`NOT RUN`: wall-clock tail-latency and pool-saturation measurement under a
representative workload. Those need the workload profiles and reproducible
baseline owned by
[issue #361](https://github.com/Limes-Labs/limes-axis/issues/361); pool
occupancy here is measured structurally at the connection pool, not derived
from a load test.

`NOT RUN`: the phase contract for the four remaining external-await handlers.
Each writes state that belongs to a larger unit of work and needs its own
analysis of what may become durable before the await.

The synchronous repository still runs on the event loop inside these
`async def` handlers. That is a separate concern from transaction scope and is
not addressed here.
