# Demo Readiness

This page defines the repeatable local demo contract for Limes Axis. It is
written for real SME and enterprise feedback sessions: the environment must use
the Axis API, migrations, persisted bootstrap records and local self-hosted
services, not browser-local mock data.

## Current Position

Axis is ready for a structured SME feedback demo when the acceptance checklist
below passes on the demo machine.

Axis is ready for an enterprise evaluation demo as an architecture and product
workflow walkthrough when the same checklist passes and the limitations section
is shared before the session. It is not yet a production enterprise deployment:
the first Helm baseline exists, but production disaster recovery, SSO
hardening, customer bucket operations, secret-manager rotation operations, high
availability and signed production operations commitments remain tracked
Enterprise work.

## No Browser-Local Mock Data

The governance console is API-required. Demo records shown in the browser must
come from Axis API responses backed by persisted tenant-scoped bootstrap rows,
Postgres operational state, generated audit artifacts or explicit deferred
runtime evidence.

The demo may include deterministic reference records because those records are
part of the migrated demo tenant state. It must not rely on hidden browser
fallback data, local random factories or UI-only mock objects.

## Local Runtime

The local demo stack is self-hosted through Docker Compose:

- Postgres for operational state and migrations.
- TypeDB for the ontology boundary.
- Temporal for workflow runtime integration.
- MinIO for the S3-compatible object-store path.
- Keycloak for self-hosted OIDC evaluation.

Start the service stack:

```bash
make demo-stack-up
```

Apply database migrations:

```bash
make demo-db-upgrade
```

Run the API:

```bash
make demo-api
```

For the guided local browser SSO walkthrough, run the API with the local
Keycloak profile instead:

```bash
make demo-api-sso
```

Run the governance console in a second terminal:

```bash
make demo-web
```

## Guided Local Keycloak SSO

The Docker Compose Keycloak service imports the local-only realm file at
`infra/docker/keycloak/axis-realm.json`. That realm creates:

- realm `axis`;
- confidential client `limes-axis-web`;
- redirect URI `http://127.0.0.1:8000/identity/oidc/callback`;
- post-logout redirect URI `http://127.0.0.1:3000/`;
- audience mapper for `limes-axis-api`;
- `axis_tenant=tenant_demo_manufacturing` claim mapping;
- demo operator `axis-operator` with password `axis-demo`;
- demo roles/scopes for Operations artifact generation, notification
  acknowledgement, audit reads and workflow reads.

The realm, password and client secret are local-only demo credentials. They are
not Helm defaults, customer credentials or production SSO guidance.

After `make demo-stack-up`, verify the imported realm discovery document:

```bash
make demo-keycloak-check
```

You can also dry-run the canonical enterprise realm bootstrap boundary
(read-only) against the local demo realm. This is the same tool used for
enterprise realms with their own values — see
[`docs/runbooks/keycloak-realm-bootstrap.md`](runbooks/keycloak-realm-bootstrap.md).
Divergence here (for example, canonical platform roles missing from a realm
imported by an older compose file) is reported as an update plan, never applied
in check mode:

```bash
make demo-keycloak-bootstrap-check
```

Then run:

```bash
make demo-db-upgrade
make demo-api-sso
make demo-web
```

Open `http://127.0.0.1:3000`, use the account menu and choose **Sign in with SSO**.
After Keycloak redirects back to the Axis API, the console uses the
HTTP-only Axis session cookie through normal API requests. The account menu
still exposes the bearer-token bridge as a developer fallback, but the guided
demo path should use browser SSO.

The local console is configured for both `localhost:3000` and
`127.0.0.1:3000` development access, and the API also allows the
`localhost:3100` and `127.0.0.1:3100` origins used by Playwright against the
production Next.js build. This keeps the in-app Browser, local review sessions
and automated browser checks on the same Axis API.

Run static demo checks:

```bash
make demo-check
```

Run the security posture and threat model contract:

```bash
make security-check
```

Run the Kubernetes/Helm deployment package contract:

```bash
make deployment-check
make deployment-profile-render-check
make deployment-backup-rehearsal-plan
make deployment-restore-rehearsal-plan
make deployment-typedb-recovery-rehearsal-plan
make deployment-object-storage-recovery-rehearsal-plan
make deployment-temporal-recovery-rehearsal-plan
make deployment-secret-rotation-rehearsal-plan
make deployment-ha-rehearsal-plan
make deployment-load-rehearsal-plan
make deployment-tls-readiness-plan
```

Run the API/web container image contract:

```bash
make container-check
```

