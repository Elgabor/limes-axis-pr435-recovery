# Connector capability matrix

Audit baseline: `a02383c`, after PR #318 and its subsequent fixes. This matrix
describes shipped code, conditional runtime paths and remaining gaps. It does
not certify a deployment or enable a connector. The
[connector journey](platform-connectors.md) owns the detailed contracts;
[configuration](configuration-reference.md) owns the current API flags.

## Source families actually wired

| Live connector ID | Source | Implemented adapter boundary |
| --- | --- | --- |
| `file_csv_manufacturing_assets` | CSV in an allowlisted local dropzone | Header validation, bounded file batches, checkpoints and review-only proposals |
| `external_db_operational_mirror` | Postgres | Metadata preview, bounded verification/discovery, governed live-sync batches and activated-table extraction |

These are the two IDs dispatched by
[`SelfHostedConnectorLiveSyncRuntime`](../services/api/src/axis_api/connector_execution.py).
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
| Files | Conditional: bounded CSV dropzone reads and preview; no document parsing | Not a file-source adapter; raw extraction envelopes can be written to the governed object store | CSV: G0–G7. Object output: G0, G2–G7. S3-compatible export storage is not S3/MinIO ingestion. |
| Streams | Absent: batch file reader only | Absent: bounded pull reads only | Future webhook/queue/industrial-event ingestion must reuse G0–G7 and define backpressure, tenant fairness and event checkpoints. Temporal scheduling is not a stream source. |
| Writeback | No external source writeback | Read-only source sessions; no external source writeback | Governed Axis ontology promotion exists separately: G0, G1, G7 plus the existing approval/workflow/policy/idempotency boundary. It does not authorize writes to the source. |
| Retries | Conditional: failed-run resume from committed batches; duplicate completed execution replays | Same live-sync path; activated ingestion additionally has bounded jittered retries, fenced claims, dead-letter and governed requeue | G0–G7 for live sync; G0, G2–G7 for ingestion. No generic provider-specific retry adapter or cross-source delivery guarantee. |
| Observability | Metadata-only runs, checkpoints, claims, last successful sync and evidence views | Same, plus resource observations, binding eligibility, ingestion overview, attempt history and extraction-batch reconciliation | G0, G7 for reads; evidence originates in the gated write paths. Optional worker telemetry emits outcome counts. This is not a uniform connector-health/SLO contract. |

## Existing gates and owners

The paths share boundaries, but do not all execute the same sequence. In
particular, discovery and activated source ingestion use persisted lease,
policy and binding evidence; do not assume they independently re-run the
`active_live` manifest gate of the older live-sync route.

| Gate | Existing decision | Owner and evidence |
| --- | --- | --- |
| G0 — Principal and tenant | Production OIDC, authenticated tenant/actor binding, registered-tenant admission and operation scopes. Discovery uses `connectors:source:discover`; activation uses `connectors:source:activate`; ingestion writes/reads use `connectors:source:ingest` / `connectors:source:ingest:read`. | [HTTP binding](../services/api/src/axis_api/main.py), [tenant admission](../services/api/src/axis_api/tenant_admission.py), [source route tests](../services/api/tests/test_connector_postgres_discovery.py), [activation tests](../services/api/tests/test_connector_source_activation.py) |
| G1 — Manifest and run lifecycle | Registration is not activation. Governed live sync requires a persisted `active_live` manifest, explicit live policy/mode and a valid governed run; preview/configuration/promotion have their own existing lifecycle checks. | [Manifest lifecycle](../services/api/src/axis_api/connector_manifests.py), [run gates](../services/api/src/axis_api/connector_runs.py), [lifecycle tests](../services/api/tests/test_connector_manifests.py), [live-sync tests](../services/api/tests/test_connector_live_sync.py) |
| G2 — Credentials | Handles are references. Source operations resolve executed lease evidence server-side, bound to tenant/connector; material stays in memory. `env://` is the implemented live resolver. Static-DSN paths remain distinct. | [Lease boundary](../services/api/src/axis_api/connector_credential_leases.py), [resolver](../services/api/src/axis_api/connector_secret_resolution.py), [resolver tests](../services/api/tests/test_connector_lease_scoped_live_sync.py) |
| G3 — Egress and source profile | Persisted approved-private-endpoint policy and connection-profile binding. Discovery/live reads add dial-target hash matching when runtime enforcement is enabled. Activated extraction checks its static DSN against approved endpoint evidence. | [Egress policies](../services/api/src/axis_api/connector_egress_policies.py), [dial enforcement](../services/api/src/axis_api/connector_execution.py), [extraction](../services/api/src/axis_api/connector_source_extraction.py) |
| G4 — Schema and binding | CSV required columns/header fingerprint. DB schema allowlists and observations; activation validates selected fingerprints and persists bindings atomically. Ingestion pins binding fingerprints server-side and rejects stale selections. | [CSV preview](../services/api/src/axis_api/connectors.py), [discovery](../services/api/src/axis_api/connector_postgres_discovery.py), [activation](../services/api/src/axis_api/connector_source_activation.py), [ingestion](../services/api/src/axis_api/connector_source_ingestion.py) |
| G5 — Runtime, claims and replay | Default-off live/extraction gates, per-run idempotency, checkpoint ownership and committed batch resume. The ingestion outbox uses claim tokens, lease expiry, bounded retries and dead-letter; requeue preserves previous attempt evidence. | [Live-sync runner](../services/api/src/axis_api/connector_runs.py), [ingestion dispatcher](../services/api/src/axis_api/connector_source_ingestion.py), [worker composition](../services/worker/src/axis_worker/runtime.py), [worker workflow](../services/worker/src/axis_worker/workflows/connector_live_sync_workflows.py) |
| G6 — Bounded source access | CSV root/path and file/row/batch limits; DB read-only sessions, bounded profiles and queries. Extraction adds row/byte/page/time caps, explicit truncation and oversized-row refusal. | [Readers](../services/api/src/axis_api/connector_execution.py), [extraction reader](../services/api/src/axis_api/connector_source_extraction.py), [reader tests](../services/api/tests/test_connector_source_extraction.py) |
| G7 — Evidence and downstream use | Tenant-scoped metadata, append-only audit, redaction and read scopes. Live-sync records feed reviewable proposals. Extraction rows go into object-store envelopes; database/API evidence contains counts, digests and watermark presence. Approval-gated exports do not bypass source or graph permissions. | [Evidence invariants](../services/api/src/axis_api/connector_evidence_invariants.py), [batch exports](../services/api/src/axis_api/connector_source_batch_exports.py), [promotion](../services/api/src/axis_api/connector_ontology_promotions.py), [batch tests](../services/api/tests/test_connector_extraction_batches.py) |

