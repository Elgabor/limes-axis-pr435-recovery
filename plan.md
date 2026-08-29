# Limes Axis Public Plan

Last updated: 2026-07-11

## Summary

Limes Axis is the sovereign AI control plane for European operations.

The private commercial source can run locally or in controlled infrastructure
and supports managed cloud, dedicated enterprise and on-prem deployment paths.
A future OSS edition may be released through a deliberate, capability-limited,
fresh-history export.

Axis is designed to integrate first and replace gradually: existing systems stay
in place while Axis becomes the governed layer where data, workflows, people,
permissions and AI agents operate together.

## Product Principles

- Sovereignty must be practical: self-hosted deployments must not require
  managed services.
- AI agents must be governed, permissioned, observable and auditable.
- Human approval remains central for risky actions.
- Operational ontology is the core context layer.
- Workflow execution must be durable and inspectable.
- A future OSS edition and commercial operations should reinforce each other
  through explicit shared contracts, not automatic repository synchronization.
- The initial repository is unified, but future extraction into modules/repos is
  expected when parts grow large enough.

## Public Architecture Direction

Axis will use:

- Python + TypeScript as the two-language rule.
- Next.js + React for the governance console.
- FastAPI for the core API.
- REST/OpenAPI for public and internal contracts.
- Postgres for operational and transactional data.
- TypeDB for operational ontology and relationship-aware reasoning.
- Temporal OSS as the initial self-hosted workflow runtime behind an adapter.
- OIDC-first identity, with self-hosted Keycloak support.
- RBAC, ABAC and relationship-aware permissions.
- Append-only audit ledger.
- Provider-agnostic model routing with no external data egress by default.
- Docker Compose for local development and Kubernetes/Helm for production paths.

## Milestone Roadmap

### Foundation

- [x] Create the initial monorepo structure.
- [x] Add Python/FastAPI service foundation.
- [x] Add Next.js governance console foundation.
- [x] Add local Docker Compose runtime.
- [x] Add Postgres, TypeDB and Temporal local services.
- [x] Define tenant, actor, audit, action and workflow schemas.
- [x] Define the operational ontology primitives.
- [x] Define the Workflow Runtime Port and Temporal adapter.
- [x] Define the typed action registry.
- [x] Define the L0-L4 agent autonomy model.
- [x] Add OIDC/Keycloak identity boundary.
- [x] Add initial test, lint and CI commands.
- [x] Add repository issue, PR and security policy templates.
- [x] Generate and check the OpenAPI contract.
- [x] Add API readiness checks and console API status.
- [x] Add opt-in Postgres, TypeDB and Temporal integration tests.
- [x] Add Playwright smoke tests to the web CI gate.

Foundation acceptance is tracked in
[`docs/foundation-acceptance.md`](./docs/foundation-acceptance.md).

### Platform

- [x] Build the governance console overview.
- [x] Build the ontology explorer.
- [x] Build the workflow console.
- [x] Build the agent registry.
- [x] Build the action registry UI.
- [x] Build the approval inbox.
- [x] Build the audit explorer.
- [x] Build the model routing and cost observability layer.
- [x] Add the Postgres persistence foundation for approvals, actions and audit events.
- [x] Add API-backed approval decisions with audit writes.
- [x] Connect the approval console to persisted decision submission without local
  decision fallback.
- [x] Enforce demo approval decision permissions before persistence.
- [x] Signal approval decisions through the workflow runtime adapter.
- [x] Reconcile persisted workflow run state and timeline history when approval
  decisions are recorded.
- [x] Transition or create linked action-run evidence when approval decisions
  are recorded, with idempotent approval gate records.
- [x] Persist typed action run requests with idempotency enforcement.
- [x] Signal workflow runtime from typed action payloads behind policy.
- [x] Append persisted workflow timeline evidence when action runs are recorded
  against known workflow runs.
- [x] Record governed action-run outcomes with audit evidence, idempotency and
  workflow completion timeline updates.
- [x] Add scheduled/periodic background maintenance jobs on Temporal Schedules in
  the worker (audit retention deletion sweep, orphaned/expired session sweep and
  tenant-state reconciliation), reusing existing persistence/service functions,
  with idempotent create-or-update schedule registration behind a master enable
  flag, and deploy the worker via Docker Compose and Helm.
- [x] Add OTel-first observability: OpenTelemetry distributed tracing and metrics
  for the API and worker (FastAPI request spans plus manual spans around action
  runs, approvals, connector sync, audit export and scheduled jobs), W3C
  trace-context propagation across the API-to-worker signal boundary, tenant/actor
  span attributes with audit-grade privacy (no tokens, secrets or client IPs), an
  OTLP/HTTP exporter and a deployment-readiness observability posture — all behind
  a master enable flag that is off by default.
- [x] Bind approval/action mutation endpoints to OIDC-derived actor identity
  and scopes.
- [x] Enforce relationship-derived ontology scopes on entity detail reads and
  action payload resource references.
- [x] Route ontology graph reads through a permission-aware query adapter with
  optional TypeDB read boundary.
- [x] Normalize TypeDB read answers and map structured ontology document rows
  into the public graph response shape.
- [x] Enforce OIDC-derived relationship scopes at the ontology graph/entity
  read boundary for the persisted-reference and TypeDB query runtimes, and
  append audit evidence for denied ontology reads.
- [x] Add relationship ownership, evidence, confidence, validity and
  verification metadata to ontology API responses and TypeDB graph primitives.
- [x] Add a governance console OIDC session bridge for bearer-token API calls.
- [x] Add a public-safe OIDC readiness report and `/ready` identity summary for
  enterprise SSO posture checks.
- [x] Add an OIDC authorization-code PKCE callback and HTTP-only API session
  cookie boundary for browser SSO.
- [x] Validate OIDC authorization-code callback `id_token` signatures, expiry,
  client audience, authorized party, nonce and cross-token subject binding
  before creating browser SSO sessions.
- [x] Add a persistent OIDC browser-session store, logout endpoint and
  server-side session revocation audit evidence.
- [x] Add production OIDC session lifecycle: server-side refresh-token rotation
  with encrypted-at-rest refresh credentials, idle/absolute session timeouts,
  concurrent-session caps, tenant-isolated session listing and revocation
  endpoints, `__Host-` Secure cookie posture and CSRF protection for
  cookie-authenticated session mutations.
- [x] Capture per-session device metadata (bounded user agent, client IP under
  an explicit trusted-proxy flag, derived device label) at login and refresh
  rotation, expose it through the owner/admin session listing only, keep it
  out of audit payloads, and cursor-paginate `GET /identity/sessions`.
- [x] Query persisted audit events from the audit explorer.
- [x] Add demo audit export manifests, retention enforcement and integrity proof.
- [x] Add self-hosted KMS-style ledger signature proof for audit export bundles.
- [x] Add permission-gated physical audit retention deletion with dry-run,
  legal-hold blocking and redacted deletion evidence.
- [x] Add persisted audit legal hold activation/release workflow that blocks
  matching retention deletion candidates.
- [x] Bind persisted audit read/export/retention/legal-hold endpoints to
  OIDC-derived tenant, actor and scopes when authenticated or required.
- [x] Add the tenant-scoped platform policy engine foundation with typed rule
  conditions, append-only idempotent revisions, deterministic evaluation and
  policy-gated action run enforcement.
- [x] Add the read-and-evaluate platform policy console surface with registry
  filters, revision history and a dry-run evaluation panel.
- [x] Add console platform policy authoring: a validated create form with an
  advisory preview evaluation, an idempotent revise form surfacing 200
  replays versus 201 creations, and a revision compare view.
- [x] Persist workflow run state and tenant-scoped history views.
- [x] Build replay and simulation foundations.
- [x] Persist replay simulation outputs as governed audit artifacts.
- [x] Add retention-aware replay windows for simulation responses.
- [x] Add connector manifest foundation and file/CSV preview.
- [x] Add metadata-only external database connector preview.
- [x] Add tenant-scoped persisted connector manifest records.
- [x] Add governed connector manifest lifecycle transitions for preview states.
- [x] Add governed connector manifest live enablement with scope, policy and
      evidence gates.
- [x] Add tenant-scoped connector configuration persistence.
- [x] Require active preview connector manifests before tenant configuration writes.
- [x] Require active preview connector manifests before credential handle creation.
- [x] Require active preview connector manifests before credential lease requests.
- [x] Require active preview connector manifests before connector run creation.
- [x] Require active preview connector manifests before manual import requests.
- [x] Require active preview connector manifests before ontology proposal creation.
- [x] Require active preview connector manifests before ontology promotion execution.
- [x] Persist connector ontology proposals without graph mutation.
- [x] Activate and harden the live TypeDB graph promotion path behind
  `AXIS_ONTOLOGY_MUTATIONS_ENABLED`: idempotent `put` TypeQL keyed on
  `axis_id`, atomic write transaction, mandatory read-back verification,
  fail-closed unavailable/failed statuses, schema bootstrap tooling and a
  governed connector-console promote action.
- [x] Record manual connector import requests behind approval, workflow and
  idempotency gates.
- [x] Add Vault/KMS credential lease records with renew/revoke evidence.
- [x] Add optional self-hosted Vault/KMS lease runtime adapter.
- [x] Add provider-specific Vault/KMS credential lease profiles and policy
  hardening without secret material retrieval.
- [x] Add credential lease registry read audit and audit-ledger evidence invariants.
- [x] Author connector promotion policies before required enforcement.
- [x] Enforce enabled required connector promotion policies before ontology
  mutation execution.