Plan, capture or restore repeatable local demo state with the
[`backup and restore runbook`](./backup-restore.md):

```bash
make demo-backup-plan
make demo-backup-local
AXIS_BACKUP_DIR=.axis/backups/<backup-id> make demo-restore-local
```

Run static and live checks after the API and web console are running:

```bash
make demo-check-live
```

The live check includes the OIDC readiness contract at
`/identity/oidc/readiness` and the IdP onboarding report at
`/identity/oidc/onboarding`. The reports are public-safe: they show whether
bearer tokens are required, whether the issuer is HTTPS, whether JWKS is
explicitly configured, whether asymmetric algorithms are used, which
actor/tenant claims are bound, whether the authorization-code session-cookie
settings are hardened, whether the federated end-session redirect is configured
and which exact redirect/logout URIs an identity administrator must allow. They
do not expose tokens, secrets, passwords or raw JWKS material. A
local default profile can pass the demo contract while still showing
`enterprise_sso_ready=false`; enterprise evaluation sessions should share that
status honestly.

The live check also includes `/deployment/readiness`, which aggregates identity,
OIDC secure-cookie/session posture, external model egress, live connector
execution, audit signing, object-store posture, network egress restrictions,
`deployment_tenancy_profile` posture and public-safe disaster-recovery
procedure readiness into explicit production blockers. The current local
profile can be demo-safe while `production_ready=false`; that is intentional
until enterprise deployment, S3/MinIO object-store posture, restricted/offline
egress, tenancy profile evidence, DR procedures and signed support commitments
are complete.

The live check also includes `/support/diagnostics`, a public-safe support
bundle for design-partner triage. It reports demo-support readiness,
production-support blockers, support model readiness, SLO target configuration,
support commitment readiness, support artifact links and redaction policy
without returning bearer tokens, raw JWKS, credential material, signing
material, database DSNs, customer runbook URLs, status page URLs, contract text,
staffing details or personal contact details.

Run browser smoke tests against the production Next.js build:

```bash
pnpm --filter @limes-axis/web test:e2e
```

Run the live overview and product-story checks when the local API is running.
The command builds once, runs read-only scenarios across desktop, mobile and
tablet in parallel, then serializes the shared-state writes once in Chromium:

```bash
pnpm --filter @limes-axis/web test:e2e:live
```

Stop the stack:

```bash
make demo-stack-down
```

## Acceptance Checklist

- [ ] `make demo-stack-up` starts Postgres, TypeDB, Temporal, Temporal UI, MinIO
      and Keycloak.
- [ ] `make demo-db-upgrade` applies all Alembic migrations against the local
      Postgres database.
- [ ] `make demo-api` starts FastAPI on `http://127.0.0.1:8000`.
- [ ] `make demo-keycloak-check` verifies the local Keycloak realm discovery
      document after `make demo-stack-up`.
- [ ] `make demo-api-sso` starts FastAPI with the local-only Keycloak browser
      SSO profile for guided artifact walkthroughs.
- [ ] `make demo-web` starts the Next.js console on `http://127.0.0.1:3000`.
- [ ] `make demo-check` passes static repository checks.
- [ ] `make security-check` passes the threat model and security posture
      contract for the current repository state.
- [ ] `make deployment-check` passes the Helm chart, public deployment guide
      and externalized secret/configuration contract.
- [ ] `make deployment-profile-render-check` passes the Helm profile render gate
      for single-tenant managed, private-cloud and on-prem/offline overlays.
- [ ] `make deployment-backup-rehearsal-plan` prints the Kubernetes Postgres
      backup rehearsal and restore-catalog validation steps without exposing a
      database DSN or other secret material.
- [ ] `make deployment-restore-rehearsal-plan` prints the Kubernetes Postgres
      restore rehearsal steps for an isolated target Secret containing
      `AXIS_POSTGRES_RESTORE_DSN` without exposing a restore DSN or other
      secret material.
- [ ] `make deployment-typedb-recovery-rehearsal-plan` prints the Kubernetes
      TypeDB recovery rehearsal steps for an isolated target Secret containing
      `AXIS_TYPEDB_RESTORE_DATABASE`, including `database export`,
      `database import`, TypeDB Console preflight, checksum evidence and
      restore-target probing without exposing TypeDB credentials; live
      execution also requires `AXIS_TYPEDB_RECOVERY_IMAGE`.
