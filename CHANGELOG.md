# Changelog

This file records notable changes to Limes Axis. It describes shipped or
release-bound behavior, not the complete commit history.

## [Unreleased]

### Added

- Reproducible ingestion strategy benchmarks for REST, database, object and
  document fixtures, with peak memory, queue delay, bounded admission, tenant
  turn scheduling and checkpoint/replay checks. The experiments evaluate
  candidates locally; production scheduling and connector contracts retain
  their existing behavior ([#365](https://github.com/Limes-Labs/limes-axis/issues/365)).

- Opt-in S3/MinIO prefix ingestion through the existing governed source outbox:
  conditional bounded reads, cross-request hash checkpoints, absence observations,
  fenced atomic metadata commits and source-neutral discovery aliases. Migration
  0066 adds binding checkpoint state; API/worker runtime dependencies now include
  the repository Python SDK ([#335](https://github.com/Limes-Labs/limes-axis/issues/335)).

- Versioned SME/enterprise performance workloads, local load/soak and Python
  stack-profiling harnesses, query/pool/resource baseline evidence and a
  noise-aware regression policy. Real deployment SLOs and unimplemented search
  remain separate evidence ([#361](https://github.com/Limes-Labs/limes-axis/issues/361)).

- Seven-layer architecture contract with component/issue ownership, public port
  and backend adoption decisions, plus an offline guard against new core-to-vertical
  imports. Existing reference coupling remains explicitly inventoried
  ([#352](https://github.com/Limes-Labs/limes-axis/issues/352)).

- Opt-in connector event protocol 1.1 with scoped replay/ordering decisions,
  bounded signed webhook validation and a tested offline reference. Kafka/MQTT
  mappings define future host adoption; no event transport is enabled
  ([#340](https://github.com/Limes-Labs/limes-axis/issues/340)).

- Local files-only OSS candidate preparation with exact committed allowlists,
  capability/licence/content checks, reproducible provenance manifests and an
  explicit human release gate. Candidates remain private and publication-blocked
  ([#321](https://github.com/Limes-Labs/limes-axis/issues/321)).

- Hosted prospect sandbox specification: dedicated evaluation environments,
  authenticated time-limited access, generation replacement, synthetic workflow
  installation and retention-aware cleanup gates. This is a design contract;
  hosted invitations and reset are not enabled
  ([#322](https://github.com/Limes-Labs/limes-axis/issues/322)).

- MCP 2026-07-28 gateway design: audience-bound authorization, governed capability
  mappings, transport/resource budgets and a defensive threat model. This defines
  implementation gates without enabling an endpoint, tool or task runtime
  ([#367](https://github.com/Limes-Labs/limes-axis/issues/367)).

- Legacy API usage counters and deprecation/Sunset notices with a planned
  2027-01-01 removal subject to observed migration and maintainer review.
  `/demo/bootstrap` shares the existing governed demo handler; console and CI
  use the new path while all 103 legacy operations remain supported
  ([#357](https://github.com/Limes-Labs/limes-axis/issues/357)).

- Reusable connector conformance checks and reference fault fixtures in the
  authoring SDK, plus a metadata-only freshness/lag/checkpoint/error/retry health
  model. Preview/supported release criteria require adapter-specific and host
  evidence; no source is automatically certified or enabled
  ([#342](https://github.com/Limes-Labs/limes-axis/issues/342)).

- Connector authoring protocol 1.0 in the Python SDK: typed source, discovery,
  read, checkpoint, health and optional writeback contracts, explicit version
  negotiation and a bounded offline reference. The author guide maps adoption
  to existing host gates without enabling new sources
  ([#334](https://github.com/Limes-Labs/limes-axis/issues/334)).
- A repository-topology ADR makes the private repository the commercial source
  of truth and defines the fail-closed, fresh-history boundary for any future
  OSS edition ([#319](https://github.com/Limes-Labs/limes-axis/issues/319)).
- A machine-checked capability matrix assigns current and planned product scope
  to OSS, shared SDK, Hosted or Enterprise/private-cloud editions and blocks
  export on undecided entries
  ([#320](https://github.com/Limes-Labs/limes-axis/issues/320)).
- A compliance-readiness matrix records deployment-specific applicability,
  roles, control/evidence ownership and unresolved ISO/IEC 27001, GDPR, EU AI
  Act and NIS2 review boundaries
  ([#372](https://github.com/Limes-Labs/limes-axis/issues/372)).
- Repository governance baseline with code ownership, support and conduct
  policies, architecture decision records, bounded dependency updates and an
  automated documentation-path check ([#323](https://github.com/Limes-Labs/limes-axis/issues/323)).

### Changed

- The connector console loads a bounded, principal-scoped summary and selected
  details on demand. A local 60-connector browser fixture drops from seven
  initial requests/161,020 bytes to two requests/9,587 bytes; pagination, audit
  and identity invalidation retain explicit contracts. Existing registries and
  aliases remain supported
  ([#364](https://github.com/Limes-Labs/limes-axis/issues/364)).

- Model endpoint and invocation persistence now has an aggregate owner behind
  the existing repository methods, preserving caller-owned transactions and
  SQL behavior. Shared facade/aggregate contracts also run against PostgreSQL
  in CI ([#356](https://github.com/Limes-Labs/limes-axis/issues/356)).

- Model HTTP handlers now live in a domain router, with the existing application
  dependencies, authorization, tenant binding and audit behavior preserved.
  A generated route ownership map tracks the remaining composition-root work
  ([#355](https://github.com/Limes-Labs/limes-axis/issues/355)).

- The connector capability audit records the existing source families, runtime
  gates and gaps. Bounded Postgres extraction now uses its profile's statement
  timeout and returns a null watermark for tables without a single-column
  primary key, fixing two read-loop errors found by the audit
  ([#333](https://github.com/Limes-Labs/limes-axis/issues/333)).

- API settings are grouped into seven capabilities behind the existing flat
  environment facade, with a generated operator reference. Production startup
  now rejects non-positive rate limits and inconsistent enabled source-ingestion
  retry and extraction claim windows. Existing aliases, defaults and development
  behavior are preserved ([#358](https://github.com/Limes-Labs/limes-axis/issues/358)).

- Governed model invocations commit the requested record before calling the
  provider, so a provider timeout no longer occupies a database connection and
  the idempotency key survives an interrupted process. At most one provider
  call is now issued per tenant and idempotency key, including under concurrent
  duplicate delivery; a replay whose outcome is not yet recorded returns status
  `requested` with an explanatory note and is never re-invoked automatically
  ([#362](https://github.com/Limes-Labs/limes-axis/issues/362)).
- Container build, signing-provenance and SARIF upload actions use reviewed
  dependency updates; static contract checks retain the exact expected versions.

- Data-asset lineage batches promotion history reads while retaining tenant
  isolation, chronological output and the latest-50 limit per proposal.
- CSV preview detects duplicate headers in one pass with unchanged validation
  messages and ordering.
- Local development targets load the repository-root environment file; setup
  uses committed lockfiles and verification includes the public schema package.
- The data asset catalog read is bounded to the assets it returns instead of
  materializing every current stewardship row and grouping every observation
  row for the tenant. A new `(tenant_id, asset_id)` index on
  `data_asset_resource_observations` keeps the scoped count proportional to the
  requesting tenant's rows; without it the planner combined two single-column
  indexes and scanned index entries belonging to every other tenant. Responses
  are unchanged ([#363](https://github.com/Limes-Labs/limes-axis/issues/363)).

- Source extraction revalidates current lease/binding/egress evidence before
  source access, preserves actual dial/read facts through failures and retries
  temporary source/storage errors within the existing attempt budget. The bounded
  PostgreSQL reader now uses its profile timeout and supports a null watermark
  in the single-pass no-primary-key branch (connector standardization P2).

- The architecture overview now describes current runtime truth while delivery
  history lives in a separate changelog ([#359](https://github.com/Limes-Labs/limes-axis/issues/359)).
- The API compatibility suite is warning-clean and fails on new warnings
  ([#377](https://github.com/Limes-Labs/limes-axis/issues/377)).

## Changelog Policy

Every pull request that changes user-visible behavior, public schemas, security
posture, data migrations, deployment requirements or supported dependencies must
add an entry under `Unreleased`.

Pure tests, internal refactors and documentation corrections may omit an entry
when they do not change those contracts. The pull request must state why the
change is exempt. Architecture changes additionally require an ADR or an entry in
`docs/architecture-changelog.md`.

At release time, maintainers move the relevant `Unreleased` entries into a
versioned section with an ISO date. Entries describe outcomes and compatibility
impact; commit-by-commit chronology stays in Git history.