### Runtime profiles are distinct

- CSV/Postgres live sync requires `AXIS_CONNECTOR_SYNC_EXECUTION_ENABLED` and
  `AXIS_CONNECTOR_LIVE_SYNC_EXECUTION_ENABLED`, a supported ID and its profile.
  The Postgres adapter also requires `AXIS_EXTERNAL_DB_SYNC_EXECUTION_ENABLED`,
  `AXIS_EXTERNAL_DB_LIVE_QUERY_PREFLIGHT_ENABLED` and
  `AXIS_EXTERNAL_DB_LIVE_QUERY_EXECUTION_ENABLED`.
- Discovery uses `AXIS_EXTERNAL_DB_DISCOVERY_ENABLED`. A configured DSN or
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

Remaining reusable gaps:

- No stable multi-source SDK/version negotiation or uniform health contract.
  The [SDK issue](https://github.com/Limes-Labs/limes-axis/issues/334) and
  [conformance issue](https://github.com/Limes-Labs/limes-axis/issues/342) own those extensions.
- Live-sync resume uses offsets, so source mutation can change the rows seen
  after a checkpoint. Keyset extraction restarts with no incoming watermark;
  recording a watermark does not yet implement incremental ingestion across requests.
- Extraction materializes a bounded envelope in memory. Page limits do not
  imply end-to-end streaming, tenant fairness or measured memory/backpressure guarantees.
- Provider-specific secret resolvers, document permission propagation, CDC,
  inbound object/event sources and external writeback remain separate work.
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
| S3/MinIO input | 3 — batch/object exchange | 2 — governed data-lake input | Reuse the object-store port but add actual listing, read, checkpoint and ingestion permission contracts in [#335](https://github.com/Limes-Labs/limes-axis/issues/335). |
| Generic REST pull | 4 — application integration | 4 — approved application endpoints | Needs bounded pagination, rate-limit/retry semantics and endpoint governance in [#336](https://github.com/Limes-Labs/limes-axis/issues/336). |
| Microsoft 365 / Google Workspace documents | 5 — after source ACL contract | 5 — after source ACL contract | Identity/permission propagation, revocation, deletion and document parsing precede grounded retrieval; [#338](https://github.com/Limes-Labs/limes-axis/issues/338). |
| Collaboration and engineering sources | 6 — reuse document/REST contracts | 6 — reuse document/REST contracts | Avoid a parallel auth and content pipeline; [#339](https://github.com/Limes-Labs/limes-axis/issues/339). |
| Webhooks, queues and industrial events | 7 — after batch conformance | 7 — pilot only after event contracts | Define ordering, acknowledgements, replay, backpressure and tenant fairness first; [#340](https://github.com/Limes-Labs/limes-axis/issues/340). |

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

Unit evidence uses temporary files, isolated SQLite and substituted source
drivers. It does not prove real Postgres source behavior, distributed claims,
Temporal service execution, object-store credentials or cloud-provider access.
The existing [Postgres source-ingestion integration lane](../services/api/tests/integration/test_connector_source_ingestion_runtime.py)
tests the durable validation lifecycle; it is not live extraction-loop evidence.
The [live-sync integration lane](../services/api/tests/integration/test_connector_scheduled_live_sync_runtime.py)
is separately gated. GitHub's general live API/browser lane also does not run
every connector-source integration test.

Record the revision, commands, actual PASS/FAIL counts and NOT RUN service lanes
in the PR. When a runtime changes, update its matrix cell, gate mapping and
evidence together; do not change a cell from conditional to supported based only
on a manifest flag or a green unrelated browser test.