- [ ] `make deployment-object-storage-recovery-rehearsal-plan` prints the
      Kubernetes object storage recovery rehearsal steps for an isolated target
      Secret containing `AXIS_CONNECTOR_EXPORT_S3_RESTORE_BUCKET`, including
      MinIO Client preflight, `mc alias set`, `mc cp`, `mc cat`, checksum
      evidence and restore-target probing without exposing S3 credentials; live
      execution also requires `AXIS_OBJECT_STORAGE_RECOVERY_IMAGE`.
- [ ] `make deployment-temporal-recovery-rehearsal-plan` prints the
      Kubernetes Temporal recovery rehearsal steps for an isolated recovery
      Secret containing `AXIS_TEMPORAL_RECOVERY_WORKFLOW_ID`, including
      Temporal CLI preflight, `operator namespace describe`, `workflow list`,
      `workflow show --output json`, checksum evidence and namespace/history
      evidence capture without exposing Temporal credentials; live execution
      also requires `AXIS_TEMPORAL_RECOVERY_IMAGE`.
- [ ] `make deployment-secret-rotation-rehearsal-plan` prints the Kubernetes
      secret rotation rehearsal steps for an active runtime Secret and a staged
      Secret marked with `limes-axis.io/secret-rotation-target=staged`,
      including required key parity checks, `cmp -s`,
      `secret-rotation.summary.json`, `secret-rotation.sha256` and no raw
      secret output; live execution also requires
      `AXIS_SECRET_ROTATION_IMAGE`.
- [ ] `make deployment-ha-rehearsal-plan` prints the Kubernetes HA restart
      rehearsal steps for sequential API/web `kubectl rollout restart`,
      `kubectl rollout status`, `kubectl wait --for=condition=available`,
      optional HPA/PDB checks, API `/ready` polling and `helm test`.
- [ ] `make deployment-load-rehearsal-plan` prints the bounded Kubernetes load
      rehearsal steps for short-lived Fortio Jobs, including
      `kubectl create job`, `kubectl wait --for=condition=complete`,
      `kubectl logs`, cleanup and API/web target URLs.
- [ ] `make deployment-tls-readiness-plan` prints the Kubernetes TLS readiness
      rehearsal steps for Ingress, TLS Secret, cert-manager Certificate,
      `dig +short`, `openssl s_client` and HTTPS reachability checks.
- [ ] `make container-check` passes the API/web Dockerfile, `.dockerignore`,
      Makefile and public deployment documentation contract.
- [ ] `make demo-backup-plan` prints the local backup commands and artifacts
      without touching local runtime state.
- [ ] `make demo-backup-local` captures `postgres.dump`, `minio-data.tar.gz`,
      `typedb-data.tar.gz` and a checksum manifest for the Docker Compose demo
      stack.
- [ ] `AXIS_BACKUP_DIR=.axis/backups/<backup-id> make demo-restore-local`
      restores local demo state only after explicit confirmation in the target.
- [ ] `make demo-check-live` passes `/health`, `/ready` and web home checks.
- [ ] `make demo-check-live` passes the browser no-store CORS preflight used by
      API-required console pages, including the `3100` origins used by
      production-build Playwright checks.
- [ ] `make demo-check-live` verifies the manufacturing operations snapshot
      returns persisted tenant-scoped domain rollups.
- [ ] `make demo-check-live` verifies the demo readiness report is derived
      from persisted demo evidence.
- [ ] `make demo-check-live` verifies the OIDC readiness report is explicit,
      public-safe and clear about whether enterprise SSO hardening is ready.
- [ ] `make demo-check-live` verifies the deployment readiness report is
      explicit, public-safe and clear about current production blockers.
- [ ] `make demo-check-live` verifies the support diagnostics bundle is
      explicit, public-safe and clear about support blockers.
- [ ] The console shell uses the Axis brand palette and passes browser checks
      for dark theme tokens, visible API-backed state and no horizontal
      overflow.
- [ ] `pnpm --filter @limes-axis/web test:e2e` passes API-unavailable smoke
      tests against a production build with browser-local fallbacks disabled.
- [ ] `pnpm --filter @limes-axis/web test:e2e:live` passes the live overview and
      product-story checks against the running Axis API without flaky retries or
      skipped stateful cases.
- [ ] The overview page loads from `/demo/manufacturing/overview`.
- [x] The overview page composes `/demo/manufacturing/operations/snapshot` into
      the first-screen operational cockpit.
- [x] `/demo/manufacturing/demo-readiness` serves the readiness report as an
      API surface; the redesigned overview no longer renders it as a
      first-screen panel.
