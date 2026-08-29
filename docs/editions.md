# Axis Editions

This page defines how product capabilities are assigned to a future OSS
edition, Hosted Axis, Enterprise/private-cloud Axis or shared SDKs. It applies
to product scope; all current source still lives in the private commercial
repository described by
[ADR 0002](./adr/0002-commercial-source-and-oss-export-boundary.md).

The authoritative, machine-readable decisions live in
[`edition-capabilities.toml`](./edition-capabilities.toml). The human-readable
[capability matrix](./editions-matrix.md) is generated from that file and must
never be edited directly.

## Disposition Rules

| Disposition | Rule |
| --- | --- |
| `oss` | A useful single-tenant, self-hostable baseline with no required Limes-managed service. It teaches or enables the core workflow without exposing commercial operations. |
| `shared-sdk` | A narrow, versioned interoperability contract whose adoption benefits every edition and does not contain commercial policy, secrets or operating automation. |
| `hosted` | Limes operates shared infrastructure or fleet concerns: managed multi-tenancy, metering/billing, managed model or connector execution, sandboxes, upgrades or service operations. |
| `enterprise-private-cloud` | The capability is customer/dedicated-environment work: advanced identity, compliance operations, premium integrations, HA/DR/SLO engineering or supported vertical packs. |
| `undecided` | Product ownership or the safe boundary is unresolved. It is valid planning state but blocks every OSS export. |

Apply the rules in this order:

1. Preserve useful OSS user value: a candidate must complete a real local flow,
   not expose interfaces whose useful implementation remains commercial.
2. Keep managed operational burden Hosted: fleet scheduling, shared tenancy,
   abuse controls, billing, upgrades and service-level operations stay with the
   operator that performs them.
3. Keep customer-specific compliance and deployment work Enterprise/private
   cloud: code alone cannot supply organizational approvals, legal decisions,
   production evidence or contractual commitments.
4. Separate multi-tenant control-plane behavior from single-tenant product
   behavior. Do not weaken tenant, authorization, audit, credential, egress or
   execution gates to make an OSS baseline smaller.
5. Share stable contracts when openness improves interoperability. Do not label
   an internal storage model or commercial orchestration surface as an SDK.
6. Prefer defensible operations and maintained packs over artificial source
   withholding. A feature belongs commercially because Limes owns material
   operating, assurance or integration responsibility, not because a file is
   difficult to split.

## Inventory Model

The matrix classifies atomic capability IDs, not top-level directories. Current
areas such as `apps/web`, `services/api` and `infra/helm/limes-axis` contain
multiple dispositions and are not export units. Issue
[#321](https://github.com/Limes-Labs/limes-axis/issues/321) must translate the
approved IDs into a path allowlist and fail closed when a mixed area has not
been separated safely.

The inventory covers:

- the web console, control API and worker services;
- JSON Schemas, OpenAPI and the Python SDK;
- current CSV/manual and self-hosted Postgres connector baselines, plus planned
  generic and premium connector families;
- Docker Compose, generic Kubernetes assets and commercial deployment profiles;
- current governance, ontology, workflow, audit, model, agent, tenancy and
  operations capabilities;
- planned Search, Documents, embeddings, Assistant, Scenarios, vertical,
  onboarding, sandbox, organization and managed-service capabilities.

## Review And Export Gate

The product owner (`@metaforismo` at this baseline) reviews the matrix quarterly,
before each commercial or OSS release, and whenever a capability changes user
value, operational responsibility, compliance scope, tenancy model or shared
contract. Security and legal owners review affected disclosure/provenance
boundaries; code owners review implementation evidence.

Run:

```bash
make edition-matrix-check
make edition-export-readiness
```

The first command validates schema, evidence paths, full repository-area
coverage and generated documentation. The second additionally fails when any
entry is `undecided`. A passing matrix is necessary but not sufficient for
publication: #321 must still prove a clean allowlisted export, provenance,
secret/proprietary scans, reproducibility and human approval.

Every matrix PR records the changed capability IDs, rationale, reviewer roles
and remaining `NOT RUN` boundaries. Git history is the decision log; silent
file moves do not change product disposition.

## Current Boundaries

- `undecided`: none at this review. Adding one is allowed for honest planning
  but immediately makes `make edition-export-readiness` fail.
- `NOT RUN`: no OSS tree, export manifest or fresh-history repository has been
  generated.
- `NOT RUN`: no legal, licence/provenance or independent security approval has
  been performed.
- No disposition is a promise of an OSS release date, support level, price or
  cross-edition compatibility beyond the contracts in ADR 0002.
