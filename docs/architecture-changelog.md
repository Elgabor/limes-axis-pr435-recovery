# Limes Axis Architecture Changelog

This changelog preserves architectural delivery history and the reasons behind
the current shape. It is not the source of truth for current runtime behavior;
use [the architecture overview](./architecture.md) and the linked platform
contracts for that.

## Recording an Architecture Change

Add an entry only when component ownership, a data flow, a trust boundary or a
runtime dependency changes. Each entry should include:

- date and pull request or issue;
- affected boundary;
- decision and reason;
- migration or compatibility consequences;
- current-document and test evidence updated by the change.

Small implementation increments that do not alter architecture belong in the
normal release changelog or pull request, not here.

## 2026-08-29 — Separate Current Truth from Delivery History

**Issue:** [#359](https://github.com/Limes-Labs/limes-axis/issues/359)

The original architecture page had grown by appending each connector, identity
and governance increment to the current runtime description. That preserved
useful evidence but made the implemented component and data-flow shape difficult
to scan.

The current-state overview now owns only component relationships, data ownership,
trust boundaries, owner modules and contract tests. This changelog owns delivery
sequence and rationale. Existing detailed platform guides remain the source for
endpoint- and capability-level contracts.

An alternative split into one ADR per existing boundary was rejected for this
migration: it would scatter the baseline history across many files before those
decisions had independent lifecycles. New decisions may still use dedicated ADRs
when one decision needs a longer rationale or has meaningful alternatives.

### Measured Effect

- The current-state overview decreased from 368 to 152 lines.
- The previous 189-line runtime narrative was replaced by one component/data-flow
  diagram, three governed flow descriptions and a ten-boundary ownership table.
- Three focused documentation contract tests now verify local evidence links and
  the pull-request architecture-drift check.

## Pre-split Delivery History

The following sequence was migrated from the original architecture document. It
records how the current boundaries emerged; statements here may have been
superseded by later entries.

### Foundation and Data Ownership

- The repository began as a unified, self-hostable product with extractable
  boundaries for the console, API, worker, schemas and deployment assets.
- Postgres became the operational store for transactional state and append-only
  audit evidence. TypeDB remained behind Axis ontology query and mutation ports.
- Search stayed on Postgres behind an adapter until a separate engine could be
  justified by measured need.
- Temporal became the first workflow implementation while application code kept
  an Axis-owned workflow port.

### Model Routing

- Model routing was introduced as provider-agnostic and default-deny for external
  egress.
- Public read models first exposed route posture and synthetic cost evidence.
- Provider adapters, persisted invocation records and runtime telemetry were added
  behind the same policy and audit boundary rather than exposed directly to API
  callers.

### Connector Runtime

- Initial connectors provided file/CSV validation and metadata-only external
  database previews without SQL execution, stored credentials or graph mutation.
- Manifest registration and connector configuration were separated from runs.
  Public inputs rejected connection strings, raw queries and credential material.
- Credential handles then represented external secret references. Lease request,
  renewal and revocation added Vault/KMS adapter evidence without returning secret
  values.
- Governed dry runs and scheduled plans reused connector run records. Dispatch,
  execution and scheduling became separate permissioned transitions with
  idempotency and append-only audit events.
- The self-hosted demo executor was introduced behind an explicit gate. External
  database execution remained metadata- or count-only and required a persisted
  egress policy, active lease evidence and a worker checkpoint claim.
- Preflight evidence became bound to the exact connector, run, checkpoint, claim
  and worker. Registry read models exposed missing, mismatched or unsafe evidence
  without revealing secret references, DSNs or row payloads.
- Aggregate invariant reports and immutable snapshots composed checkpoint, claim,
  lease and egress evidence into public-safe review artifacts. Approval-gated
  exports added checksums, hash-chain proofs and an object-storage materialization
  boundary.
- Source ingestion was split into validation and bounded read-only extraction.
  Raw rows moved exclusively to deterministic tenant-scoped object-store keys;
  Postgres retained metadata, digests, watermarks and provenance.
- Batch evidence, attempt timelines, cross-request overviews and read-only
  reconciliation made the two-store boundary inspectable. Metadata-only batch
  exports reused the approval, checksum and idempotency gates.

### Connector Ontology Governance

- Connector previews first produced persisted ontology proposals with explicit
  `not_applied` graph status.
- Manual import requests and decisions added approval and workflow evidence while
  keeping mutation disabled.
- Controlled promotions introduced a TypeDB mutation adapter behind scope,
  approval, idempotency and audit checks.
- Promotion policies and versioned policy sets added authoring, enablement,
  activation, replacement and rollback transitions. Rejections became durable
  evidence rather than unrecorded validation failures.

### Identity and Tenant Binding

- The API adopted OIDC-first bearer validation with configurable issuer,
  audience, algorithms and JWKS, using Keycloak as the local self-hosted path.
- Public-safe readiness and onboarding reports exposed posture and exact redirect
  requirements without tokens, secrets or raw JWKS material.
- A session read model became the console source of truth for actor, tenant,
  scopes and expiry. Tenant-aware reads were made fail-closed during identity or
  transport transitions.
- Authorization-code login added PKCE, signed state and an HTTP-only Axis session
  cookie. Only API-owned session metadata was persisted; logout revoked that
  record and cleared the cookie.
- The local browser bearer bridge remained for developer and demo workflows, but
  display identity moved to the API-validated session model.

### Permissions, Replay and Delivery

- RBAC, ABAC and relationship-aware checks were applied before governed actions
  and approvals. Authenticated mutation paths bound actor and tenant from the
  verified principal.
- Approval decisions became single-assignment per tenant and approval ID.
  Semantic retries returned the original result; conflicting retries failed
  without repeating audit, workflow or action side effects.
- PostgreSQL advisory locks serialized first-use approval decisions across API
  replicas.
- A transactional approval outbox was added as an opt-in path for crash-atomic
  workflow delivery while preserving the synchronous compatibility path during
  rollout.

### Repository Extraction Rule

The monorepo remained deliberate. Extraction was reserved for boundaries where
at least two pressures become material: divergent release cadence, ownership,
enterprise-only secrets, customer-specific integrations, independent SDK
versioning, connector scale, Cloud-specific operations or separate docs/community
needs.