- [ ] The ontology page loads from `/demo/manufacturing/ontology`.
- [ ] The workflow page loads from `/demo/manufacturing/workflows`.
- [ ] The approval inbox loads from `/demo/manufacturing/approvals`.
- [ ] The audit explorer loads from `/demo/manufacturing/audit`.
- [ ] The agents page loads from `/demo/manufacturing/agents`.
- [ ] The actions page loads from `/demo/manufacturing/actions`.
- [ ] The model routing page loads from `/demo/manufacturing/model-routing`.
- [ ] The simulation page loads from `/demo/manufacturing/simulation/replay`.
- [ ] The connectors page loads from `/demo/manufacturing/connectors`.
- [x] The manufacturing operations snapshot loads from
      `/demo/manufacturing/operations/snapshot`.
- [x] The demo readiness report loads from
      `/demo/manufacturing/demo-readiness`.
- [x] A daily plant brief can be generated with persisted audit evidence.
- [x] Quality, maintenance and supplier risk scenarios can be generated with
      persisted audit evidence.
- [x] The Operations page exposes the artifact generation walkthrough through
      API-backed, OIDC-scope-gated browser actions.
- [x] A guided local Keycloak/browser SSO setup lets design partners execute
      gated Operations mutations without manually pasting bearer tokens.
- [ ] Connector manifest, configuration, credential handle and credential lease
      paths reject raw secret material.
- [ ] Connector evidence snapshots and exports use persisted audit artifacts.
- [ ] External model egress remains disabled unless explicitly configured.
- [ ] Live source-system connector execution remains blocked unless the guarded
      opt-in runtime boundary is configured.

## SME Feedback Demo

The SME demo should focus on operational governance:

- How Axis sits above ERP, MES, QMS, CMMS and supplier systems.
- How the ontology turns operational records into governed relationships.
- How approvals, actions, workflows, audit and agent boundaries are connected.
- How sensitive connector operations are staged through manifests, credential
  handles, leases, egress policies and evidence snapshots.
- How a plant manager or operations leader can review risk, action proposals
  and evidence without trusting an ungoverned agent.

Feedback to collect:

- Which operational systems must be connected first.
- Which approval gates map to existing SOPs.
- Which fields must be added to the manufacturing operations reference.
- Which audit exports are needed for internal governance or customers.
- Which deployment posture is acceptable: SaaS, managed single tenant,
  private cloud or on-prem.

## Enterprise Evaluation Demo

The enterprise evaluation demo should be framed as a product and architecture
walkthrough, not a production readiness claim.

Show:

- The self-hosted local stack and absence of required managed services.
- The OIDC/Keycloak direction, token-bound mutation paths, authorization-code
  session-cookie boundary, secure browser-session readiness gate, OIDC
  readiness report and guided local Keycloak browser SSO setup. Enterprise SSO
  hardening remains separate from the local-only demo realm.
- The support diagnostics bundle and current support operations runbook.
- The first Helm deployment baseline in `infra/helm/limes-axis`, the
  deployment guide and the `deployment-check` output.
- The API and web image baseline, local build commands and the
  `container-check` output.
- The current threat model, including assets, trust boundaries, abuse paths,
  existing controls and open production hardening work.
- Tenant-scoped persisted reference records.
- Append-only audit events, export manifests and signature evidence.
- Deferred runtime boundaries for risky or external operations.
- The private commercial source-of-truth topology and the blocked-by-default
  path to a future, fresh-history OSS export.

Confirm before the session:

- No customer secrets are entered.
- No production source systems are connected.
- No unmanaged external model egress is enabled.
- No production deployment or compliance certification is claimed.

## Current Limitations

- Full live connector execution is not yet the default demo path. The current
  live capability is a bounded opt-in Postgres read path that requires
  `active_live` manifests, preflight gates, a targeted worker checkpoint claim
  and a configured allowlisted profile; it persists counts and public-safe
  evidence only.
- Full manufacturing operations reference demo remains open until broader
  TypeDB query coverage, workflow execution and replay are fully backed by real
  persistence paths.
- The first Helm chart and Kubernetes deployment guide are present, including
  optional External Secrets Operator synchronization, optional TLS Ingress
  routing and optional cert-manager ingress-shim annotations for runtime
  services plus optional HorizontalPodAutoscaler and PodDisruptionBudget
  controls, scheduling/topology pass-through values and configurable rollout
  controls for RollingUpdate strategy, revision history, termination grace and
  lifecycle hooks, a Postgres production backup rehearsal plan, an isolated
  Postgres restore rehearsal plan, a TypeDB recovery rehearsal plan and an
  object storage recovery rehearsal plan, a Temporal recovery evidence
  rehearsal plan, an active/staged Secret rotation rehearsal plan, a HA restart
  rehearsal, a bounded load rehearsal and a TLS readiness rehearsal, but
  sustained customer-profile HA validation under load, automated
  DNS/certificate operations, renewal drills, full cluster
  backup/restore across Temporal persistence, full-bucket object storage
  restore, rollout-drain exercises, full load/capacity planning,
  secret-manager rotation drills and access reviews are not complete.
