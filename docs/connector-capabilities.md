# Connector capability matrix

Audit baseline: `a02383c`, after PR #318 and its subsequent fixes. This matrix
describes shipped code, conditional runtime paths and remaining gaps. It does
not certify a deployment or enable a connector. The
[connector journey](platform-connectors.md) owns the detailed contracts;
[configuration](configuration-reference.md) owns the current API flags.

## Source families actually wired

| Connector ID | Source | Implemented adapter boundary |
| --- | --- | --- |
| `file_csv_manufacturing_assets` | CSV in an allowlisted local dropzone | Header validation, bounded file batches, checkpoints and review-only proposals |
| `external_db_operational_mirror` | Postgres | Versioned metadata discovery, bounded live-sync batches and durable activated-table extraction |
| `s3_object_storage` | S3 / MinIO approved bucket prefix | Opt-in protocol 1.0 discovery and bounded incremental object extraction through the ingestion outbox |

The CSV/Postgres IDs are dispatched by
[`SelfHostedConnectorLiveSyncRuntime`](../services/api/src/axis_api/connector_execution.py).
The [S3 host](s3-source-ingestion.md) uses the existing activated-source ingestion
outbox, with binding checkpoints and current manifest/lease/policy checks.
Tenant-scoped manifest registration can describe other sources, but does not
install an adapter or make a new ID executable. The persisted registry and
manifest lifecycle remain authoritative; there is no browser-local fallback.
The older seeded `sync_modes` describe the reference manifest, not a complete
list of subsequently implemented runtime paths.

## Capability matrix

**Implemented** means a concrete code path exists. **Conditional** means it also
requires the named gates, a configured profile and a supported source.
**Absent** means no source adapter/path is wired. Tests and live verification
are separate evidence levels, listed below. Gate IDs refer to the existing
boundaries in the next section; they are not new permissions or switches.

| Capability | Local CSV | Postgres | Gate chain and reusable gap |
| --- | --- | --- | --- |
| Discovery | Implemented: uploaded headers and schema fingerprint; no directory inventory | Conditional: connectivity and bounded base-table/column discovery; no row data or view enumeration | CSV: G0, G4, G7. DB: G0, G2, G3, G4, G6, G7. Truncation is explicit; observations do not prove completeness or deletion. |
| Auth | Axis identity, scopes and source-file restrictions; no remote source login | Executed/renewed lease evidence plus static DSN, or opt-in lease-scoped `env://` resolution for live read/discovery | G0, G1 where applicable, G2, G3. Vault/AWS/GCP/Azure secret material resolvers fail closed as not implemented. |
| Incremental sync | Conditional: resume a governed batch run by offset from its committed checkpoint | Conditional: offset-based live-sync resume; extraction has within-request PK keyset pages and a recorded watermark | Live sync: G0–G7. Extraction: G0, G2–G7. No general cross-run change-feed or incremental watermark-consumption contract; mutable-source offsets are not snapshot isolation. |
| CDC | Absent | Absent: no WAL/log-position consumer | Future source adapters must reuse G0–G7 and add durable source cursor/replay semantics. A sync checkpoint is not CDC. |
| Files | Conditional: bounded CSV dropzone reads and preview; no document parsing | Not a file-source adapter; raw extraction envelopes can be written to the governed object store | CSV: G0–G7. Object output: G0, G2–G7. The separately gated [S3 input](s3-source-ingestion.md) adds prefix listing, conditional object reads and cross-request hash checkpoints. |
| Streams | Absent: batch file reader only | Absent: bounded pull reads only | [Event protocol 1.1](connector-events.md) defines webhook/queue/industrial semantics and an offline reference; production ingress remains absent and requires G0–G7 adoption. Temporal scheduling is not a stream source. |
| Writeback | No external source writeback | Read-only source sessions; no external source writeback | Governed Axis ontology promotion exists separately: G0, G1, G7 plus the existing approval/workflow/policy/idempotency boundary. It does not authorize writes to the source. |
| Retries | Conditional: failed-run resume from committed batches; duplicate completed execution replays | Same live-sync path; activated ingestion additionally verifies committed raw batches before reuse, with bounded jittered retries, fenced claims, dead-letter and governed requeue | G0–G7 for live sync; G0, G2–G7 for ingestion. No generic provider-specific retry adapter or cross-source delivery guarantee. |
| Observability | Metadata-only runs, checkpoints, claims, last successful sync and evidence views | Same, plus resource observations, binding eligibility, ingestion overview, attempt history and extraction-batch reconciliation | G0, G7 for reads; evidence originates in the gated write paths. Optional worker telemetry emits outcome counts. The SDK now supplies a [shared health model](connector-conformance.md); production collection and source-specific SLO evidence remain separate. |