- [x] Add connector console policy authoring controls with API persistence only.
- [x] Add connector promotion policy enablement workflow with audit evidence.
- [x] Add versioned connector promotion policy sets for multi-policy required gates.
- [x] Add governed connector promotion policy set replacement and rollback evidence.
- [x] Add atomic adoption of approved draft policy revisions during policy-set replacement.
- [x] Add deferred scheduled connector sync planning from run records.
- [x] Add idempotent deferred dispatch claims for scheduled connector sync.
- [x] Add scheduled connector sync execution boundary with opt-in self-hosted runtime.
- [x] Add Postgres external DB sync adapter boundary with public-safe profile evidence.
- [x] Add external DB live-query preflight policy evidence without live query execution.
- [x] Add credential lease evidence hardening for external DB live-query preflight.
- [x] Add egress policy evidence hardening for external DB live-query preflight.
- [x] Add secret reference resolver evidence hardening for external DB live-query preflight.
- [x] Persist tenant-scoped egress policy records for external DB preflight.
- [x] Add egress policy registry read audit and audit-ledger evidence invariants.
- [x] Persist tenant-scoped sync execution checkpoints for scheduled connector runs.
- [x] Expose tenant-scoped sync execution checkpoints through the connector API.
- [x] Show tenant-scoped sync execution checkpoints in the connector console.
- [x] Require `connectors:sync:checkpoint:read` for checkpoint API reads.
- [x] Add `created_before` pagination filter for checkpoint API reads.
- [x] Add `created_after` time-window filter for checkpoint API reads.
- [x] Reject invalid checkpoint time windows before checkpoint storage reads.
- [x] Write append-only audit evidence for valid checkpoint API reads.
- [x] Report public-safe checkpoint evidence invariants on checkpoint API reads.
- [x] Persist worker-safe sync checkpoint claims without starting live sync.
- [x] Add worker-safe sync checkpoint claim renewal and release.
- [x] Reject competing active worker claims for the same sync checkpoint.
- [x] Expire stale worker claims before replacement sync checkpoint ownership.
- [x] Expose worker checkpoint claim registry with read scope and audit evidence.
- [x] Filter worker checkpoint claim registry by connector and run.
- [x] Paginate worker checkpoint claim registry with opaque cursors.
- [x] Filter worker checkpoint claim registry by claiming worker.
- [x] Filter worker checkpoint claim registry by created time window.
- [x] Report public-safe checkpoint claim evidence invariants on claim registry reads.
- [x] Expose aggregate connector evidence invariant reports across checkpoints,
      claims, credential leases and egress policies.
- [x] Materialize aggregate connector evidence invariant snapshots as
      append-only audit artifacts.
- [x] Expose aggregate connector evidence invariant snapshot history from
      append-only audit artifacts.
- [x] Show aggregate connector evidence invariant snapshot history in the
      connector console from the API-backed history endpoint.
- [x] Add a governed connector console action that creates aggregate evidence
      snapshots through the API-backed snapshot endpoint.
- [x] Link connector evidence snapshot artifacts to their audit ledger event
      detail in the audit explorer.
- [x] Add signed/public-safe connector evidence snapshot export bundles with
      manifest checksum and hash-chain proof.
- [x] Add governed connector evidence snapshot export requests with approval,
      workflow and idempotency evidence before WORM/object-store retention.
- [x] Add governed connector evidence snapshot export request decisions with
      approval decision persistence, workflow signal evidence and audit trail.
- [x] Materialize approved connector evidence snapshot exports to a configured
      local object-store adapter with checksum, storage URI and audit evidence
      before enterprise WORM/S3 retention.
- [x] Require an active worker checkpoint claim before external DB live-query
  preflight can enter the provider-specific runtime boundary.
- [x] Allow external DB live-query preflight execution to target an explicit
  worker checkpoint claim.
- [x] Add opt-in governed external DB live-read execution against an
      allowlisted Postgres profile, persisting only public-safe counts and
      checkpoint evidence.
- [x] Show worker checkpoint claim registry in the connector console.
- [x] Make the connector console API-required instead of using local fallback data.
- [x] Make the remaining web consoles API-required instead of using local fallback data.
- [x] Remove non-connector browser-runtime seed records and guard against
  reintroduction.
- [x] Remove connector browser-runtime seed records and guard against
  reintroduction.
- [x] Persist the manufacturing overview reference as a tenant-scoped bootstrap
  record.
- [x] Persist the manufacturing workflow console reference as a tenant-scoped
  bootstrap record.
- [x] Remove the workflow console runtime seed factory from the API module.
- [x] Persist the manufacturing connector registry reference as a
  tenant-scoped bootstrap record.
- [x] Remove the connector registry runtime seed factory from the API module.
- [x] Use the persisted connector registry reference for manual import request
  creation.
- [x] Use the persisted connector registry reference for promotion policy
  authoring, enablement and revision.
- [x] Use the persisted connector registry reference for promotion policy set
  activation, replacement and rollback.
- [x] Use the persisted connector registry reference for file/CSV and external
  DB preview.
- [x] Persist the manufacturing agent registry reference as a tenant-scoped
  bootstrap record.
- [x] Remove the agent registry runtime seed factory from the API module.
- [x] Persist the manufacturing action registry reference as a tenant-scoped
  bootstrap record.
- [x] Remove the action registry runtime seed factory from the API module.
- [x] Persist the manufacturing approval inbox reference as a tenant-scoped
  bootstrap record.
- [x] Remove the approval inbox runtime seed factory from the API module.
- [x] Persist the manufacturing audit explorer reference as a tenant-scoped
  bootstrap record.
- [x] Remove the audit explorer runtime seed factory from the API module.
- [x] Persist the manufacturing model routing reference as a tenant-scoped
  bootstrap record.
- [x] Remove the model routing runtime seed factory from the API module.
- [x] Persist the manufacturing ontology graph and entity detail reference as a
  tenant-scoped bootstrap record.
- [x] Remove the ontology graph/detail runtime seed factory from the API module.
- [x] Add a module-level guard against reintroducing manufacturing runtime
  reference factories in the API module.
- [x] Add tenant-scoped manufacturing operation records with a persisted read
  API for production, supply, quality and maintenance reference data.
- [x] Add an audit-backed daily plant brief generated from persisted operation
  records with idempotency and permission checks.
- [x] Add an audit-backed quality risk scenario generated from persisted
  Quality operation records with idempotency and permission checks.
- [x] Add an audit-backed maintenance risk scenario generated from persisted
  Maintenance operation records with idempotency and permission checks.
- [x] Add an audit-backed supplier delay scenario generated from persisted
  Supply operation records with idempotency and permission checks.
- [x] Add a read-only manufacturing operations snapshot that composes persisted
  operation records, generated artifacts, workflows, approvals and audit evidence.
- [x] Make the governance overview compose the persisted manufacturing
  operations snapshot in the browser console.
- [x] Add a live demo readiness check for the manufacturing operations
  snapshot contract.
- [x] Add an API-backed demo readiness report for SME feedback and enterprise
  evaluation walkthroughs.
- [x] Allow the local Next.js demo console to hydrate from `127.0.0.1` for
  in-app Browser and local feedback sessions.
- [x] Allow the API CORS contract to support the `3100` origins used by
  production-build Playwright demo checks.
- [x] Apply the public Axis brand palette to the console shell and verify it in
  unit, Playwright and in-app Browser checks.
- [x] Harden the operations console responsive layout so laptop-width
  enterprise demos keep KPI cards readable and move the side rail below the
  primary workflow surface before content is compressed.
- [x] Split production-build browser checks into deterministic offline and live
  E2E scripts.
- [x] Add an API-backed platform notification center derived from persisted
  operations, workflow, approval and audit state.
- [x] Persist platform notification read/ack state per tenant actor, enforce
  `notifications:acknowledge` and write append-only audit evidence.
- [x] Add an API-validated identity session read model for the console account
  surface, without returning token material or trusting browser-only claims.
- [x] Add an API-backed Operations artifact walkthrough that generates daily
  briefs and risk scenarios from the browser only when an API-verified OIDC
  actor has the required scopes, then refreshes persisted snapshot evidence.
- [x] Bind Operations artifact mutation endpoints to OIDC actors/scopes when
  authenticated, rejecting actor or tenant impersonation before permission
  evaluation.
- [x] Add a guided local Keycloak/browser SSO setup so design partners can run
  Operations artifact walkthroughs without manual bearer-token handling.
- [x] Add an API-backed Settings/Readiness console for identity, deployment,
  support diagnostics and runtime dependency posture, without browser-local
  fallback settings records.
- [x] Guard all API-owned reference endpoints beyond overview, workflow
  console, approval inbox, audit explorer, model routing, ontology,
  connector registry, agent registry and action registry with persisted,
  tenant-scoped bootstrap records.
- [x] Add repeatable demo environment runbook and automated readiness checks.
- [x] Add initial security review and threat model documentation with automated
  security posture checks.
- [x] Add a public-safe deployment readiness posture report with explicit
  production blockers.
- [x] Add a public-safe support diagnostics bundle and support operations
  runbook baseline.
- [x] Add initial Helm charts and production deployment guide baseline.
- [x] Add buildable API and web container image baseline.
- [x] Add container release provenance, signing and SBOM workflow baseline.
- [x] Add release promotion evidence and rollback drill gate for container
  publication.
- [x] Add a GitHub Environment reviewer hook for governed container publish
  runs without blocking build-only tag checks.
