# ADR 0015: Layered capability ownership and vertical dependency direction

- **Status:** Accepted
- **Date:** 2026-09-07
- **Owners:** @metaforismo
- **Related:** [Issue #352](https://github.com/Limes-Labs/limes-axis/issues/352), [layer contract](../layered-architecture.md)

## Context

Axis hosts many capabilities in one API/worker/console topology. The manufacturing
reference also supplies DTOs and readers used by shared core. Without explicit
owners and extension direction, new verticals could add sector dependencies to
core or duplicate identity, metadata, workflow and intelligence authorities.

## Decision

Assign seven capability owners: deployment, trust, data, operational model,
workflow, intelligence and experience. Every current service/package and every
issue in the dated open snapshot has one accountable owner and explicit dependent
layers. Service hosting and semantic capability ownership are distinct.

Record public ports with current/planned status, input/output, failures,
compatibility and source evidence. Keep existing governed ports and deployment
profiles. Retain TypeDB and Temporal adapters, defer OpenFGA pending migration
and scale evidence, select Postgres primitives for the first FTS implementation,
and keep the narrow Axis metadata contract over existing stores.

Verticals consume shared core contracts. New shared-core imports of reserved
vertical namespaces or historical manufacturing/reference modules are forbidden.
An AST guard records exact existing symbol/count debt, rejects growth and requires
stale exceptions to be removed. It does not automatically regenerate its budget.
Historical DTOs, IDs and routes remain compatible until reviewed extraction.

## Consequences

- Owners and dependency contracts are reviewable without a premature service split.
- CI detects missing service ownership, duplicate issue mapping, stale inventory
  and new Python core-to-vertical imports without importing runtime code.
- The layer map is neither an edition export policy nor a strict import DAG.
- Existing manufacturing coupling remains explicit debt; the static guard cannot
  certify semantic independence or sandbox arbitrary plugin code.
- New backend/pack adoption still needs implementation, versioning, tenant/failure
  tests and deployment evidence; this decision enables no runtime capability.

## Alternatives Considered

- **Map directories to layers or split seven services now:** misrepresents mixed
  composition roots and adds operational complexity without contract evidence.
- **Rewrite manufacturing names and payloads immediately:** risks callers,
  persisted IDs and public compatibility beyond an architecture-contract slice.
- **Permit every current or future reference import:** gives no enforceable
  direction for new sector support.
- **Adopt every external platform at once:** duplicates owners before workload,
  permission, migration and recovery evidence exists.

## Verification

The offline registry checker runs in docs-check/CI. Focused tests exercise ownership
coverage, port evidence, stale artifacts, relative/aliased/dynamic imports and
legacy-count growth/removal. The PR records live issue snapshot comparison,
full make verification and exact-head CI. Production pack installation, backend
adoption, legacy decoupling and deployment certification remain NOT RUN.

## Supersession

None. The current runtime architecture and prior port ADRs remain authoritative.
