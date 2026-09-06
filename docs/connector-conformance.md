# Connector conformance and operational health

[Issue #342](https://github.com/Limes-Labs/limes-axis/issues/342) adds reusable
fixture checks and an operational health model to the existing
[`axis_sdk.connector_authoring`](connector-authoring.md) namespace. Protocol 1.0,
REST contracts and production source registrations are unchanged. These checks
cover read-only discovery and bounded reads; optional writeback, CDC and streaming
require separate conformance evidence.

## Run and reuse the fixture suite

```sh
cd packages/sdk-python
uv run python examples/connector_conformance.py
uv run pytest tests/test_connector_conformance.py tests/test_connector_operational_health.py -q
```

The [example](../packages/sdk-python/examples/connector_conformance.py) uses three
synthetic assets and no external source, credentials, persistence or network.
The [harness](../packages/sdk-python/src/axis_sdk/connector_authoring/conformance.py)
accepts any `SourceConnector` plus a bound context and `ConformanceProfile`.
The profile names the resource, expected record count and ordered golden-record
digest, per-page limits and maximum page/resource counts. `records_digest`
calculates the digest from the author's versioned fixture, not from the adapter's
actual output. Canonical UTF-8 JSON records separated by newlines make the digest
independent of page boundaries; order and values remain significant.

`run_conformance` reports eight checks:

| Check | Required evidence |
| --- | --- |
| Negotiation | Explicit discovery/read/health capabilities and context-compatible protocol/connector identity before adapter calls |
| Discovery | Valid bounded discovery, unique resource IDs and the requested resource selection |
| Health | A valid adapter health response reporting ready for the healthy fixture |
| Read | Row/byte limits, bound advancing checkpoints, no cursor cycles, page bound, complete count and golden digest |
| Credentials | An author-injected unavailable-credentials fixture returns the protocol 1.0 source-unavailable error |
| Schema drift | A changed selection is refused with resource-mismatch |
| Throttling | Rate-limited is returned without the harness retrying the operation |
| Partial data | Positive bounded partial data is labelled truncated with no resumable checkpoint |

Authors supply the four `ReadFixture` cases through their adapter's isolated
source clients. Missing fixtures are `not_run` and prevent `report.passed`.
An unexpected exception, invalid batch, wrong outcome, wrong fixture context or
incomplete stream fails its check. Invalid returned data cannot be mistaken for
an expected adapter-raised error. The report retains fixed reasons, error codes,
counts and the expected fixture digest. `pages` counts read attempts, including
failed calls; `records` counts validated rows. It excludes rows, cursors and raw
exception messages. Store reports with fixture/source/package revision and the
command/environment used; the harness does not attest those caller-supplied facts.

[Reference failure fixtures](../packages/sdk-python/src/axis_sdk/connector_authoring/fixtures.py)
exercise the harness with synthetic errors and the in-memory reference. They do
not test a real credential resolver, provider or another adapter. A real adapter
must supply its own failure injection; reusing these synthetic readers does not
qualify that adapter. Protocol 1.0 has no credential-specific error variant:
`source_unavailable` is the fixture's broad source error. Its SDK retryability
hint does not determine whether the host retries a credential failure.

Only the supplied fixture adapters execute. The harness does not discover hosts,
resolve credentials, activate sources, write data, retry operations or commit
checkpoints. Use trusted isolated fixture clients. Normal stream reads also check
elapsed time after a call returns; synchronous Python cannot preempt a blocked
client. Driver timeouts, cooperative cancellation, discovery/health deadlines
and source-specific fault recovery require adapter/host evidence separately.

## Metadata-only operational health

[`health.py`](../packages/sdk-python/src/axis_sdk/connector_authoring/health.py)
projects one host-bound `HealthObservation` under explicit operator
`HealthBudgets`. It is a pure calculation: no polling, persistence, scheduling,
credential resolution or authorization is performed.

| Field/metric | Meaning |
| --- | --- |
| Scope | Tenant, connector and resource IDs bound by the host before observation |
| `observed_at` | Time of the coherent observation; all times must carry a timezone |
| Freshness | Seconds since the last complete, durably committed success |
| Lag | Observed source head time minus the committed source watermark time; both must be known and comparable |
| Checkpoint | Unknown, absent, explicitly not applicable, committed or invalid; committed time carries no cursor value |
| Checkpoint age | Seconds since durable checkpoint commit, compared with the operator's budget when applicable |
| Error | Fixed category plus occurrence time; an error remains active until a strictly later complete success |
| Retry | Host-observed idle/scheduled/in-progress/exhausted state, attempt count and scheduled time; an overdue schedule is visible |

An idle source whose head equals its committed watermark has zero lag even when
its latest event is old. If either source position cannot be expressed as a
comparable timestamp, lag stays unknown; never replace it with zero or convert a
row offset into seconds. The source head and watermark must describe the same
source ordering and coherent observation. Late event-time values are not valid
positions unless the adapter documents that ordering guarantee.

Unknown history remains `null` with an unknown reason. Explicit checkpoint
`not_applicable` is distinct from missing evidence; the host uses it only for a
source contract that does not require a resumable checkpoint. Operators choose
all three budgets for their source workload. A checkpoint-age budget is a
commit-cadence requirement, not evidence that every idle source must advance.

Status precedence is unavailable, degraded, unknown, ready. Active credential,
schema, source-unavailable or invalid-checkpoint errors and exhausted retries
are unavailable. Partial data, throttling, unknown errors, retry activity and
budget breaches degrade health. Missing required observations yield unknown
when no stronger failure is present. Ready requires known metrics within budget,
a valid/applicable checkpoint state and no active error/retry. Future history,
watermarks ahead of the observed head and incoherent retry/checkpoint metadata
are rejected. Unknown and failure reasons remain visible even with a stronger
status. Health does not itself make a connector eligible for execution or support.

## Existing host ownership and adoption

Production adapters and host records retain their existing paths. This change
provides the shared model and fixture suite; it does not add a collector, API
endpoint, persisted health table or migrate existing adapters automatically.

| Observation or action | Existing owner and adoption rule |
| --- | --- |
| Tenant, actor, read permissions | [Identity/tenant gates](connector-authoring.md#existing-host-gates-to-reuse); never accept a client-supplied observation as access authority |
| Successful ingestion/error/attempt metadata | [`connector_source_ingestion.py`](../services/api/src/axis_api/connector_source_ingestion.py): use durable extract completion, attempt outcomes and safe error categories; a validation-only success or preview is not an ingestion success |
| Retry schedule, exhaustion and claims | The existing ingestion dispatcher and [`worker live-sync activities`](../services/worker/src/axis_worker/connector_live_sync_activities.py); observe decisions without scheduling a second retry loop |
| Durable checkpoint/fencing | [`connector_runs.py`](../services/api/src/axis_api/connector_runs.py), [`persistence.py`](../services/api/src/axis_api/persistence.py); project presence/commit metadata only after committed work |
| Source lag | Adapter-supplied comparable source head/watermark metadata under the existing resource binding; current opaque offsets alone provide no time-lag evidence |
| Credentials, egress, lifecycle | Existing [capability gates G0–G7](connector-capabilities.md); a test report or ready health never bypasses a lease, approval, policy, lifecycle or claim check |
| Audit and raw payloads | Existing metadata-only audit and governed payload storage; no report may contain credential values, raw source rows or checkpoint tokens |

## Certification policy

These levels are release-review decisions, scoped to an exact adapter build,
protocol, source versions and deployment profile. They are not inferred from
`report.passed`, `HealthResult.ready`, a manifest flag or an unrelated CI job.

| Level | Minimum release evidence | Operational meaning |
| --- | --- | --- |
| Unverified | Missing/failing checks or unreviewed source/host evidence | No support claim; missing results remain NOT RUN |
| Preview | All eight checks using that adapter's own versioned healthy/failure clients and golden data; existing host tenant/credential/egress/claim/audit gates mapped and tested; maintainer review records scope, build digest, limitations and owner | Explicitly limited evaluation under existing activation gates; no production reliability promise |
| Supported | Preview evidence plus tests against the declared real source versions, driver timeouts, interrupted/partial work, durable checkpoint recovery, rate limits and concurrent claims; host gate integration, observed workload budgets, retry/dead-letter/requeue behavior, runbook and accountable maintainer approval | Support only for the reviewed source/version/profile and published limits |

A certification record must link the exact adapter/build digest, protocol,
fixture revision, commands and dated reports, real-source/host evidence, health
budgets, known gaps, maintainer and review date. Revalidate after adapter, source,
protocol or host-boundary changes; failing required evidence prevents promotion
and requires review of an existing support claim. There is no automated status
promotion or approval endpoint in this implementation.

The reference is an SDK fixture demonstration only. Neither it nor the two
existing live source registrations gain preview/supported certification from
this PR. The existing live adapters must explicitly adopt the ports and provide
their own evidence before claiming a level under this policy.

## Verification boundaries

SDK tests cover reference pagination, empty/partial/malformed output, golden
mismatches, cursor cycles, absent/wrong fault fixtures, fixed error reporting,
elapsed read budgets and health projection including idle sources and unknown
lag. The executable example is tested. `make verify` retains API/worker/REST
regression coverage, and CI retains its live-API/PostgreSQL lane.

NOT RUN by this fixture suite: real credentials/providers, production adapter
adoption, source-specific drivers, distributed claims, source clock consistency,
production load/soak and support certification. Exact full-suite and CI results
are recorded in the implementation PR, without promoting fixture evidence into
production conformance.
