# Architecture Decision Records

ADRs record durable decisions that change component ownership, data flow, trust
boundaries, runtime dependencies or repository-wide engineering policy. Current
runtime truth remains in [the architecture overview](../architecture.md); delivery
sequence remains in [the architecture changelog](../architecture-changelog.md).

## Workflow

1. Copy [`0000-template.md`](./0000-template.md).
2. Use the next four-digit number and a short kebab-case title.
3. Open the ADR in `Proposed` state with the implementation pull request.
4. Record concrete alternatives, consequences and verification evidence.
5. Change the state to `Accepted`, `Rejected` or `Superseded` during review.
6. Never rewrite an accepted decision to hide history; supersede it with a new
   ADR and link both records.

## Records

- [`0001-repository-governance-baseline.md`](./0001-repository-governance-baseline.md) — Accepted
- [`0002-commercial-source-and-oss-export-boundary.md`](./0002-commercial-source-and-oss-export-boundary.md) — Accepted
- [`0003-external-await-transaction-boundary.md`](./0003-external-await-transaction-boundary.md) — Proposed
