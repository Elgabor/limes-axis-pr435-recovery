# Hosted prospect sandbox contract

**Status: design only; hosted admission is not enabled.** This specification
resolves [#322](https://github.com/Limes-Labs/limes-axis/issues/322).
[ADR 0012](adr/0012-prospect-sandbox-lifecycle.md) records the deployment and
reset decision. The capability remains **Planned / Hosted** in the
[edition matrix](editions-matrix.md).

The first release is an operator-invited evaluation of real Axis API, Postgres,
workflow and audit behavior using a versioned synthetic manufacturing scenario.
It is separate from the [local developer demo](demo-readiness.md) and from any
future OSS distribution. A working reference screen is not proof that its
workflow executed. Customer uploads, customer credentials, arbitrary connectors,
external model providers, self-registration, trials and billing are outside this
initial profile.

All requirements below are release gates for future implementation. They do not
add an endpoint, setting, scheduler, deployment overlay or deletion command.

## Existing foundations and missing capabilities

This inventory was checked against source revision
`02e96ee53948d2230536790f2f2985bd1699374f`.

| Foundation | Current behavior | Work still required before hosted invitations |
| --- | --- | --- |
| [Tenant lifecycle](../services/api/src/axis_api/platform_tenants.py) | Operator-scoped provisioning, suspension, reactivation and three typed quotas; audited and idempotent provisioning | Invite/lease records, generation ownership, expiry, reset and deletion orchestration |
| [Principal admission](../services/api/src/axis_api/tenant_admission.py), [HTTP boundary](../services/api/src/axis_api/main.py) | Verified tenant binding and registered-only active-tenant admission; login/refresh check current lifecycle state | Expiry/generation checks on every protected request, session establishment and refresh; equivalent worker checks |
| [Rate limits](../services/api/src/axis_api/rate_limit.py), [session persistence](../services/api/src/axis_api/persistence.py) | Verified bearer/cookie tenant quotas on protected paths; process-local request buckets; session cap applies per actor within a tenant | Invite/user totals, durable workload/storage budgets and aggregate enforcement across restarts/replicas |
| [Demo bootstrap](../services/api/src/axis_api/demo_bootstrap.py) | Copies available persisted reference surfaces, preserves existing target records, and replays a stored bootstrap marker | Complete, immutable pack validation and installation receipt; a bootstrap marker is not a reset or executable-workflow receipt |
| [Workflow runtime](../services/api/src/axis_api/workflow_runtime.py), [worker](../services/worker/src/axis_worker/temporal_adapter.py) | Governed workflow starts/signals through existing ports | Sandbox workflow installation, tenant/generation fencing and verified drain/termination |
| [Scheduled jobs](platform-scheduled-jobs.md) | Session recovery and inactive-tenant session reconciliation | Expiry/reset schedules and interrupted-lifecycle recovery; current maintenance does not expire sandbox leases |
| [Object storage](../services/api/src/axis_api/object_storage.py), [audit](platform-audit.md) | Governed storage and audit export, retention and legal-hold primitives | Complete generation inventory, deletion across all stores, backup handling and retained deletion evidence |
| [Managed deployment profile](../infra/helm/limes-axis/profiles/single-tenant-managed.yaml) | Helm baseline with explicit readiness evidence gates | Evaluation-specific limits, identity/network isolation, inventory and a hosted acceptance rehearsal |

The generic vertical-pack release/installer and complete tenant deletion are not
present. The pack work belongs to [#348](https://github.com/Limes-Labs/limes-axis/issues/348)
and [#349](https://github.com/Limes-Labs/limes-axis/issues/349); deletion belongs
to [#325](https://github.com/Limes-Labs/limes-axis/issues/325). This contract
specifies their sandbox inputs and acceptance evidence without claiming those
implementations. Invite delivery is blocked until the missing gates pass.

## Isolation and authority

Use one dedicated evaluation deployment per prospect organization. Its API,
worker, database credential/database, object-store credential/bucket, Temporal
namespace/task queue and IdP client/role mappings must be isolated from
production and from other evaluations. Shared physical infrastructure is allowed
only with independently enforced resource and network boundaries. A Kubernetes
namespace or a tenant ID alone is insufficient proof of storage isolation.

Every writable record and runtime identifier belongs to an immutable
`(sandbox_id, generation, tenant_id)` assignment. Each replacement generation
gets a new tenant ID and resource inventory; IDs and credentials are never
reassigned to another prospect. Canonical synthetic seed and platform-operator
tenants may exist in the deployment but are never selectable by prospect users.
All API reads, worker jobs, object keys, workflow IDs, reports and callbacks retain
the existing tenant binding in addition to the generation fence.

Provisioning uses the existing platform tenant API and its
`platform:tenant:operator` plus per-action scopes. The packaged first-tenant
bootstrap remains restricted to its existing empty-registry/direct-database
boundary; it is not an invitation endpoint. Scenario bootstrap uses
`POST /demo/bootstrap` with a verified **target-tenant** installation identity
holding `demo:scenario:bootstrap`. A platform-operator token from another tenant
cannot bypass the bootstrap handler's tenant check. Installation authority is
removed before prospect admission; prospects cannot provision, change quotas,
bootstrap, reactivate, select a pack or administer the fleet.

Require OIDC authentication, registered-only tenant admission, TLS, exact
origins/callbacks, secure sessions, CSRF checks and verified actor attribution.
Use `AXIS_TENANT_STATE_CACHE_TTL_SECONDS=0` in the future evaluation profile for
fresh lifecycle reads. This existing setting does not implement a lease check.
Identity or lease-store uncertainty must deny access; a stale active lease must
never extend an evaluation. Neither the local auth-optional demo mode nor the
local demo realm/password is a hosted deployment option.

The existing restricted-egress boundary allows only approved infrastructure and
fixture sources. Prospects supply no network destinations or provider keys.
An approved fixture adapter still needs its normal execution gate, active
credential lease, egress policy, schema/binding and claim evidence. Model calls
remain disabled in this profile. Support and lifecycle workers use separate,
audited service identities with only the scopes required for each operation;
being a scheduler does not grant tenant or destructive authority.

## Ownership and durable lifecycle record

The existing control API owns the future sandbox domain and admission policy.
The existing worker owns durable orchestration through Temporal; deployment
operations owns resource creation and verified removal using the deployment
boundary. No browser, invitation token or worker job gains direct authority to
skip domain checks. The fleet's durable lease, operation receipts and minimal
retention records must survive removal of an evaluation deployment, with access
through the same platform-operator authorization and audit model.

The future lease record must include:

- opaque sandbox ID, owner/operator reference, approved identity bindings and
  the immutable tenant/resource assignment for each generation;
- profile version, pack release/digest, source release SHA, creation time,
  invite/installation deadlines, absolute access deadline and next reset time,
  all in UTC (the access deadline is set once at first activation);
- lifecycle state, current generation/revision, last completed operation and
  idempotency key, quota reservations and installation/readiness receipts;
- suspension/closure reason, cleanup progress per store, retention/hold status,
  audit export digests and deletion verification references.

Secrets and raw invite tokens are stored through the credential boundary, never
in this record or logs. Invite validation stores a token digest and binds a
single-use, short-lived invite to the approved IdP issuer/subject and tenant.
An email address can support delivery but is not sufficient identity authority.
Replays return the same assignment; changed identity, pack, deadline or resource
payload under the same operation key is a conflict. Accepting an invite is
atomic with seat reservation and the recorded verified identity. A reset never
reopens a spent invite or permits a different person to claim its tenant.

### State transitions

These are specification labels for the new sandbox record, **not** additions
to the current `TenantLifecycleStatus` enum. Existing tenant states remain
`active`, `suspended` and `pending_deletion`; the last value is not a deletion
pipeline. The sandbox admission gate is an additional conjunction, so an active
tenant alone cannot admit a provisioning or expired sandbox.

| State / transition | Admission and required behavior |
| --- | --- |
| `invited` | No application access. Operator has approved profile, identity and deadlines; unused invites expire and release reservations. |
| `provisioning` | No prospect access. Register tenant, set quotas, allocate resources, install/verify the pinned pack and record receipts. Only the narrowly scoped installer may run the acceptance work in this state; prospect work is denied. Retry uses the same operation key. |
| `active` | Admit only the assigned verified identity, active tenant, current generation and unexpired lease. All readiness/installation gates must have passed. |
| `resetting` | Deny new prospect requests and jobs; fence and suspend the old generation before draining work. Install a new generation only after the old one is quiescent. |
| `suspended` | Deny access for abuse, support or an uncertain lifecycle outcome. Resumption requires operator review and fresh gates, and cannot extend an expired lease. |
| `closing` | Expiry, cancellation or completed evaluation permanently denies this lease. Revoke access, stop work and perform retention-aware cleanup. It cannot return to active. |
| `closed` | All live resources removed and remaining retained artifacts are explicitly inventoried with their deadlines. Do not claim complete erasure while backup/evidence copies remain. |

A hold or cleanup error leaves the operation in `resetting`/`closing` with an
explicit blocked reason, deadline and operator alert. It must not produce a
successful reset or deletion receipt. Retry resumes verified unfinished steps.
On recovery after an outage, expiry wins over a scheduled reset or reactivation.
Only a separately approved new lease may start another evaluation.

## Initial operating profile

These are versioned **proposed release limits**, not installed configuration,
measured capacity or a service commitment. Operators must validate the complete
fixture journey inside them before issuing invitations. Changes require a new
profile revision and recorded approval; the UI cannot request unlimited values.

| Limit | Initial profile | Enforcement required |
| --- | --- | --- |
| Invite validity | 24 hours from issue | Atomic invite acceptance checks the server deadline |
| Installation attempt | 15 minutes, including bounded retries | Installer-only authority; timeout denies admission and begins recovery/cleanup |
| Access lifetime | 72 hours from first successful activation; absolute, never extended by login or reset | Admission checks every request/login/refresh; workers check before every new unit of work |
| Automatic reset | Every 24 hours while the lease is active | Durable schedule, generation lock and recovery sweep; show the next reset time and a 15-minute warning |
| Admitted users | 5 verified people per organization | Durable identity/seat reservation, separate from browser-session quotas |
| Browser sessions | `max_concurrent_sessions=2` | Existing limit per actor within the tenant; not a five-user or tenant-total session limit |
| Protected API traffic | `api_requests_per_window=120`, 60-second global window | Existing per-process middleware plus a hosted aggregate admission budget; no distributed guarantee from current middleware alone |
| Ingestion | `max_connector_sync_rows_per_run=1000`; one active fixture ingestion job | Existing row cap applies to governed live sync; other fixture ingestion paths need explicit equivalent enforcement. Future durable concurrent-job admission is also required; existing byte/page/timeout limits can only be tightened |
| Workflow work | 2 active runs, at most 50 starts per generation, 120 seconds per runnable activity | Atomic reservations, bounded retries and normal workflow timeouts; waiting for a human consumes a run slot and cannot outlive the lease |
| Stored evaluation payloads | 256 MiB per generation, including staging and object versions | Reserve bytes before writes and reconcile actual storage; failed attempts remain charged until cleanup is verified |
| User-supplied sources | None | Only pinned synthetic fixtures and install-time allowlisted adapters; no uploads or arbitrary connector registration |
| External model/provider calls | None | Existing execution/egress gates stay disabled; no prospect-funded keys |

Deployment operations must also record finite API/worker concurrency, CPU,
memory, database connection and disk limits in the approved rendered profile.
No invitation is issued with missing resource limits or an unmeasured workload
that exceeds them. The existing managed Helm overlay is a starting point, not
that profile: its autoscaling and false evidence defaults cannot be interpreted
as validated sandbox isolation or quota enforcement.

Reservation keys include tenant, generation and operation ID. Duplicate delivery
must not double-charge or create extra work; an unknown outcome keeps its
reservation until reconciliation proves completion or safe release. Queues are
bounded, provide retryable busy responses, and preserve capacity for lifecycle
and support operations. A noisy evaluation must not starve expiry/cleanup or
another evaluation. Suspending a tenant does not by itself stop already-running
Temporal activities, downloads, streams or storage writes.

## Manufacturing installation and proof of real work

The sandbox installer consumes an approved immutable manufacturing-pack release;
it never copies a live customer's tenant or a mutable shared demo tenant. The
release must identify its source commit, format version, schema/migration
compatibility, checksums and expected counts/IDs for all required surfaces. It
must include synthetic-data provenance, allowed adapters/destinations, roles,
workflow definitions and a deterministic acceptance journey. This is the input
required from the future vertical-pack work, not a new generic pack format.

Installation order is: allocate isolated resources; register the target tenant;
apply quotas and narrowly scoped installation identity; validate the entire pack;
load tenant-bound fixture records through existing domain boundaries; register
and start the declared workflow through the existing workflow port; verify the
journey; remove installation privileges; then admit the approved users.

The existing bootstrap is reusable only for its reference-record step. It skips
missing non-overview surfaces, preserves existing target surfaces and returns a
stored marker on replay. The installer must therefore reject a missing or wrong
surface before admission, check the post-install digests/counts, and reject a
partially populated target with unknown provenance. A marker alone must not
mark a pack complete. Retrying an exact installation reuses its receipt; a
mismatched pack requires a new generation, never an in-place overwrite.

The acceptance journey must show synthetic supplier-delay inputs entering the
approved fixture path, a persisted risk/action proposal, a real approval
recorded through the governed API, a real Temporal workflow receiving that
decision, and linked persisted run/history/audit evidence visible in the console.
The outcome may be an explicitly labelled simulation with no external business
side effect. Reference timeline rows or an adapter's degraded/deferred result
cannot satisfy the real-workflow receipt. Installation records API release,
pack digest, generation, run ID and the evidence IDs from this execution.

The UI identifies synthetic data, current generation, expiry and next reset in
plain language. Loading and failure states stay API-backed. It must distinguish
seeded examples, current executed results and disabled capabilities, and show
reset progress or closure rather than stale success after a generation changes.
It clears queries, drafts, local selections and session context for the old
tenant. Users acknowledge that evaluation work is disposable before activation.

## Automatic reset and interrupted work

Reset replaces the evaluation generation; it is not a call to the current
bootstrap endpoint and not a deletion of audit history. Use one durable,
serialized lifecycle operation per sandbox, with an expected revision and a
monotonically increasing generation fence. Workload finalization must compare
its expected fence and deadline in the same serialized transaction as its domain
writes and audit evidence; an earlier admission check is insufficient. Commit
intent before external awaits, then reconcile/finalize without holding a database
transaction across the await. The orchestrator requires an old-runtime fence
receipt before activating a replacement; it cannot infer revocation from sending
a request or from an unavailable runtime:

1. Commit the reset intent and denial fence before external work. Suspend the
   old tenant through its governed lifecycle boundary; revoke its sessions,
   tenant role mappings and credential leases, and disable its schedules.
2. Reject old-generation prospect API calls, workload claims, callbacks, streams and result
   finalization. Scoped lifecycle/support operations remain authorized through their
   existing owners. Cancel/drain running work with a recorded timeout; isolate or
   terminate owned runtime resources if cooperative cancellation cannot prove
   quiescence. A timeout leaves access denied and raises an operator alert.
3. Inventory all stores and preserve required audit/hold evidence. A legal hold,
   unknown inventory or missing retention approval blocks destructive cleanup.
4. Allocate a fresh tenant and isolated resource set, install the same approved
   pack and verify the complete journey. Every step has an idempotent receipt;
   a worker restart reconciles that receipt before retrying a side effect.
5. Activate the new assignment only after the old generation is fenced and the
   new one passes readiness. Retain the original absolute access deadline and
   approved identities; require fresh authentication for the new tenant.
6. Remove old resources through the verified cleanup flow. Track that work and
   any retained artifacts independently; a successful new activation is not
   proof of old-data deletion.

At expiry the same denial/drain/cleanup path runs without creating a replacement.
The scheduler handles reconciliation, not the access deadline itself. Requests
and worker admission use server time and the durable lease, so a stopped
scheduler cannot prolong access. Long-lived work must be cancelled at the
lease deadline and recheck its fence before committing any result. No new work
is accepted while deadline, lease or generation state is uncertain.

## Audit, support and deletion

Prospect users receive only the tenant-scoped roles required by the journey.
Support begins with read-only, redacted diagnostics. Any elevated access is
approved, time-limited, bound to the sandbox/tenant/generation and recorded with
a case reference, verified support actor and reason. No impersonation through a
request-body actor or shared demo account is permitted. Lifecycle recovery uses
platform-operator authority and does not reactivate an expired evaluation.

Audit existing tenant provisioning/suspension, quota, identity, approval,
workflow and connector operations through their current owners. Future sandbox
events additionally record invite issue/accept/revoke, installation, expiry,
reset, cleanup and support access. Event metadata contains IDs, profile/pack
versions, reasons, counts, operation keys and digests; it excludes invite
secrets, credentials, raw source rows and unnecessary identity/contact data.
Denied lifecycle operations and partial failures also have observable evidence.

Before invitation, the operator must approve a retention profile and identify
its owner. The initial proposal deletes ordinary evaluation payloads within
24 hours of closure/reset, retains minimal restricted operational evidence for
30 days, and requires evaluation-only backups to expire within 30 days. These
are design targets, not current deletion behavior or legal guarantees. A hold
or an unresolved retention decision blocks deletion and must be reported with
the affected objects, owner and next review; it does not restore user access.

Cleanup inventories Postgres tenant/domain rows, reference records, sessions,
leases, object versions and multipart/staging uploads, TypeDB data if enabled,
Temporal histories/schedules, IdP mappings, exports, caches, telemetry and
backups. A dropped namespace, suspended tenant, deleted current object version
or revoked key is not a complete deletion receipt. Use existing audit retention
and legal-hold boundaries for ledger data; never truncate the ledger to reset
an evaluation. Preserve required evidence outside disposable resources before
removing them, with the original tenant binding, redaction and access controls.

Each store reports completion or an explicit retained/blocked result and expiry.
The final receipt records inventory version, generation, actor, operation ID,
counts, digests and verification times, not deleted payloads. A restored backup
must reapply closed-lease and generation tombstones before enabling traffic or
jobs. Deletion/crypto-erasure and backup guarantees need the actual future
pipeline and rehearsal; current `pending_deletion` or audit-retention support
does not provide them.

There is no automatic conversion to a paid tenant, movement of trial data into
production, billing event or source-code publication. A commercial deployment
is separately provisioned and approved. Self-serve invitations/trials remain a
separate product and abuse-control decision after the relevant billing and
operational foundations exist.

## Verification and release gate

Specification review checks the owner links above against code and reruns the
existing tenant, identity, bootstrap and edition/architecture contract tests.
`make docs-check` checks local links and the generated edition matrix. These
checks validate reuse assumptions and documentation, not hosted behavior.

Before the first invitation, record **PASS** for every case below on the exact
application SHA, rendered deployment profile, pack digest and runtime versions.
Keep separate API, browser, real-service and operational evidence. A skipped,
partial or simulated case cannot open the hosted gate.

| Required rehearsal | Observable acceptance evidence |
| --- | --- |
| Two independent evaluations | Each identity, API route, object credential, workflow/task queue and support role can access only its assigned resources; no production route or credential is present |
| Invite replay and races | One accepted identity/seat and assignment; expired/revoked/wrong-identity or changed-payload attempts denied and audited |
| Complete pack / real journey | All digests and surfaces match; real workflow run and approval/audit chain; missing/corrupt/deferred installation remains inaccessible |
| Quota pressure | Row/byte/job/user limits and finite queues hold under duplicate work, restart and multiple API instances; lifecycle work retains capacity |
| Expiry with scheduler unavailable | Bearer and cookie access, refresh, streams and worker starts cease at the deadline; late results cannot write into an active generation |
| Reset crash after each phase | One replacement generation; old sessions, retries and callbacks never regain authority; original lease deadline unchanged |
| Partial storage/IdP/Temporal outage | No success receipt or new admission until the recorded prerequisite is recovered; retries preserve audit/idempotency |
| Holds, cleanup and restore | Held objects retained with explicit status; all other stores verified; old versions/uploads/backups inventoried; restore cannot resurrect access |
| Support and UI | Least-privilege support audit, synthetic-data disclosure, warning/expiry/reset states, fresh login and cleared browser data |

**NOT RUN in this design slice:** hosted provisioning, invite delivery, live
sandbox identity isolation, expiry/reset orchestration, packaged manufacturing
workflow installation, hosted quota/abuse/load tests, support-access operations,
complete deletion/backup restore and independent operational/security review.
The future hosted capability remains blocked until those release gates pass.