- [x] Add container vulnerability scanning policy baseline.
- [x] Add vulnerability management baseline with SARIF and expiring exceptions.
- [ ] Build the full connector framework beyond preview-only manifests.
  (In progress: governed live sync, scheduled live sync, lease-scoped secret
  resolution, runtime egress enforcement and the live TypeDB graph promotion
  path are now activated and hardened behind explicit flags, and every
  connector read/write route binds the OIDC principal tenant; remaining work
  is broader connector coverage and per-tenant enablement.)
- [x] Add governed live connector sync execution for the file/CSV dropzone and
  allowlisted external Postgres sources behind explicit flags, `active_live`
  manifests, lease/egress evidence, committed batch checkpoints, fail-closed
  error taxonomy, claim-gated resume and proposal-only output.
- [x] Add lease-scoped secret resolution and runtime egress enforcement for
  external DB live paths behind
  `AXIS_EXTERNAL_DB_LEASE_SCOPED_SECRET_RESOLUTION_ENABLED` and
  `AXIS_EXTERNAL_DB_RUNTIME_EGRESS_ENFORCEMENT_ENABLED`, keeping the resolver
  reference-only and binding the runtime target to persisted egress policy
  evidence.
- [x] Add scheduled governed live sync behind
  `AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED` with a bounded interval,
  tenant scoping and the same fail-closed gate chain as operator-triggered
  live sync.
- [x] Enforce principal tenant binding on the connector read and write routes
  and add the canonical table-driven tenant-isolation matrix
  (`services/api/tests/test_tenant_isolation.py`) covering reads, listings,
  mutations and token/path tenant mismatches across the API surface.
- [x] Add the model router execution slice: tenant-scoped
  `/platform/models/endpoints` registration with hosting boundaries and
  supported provider types, governed `/platform/models/invocations` with
  metadata-only persisted records, usage metering and audit evidence, behind
  `AXIS_MODEL_ROUTING_EXECUTION_ENABLED` (off by default) with external
  egress separately gated.
- [x] Add governed agent run execution: `POST/GET
  /demo/manufacturing/agents/{agent_id}/runs` with dry-run and propose modes,
  persisted append-only step timelines, autonomy ceilings, platform policy
  enforcement, model-routed proposal parsing that fails closed, and
  approval-gated action run creation, behind
  `AXIS_AGENT_RUN_EXECUTION_ENABLED` (off by default).
- [x] Support arbitrary policy-set comparison over historical replay windows
  behind `AXIS_REPLAY_ARBITRARY_POLICY_SET_DIFF_ENABLED`.
- [x] Redesign the core console pages with the shared brand primitives,
  light/dark theming and the ontology graph view.
- [x] Make `packages/schemas` a real contract package: JSON Schema (draft
  2020-12) files for action definitions, tenants, audit ledger events,
  connector manifests, model endpoints and agent runs, ajv-backed lint/test
  scripts wired into CI, and an API-side contract test
  (`test_schemas_package_contract.py`) that validates real domain payloads
  against the published schemas.
- [x] Add the compose-based manufacturing plant walkthrough example
  (`examples/manufacturing-plant`) covering stack bring-up, console tour,
  flag-gated model routing with a local Ollama endpoint, a governed agent
  dry-run, the SDK quickstart and teardown.
- [x] Add the security review checklist (`docs/security-review-checklist.md`)
  and the secret rotation and incident response runbooks under
  `docs/runbooks/`.
- [ ] Build the manufacturing operations reference demo.
  (In progress: the persisted cockpit, governed artifacts, walkthrough example
  and flag-gated model/agent execution exist; remaining work is broader live
  workflow execution and connector-backed production actions.)
- [ ] Add sustained production HA validation under customer-profile load, TLS
  certificate automation, backup/restore and cluster operations hardening.
- [x] Add optional External Secrets Operator chart integration for runtime
  secret synchronization.
- [x] Add optional Kubernetes Ingress/TLS chart routing for the API and web
  console.
- [x] Add optional cert-manager ingress-shim annotation support for Kubernetes
  TLS certificate requests.
- [x] Add Kubernetes TLS readiness rehearsal runbook and script for Ingress,
  TLS Secret, cert-manager Certificate, DNS, TLS handshake and HTTPS
  reachability checks.
- [x] Add optional Kubernetes HorizontalPodAutoscaler and PodDisruptionBudget
  chart controls for API and web workloads.
- [x] Add optional Kubernetes scheduling and topology-spread controls for API
  and web workloads.
- [x] Add configurable Kubernetes rollout strategy, revision history,
  termination grace and lifecycle hook controls for API and web workloads.
- [x] Add Kubernetes rollout rehearsal runbook and script for Helm upgrade,
  deployment rollout status, API readiness and rollback mechanics.
- [x] Add Kubernetes HA restart rehearsal runbook and script for sequential
  API/web workload restarts, availability waits, optional HPA/PDB checks and
  Helm smoke tests.
- [x] Add Kubernetes bounded load rehearsal runbook and script with Fortio Jobs
  for API/web smoke-load targets.
- [x] Add Helm smoke tests for in-cluster API readiness and web service checks.
- [x] Add a Kubernetes production Postgres backup rehearsal with restore-catalog
  validation and public-safe evidence capture.
- [x] Add a Kubernetes isolated Postgres restore rehearsal with checksum,
  restore-catalog validation and public-safe evidence capture.
- [x] Add a Kubernetes TypeDB recovery rehearsal with `database export`,
  `database import`, checksum evidence and an isolated restore-target gate.
- [x] Add S3/MinIO-compatible object-store adapter readiness with explicit WORM
  retention gates for governed connector evidence exports.
- [x] Add a bounded Kubernetes object storage recovery rehearsal with MinIO
  Client copy, restore-target isolation and checksum evidence.
- [x] Add a bounded Kubernetes Temporal recovery rehearsal with Temporal CLI
  namespace/history evidence capture and checksum evidence.
- [x] Add a Kubernetes Secret rotation rehearsal with active/staged Secret
  comparison, redacted key-status evidence and SHA-256 fingerprints without raw
  secret output.
- [x] Add the typed Python SDK foundation (`limes-axis-sdk`, module
  `axis_sdk`) for the governed REST surface, with sync/async clients, typed
  error envelope mapping, idempotent-only retries and in-process end-to-end
  tests against the API application.