## Existing gates and owners

The paths share boundaries, but do not all execute the same sequence. In
particular, discovery and activated source ingestion use persisted lease,
policy and binding evidence. S3 operations also require a current `active_live`
manifest and active unexpired grants; the older Postgres discovery/extraction
path retains its existing contract.

| Gate | Existing decision | Owner and evidence |
| --- | --- | --- |
| G0 — Principal and tenant | Production OIDC, authenticated tenant/actor binding, registered-tenant admission and operation scopes. Discovery uses `connectors:source:discover`; activation uses `connectors:source:activate`; ingestion writes/reads use `connectors:source:ingest` / `connectors:source:ingest:read`. | [HTTP binding](../services/api/src/axis_api/main.py), [tenant admission](../services/api/src/axis_api/tenant_admission.py), [source route tests](../services/api/tests/test_connector_postgres_discovery.py), [activation tests](../services/api/tests/test_connector_source_activation.py) |
| G1 — Manifest and run lifecycle | Registration is not activation. Governed live sync requires a persisted `active_live` manifest, explicit live policy/mode and a valid governed run; preview/configuration/promotion have their own existing lifecycle checks. | [Manifest lifecycle](../services/api/src/axis_api/connector_manifests.py), [run gates](../services/api/src/axis_api/connector_runs.py), [lifecycle tests](../services/api/tests/test_connector_manifests.py), [live-sync tests](../services/api/tests/test_connector_live_sync.py) |
| G2 — Credentials | Handles are references. Source operations resolve executed lease evidence server-side, bound to tenant/connector; material stays in memory. `env://` is the implemented live resolver. Static-DSN paths remain distinct. | [Lease boundary](../services/api/src/axis_api/connector_credential_leases.py), [resolver](../services/api/src/axis_api/connector_secret_resolution.py), [resolver tests](../services/api/tests/test_connector_lease_scoped_live_sync.py) |
| G3 — Egress and source profile | Persisted approved-private-endpoint policy and connection-profile binding. Discovery/live reads add dial-target hash matching when runtime enforcement is enabled. Activated extraction checks its static DSN against approved endpoint evidence. | [Egress policies](../services/api/src/axis_api/connector_egress_policies.py), [dial enforcement](../services/api/src/axis_api/connector_execution.py), [extraction](../services/api/src/axis_api/connector_source_extraction.py) |
| G4 — Schema and binding | CSV required columns/header fingerprint. Postgres discovery fingerprints bounded names, types, nullability, primary-key membership, identity and generated modes. Activation validates the fingerprint version and replaces an active binding only through an explicit predecessor. Ingestion rejects stale selections before reading rows. | [CSV preview](../services/api/src/axis_api/connectors.py), [discovery](../services/api/src/axis_api/connector_postgres_discovery.py), [activation](../services/api/src/axis_api/connector_source_activation.py), [schema evidence](../services/api/src/axis_api/connector_source_schema.py), [ingestion](../services/api/src/axis_api/connector_source_ingestion.py) |
| G5 — Runtime, claims and replay | Default-off live/extraction gates, per-run idempotency and checkpoint ownership. PostgreSQL raw batches use content-addressed keys, commit under an unexpired claim and are verified before replay; a governed requeue creates a new snapshot generation. The S3 path retains its binding checkpoint CAS. | [Live-sync runner](../services/api/src/axis_api/connector_runs.py), [ingestion dispatcher](../services/api/src/axis_api/connector_source_ingestion.py), [worker composition](../services/worker/src/axis_worker/runtime.py), [worker workflow](../services/worker/src/axis_worker/workflows/connector_live_sync_workflows.py) |
| G6 — Bounded source access | CSV root/path and file/row/batch limits; DB read-only sessions, bounded profiles and queries. Extraction adds row/byte/page/time caps, explicit truncation and oversized-row refusal. | [Readers](../services/api/src/axis_api/connector_execution.py), [extraction reader](../services/api/src/axis_api/connector_source_extraction.py), [reader tests](../services/api/tests/test_connector_source_extraction.py) |
| G7 — Evidence and downstream use | Tenant-scoped metadata, append-only audit, redaction and read scopes. Live-sync records feed reviewable proposals. Extraction rows go only into object-store envelopes; database/API evidence contains counts, digests, storage references and watermark presence. Stored size and checksum must match before a raw batch is accepted or reused. Approval-gated exports do not bypass source or graph permissions. | [Evidence invariants](../services/api/src/axis_api/connector_evidence_invariants.py), [batch exports](../services/api/src/axis_api/connector_source_batch_exports.py), [promotion](../services/api/src/axis_api/connector_ontology_promotions.py), [batch tests](../services/api/tests/test_connector_extraction_batches.py) |