- Local Docker Compose backup and restore procedures are available for
  repeatable demos; production backup, restore, retention, HA and disaster
  recovery procedures are not complete.
- Enterprise SSO hardening now has an explicit API readiness profile, IdP
  onboarding API report, PKCE authorization-code, HTTP-only session-cookie API
  boundary, secure browser-session deployment gate and server-side local and
  federated logout revocation, but refresh-token rotation and production SSO
  operations runbooks are not complete.
- API rate limiting is available and tracked by deployment readiness, but
  global abuse throttling, alerting and incident response runbooks are not
  complete.
- S3/MinIO WORM adapter readiness and a bounded object storage recovery
  rehearsal exist for governed connector evidence exports, but customer bucket
  provisioning review, KMS policy, legal operations and full-bucket restore
  drills are not complete.
- Production support-readiness checks now include support model, escalation,
  SLO and support commitment gates, but actual signed customer agreements,
  personal staffing assignments and legal documents remain external
  commercial artifacts.
- Deployment tenancy profile gates now distinguish `saas_multi_tenant`,
  `single_tenant_managed`, `private_cloud` and `on_prem`, but complete
  customer-specific dedicated deployment reference architectures remain future
  hardening work.
- External model-provider execution is disabled by default.

## Automated Checks

The `services/api/scripts/check_demo_environment.py` script verifies:

- Demo Makefile targets.
- Local demo backup and restore Makefile targets.
- Local Docker Compose runtime services.
- Critical OpenAPI routes.
- Demo readiness documentation and README links.
- Backup and restore runbook commands, artifact names and destructive-restore
  warning language.
- Browser no-store CORS preflight for API-required console fetches across the
  local dev and Playwright production-build origins.
- Manufacturing operations snapshot contract with persisted domain rollups.
- Demo readiness report contract with tracks, checks and an explicit
  `derived_from_persisted_demo_evidence` boundary.
- OIDC readiness report contract with public-safe identity configuration
  status and no secret disclosure.
- Deployment readiness report contract with public-safe production blockers for
  identity, OIDC secure-cookie/session posture, external model egress,
  connector execution, audit signing and object-store posture.
- Deployment package contract for `infra/helm/limes-axis`, public deployment
  docs and externalized Kubernetes Secret usage through `make deployment-check`.
- Helm profile render gate for single-tenant managed, private-cloud and
  on-prem/offline overlays through `make deployment-profile-render-check`.
- Deployment rollout rehearsal plan for Helm upgrade, Kubernetes rollout
  status, API `/ready` and rollback mechanics through
  `make deployment-rollout-rehearsal-plan`.
- Helm smoke-test hook for in-cluster API `/ready` and web service checks
  through `helm test`.
- Secret rotation rehearsal plan for active/staged runtime Secret comparison,
  required key parity checks, redacted key-status evidence and SHA-256
  fingerprints without raw secret output through
  `make deployment-secret-rotation-rehearsal-plan`.
- HA restart rehearsal plan for API/web workload restart mechanics,
  Kubernetes availability waits, optional HPA/PDB checks and Helm smoke tests
  through `make deployment-ha-rehearsal-plan`.
- Bounded load rehearsal plan for short-lived Fortio Kubernetes Jobs,
  `kubectl create job`, `kubectl logs` evidence and cleanup through
  `make deployment-load-rehearsal-plan`.
- TLS readiness rehearsal plan for Ingress, cert-manager Certificate, DNS,
  `openssl s_client` and HTTPS reachability checks through
  `make deployment-tls-readiness-plan`.
- Container image package contract for API/web Dockerfiles, local build
  commands and `.dockerignore` through `make container-check`.
- Support diagnostics report contract with public-safe support model readiness,
  SLO targets, escalation channel classes, support commitment booleans, support
  blockers, artifact links and redaction policy.
- Threat model and security posture contract through `make security-check`.
- Optional live API and web checks when URLs are provided.

The check is intentionally conservative. If a demo command, route or document
is removed, the test suite should fail before a feedback session relies on a
broken path.