The browser governance console no longer ships local overview fallback records.
Visible records must come from Axis API responses or persisted tenant state. The
manufacturing overview endpoint now reads a tenant-scoped
`demo_reference_records` bootstrap row and returns explicit API errors when the
record is missing or invalid. The connector registry endpoint follows the same
pattern with `surface=connectors` and
`reference_id=manufacturing-connector-registry`. The agent registry endpoint
also reads from `surface=agents` and
`reference_id=manufacturing-agent-registry`; the API module no longer defines
an agent registry runtime seed factory. The action registry endpoint reads from
`surface=actions` and `reference_id=manufacturing-action-registry`; action run
requests validate their action definitions against that same persisted record
instead of a runtime seed factory and derive ontology resource relationship
scopes from `surface=ontology/reference_id=manufacturing-ontology` before
writing action/audit state.
The workflow console reference endpoint reads from `surface=workflows` and
`reference_id=manufacturing-workflow-console`, while
`/demo/manufacturing/workflows/runs` continues to query operational workflow run
state and tenant-scoped timeline events. The API module no longer defines a
workflow console runtime seed factory; tests validate the Alembic bootstrap
payload directly. The approval inbox endpoint reads from
`surface=approvals` and `reference_id=manufacturing-approval-inbox`; approval
decision submissions validate approval ids, workflow ids and required
permissions against that same persisted record before writing approval, audit
or workflow-signal evidence. The API module no longer defines an approval
inbox runtime seed factory; tests validate the Alembic bootstrap payload
directly. The audit explorer reference endpoint reads from
`surface=audit` and `reference_id=manufacturing-audit-explorer`; the separate
audit events and export endpoints continue to query persisted `audit_events`.
The API module no longer defines an audit explorer runtime seed factory; tests
validate the Alembic bootstrap payload directly.
The model routing reference endpoint reads from `surface=model-routing` and
`reference_id=manufacturing-model-routing`; live provider routing, usage
metering and billing adapters remain separate Platform work. The API module no
longer defines a model routing runtime seed factory; tests validate the Alembic
bootstrap payload directly.
The ontology graph and entity detail endpoints read from `surface=ontology` and
`reference_id=manufacturing-ontology`; the query runtime now applies metadata
and relationship-scope filtering to that persisted graph instead of loading a
route-owned seed. The API module no longer defines ontology graph/detail
runtime seed factories; tests validate the Alembic bootstrap payload directly.
The API test suite also includes a consolidated reference-surface guard that
fails if a listed reference endpoint loses its Alembic bootstrap record or if
the API reintroduces a `get_manufacturing_*` runtime reference factory.
Approval decisions now transition linked action-run evidence or create an
idempotent approval gate record in Postgres. Action runs can also record
governed dry-run/execution outcomes with audit evidence and workflow completion
timeline updates. The full manufacturing reference demo remains open until
broader live workflow execution and replay paths are backed by real persistence.
The local demo environment now has a repeatable runbook and automated readiness
check in `docs/demo-readiness.md` and
`services/api/scripts/check_demo_environment.py`. The check validates the demo
Makefile targets, local self-hosted runtime services, critical OpenAPI routes,
documentation links, optional live API/web endpoints, browser no-store CORS for
dev and production-build demo origins, the persisted manufacturing operations
snapshot contract, the demo readiness report contract and the Axis console
brand shell. It is a demo readiness gate, not a production enterprise readiness
claim.
The Kubernetes deployment baseline now lives in `infra/helm/limes-axis`, with
`docs/deployment.md` and `services/api/scripts/check_deployment_package.py`
guarding chart files, externalized runtime configuration, rollout controls,
public-safe docs, the `deployment-check` Make target, cert-manager
ingress-shim annotations, Helm smoke tests and a rollout rehearsal script for
upgrade, readiness, backup capture, isolated Postgres restore and rollback
mechanics plus TypeDB export/import into an isolated target, bounded
object-storage recovery into an isolated bucket, Temporal namespace/history
evidence capture from an isolated recovery pod and active/staged Secret
rotation comparison from an isolated non-root pod. It is an initial production
deployment guide baseline, not a claim that high availability, image release
automation, DNS ownership, certificate renewal operations, full external
secret-manager rotation, access-review operations, workload restart validation,
full Temporal persistence restore, full-bucket object-store disaster recovery,
KMS-backed signing or customer bucket operations are complete.
The API and web container image baseline now includes `services/api/Dockerfile`,
`apps/web/Dockerfile`, `.dockerignore`, `make container-check`,
`make container-build-api` and `make container-build-web`. These images are
locally buildable and align with the Helm defaults. The web runtime stage
removes the bundled `npm`/`npx` package-manager surface from the final image
because production starts through the app-local Next.js binary. The container
baseline is still not image provenance, signing or registry release automation.
The container release supply-chain baseline now includes
`.github/workflows/container-release.yml`, `make container-release-check` and
`services/api/scripts/check_container_release.py`. The workflow builds the API
and web images for GHCR through a build-only `build-images` job for tag and
default manual runs. Publish runs are separate: `validate-promotion-evidence`
requires a release approval issue, a rollback plan issue, a rollback drill id
and `rollback_plan_acknowledged=true`, then verifies the issue URLs with
`gh issue view`; `publish-images` depends on that evidence gate and declares
the `axis-container-release` GitHub Environment so repository administrators
can attach required reviewer settings to publication without blocking build-only
checks. Published digests use BuildKit SBOM and provenance attestations and
GitHub OIDC keyless signing. This is still not a production deployment
certification: GitHub environment reviewer settings, registry retention,
recurring rollback drill operations and long-term SBOM archival remain
Enterprise hardening work.
The container vulnerability scanning baseline now includes
`.github/workflows/container-security.yml`, `make container-security-check`,
`make container-scan-local` and
`services/api/scripts/check_container_security_scan.py`. The workflow builds
the API and web images from their Dockerfiles and blocks fixed `CRITICAL`
OS/library vulnerabilities using Trivy `v0.71.2`, with the Trivy action pinned
to the v0.36.0 commit SHA. The local scan writes JSON evidence under
`.axis/trivy-reports/`. This is a real scan gate for the current release path,
not a production vulnerability management program: `HIGH` escalation, exception
expiry, SARIF publication, registry retention and promotion-review policy remain
Enterprise hardening work.
The vulnerability management baseline now adds HIGH/CRITICAL SARIF publication
to GitHub code scanning through the same container security workflow, with
`github/codeql-action/upload-sarif` pinned to
`8aad20d150bbac5944a9f9d289da16a4b0d87c1e`. It also adds
`.github/vulnerability-exceptions.json`, `make vulnerability-management-check`
and `services/api/scripts/check_vulnerability_management.py`. Exceptions must
have owner roles, review tickets, promotion review and expiry; HIGH exceptions
may last at most 45 days, and CRITICAL exceptions may last at most 14 days.
There are no approved vulnerability exceptions in the current baseline. This is
still not an enterprise vulnerability management operating model: registry
retention, recurring release rollback drills, customer-specific gates and
operational review cadence remain hardening work.

The manufacturing operations dataset now has a dedicated persisted surface:
`GET /demo/manufacturing/operations` reads tenant-scoped
`manufacturing_operation_records` rows and supports server-side filters for
domain, status, record type and source system. The first bootstrap covers
production orders, material lots, supplier posture, quality batch evidence,
machine status and maintenance windows as redacted business metadata from
ERP/MES/QMS/CMMS/Supplier Portal boundaries. Live source-system queries and
secret retrieval remain behind connector runtime, credential lease and egress
policy boundaries.
`GET /demo/manufacturing/operations/snapshot` composes the persisted operation
records with generated daily briefs, risk scenarios, workflow runs, approval
records and recent audit events. It is read-only, stores no new rows and does
not generate artifacts, signal workflows, run connectors or query source
systems. The governance overview now consumes this snapshot alongside the
overview reference endpoint, so the first screen shows persisted domain rollups,
generated artifacts, active workflows, pending approvals and recent audit
evidence instead of only the older overview reference payload.
`GET /demo/manufacturing/demo-readiness` derives SME feedback and enterprise
evaluation walkthrough readiness from the persisted operations snapshot. It
returns tracks, evidence checks, production-readiness limitations, next actions
and the `derived_from_persisted_demo_evidence` boundary. The governance
overview consumes this endpoint in the browser, with no local readiness
fallback records.
The Operations overview can also call the live artifact endpoints from the
browser: `POST /demo/manufacturing/operations/daily-brief`,
`POST /demo/manufacturing/operations/risk-scenarios/quality`,
`POST /demo/manufacturing/operations/risk-scenarios/maintenance` and
`POST /demo/manufacturing/operations/risk-scenarios/supplier-delay`.
The console derives `requested_by`, `actor_scopes` and `tenant_id` only from the
API-validated identity session, blocks submission when required scopes are
missing and refreshes the persisted operations snapshot after success. The
guided local Keycloak/browser SSO setup now imports a local-only Keycloak
realm, provides an API SSO profile and exposes a console **Sign in with SSO**
path so design partners can run the mutation walkthrough without pasting bearer
tokens.
`GET /demo/manufacturing/notifications` derives topbar platform notifications
from the same persisted operations snapshot, including operation-domain
attention, pending approval gates, blocked workflow signals and recent audit
evidence. The browser no longer synthesizes notifications from the overview
reference payload. `POST
/demo/manufacturing/notifications/{notification_id}/acknowledgement` persists
read/ack state per tenant actor, enforces `notifications:acknowledge`, writes
`platform.notification.acknowledged` audit evidence and refreshes the
notification read model without browser-local fallback data.
The `/settings` console reads `/ready`, `/identity/oidc/readiness`,
`/identity/session`, `/deployment/readiness` and `/support/diagnostics`
directly from the API. It shows enterprise SSO posture, deployment blockers,
support diagnostics, redaction policy and runtime dependencies, and falls back
only to an API-required empty state when those endpoints are unavailable.
`POST /demo/manufacturing/operations/daily-brief` creates a persisted daily
plant brief from those operation records, enforces `briefs:generate`,
`audit:read` and `workflows:read`, writes
`manufacturing.daily_brief.generated` audit evidence and returns idempotent
replays for duplicate requests. The brief generator is deterministic and does
not invoke a placeholder model provider or mutate production systems.
`POST /demo/manufacturing/operations/risk-scenarios/quality` creates a
persisted quality risk scenario from `domain=Quality` operation records,
enforces `quality:read`, `workflows:read` and `audit:read`, writes
`manufacturing.risk_scenario.generated` audit evidence and returns idempotent
replays for duplicate requests. The scenario generator does not mutate QMS/MES,
approve a hold or call a model provider.
`POST /demo/manufacturing/operations/risk-scenarios/maintenance` creates a
persisted maintenance risk scenario from `domain=Maintenance` operation records,
enforces `maintenance:read`, `workflows:read` and `audit:read`, writes
`manufacturing.risk_scenario.generated` audit evidence and returns idempotent
replays for duplicate requests. The scenario generator does not mutate CMMS/MES
work orders, approve dispatch changes or call a model provider.
`POST /demo/manufacturing/operations/risk-scenarios/supplier-delay` creates a
persisted supplier delay scenario from `domain=Supply` operation records,
enforces `supply:read`, `workflows:read` and `audit:read`, writes
`manufacturing.risk_scenario.generated` audit evidence and returns idempotent
replays for duplicate requests. The scenario generator does not mutate Supplier
Portal or ERP records, approve expedite actions or call a model provider.

The governance console includes a local OIDC session bridge for demo and
developer workflows. A user can attach a bearer token in the console toolbar;
the console stores it in browser session storage and sends it as
`Authorization: Bearer ...` to protected API calls. `GET /identity/session`
validates the attached token through the API, returns the API-owned actor,
tenant, scopes, expiry and SSO posture for the account panel, and never returns
bearer token material. The API also exposes `GET /identity/oidc/authorize` and
`GET /identity/oidc/callback` for a PKCE authorization-code flow that exchanges
the code server-side, requires `openid` scope readiness, validates the returned
`id_token` signature, issuer, expiry, client audience, authorized party when
present, login nonce and access-token subject binding, then sets an HTTP-only
signed Axis session cookie. The cookie carries a high-entropy Axis
`session_id`; the API stores only a keyed hash of that session id plus actor,
tenant, scopes and expiry in `oidc_browser_sessions`, so provider token
material is not persisted in the session store. `GET /identity/oidc/logout`
clears the Axis cookie, revokes the persisted session, writes
`identity.oidc_session.revoked` audit evidence and redirects the browser to the
configured OIDC end-session endpoint without persisting or forwarding provider
token material. `POST /identity/session/logout` performs local API session
revocation without the federated provider redirect.
`GET /identity/oidc/onboarding` returns a public-safe IdP onboarding report with
the exact redirect URIs, post-logout redirect URIs, endpoint URLs, claim
mappings, scopes, recommended IdP controls and open action items an identity
administrator needs to configure Axis. It does not return confidential client
material, cookie-signing material, provider tokens or raw JWKS material.
Without a token or session cookie, `/identity/session` reports explicit
public-evaluation state when OIDC auth is optional; when OIDC auth is required,
it returns `401` until a valid bearer token or non-revoked API session cookie is
attached.