### Runtime profiles are distinct

- CSV/Postgres live sync requires `AXIS_CONNECTOR_SYNC_EXECUTION_ENABLED` and
  `AXIS_CONNECTOR_LIVE_SYNC_EXECUTION_ENABLED`, a supported ID and its profile.
  The Postgres adapter also requires `AXIS_EXTERNAL_DB_SYNC_EXECUTION_ENABLED`,
  `AXIS_EXTERNAL_DB_LIVE_QUERY_PREFLIGHT_ENABLED` and
  `AXIS_EXTERNAL_DB_LIVE_QUERY_EXECUTION_ENABLED`.
  Its legacy host contract is version `0.1`, produces reviewable proposals and
  rejects incompatible versions, modes, outputs and required extensions before
  source access. It does not claim CDC, writeback or durable offset resume. This
  path is separate from the authoring SDK protocol used by S3.
- Postgres discovery uses `AXIS_EXTERNAL_DB_DISCOVERY_ENABLED`. A configured DSN or
  lease resolver does not override scopes, lease evidence or egress policy.
- Lease-scoped material resolution and connect-time enforcement are separate
  opt-ins: `AXIS_EXTERNAL_DB_LEASE_SCOPED_SECRET_RESOLUTION_ENABLED` and
  `AXIS_EXTERNAL_DB_RUNTIME_EGRESS_ENFORCEMENT_ENABLED`. Their disabled fallback
  is not evidence that live Vault/KMS resolution or dial enforcement occurred.
- Activated-table extraction requires worker dispatch and extraction flags:
  `AXIS_SOURCE_INGESTION_DISPATCH_ENABLED` and
  `AXIS_SOURCE_INGESTION_EXTRACTION_ENABLED`. Validation-stage completion reads
  no source rows. The extraction reader currently uses the static configured
  DSN; the live-read/discovery lease resolver is not wired into that reader.
- `AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED` enables Temporal scheduling of
  existing governed runs. It is not a tenant-wide connector enablement service.
  Worker and API environments are configured separately.

## Audit findings and corrections

The audited baseline already includes PR #318's discovery → activation →
ingestion journey, batch evidence, reconciliation and console surfaces. This
issue does not implement them again or add a second source trust path.

The audit exercised the actual extraction read loop with a substituted database
driver. At baseline, both ordering modes failed because the reader accessed the
nonexistent `external_db_discovery_statement_timeout_seconds` setting. It now
uses the existing discovery profile's bounded statement timeout. After that
correction, the no-primary-key path exposed an uninitialized watermark; it now
returns `null`, preserving the documented no-resume contract. Regression cases
cover empty, complete and row-capped reads with and without a primary key.

## Postgres schema and durable raw extraction

Postgres discovery and extraction now share one bounded catalog query and the
`postgres_schema_v2` fingerprint. A complete fingerprint covers column order,
database type, nullability, primary-key membership, identity mode and generated
mode. A truncated discovery result cannot be activated. If the live table no
longer matches the active binding, extraction stops before reading row data. A
new binding can replace the old one only by naming its active predecessor; the
old binding remains as immutable history.

