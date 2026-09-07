# P1: internal contract for the existing live-sync readers

## Problem and scope

The two live-sync readers have real callers but no version/capability check before
source access. Their legacy `source_exhausted` flag also means that a configured
row cap was reached; it does not certify a complete dataset.

This document specifies the P1 implementation authorized on 7 September 2026.
The existing analysis and initial specification are preserved as historical input.
The baseline is `731427cf8a5ff4e55c7d0b086ddbcfed427e2625`; the only pre-existing
changes were the two untracked documents in this directory.

GitHub verification on 7 September found #333/#334 closed by merged PRs
[#406](https://github.com/Limes-Labs/limes-axis/pull/406) and
[#407](https://github.com/Limes-Labs/limes-axis/pull/407). PR #407 introduces SDK
authoring protocol 1.0 and an offline reference, explicitly excluding production
adapter adoption. [#410](https://github.com/Limes-Labs/limes-axis/pull/410) adds
offline conformance/health. Main was `84f1592f4b3bd381f2b481f2edcb8bb0f6533fe6`.
None of those changes were pulled or copied into this checkout. This contribution
addresses the remaining live-sync host integration; it does not reimplement the
SDK or claim to close #334. #352 is an architectural constraint: governance stays
in its existing owners and this work adds no sector-specific model.

## User stories and implementation decisions

1. A host can plan and read with explicitly compatible internal requirements;
   an incompatible version, mode, output shape or required extension fails before
   file inspection, credential resolution or a source connection.
2. An author can inspect the descriptor used by a real ready plan for CSV dropzone
   and PostgreSQL. Supported IDs, adapter names, profiles and effective plan limits
   remain the existing ones. An arbitrary registered manifest installs no reader.
3. A caller can distinguish legacy proposals from raw envelopes. Both live-sync
   readers produce only `legacy_proposals`; `raw_envelope` remains the separate
   source-extraction path, with no bridge or storage changes in P1.
4. A caller can retain bounded/unknown completion evidence. New internal batch
   metadata never upgrades a legacy boolean into verified source completion.
5. API and worker consumers retain the existing plan/read interfaces, state
   transitions, output mappings, proposal IDs and offset resume behavior.

Extend the existing Pydantic requests/results and `ConnectorLiveSyncRuntime`
implementation. Bind descriptors directly to the existing routing: no plugin
loader, second registry, SDK dependency or new connector implementation.

The host contract is `0.1`, independent of manifest versions and of the upstream
SDK's `1.0`. Compatibility is discrete: only explicitly supported exact versions
participate; no assumed minor or major compatibility. With one supported version,
intersection selects `0.1`. Unknown optional extension names are ignored; unknown
required ones fail closed. No extensions are implemented by these two readers.
Removal requires a documented replacement and a caller migration; never silently
reinterpret ongoing legacy offsets. No partner compatibility promise is made.

Only `snapshot_bounded` is executable. Descriptors explicitly exclude incremental,
CDC, source writeback, delete capture and verified durable resume. Offset resume
is a legacy position within a run, not a consistent snapshot or incremental cursor.
Plan limits continue to come from configured profiles and tenant quota handling.
The internal batch completion reason is `row_limit` at the profile cap,
`unknown_legacy` otherwise, or `failed` on failure. The legacy boolean remains
unchanged for existing consumers. No source exhaustion guarantee is inferred.

Existing API and worker request construction uses the explicit 0.1 default at
both plan and batch boundaries. Legacy injected test runtimes lacking new plan
metadata continue using the default internal requirements; they gain no descriptor or verified evidence implicitly.
Descriptors and completion metadata are internal, not added to REST models,
persisted IDs, checkpoint formats, database schema or manifest.version.

## Acceptance and test decisions

Use the user-approved seams: planner, real adapter `read_batch`, existing API and
worker callers. Tests use synthetic temporary CSV files, a substituted PostgreSQL
driver and SQLite; no external source connections. Work one red/green slice at a
time. Existing live-sync, lease/egress and worker fixtures provide regression coverage.

| ID | Acceptance evidence |
| --- | --- |
| A1 | Both ready plans carry the descriptor used to select the reader; unsupported IDs and modes fail before source access. |
| A2 | Both descriptors expose bounded snapshot/proposal output only, conservative capabilities and existing effective plan limits. |
| A3 | Incompatible version and required extension fail at both plan and read boundaries before source access; optional extensions do not enable capabilities. |
| A4 | Existing flag-off, tenant, permission, lease, egress and worker claim tests retain their outcomes. |
| A5 | Profile-cap, short/empty, failed and descriptor-less legacy results retain bounded/unknown evidence; legacy exhaustion never becomes verified. |
| A6 | Existing caller characterization passes, OpenAPI equals the baseline, no public schema/client/ID/manifest/database changes. |
| A7 | This guide documents the actual two readers, errors, compatibility, examples, core responsibilities and verification commands. |

## Exclusions and verification boundary

P2–P5, discovery/health/writeback implementations, upstream SDK backports, new
sources, mapping changes, storage, migrations, durable checkpoints, incremental
sync, CDC and package publication are excluded. The extraction defects in this
old checkout remain outside scope; PR #406's fixes are separate upstream work.
Tenant/permission/manifest/lease/egress/claim/audit owners and disabled flag defaults
remain unchanged. Synthetic tests cannot certify real sources, crash durability,
concurrent PostgreSQL claims or a deployment.

Independent Standards and Spec reviews compare all new work, including uncommitted
files, against the initial HEAD before the local commit. Verification results and
author examples will be recorded here after implementation.

## Author guide: two wired adapters

The production host is `SelfHostedConnectorLiveSyncRuntime` in
`services/api/src/axis_api/connector_execution.py`. Its binding table owns both the
immutable descriptor and the existing plan/read methods for each supported ID.
Adding a manifest does not add a binding. These are trusted in-process adapters;
this contract provides no sandbox for partner code.

| Reader / existing ID | Profile and limits | Output and resume |
| --- | --- | --- |
| CSV dropzone / `file_csv_manufacturing_assets` | `FileCsvLiveSyncProfile`: allowlisted local filename, suffix, byte cap, row cap and batch size | Existing mapping into proposals; bounded row offset within the same run; file may change between reads |
| PostgreSQL / `external_db_operational_mirror` | `ExternalPostgresLiveQueryProfile`: allowlisted schema/table/columns, read-only session, row cap; host batch size; existing lease and egress gates | Existing mapping into proposals ordered by configured node-ID column; offset is not CDC or an incremental watermark |

The ready plan returns `descriptor`, `contract_version`, `batch_size` and
`max_records`. Effective quota capping remains host-owned. Neither descriptor
advertises discovery, SDK health, raw extraction or durable checkpoint interfaces.
Those are different ports and are not implied by a shared source family name.

An internal author can construct the requirements without changing a manifest:

```python
from axis_api.connector_execution import ConnectorLiveSyncContractRequest

requirements = ConnectorLiveSyncContractRequest(
    versions=("0.1",),
    read_mode="snapshot_bounded",
    output_shape="legacy_proposals",
)
# Supply contract=requirements on the existing PlanRequest / BatchRequest.
# The normal API/worker builders already use these defaults.
```

For a runnable offline example, the conformance test's `source` fixture creates
both real runtimes and valid synthetic requests. CSV reads a temporary five-row
file; PostgreSQL executes its existing SQL-building/read path against
`SyntheticPostgres` at the driver boundary. Run from `services/api`:

```sh
uv run pytest tests/test_connector_live_sync_contract.py -q
```

No test needs a source DSN or credential value. The PostgreSQL test profile uses
an inert synthetic address and always substitutes the driver. Incompatible cases
replace source file checks, file opening, the driver and the resolver with failing
sentinels, proving refusal before access. Optional extensions may be ignored only
while the actual mode/output/version remain supported.

Stable refusal codes: `contract_version_unsupported`, `unsupported_mode`,
`unsupported_output_shape`, `required_extension_unsupported`, and the existing
`live_sync_unsupported_connector`. Existing profile/policy/source errors keep
their codes; driver exception text never becomes contract evidence. The deferred
runtime still performs no I/O and retains its existing status.

New internal batch fields are `output_shape=legacy_proposals`,
`completion_evidence=bounded_or_unknown` and `completion_reason`. Profile caps
produce `row_limit`; uncapped/short/empty legacy reads remain `unknown_legacy`.
Failed reads through the real host produce `failed`. The old `source_exhausted`
boolean is only a stop signal, even when true. No `verified`, full-dataset or
crash-durability assertion is produced or exported by this change.

Core responsibilities remain: tenant and principal binding, permission checks,
manifest lifecycle, credential lease validation, secret resolution, egress,
quotas, claim fencing, persistence, retry decisions, audit and graph promotion.
Adapters still have no repository/session or direct audit/checkpoint writer.

## Subsequent authorization

During P1 implementation Lorenzo additionally authorized P2–P5 and one local
commit per phase. This document and its acceptance criteria still describe only
P1; subsequent phase changes will be specified and committed separately.

## P1 verification record

- Red/green: two planner descriptor cases failed for missing metadata, then passed;
  twelve incompatibility cases reached forbidden source sentinels, then passed;
  nine completion cases failed for absent evidence fields, then passed.
- PASS: 35 P1 conformance cases; 100 combined contract/live-sync/lease-egress/
  execution cases. A later combined rerun including environmental failures passed
  110 cases; four Helm-dependent cases still fail because `helm` is unavailable.
- Full API suite executed: 1,870 passed, 38 integration-gated skipped, 13 failed
  and one error. The source driver was disabled and Python network calls refused.
  The failing cases were rerun against the baseline `connector_execution` module
  loaded from initial HEAD without changing the checkout: 11 also failed and three
  passed. The other discrepancies came from the offline harness raising a generic
  error and leaking rejected sockets. Closing those sockets and using connection-
  refused semantics made all ten non-Helm cases pass on rerun; only the four
  missing-Helm cases remain. This is not an unqualified green full-suite claim.
- PASS: worker suite 62 passed, three integration-gated skipped, using its own
  isolated environment and exact worker lockfile versions.
- PASS: full API/worker Ruff, OpenAPI equality, `git diff --check`, `make docs-check`
  (41 edition capabilities and 67 documents), security posture, deployment package,
  container image/release/security and vulnerability-management contract checks.
- NOT RUN: Helm rendering (binary absent), live provider/Temporal/cloud integration,
  PostgreSQL crash/claim tests in P1, Web and SDK suites (no code or contracts touched),
  container builds/scans and deployment rehearsals. Contract checks do not certify
  running infrastructure.
- PASS: independent Standards review (no hard violations or actionable smells)
  and Spec review (no missing/wrong P1 requirements); Spec reviewer independently
  reran all 35 P1 tests. No review correction was required.

`uv` was unavailable. Existing Python 3.12 and pip restored exact versions and
artifact hashes from each service's `uv.lock` into separate `/tmp` virtualenvs;
no lockfile or project dependency changed. Tests used a temporary runner that
suppressed automatic `.env` loading, removed inherited Axis settings, refused
network connects and replaced the default PostgreSQL dial with an unavailable
source. Individual driver fixtures still substitute their own synthetic results.

No changelog entry or ADR is needed for P1: this internal extension preserves
public schemas/behavior, dependencies, component ownership and trust boundaries
(the exemption in the repository changelog policy). P2 security/behavior changes
will have their own change record.

The two pre-existing documents retain SHA-256 digests:
`01645b108bd4c0bf04596c4db47f53af62a000a86b12a29dee07b2c2e1cd5528`
(analysis) and `7675aa8275c80c170673e48402c57703c7f1cecbc56daf3a72bd5ec379798e72`
(initial specification). They are excluded from this commit.