Browser sessions carry a production lifecycle. When the provider issues a
refresh token and the refresh-credential encryption key is configured, the API
stores it only as AES-GCM ciphertext on the session row under an HKDF-derived
key (minimum key length enforced at startup), and
`POST /identity/session/refresh` rotates the Axis session id, cookie and stored
refresh credential server-side inside an absolute lifetime cap. The rotation is
guarded by an atomic `active`->`refreshing` claim and the IdP token exchange
runs outside the open database transaction, so two concurrent refreshes with
the same cookie cannot both mint a child session; provider rejection revokes
the session and forces a fresh login. Sessions enforce idle and absolute
timeouts plus a per-actor concurrent-session cap, and every lifecycle
transition (login, failed code exchange, refresh, failed refresh, revocation,
logout) appends audit evidence that references sessions only by keyed hash.
`GET /identity/sessions` lists the calling actor's sessions as opaque
references - cursor-paginated newest-first with `page_size`, `has_more` and
`next_cursor` - including the device metadata captured at login and refresh
(bounded user agent, client IP under the explicit trusted-proxy flag and a
derived device label); `POST /identity/sessions/{session_ref}/revoke` revokes
them. Tenant-wide listing and revocation require the
`identity:sessions:admin` scope and lookups stay tenant-isolated; device
metadata is visible only in this owner/admin listing and never enters audit
payloads. CSRF is enforced centrally for every
cookie-authenticated state-changing request across the API through a
double-submit `X-Axis-Csrf-Token` header matched against the HMAC-derived CSRF
cookie issued at login; bearer-token and safe-method requests are exempt, and
Secure profiles use `__Host-`-prefixed session and CSRF cookies.

The web console adopts this lifecycle in its shared API request layer rather
than per page. Cookie-session mutations read the JavaScript-readable CSRF
cookie (including the `__Host-` variant) and attach the `X-Axis-Csrf-Token`
header; bearer-bridge requests stay exempt. A cookie-session `401` triggers a
single deduplicated `POST /identity/session/refresh` followed by exactly one
retry with the rotated CSRF cookie; refresh failure announces the signed-out
state and re-runs the live queries so `/identity/session` reports the public
state, and anonymous `401`s never trigger refresh attempts. The
`/settings/sessions` view lists the actor's persisted browser sessions with
lifecycle metadata, revokes non-current sessions by opaque reference, exposes
the tenant-wide listing toggle only when the identity read model carries
`identity:sessions:admin`, and treats revoking the current session as a
federated logout navigation.
Customer-specific production SSO operations runbooks remain Enterprise
onboarding work.

The ontology explorer and entity detail pages are currently read-only and API
required; the browser no longer carries a local graph fallback. Graph reads now
pass through the Axis ontology query runtime, expose query metadata and can
filter relationships by OIDC-derived relationship scopes when a bearer token is
present or OIDC auth is required by configuration. The TypeDB read boundary is
optional and separated from graph mutations. TypeDB read answers are normalized
at the client boundary, and structured ontology document rows can be mapped into
the public graph response before relationship-scope filtering. Ontology
relationships now include ownership, source adapter, confidence, evidence,
validity and verification metadata. Broader TypeDB query coverage, live graph
promotion coverage and broader graph authorization remain Platform work.

The workflow console is currently read-only and API required, with a persisted
workflow run endpoint available when Postgres records exist. The browser no
longer carries workflow fallback records. Approval decisions now signal the
workflow runtime adapter when available. Deterministic replay, workflow history
retention and workflow mutation controls remain Platform work.

The approval queue is still read-only for listing, but the listing now comes
from a persisted tenant-scoped reference row rather than route-owned seed data.
A demo decision endpoint now persists approval decisions and appends audit
events, and the web console submits reviewer decisions to it without creating a
standalone local decision preview when persistence fails. The decision endpoint
enforces the required demo approval scope before
persistence and signals the workflow runtime adapter. When a bearer token is
present, or when OIDC auth is required by configuration, the endpoint validates
the token against configurable OIDC/JWKS settings and derives tenant, actor and
scopes from token claims before persistence. Broader relationship-aware
permission enforcement remains Platform work.

The audit explorer is API required, its reference view is now loaded from a
persisted tenant-scoped bootstrap row, and it can query persisted
`audit_events` through the demo API when records exist. The browser no longer
carries audit fallback records. The demo API can also return a redacted JSON
export bundle with manifest checksum, applied filters, retention-window
enforcement, hash-chain integrity proof and a ledger signature proof. When
`AXIS_AUDIT_LEDGER_SIGNING_SECRET` is configured, the API signs the export
manifest plus hash-chain proof with a self-hosted HMAC-SHA256 signer; when it
is not configured, the bundle reports an explicit `unsigned` proof instead of
pretending a managed KMS signature exists.
`POST /demo/manufacturing/audit/retention/delete` adds a permission-gated
physical retention deletion execution path for tenant-scoped audit rows. It
supports dry-run, blocks deletion under active persisted legal holds or an
explicit legal-hold request flag and writes
`audit.retention_deletion.executed` evidence with counts and hashes rather than
raw payloads. `POST /demo/manufacturing/audit/legal-holds`,
`GET /demo/manufacturing/audit/legal-holds` and
`POST /demo/manufacturing/audit/legal-holds/{hold_id}/release` provide the
audit-backed legal hold activation/list/release workflow used by retention
deletion. Tenant-scoped query permissions remain Platform work.

The replay/simulation foundation consumes API replay artifacts from workflow
run history, timeline events and redacted audit evidence. The `/simulation`
page shows baseline versus simulated policy decisions and
governed connector policy-set version diffs over historical events for the
manufacturing demo. Replay outputs can now be persisted as governed audit
artifacts with `simulation.replay_output.persisted` evidence, retention
metadata and idempotency protection. Replay responses now enforce
retention-aware query windows across timeline, audit and persisted output
records, with a legal-hold bypass for governance review. The browser no longer
constructs replay artifacts from local workflow or audit defaults. Temporal
deterministic replay, arbitrary policy diffing, replay-output deletion jobs and
legal hold workflows for non-audit artifacts remain Platform and Enterprise
work.