The dispatcher prepares trusted metadata in a short Axis transaction, closes
that transaction, then opens one read-only repeatable-read source snapshot per
selection. Each payload is written under a content-addressed key. Its metadata
and audit event commit together only while the worker claim is current and
unexpired. A retry verifies the stored checksum and size before reusing a
committed batch. Unknown legacy batch keys, conflicting metadata and corrupt
objects fail closed. An interrupted write can leave an unreferenced object for
reconciliation because the object store and Axis database cannot commit
atomically.

This is bounded snapshot extraction. It does not provide CDC, deletion capture,
cross-request snapshot consistency or incremental watermark consumption. Tables
without one primary-key column use one bounded pass and publish no watermark.
Raw rows remain in the object store; audit, request evidence and errors contain
metadata only.

Remaining reusable gaps:

- The [versioned authoring contract](connector-authoring.md) now defines source
  ports, negotiation and a typed health observation with an offline reference.
  CSV/Postgres retain their current ports; the S3 reader now explicitly adopts
  protocol 1.0 through the existing ingestion host. The [shared conformance suite and health model](connector-conformance.md)
  now provide offline fixture reports and operational metadata semantics; actual
  source/host adoption and release certification remain explicit evidence gates.
- Legacy live-sync resume uses offsets, so source mutation can change the rows seen
  after a checkpoint. Keyset extraction restarts with no incoming watermark;
  recording a watermark does not yet implement incremental ingestion across requests.
- Extraction materializes a bounded envelope in memory. Page limits do not
  imply end-to-end streaming, tenant fairness or measured memory/backpressure guarantees.
- Provider-specific secret resolvers, document permission propagation, CDC,
  event ingress and external writeback remain separate work. Bounded S3 object
  input is implemented as an opt-in path.
- Local reconciliation and batch-envelope retrieval do not certify every
  object-store adapter. An S3-configured reconciliation route returns an explicit
  unsupported-adapter error rather than constructing a cloud client.

## Proposed family priorities

This is engineering sequencing based on implemented boundaries and integration
gaps, not evidence of customer demand. Validate the order with SME and enterprise
users before committing a roadmap. “Next” rows are proposals, not shipped support.

