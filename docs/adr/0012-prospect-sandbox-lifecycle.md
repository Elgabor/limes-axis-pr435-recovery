# ADR 0012: Dedicated prospect evaluations with generation replacement

- **Status:** Accepted
- **Date:** 2026-09-07
- **Owners:** @metaforismo
- **Related:** [Issue #322](https://github.com/Limes-Labs/limes-axis/issues/322),
  [prospect sandbox contract](../prospect-sandboxes.md),
  [edition boundary](0002-commercial-source-and-oss-export-boundary.md)

## Context

Axis has authenticated tenant lifecycle operations, limited tenant quotas,
persisted manufacturing reference data and governed workflow ports. It does not
have hosted invitation leases, automatic reset, a released vertical-pack
installer or a complete tenant deletion pipeline. An auth-optional local demo
and a copied reference workflow cannot establish hosted evaluation readiness.

Prospects need to try a real governed workflow with synthetic data, while the
operator needs bounded access, resource consumption and cleanup. A reset must
not erase audit history or allow stale sessions/jobs to write into a fresh run.

## Decision

Keep the capability Planned / Hosted and specify the release gate before
provisioning any prospect environment. Begin with a dedicated evaluation
deployment per prospect organization, isolated from production, with explicit
database, object-store, workflow, identity, network and resource ownership.
Reuse the current API/domain authorization, worker orchestration, credential,
egress and audit boundaries; do not expose a second trust path for invites.

The control API owns a durable sandbox lease and its immutable generation/tenant
assignments. Existing tenant status remains a separate admission condition.
The worker owns durable lifecycle orchestration through Temporal, and deployment
operations owns inventory-backed allocation/removal. Lease and retained evidence
records survive disposable deployment resources under platform-operator access.

Require verified identity, registered-only admission, finite quotas and a pinned
synthetic manufacturing pack. Its installation receipt must prove a real
workflow/approval/audit journey, independently of seeded reference views. The
existing bootstrap can supply reference records but is neither a complete pack
installer nor a reset API.

Reset fences and suspends the old generation, revokes access and drains work,
then installs a new tenant/resource generation. Activation requires fresh proof
and retains the original absolute lease deadline. Access and worker admission
check expiry independently of the scheduler. Retention-aware cleanup has its own
receipts; a successful reset is not proof that all old copies have been erased.

Initial invite, lifetime, reset and workload budgets, support authority, failure
states and required rehearsals are defined in the linked contract. These are
proposed operating limits to validate, not current configuration or a hosted
service commitment. Self-serve trials, billing, production-data migration and
OSS publication remain separate decisions.

## Consequences

- More resource cost than sharing one evaluation deployment, in exchange for a
  smaller initial failure and cleanup boundary and explicit per-prospect limits.
- New lease/generation fencing and complete pack/deletion orchestration are
  prerequisites; current tenant suspension and maintenance jobs are insufficient.
- Reset discards ordinary evaluation work and requires fresh authentication;
  the UI must disclose synthetic data, deadlines, reset progress and outcomes.
- Failed or held cleanup stays visible and denied, with a named operational
  owner. It cannot be disguised as a completed deletion.
- This decision changes the planned Hosted contract only. Runtime routes,
  schemas, local demo behavior and the existing OSS export boundary are unchanged.

## Alternatives Considered

- **Expose the auth-optional local demo:** lacks verified prospect identity and
  lifecycle/resource isolation; rejected for hosted use.
- **Use browser-only mocked workflows:** cannot demonstrate the governed API,
  durable workflow or audit path; rejected as execution evidence.
- **Share one tenant across prospects:** couples identity, evidence and reset
  state; rejected. Shared evaluation infrastructure with separate tenants may
  be reconsidered after distributed quota/isolation and cleanup evidence exists.
- **Re-run bootstrap in place:** preserves existing data and replays its marker;
  does not reset jobs, sessions, object versions or workflow history.
- **Delete all tenant rows during reset:** bypasses store ownership, active work,
  retention and legal holds; rejected.

## Verification

Review the contract against the current owning modules; run existing tenant,
bootstrap, identity and documentation/edition checks and the repository CI.
The contract's hosted release matrix remains mandatory future evidence.

**NOT RUN:** hosted deployment, real invite/lease/reset operation, packaged
manufacturing workflow installation, hosted isolation/load/support rehearsals,
complete deletion/backup restore and independent operational/security review.
Acceptance of this design does not mark the hosted capability implemented.

## Supersession

None.