The connector foundation exposes a public-safe manifest registry, a
preview-only file/CSV connector for manufacturing asset intake and a
metadata-only external database preview connector. The API can validate CSV
rows, map them to ontology entity proposals and return a redacted audit event
preview through `/demo/manufacturing/connectors/file-csv/preview`. The registry
returned by `/demo/manufacturing/connectors` now reads from the tenant-scoped
`demo_reference_records` bootstrap row instead of a route-owned runtime seed.
The API module no longer defines a connector registry factory; tests validate
the Alembic bootstrap payload directly against the registry schema.
Connector configuration creation resolves connector manifests and runtime
boundaries from that persisted registry reference, then requires a matching
tenant-scoped persisted manifest in `active_preview` before storing tenant
configuration state.
Credential handle creation uses the same persisted registry reference to
validate connector manifests, then requires a matching tenant-scoped persisted
manifest in `active_preview` before storing external secret reference metadata.
Credential lease requests use the same persisted registry reference, then
require a matching tenant-scoped persisted manifest in `active_preview` before
writing lease/audit evidence or calling the lease runtime adapter.
Ontology proposal creation also resolves connector runtime boundary metadata
from that persisted registry reference, then requires a matching tenant-scoped
persisted manifest in `active_preview` before writing proposal/audit state.
Connector run creation uses the same persisted registry reference, then requires
a matching tenant-scoped persisted manifest in `active_preview` before writing
run/audit runtime boundary metadata.
Manual import request creation also uses the same persisted registry reference,
then requires a matching tenant-scoped persisted manifest in `active_preview`
before writing approval-gated import audit evidence.
Ontology promotion execution also uses that persisted registry reference, then
requires a matching tenant-scoped persisted manifest in `active_preview` before
calling the ontology mutation adapter or writing promotion/audit evidence.
Promotion policy authoring, enablement and revision also use that persisted
registry reference before writing policy/audit evidence.
Promotion policy set activation, replacement and rollback also use it before
writing policy-set/audit evidence.
It can also preview declared external DB table metadata through
`/demo/manufacturing/connectors/external-db/preview`, using profile ids and
credential handles while blocking raw connection material, SQL text and live
queries. Tenant-scoped connector manifests can now be registered through
`/demo/manufacturing/connectors/manifests`, writing
`connector.manifest.registered` audit evidence while rejecting raw connection
fields, SQL/query text and credential material. The API also stores and
queries tenant-scoped preview connector configuration through
`/demo/manufacturing/connectors/configurations`, requiring an `active_preview`
manifest and rejecting raw credential fields in configuration payloads. The API
now also stores metadata-only credential handles and rotation history through
`/demo/manufacturing/connectors/credential-handles`, using external secret
references instead of raw credential values, requiring a matching
tenant-scoped connector manifest in `active_preview` and failing explicitly if
the persisted connector registry reference is missing or invalid. Short-lived
credential leases can now be requested, renewed and revoked through
`/demo/manufacturing/connectors/credential-leases`, writing
`connector.credential_lease.*` audit evidence while returning only references,
timestamps, permission decisions and adapter evidence. Lease requests require a
matching tenant-scoped connector manifest in `active_preview` before runtime or
audit evidence is written. The lease runtime is deferred by default and can use
the optional self-hosted Vault/KMS adapter when
`AXIS_CREDENTIAL_LEASE_EXECUTION_ENABLED=true`, still without returning secret
material. Provider-specific Vault/KMS adapter profiles can be enabled with
`AXIS_CREDENTIAL_LEASE_PROVIDER_ADAPTERS_ENABLED=true`; the runtime validates
the declared provider mode against the credential handle secret provider,
secret reference prefix and KMS policy metadata for HashiCorp Vault, AWS Secrets
Manager, GCP Secret Manager, Azure Key Vault, KMS and local env refs, while
still returning only lease evidence. Connector run records can now be written through
`/demo/manufacturing/connectors/runs`; each record stores only redacted
summaries and links to an append-only
`connector.run.recorded` audit event. Governed dry-run connector execution now
calls the deferred Axis
connector execution adapter, requires credential handle ids, writes
`connector.run.execution_deferred` audit evidence and still does not start live
sync. Scheduled sync plans can now be recorded through the same run endpoint
with `execution_mode=scheduled_sync_plan`, active credential lease evidence,
schedule metadata and `connector.run.sync_scheduled` audit evidence, while the
deferred scheduler adapter keeps `external_sync_started=false`.
Scheduled plans can now be dispatch-claimed through
`/demo/manufacturing/connectors/runs/{run_id}/dispatch`, requiring
`connectors:sync:dispatch`, active lease evidence and an idempotency key. The
dispatch boundary writes `connector.run.sync_dispatch_deferred` and still keeps
`external_sync_started=false`.
Dispatch-claimed plans can now receive a sync execution attempt through
`/demo/manufacturing/connectors/runs/{run_id}/execute-sync`, requiring
`connectors:sync:execute`, active lease evidence and an idempotency key. The
default execution runtime writes `connector.run.sync_execution_deferred`; the
opt-in self-hosted demo runtime, enabled with
`AXIS_CONNECTOR_SYNC_EXECUTION_ENABLED=true`, can write
`connector.run.sync_execution_completed` without external egress, credential
material retrieval or graph mutation.
External DB sync can opt into the Postgres profile adapter boundary with
`AXIS_EXTERNAL_DB_SYNC_EXECUTION_ENABLED=true`, adding public-safe
provider/profile/table/count evidence while still omitting raw connection
strings and credential material.
When an external DB run explicitly requests live query handling, Axis first
records a separate preflight result. The default decision is
`connector.run.sync_execution_preflight_blocked`; setting
`AXIS_EXTERNAL_DB_LIVE_QUERY_PREFLIGHT_ENABLED=true` can produce
`connector.run.sync_execution_preflight_passed` only when the run carries an
approved private endpoint egress boundary, egress policy id, lease-scoped
secret reference and a targeted active checkpoint claim owned by the executing
worker. A further opt-in,
`AXIS_EXTERNAL_DB_LIVE_QUERY_EXECUTION_ENABLED=true`, can execute a bounded
read-only Postgres query only when the manifest is `active_live`, the request
sets `live_query_execute=true`, the configured profile id/schema/table matches
the run, selected columns are omitted or allowlisted, the private endpoint
reference and endpoint-target SHA-256 bind the secret DSN to the persisted
egress policy, and all preflight gates pass. The live-read result persists row
counts, profile id, row limit, query status and checkpoint evidence only; it
does not persist DSNs, SQL text, row payloads, credential material or graph
mutations. Missing `checkpoint_claim_id` or inactive target claims are rejected
before the provider-specific runtime is called, before preflight or live-read
audit is written and before a new execution checkpoint is created. Passed and
blocked preflights with a valid target claim include public-safe checkpoint
claim evidence in the sync result summary. When `live_query_requested=true`,
`execute-sync` must provide `checkpoint_claim_id`; Axis rejects the request
unless that exact claim is active, unexpired, owned by `executed_by` and
backed by `connector.run.sync_checkpoint_claimed` audit evidence whose audit id
resolves in the tenant-scoped append-only audit ledger with matching
connector/run/checkpoint/claim/worker binding and worker-lease-only payload before being
attached to an eligible `sync_execution_preflight_passed` checkpoint for the
same connector and run with `connector.run.sync_execution_preflight_passed`
audit evidence referenced by `evidence_refs`. The referenced audit id must
resolve to a persisted tenant-scoped audit ledger event with the same
connector/run/checkpoint binding, its payload must remain public-safe and the target
checkpoint result evidence must remain public-safe. The target claim result
must remain worker-lease-only with `external_sync_started=false`,
`secret_material_returned=false` and `worker_claim_only=true`. That target
preflight checkpoint still keeps `external_query_started=false`, returns no
credential material and performs no graph mutation. The passed preflight now
depends on validated egress policy
evidence from persisted tenant-scoped policy records and the validated
credential lease result: the runtime records policy
runtime/ref/scope/private-endpoint evidence, blocks unknown or unpersisted
policies before secret retrieval is considered, records lease
id/mode/runtime/result status/reference evidence, records reference-only secret
resolver evidence and blocks the path if the lease reference is missing or if
the lease evidence says secret material was returned. Network policy
preflight and completed/deferred sync execution attempts now also write
tenant-scoped `connector_sync_checkpoints` rows with public-safe cursor and
result evidence for future retry/checkpoint-aware provider adapters. The
checkpoint registry is queryable at
`/demo/manufacturing/connectors/runs/checkpoints` with tenant, connector, run,
status, `created_after`, `created_before` and limit filters, and requires the
`connectors:sync:checkpoint:read` scope. Invalid windows where `created_after`
is equal to or later than `created_before` are rejected before checkpoint
storage is queried. Valid checkpoint reads write
`connector.run.sync_checkpoints_read` audit evidence with filters, count,
evidence invariant count and checkpoint ids only. The registry response reports
public-safe evidence invariants for missing, unresolved, mismatched or unsafe
checkpoint audit evidence without copying cursor or result summaries into the
read-audit payload.
Worker claim records are persisted at
`/demo/manufacturing/connectors/runs/checkpoints/{checkpoint_id}/claims` with
the `connectors:sync:checkpoint:claim` scope, lease duration metadata,
idempotency-key replay and `connector.run.sync_checkpoint_claimed` audit
evidence. A claim is a worker lease only: it does not start external sync,
retrieve secret material or execute provider-specific connector code. A second
unexpired active claim for the same checkpoint is rejected with 409 before a
duplicate claim/audit record is written. Expired claims are marked `expired`
with `connector.run.sync_checkpoint_claim_expired` before replacement ownership
is created. Claim records are queryable at
`/demo/manufacturing/connectors/runs/checkpoints/claims` with tenant, connector,
run, checkpoint, worker, status, `created_after`, `created_before`, cursor and
limit filters. Invalid time windows are rejected before storage reads. Reads
return `has_more` and `next_cursor` for stable cursor-based pagination. Reads require
`connectors:sync:checkpoint:claim:read` and append
`connector.run.sync_checkpoint_claims_read` audit evidence with filters,
pagination metadata, returned claim count and claim ids only. Claim renewal and
release update the same persisted lease record through dedicated scopes, writing
`connector.run.sync_checkpoint_claim_renewed` and
`connector.run.sync_checkpoint_claim_released` audit evidence without
provider-specific connector execution.
enforcement, real secret retrieval and real query execution stay outside this
slice.
The `/connectors` console now fetches connector, credential, egress policy,
run, sync checkpoint, checkpoint claim, evidence invariant, evidence snapshot,
proposal, import and promotion records from the Axis API. Checkpoint rows are
requested with the checkpoint read scope and shown per selected connector with
sequence, adapter, cursor summary, result evidence and audit refs. Checkpoint
claim rows are requested with
`connectors:sync:checkpoint:claim:read` and shown next to the selected
connector checkpoints with worker ownership, lease, renewal/release, invariant
status and secret-material evidence. Evidence snapshot history is requested
with `connectors:evidence:snapshot:read` and shown with newest snapshot id,
invariant totals, evidence surface count and digest prefixes. The console can
create a selected-connector evidence snapshot through
`POST /demo/manufacturing/connectors/evidence-invariants/snapshots` with
`connectors:evidence:snapshot`, generated snapshot/idempotency ids and a
public-safe review reason, then refreshes API-backed history. Snapshot artifacts
with audit event ids link to `/audit?event_id=...`, where the audit explorer
selects the matching persisted event after loading API-backed ledger records.
Persisted snapshot audit events expose only redacted `snapshot_id`,
`connector_id` and idempotency preview fields, and the audit explorer links
back to `/connectors?snapshot_id=...&connector_id=...` so reviewers can reopen
the selected API-backed snapshot artifact. The connector console also loads the
API-backed snapshot export bundle, showing export id, record count, checksum
prefix, redaction policy, integrity algorithm and ledger signature status.
`GET /demo/manufacturing/connectors/evidence-invariants/snapshots/export`
uses `connectors:evidence:snapshot:read`, supports the same snapshot filters
plus an export reason, returns public-safe snapshot metadata with a manifest
checksum and SHA-256 hash-chain proof, and uses the self-hosted audit ledger
signer when configured. `POST
/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests`
records an approval-required export request with workflow id, idempotency key,
snapshot filter, requested snapshot count, checksum preview and storage status
`not_written`; it creates approval/audit evidence and waits for explicit
materialization before writing any storage artifact. `POST
/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests/{export_request_id}/decision`
records the approval decision, updates the export request to
`approval_approved` or `approval_rejected`, signals the workflow runtime through
the Axis adapter and keeps storage status `not_written` until the approved
request is explicitly materialized. `POST
/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests/{export_request_id}/materializations`
requires `connectors:evidence:snapshot:export:materialize`, verifies that the
request was approved and the snapshot checksum still matches, writes the
public-safe export bundle to the configured object-store adapter, records
checksum/size/storage URI metadata and appends audit evidence. Local demos use
the filesystem adapter; S3-compatible profiles can write retained objects when
the WORM readiness gate is configured. If the backend is unavailable the
console shows an
API-required empty state instead of rendering local connector fallback records.
Preview-derived ontology proposals can now be persisted through
`/demo/manufacturing/connectors/ontology-proposals`; each proposal is
audit-backed, initially marked with `graph_mutation_status=not_applied` and
fails explicitly when the persisted connector registry reference is missing or
invalid.
Manual connector import requests can now be recorded through
`/demo/manufacturing/connectors/manual-imports`; each request is tenant-scoped,
idempotent, approval-gated, workflow-referenced and audit-backed with
`connector.manual_import.requested`, while graph mutation remains
`not_applied`. Creation resolves connector runtime boundary metadata from the
persisted connector registry reference and fails explicitly if that reference
is missing or invalid before writing rows or audit events. Decisions can now be
recorded through
`/demo/manufacturing/connectors/manual-imports/{import_id}/decision`; each
decision stores the approval outcome, workflow signal status and
`connector.manual_import.decision_recorded` audit evidence without executing
the connector. Approved proposal promotion can now be requested through
`/demo/manufacturing/connectors/ontology-proposals/promotions`; each promotion
requires approval evidence, workflow signal evidence, idempotency,
`connectors:ontology:promote` and a tenant-scoped connector manifest in
`active_preview`, then applies or defers the TypeDB graph mutation through the
Axis ontology mutation adapter with append-only
`connector.ontology_promotion.*` audit evidence. Replays with the same
idempotency key and payload return the existing request or promotion instead of
writing duplicate audit events. Connector promotion policies can now be
authored through `/demo/manufacturing/connectors/promotion-policies`; each
policy records the authoring permission, required promotion scopes, approved
manual import state, workflow signal state, allowed risk levels and
`connector.promotion_policy.authored` audit evidence without executing
connectors or mutating TypeDB. Authoring validates connector ids through the
persisted registry reference and fails explicitly if that reference is missing
or invalid before writing rows or audit events. Policies are enabled through
`/demo/manufacturing/connectors/promotion-policies/{policy_id}/enable`, which
requires `connectors:promotion_policy:enable`, an approved decision, workflow
signal evidence and writes `connector.promotion_policy.enabled`; enablement
revalidates the policy connector through the persisted registry reference
before updating state. Draft policies can be revised append-only through
`/demo/manufacturing/connectors/promotion-policies/{policy_id}/revise`, which
requires `connectors:promotion_policy:revise`, approved revision evidence,
workflow signal evidence and an idempotency key. Revisions validate the
requested connector through the persisted registry reference before writing the
new draft or audit evidence. Enabled required policies are not revised in
place; future versions must be adopted through a governed policy-set
transition. Enabled required policies are auto-selected when a
promotion request omits `policy_id` and are enforced before the TypeDB mutation
adapter is called. When more than one enabled required policy applies,
`/demo/manufacturing/connectors/promotion-policy-sets`
can activate a versioned active set with
`connectors:promotion_policy_set:activate`; activation validates the connector
through the persisted registry reference before writing set/audit evidence. The
promotion endpoint evaluates all policies in that set and stores
`policy_set_id`, `policy_ids` and
`policy_set_enforced` evidence. When a policy set is active, explicit single
`policy_id` selection is rejected so promotions cannot bypass the full
required-gate set. Replacing or rolling back an active set requires
`replaces_policy_set_id`, an approved transition decision and workflow evidence.
Replacement writes `connector.promotion_policy_set.replaced`; rollback restores a
superseded target through a new active version, writes
`connector.promotion_policy_set.rolled_back` and marks the previous active set
`superseded`. Replacement can carry `policy_revision_adoptions` so approved
draft revisions are adopted atomically with the set transition; Axis writes
`connector.promotion_policy.revision_adopted`, supersedes the current required
policy and stores adoption evidence on the new active set. Policy and
policy-set promotion rejections write
`connector.ontology_promotion.rejected` audit evidence with the effective
policy context before the API returns 422. If multiple required policies exist
without an active set, Axis still rejects implicit selection.
The file/CSV and external DB preview endpoints now resolve connector ids,
schema fields, runtime row limits and public-safe sample rows through the same
persisted connector registry reference before returning preview output. Missing
or invalid registry references return explicit 404/422 responses before any
preview mapping is generated.
The `/connectors` console shows runtime boundaries, required permissions,
blocked operations, tenant configuration, credential handle posture, connector
run evidence from persisted registry-backed run creation, deferred execution metadata,
persisted ontology proposal
evidence, promotion evidence, manual import decision evidence, promotion policy
authoring/enforcement evidence, versioned policy-set evidence, aggregate
evidence invariant posture, evidence snapshot history and schema mapping from
API-backed records only.
It can author promotion policies through the API when available, enable them
with approval/workflow evidence and reports API persistence errors without
recording local public-safe previews when the API is offline. The browser
runtime no longer exports connector registry, preview, credential, run,
proposal, import, promotion policy or policy-set default records; connector
unit tests use local fixtures instead of product runtime fallbacks.
Live connector manifests can now move from `active_preview` to `active_live`
only when both lifecycle and live-enable scopes, live-capable runtime policy,
live sync mode and approval/policy/credential evidence are present. The
transition writes append-only audit evidence and still does not retrieve
secrets, execute connector code, start external sync or mutate the ontology
graph. Scheduled governed live sync, lease-scoped secret resolution and
runtime egress enforcement now exist behind their own explicit flags (all off
by default). Broader provider adapters beyond the file/CSV dropzone and
allowlisted Postgres profiles, and connector-backed production actions, remain
Platform work.