| Family | SME priority | Enterprise priority | Reason and next ownership |
| --- | --- | --- | --- |
| CSV and Postgres | 1 — use and validate current paths | 1 — establish the governed reference | Existing adapters provide the reference for SDK and conformance work; keep runtime limits and operational evidence visible. |
| MySQL/MariaDB | 2 — next relational family | 3 — after reference conformance | Reuse discovery, lease and egress boundaries; define engine-specific checkpoint semantics in [#337](https://github.com/Limes-Labs/limes-axis/issues/337). |
| S3/MinIO input | 3 — batch/object exchange | 2 — governed data-lake input | Implemented as opt-in [governed object ingestion](s3-source-ingestion.md) in [#335](https://github.com/Limes-Labs/limes-axis/issues/335); production deployment certification remains separate. |
| Generic REST pull | 4 — application integration | 4 — approved application endpoints | Needs bounded pagination, rate-limit/retry semantics and endpoint governance in [#336](https://github.com/Limes-Labs/limes-axis/issues/336). |
| Microsoft 365 / Google Workspace documents | 5 — after source ACL contract | 5 — after source ACL contract | Identity/permission propagation, revocation, deletion and document parsing precede grounded retrieval; [#338](https://github.com/Limes-Labs/limes-axis/issues/338). |
| Collaboration and engineering sources | 6 — reuse document/REST contracts | 6 — reuse document/REST contracts | Avoid a parallel auth and content pipeline; [#339](https://github.com/Limes-Labs/limes-axis/issues/339). |
| Webhooks, queues and industrial events | 7 — after batch conformance | 7 — pilot only after event contracts | Contract and offline webhook reference defined; production adapters still require governed host adoption and wire/durability evidence; [#340](https://github.com/Limes-Labs/limes-axis/issues/340). |

## Verification and evidence levels

The following selectors identify executable evidence, not just a file claiming
coverage. `test_connector_capability_documentation.py` checks that referenced
test functions still exist and that the supported live IDs remain represented.

| Boundary | Focused test selector |
| --- | --- |
| Tenant and source scope | `services/api/tests/test_connector_postgres_discovery.py::test_discovery_route_rejects_cross_tenant_principal` |
| Lifecycle | `services/api/tests/test_connector_live_sync.py::test_execute_live_sync_requires_active_live_manifest` |
| Credential material | `services/api/tests/test_connector_lease_scoped_live_sync.py::test_execute_live_sync_resolves_env_secret_without_persisting_material` |
| Egress | `services/api/tests/test_connector_lease_scoped_live_sync.py::test_execute_live_sync_blocks_runtime_egress_mismatch_with_stage_audit` |
| Activation replay | `services/api/tests/test_connector_source_activation.py::test_identical_resubmission_replays_without_new_rows_or_audit` |
| Resume | `services/api/tests/test_connector_live_sync.py::test_execute_live_sync_resumes_from_last_committed_checkpoint` |
| Bounded source reader | `services/api/tests/test_connector_source_extraction.py::test_bounded_reader_uses_profile_timeout_and_reports_ordering` |
| Legacy contract negotiation | `services/api/tests/test_connector_live_sync_contract.py` |
| Versioned schema and replacement | `services/api/tests/test_connector_schema_versions.py` |
| Durable raw replay and fencing | `services/api/tests/test_connector_raw_durability.py` |
| Controlled CSV/Postgres proof | `services/api/tests/test_connector_csv_snapshot_proof.py`, `services/api/tests/test_connector_controlled_proof.py` |
| Retry/dead-letter | `services/api/tests/test_connector_source_ingestion.py::test_operational_failure_retries_then_dead_letters_when_exhausted` |
| Attempt history | `services/api/tests/test_connector_source_ingestion.py::test_completed_attempt_appends_metadata_only_timeline` |
| Source payload confinement | `services/api/tests/test_connector_source_extraction.py::test_raw_row_values_never_reach_views_audit_errors_or_evidence` |
| Graph promotion boundary | `services/api/tests/test_connector_ontology_promotions.py::test_connector_ontology_promotion_endpoint_requires_approved_manual_import` |
| Unsupported reconciliation | `services/api/tests/test_connector_extraction_batches.py::test_s3_configured_reconciliation_returns_409_without_client_construction` |
| Scheduled ownership | `services/worker/tests/test_connector_live_sync_workflow.py::test_activities_resume_claims_checkpoint_and_releases_on_completion` |
| Extraction flag composition | `services/worker/tests/test_source_ingestion_wiring.py::test_extraction_runtime_built_only_when_both_gates_open` |

Use `make test-api PYTEST_ARGS='tests/test_connector_source_extraction.py -q'`
for the reader regression and
`make test-worker PYTEST_ARGS='tests/test_source_ingestion_wiring.py -q'`
for worker composition.
Run other selectors inside their corresponding package, omitting the
`services/api/` or `services/worker/` prefix. Run `make docs-check` for local links.

The connector proof runner clears deployment `AXIS_*` variables and disables
`.env` loading. The default command is offline; the second command requires an
explicitly isolated PostgreSQL instance on the supplied loopback port:

```sh
cd services/api
uv run python scripts/verify_connector_standardization.py
uv run python scripts/verify_connector_standardization.py --postgres-port 62903
```

Unit evidence uses temporary files, isolated SQLite and substituted source
drivers. The controlled proof additionally covers a synthetic SELECT-only role,
schema drift, concurrent updates, timeout/retry, process interruption and claim
fencing on isolated PostgreSQL. It does not prove production credentials,
distributed execution, Temporal service behavior, cloud object-store operation,
power-loss durability or production load.
The existing [Postgres source-ingestion integration lane](../services/api/tests/integration/test_connector_source_ingestion_runtime.py)
tests the durable validation lifecycle; it is not live extraction-loop evidence.
The [live-sync integration lane](../services/api/tests/integration/test_connector_scheduled_live_sync_runtime.py)
is separately gated. GitHub's general live API/browser lane also does not run
every connector-source integration test.

Record the revision, commands, actual PASS/FAIL counts and NOT RUN service lanes
in the PR. When a runtime changes, update its matrix cell, gate mapping and
evidence together; do not change a cell from conditional to supported based only
on a manifest flag or a green unrelated browser test.
