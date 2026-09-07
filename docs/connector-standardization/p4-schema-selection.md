# P4: versioned source schemas and governed binding replacement

Base: P3 `cb947f6`. Qualify the existing raw PostgreSQL consumer; raw payloads
remain separate from legacy graph proposals. No sector mapping is required.

New PostgreSQL discovery uses `postgres_schema_v2`: ordered column names, exact
PostgreSQL types (including type modifiers), nullability, primary-key membership,
identity and generated-column mode. Legacy `column_names_v1` hashes keep their
original meaning and detect name/order changes only. Discovery and extraction
share the versioned fingerprint function. A bounded/incomplete schema cannot be
activated. Unknown versions fail closed before source access.

Each raw read compares the selected schema with the actual catalog inside the
same read-only repeatable-read transaction before fetching source rows. Drift
records dial=true/read=false and requires discovery and a new governed selection.

Activation gains an optional `supersedes_binding_id`. Replacement must name the
currently active predecessor for the same tenant/connector/resource, use a new
binding ID, pin the current observation fingerprint and version, and pass the
existing authenticated activation scope and current lease/egress checks. All
selections validate before any predecessor is retired. One transaction supersedes
old bindings, creates replacements and records the relationship in audit. Exact
replays do not write again; conflicting predecessors fail closed. Old requests
retain their pins and fail on inactive bindings; a new ingestion request is needed.

Migration 0067 adds fingerprint-version columns with legacy defaults, the optional
predecessor ID and the `superseded` binding status. Existing IDs/fingerprints and raw
history are preserved. Downgrade refuses when superseded history exists rather
than silently discarding it. Additive public schemas are regenerated.

Acceptance: live name/type/key drift; wrong/unknown version; governed replacement,
idempotence, stale selection/predecessor/tenant refusal and multi-selection atomicity;
real PostgreSQL migration preserving historical rows. No graph or source writes.

## Verification and operator path (2026-09-07)

The console preserves the discovery schema version and sends it with the reviewed
fingerprint. Its optional “Existing binding to replace” field names the active
predecessor; incomplete schemas cannot be selected. The API preserves the old row
and links the new binding in the same audit transaction. Repeat discovery after
source drift, review the schema, replace the old binding and submit a new ingestion
request. Existing requests are not silently retargeted.

- 15 schema/replacement boundary tests passed, including v2 type/key/name drift,
  unknown version pre-dial, stale/wrong predecessor/version/scope and batch atomicity.
- 70 discovery/activation/observation tests passed. The broad connector pass had
  722 passes and 9 isolated-PG skips; six older test doubles still intercepted the
  pre-P3 method signature. Those seams were updated and their entire 26-test file
  passed, including the original crash/requeue/classification scenarios.
- 9 real PostgreSQL tests passed: full migration chain through 0065 with preserved
  legacy binding, safe downgrade/re-upgrade and refusal to lose superseded history,
  plus the eight P3 durability/claim/process-interruption scenarios.
- 136 targeted console/contract tests, TypeScript typecheck, focused ESLint, Ruff,
  docs-check and both independent review axes passed after the console correction.
- The TypeScript lockfile was restored unchanged with the already available pnpm
  10.6.1; lifecycle install scripts were disabled. No dependencies were added.

Legacy v1 checks only ordered names; v2 checks the declared PostgreSQL metadata
above. Neither version certifies business meaning, mapping approval, cross-table
consistency, default expressions or upstream deletion propagation. P5 performs the
controlled live-source proof; these limits remain explicit.