The agent registry is API required for catalog browsing; the browser no
longer carries local agent fallback records, and the API module no longer
defines an agent registry runtime seed factory. Governed agent run execution
now exists behind `AXIS_AGENT_RUN_EXECUTION_ENABLED` (off by default): runs
persist append-only step timelines, enforce autonomy ceilings, registry
permissions and platform policies, route model calls through registered
endpoints, and turn parseable proposals into approval-gated action runs
(dry-run mode records the proposal only). Runs never execute side effects
directly and fail closed on unparseable or unpermitted model output. Direct
production action execution, tenant-scoped agent configuration storage and
SDK/connector-driven agent registration remain Platform work.

The action registry UI is API required for catalog browsing. The browser no
longer carries local action fallback records, and the API module no longer
defines an action registry runtime seed factory. Typed dry-run/proposal action
requests can now be persisted through the demo API with idempotency enforcement
and append-only audit events. Approval-gated action payloads now signal the Axis
workflow runtime adapter after persistence, with explicit degraded status when
the runtime is unavailable. When a bearer token is present, or when OIDC auth is
required by configuration, action run creation derives tenant, actor and scopes
from token claims and rejects actor impersonation before persistence. Action
payload fields marked as ontology references also require the scopes attached to
their connected ontology relationships from the persisted ontology reference
record, preventing cross-domain resource references from bypassing the typed
action permission check. Live production execution, connector invocation and
broader relationship-aware permission enforcement remain Platform work.

Approval decisions now also reconcile persisted workflow state when the linked
`workflow_runs` row exists: the pending signal records the decision, the run
state/status/current step are updated and a workflow timeline event is appended.
This keeps the persisted workflow console coherent without requiring a live
Temporal worker.

The model routing and cost observability layer has two parts. The reference
telemetry view stays read-only and API required: the browser no longer carries
local route telemetry fallback records, the API reference comes from a
persisted tenant-scoped bootstrap row and the API module no longer defines a
route telemetry seed factory. The execution slice is now real behind
`AXIS_MODEL_ROUTING_EXECUTION_ENABLED` (off by default): tenant-scoped model
endpoints register through `/platform/models/endpoints` with hosting
boundaries and openai-compatible provider support, governed invocations run
through `/platform/models/invocations` with metadata-only persisted records
(token counts, latency, status; prompt excerpts default to zero characters),
audit evidence and usage metering, and non-self-hosted egress stays separately
gated by `AXIS_EXTERNAL_MODEL_EGRESS_ENABLED=false`. Provider-specific billing
ingestion, tenant budget enforcement and additional provider adapters remain
Platform work.

### Enterprise

- [x] Add the tenant lifecycle and per-tenant quota foundation that starts the
  multi-tenant SaaS reference: operator-scoped provisioning with idempotent
  replay and bootstrap admin actors, suspend/reactivate with fail-closed
  request rejection at the OIDC principal boundary, and typed quotas (API
  requests per window, concurrent sessions, live-sync rows per run) enforced
  through a short-TTL tenant state cache with per-change audit evidence.
- [x] Add the tenant operations console: a top-level `/tenants` operator
  surface with the tenant list (status filter, API-required and empty states),
  a provision form with client-side `tenant_id` validation, a client-generated
  idempotency key and distinct 201/replay/409/422 handling, a tenant detail
  view with the lifecycle timeline and suspend/reactivate actions (inline 403
  on missing scope), and a per-tenant quota view/edit with null-clear semantics
  and confirmed PUT, all through the typed `lib/platform-tenants.ts` bindings.
  The list and detail-derivation read at the `limit=200` API maximum and show a
  visible cap notice past it (no silent truncation).
- [x] Add per-tenant usage metering: the cumulative consumption ledger beneath
  the quota ceilings. A `tenant_usage_records` table (migration 0049) accounts
  the `api_request`, `connector_sync_rows` and `session_created` metrics at the
  existing choke points via a bounded in-process aggregator on the hot path
  (batched, flushed to per-period buckets) and durable per-event upsert-adds for
  the low-volume paths, correct under concurrency (single-statement upsert-add;
  drain/restore with no loss or double count). An operator-scoped
  (`platform:tenant:usage`) `GET /platform/tenants/{id}/usage` returns per-metric
  totals + a per-period breakdown over a queryable window, with a read-only usage
  panel on the tenant detail console. Quotas are ceilings, metering is cumulative
  accounting, and billing is a future consumer.
- [x] Add a single-tenant `GET /platform/tenants/{id}` route and server-side
  cursor pagination so the console is not bounded by the `limit=200` listing
  ceiling (the console requests full pages and follows `next_cursor` beyond
  the page maximum).
- [ ] Add tenant deletion and data-export pipelines and approval-gated
  lifecycle transitions on top of the lifecycle foundation and its console.
- [x] Add baseline single-tenant managed deployment profile, render checks and
  readiness gates.
- [x] Add baseline private-cloud and on-prem/offline deployment profiles,
  render checks and readiness gates.
- [x] Add Helm charts and production deployment guide baseline.
- [ ] Add complete customer-specific single-tenant managed reference
  architecture.
- [ ] Add complete customer-specific private-cloud and on-prem reference
  architectures.
- [x] Add local Docker Compose backup and restore procedures for repeatable demos.
- [ ] Add complete production backup, restore, retention and disaster recovery
  procedures across all stateful services.
- [x] Add S3 object-lock/WORM enforcement for audit export bundles: bootstrap
  bucket object-lock verification, a fail-closed COMPLIANCE export gate with
  truthful manifest `worm_retention_enforced` and explicit RetainUntilDate, the
  local-store WORM limitation, and audited object-store legal hold apply/release
  reconciled with the existing DB-level audit legal hold.
- [ ] Add enterprise-grade audit export workflows beyond the current retention,
  integrity and WORM controls (provider-specific KMS signing, richer legal
  operations, deterministic Temporal replay).
- [ ] Add enterprise identity and SSO hardening beyond the current OIDC
  readiness/profile, IdP onboarding report, PKCE callback, ID-token nonce
  and subject binding, secure browser-session readiness gate, federated logout
  and server-side session revocation reports.
- [x] Adopt the cookie-session lifecycle in the web console: centralized CSRF
  header attach, single-retry deduplicated session refresh on `401`, a
  `/settings/sessions` management view with revocation and logout semantics.
- [x] Add deployment readiness secure-cookie session posture gate for Secure
  cookies, signing secret presence, bounded TTL and HTTPS API/public/redirect
  URLs.
- [x] Add deployment readiness profile reporting for identity, egress,
  connector execution, audit signing, S3/MinIO object-store posture and WORM
  retention gates.
- [x] Add public-safe production backup/restore and disaster-recovery procedure
  readiness gates for approved runbook, RPO/RTO, rehearsal evidence, restore
  ownership and customer approval.
- [x] Add restricted/offline Kubernetes network egress modes and deployment
  readiness gating beyond the initial port allowlist.
- [x] Add deployment tenancy profile readiness gates for SaaS multi-tenant,
  single-tenant managed, private-cloud and on-prem paths with public-safe
  isolation, data-residency, operator-access and break-glass evidence.
- [x] Add public-safe Helm deployment profile overlays for single-tenant
  managed, private-cloud and on-prem/offline paths without customer-specific
  evidence defaults.
- [x] Add Helm deployment profile render gate for dedicated deployment overlays.
- [x] Add Helm values schema validation for deployment modes and profile
  safety-critical knobs.
- [x] Add configurable API rate limiting for public and sensitive routes,
  with deployment readiness gating.
- [x] Add initial security review and threat model documentation.
- [ ] Add external security review, penetration testing and production threat
  model validation.
- [x] Add support and operations runbook baseline.
- [x] Add production support-readiness contract for support model, escalation
  channel classes, SLO targets and customer-facing runbook/status-page
  configuration.
- [x] Add public-safe production support commitment readiness gates for signed
  support commitments, named staffing model, customer-specific incident
  operations and legal SLA terms.

### Operate

Operate closes the open Platform and Enterprise items above and adds the layer
where organizations work with Axis every day: permission-aware search, grounded
and cited answers, ontology conversation, forward-looking simulation, packaged
verticals, SME-grade onboarding and a clear editions boundary — all inside the
existing governance, audit, tenancy and sovereignty boundaries. The detailed
plan is
[`docs/plans/2026-07-11-operate-milestone.md`](./docs/plans/2026-07-11-operate-milestone.md).

- [x] Record this private repository as the complete commercial source of truth
  and define a one-way, fresh-history OSS export boundary in an ADR.
- [ ] Run the editions audit against the written boundary rule, block export
  while any capability is undecided and publish the editions statement in
  `docs/editions.md`.
- [ ] Design the invite-based hosted prospect sandbox with automatic reset and
  time-boxed access as the first hosted-edition deliverable.
- [ ] Complete the governance console redesign (phases 2-6): action-first
  overview and approvals, rebuilt agents, workflows, connectors and ontology
  surfaces, governance pages, onboarding checklist and demo-data switch.
- [ ] Broaden the connector framework with object-storage drop ingestion, a
  generic REST-pull source, an additional external database profile,
  per-tenant connector enablement and a documented connector-authoring
  contract.
- [ ] Add the Axis Search foundation: tenant-scoped document, connector and
  ontology indexing with Postgres full-text search behind a search adapter
  boundary.
- [ ] Add the document upload subsystem with text extraction, size and type
  limits through the object-store adapter.
- [ ] Add self-hosted embedding capability to the model router and hybrid
  full-text plus vector retrieval behind explicit flags, with graceful
  full-text-only degradation.
- [ ] Add grounded, citation-bound answer generation over permission-filtered
  retrieval, with fail-closed refusal when grounding is missing.
- [ ] Add Axis Assistant: tenant-scoped governed conversations grounded in
  permission-filtered ontology and search reads, with a cite-or-refuse
  composer, a global context-aware console panel and a dedicated page.
- [ ] Route assistant action requests through the existing agent-run propose
  mode, autonomy ceilings and the approval pipeline, never a new execution
  path.
- [ ] Add Axis Scenarios: deterministic what-if simulation with a generic
  typed-perturbation contract, vertical-registered vocabularies and governed
  persisted outputs on the replay foundation.
- [ ] Close the manufacturing reference demo with live workflow execution and
  connector-backed production actions.
- [ ] Define the reusable vertical template (ontology, agent, workflow,
  connector, scenario-vocabulary packs plus demo dataset), ship Axis for
  Manufacturing as its first instance and validate the template shape at
  design level against a second vertical.
- [ ] Add guided tenant onboarding with a one-command demo tenant bootstrap and
  a documented default self-hosted model stack for the demo runtime.
- [ ] Add a single-node deployment profile with render checks and readiness
  gates.
- [ ] Extend per-tenant usage metering to model, search, embedding and
  assistant metrics with exportable signed usage statements.
- [ ] Add console internationalization with Italian as the first locale, after
  the console redesign stabilizes.
- [ ] Add repository hygiene: changelog, architecture decision records,
  code owners, code of conduct, support policy and automated dependency
  updates.
- [ ] Close the remaining open Platform items (sustained HA validation) and
  Enterprise items (tenant deletion and export, reference architectures,
  production disaster recovery, enterprise audit export, SSO hardening,
  external security review) as tracked in their sections above.

## Expansion Rule

Axis starts unified, but the architecture must keep boundaries extractable.

Future repositories may include:

- `limes-axis-cloud`
- `limes-axis-enterprise`
- `limes-axis-connectors`
- `limes-axis-sdk`
- `limes-axis-deploy`
- `limes-axis-docs`

Extraction should happen when a module has at least two of these traits:

- independent release cadence;
- separate team or ownership;
- enterprise-only secrets, permissions or deployment logic;
- customer-specific integrations;
- independent SDK versioning;
- large connector surface;
- cloud operations that differ materially from a future OSS edition;
- documentation needs that outgrow the product repo.

## Contribution Policy

The repository retains Apache-2.0 licence text and a Contributor License
Agreement from its earlier public topology. Qualified legal review must decide
their treatment before external contribution intake or an OSS export.

The CLA text in this repository is an initial project baseline and should be
reviewed legally before broad external contribution intake.

## What Is Intentionally Not Promised Yet

- No production readiness claim.
- No completed ERP/MES/CRM integrations.
- No uncontrolled autonomous agents.
- No dependency on a proprietary hosted model provider.
- No promise that commercial capabilities will be included in a future OSS
  export.
