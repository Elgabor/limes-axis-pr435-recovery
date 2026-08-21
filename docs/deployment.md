# Deployment Baseline

This page defines the first Kubernetes and Helm deployment baseline for the
Limes Axis open core. It is a self-hostable package for enterprise evaluation,
cluster planning and future hardening. It is not a production certification.

The chart lives in `infra/helm/limes-axis` and currently deploys only the Axis
API and web console. The repository includes local API and web image builds,
while production operators must still supply signed, published images and the
external services that the open core depends on.

## Shared request admission control

Production replicas must share one Redis-compatible rate-limit backend. Set
`AXIS_API_RATE_LIMIT_BACKEND=redis`, `AXIS_API_RATE_LIMIT_FAILURE_MODE=closed`,
and provide `AXIS_REDIS_URL` through the deployment Secret rather than the Helm
ConfigMap. Startup rejects a production profile that enables rate limiting with
an in-memory backend, an open failure mode, no Redis URL, or less than full
route coverage (`AXIS_API_RATE_LIMIT_PATHS=["*"]`). Verified bearer and browser
sessions share tenant quota buckets. The in-memory backend remains available
only for local development and tests.

Production startup also rejects a disabled API limiter. `/health` remains a
process-local liveness signal and is never gated by Redis or request quotas;
`/ready` remains the dependency-aware traffic admission signal. The chart maps
the Redis URL through `secrets.existingSecret` or the optional ExternalSecret.

Production startup also requires
`AXIS_TENANT_ADMISSION_MODE=registered_only`. In that mode, a valid OIDC tenant
claim is necessary but not sufficient: the tenant must have a persisted,
active platform tenant record. Unknown, suspended and pending-deletion tenants
fail closed before route logic or browser-session creation. The default
`claims_only` mode remains available only for local/demo environments that have
not populated the tenant registry yet.

### Apply database migrations once

Before `/ready` is allowed into service and before the first-tenant bootstrap,
one designated migration owner must run the packaged Alembic upgrade from the
same immutable API image and Secret-backed environment:

```bash
kubectl -n limes-axis exec deployment/limes-axis-api -c api -- \
  alembic upgrade head
kubectl -n limes-axis exec deployment/limes-axis-api -c api -- \
  alembic current
```

Adjust the namespace and Deployment name when the Helm release is renamed.
Wait for both commands to exit successfully and confirm `alembic current`
reports the expected head before admitting traffic. Run this gate once per
release; do not launch concurrent migration owners. The API image packages
`alembic.ini` and the migration tree, while `/ready` remains the fail-closed
traffic gate if the schema or another dependency is unavailable.

### Bootstrap the first registered tenant

An empty `registered_only` deployment intentionally rejects every OIDC tenant,
including a platform operator, until the first active tenant exists. After the
database migrations finish and before the first operator login, run the
packaged one-shot command from the same immutable API image and with its normal
`AXIS_POSTGRES_DSN` Secret environment:

```bash
kubectl -n limes-axis exec deployment/limes-axis-api -c api -- \
  axis-bootstrap-first-tenant \
  --tenant-id tenant_axis_platform_ops \
  --display-name "Axis platform operators" \
  --operator-id deployment-bootstrap \
  --idempotency-key first-tenant-v1 \
  --bootstrap-admin-id platform-operator-role \
  --bootstrap-admin-display-name "Platform operator" \
  --bootstrap-admin-scope platform:tenant:operator \
  --bootstrap-admin-scope platform:tenant:provision
```

The command uses direct database authority, records the operator identity and
requested IdP-owned admin scopes as audit evidence, and creates the tenant via
the same domain permission and idempotency path as `POST /platform/tenants`.
It also appends `platform.tenant.first_bootstrap.completed` with
`authority=direct_database`; it never grants scopes in Axis. Concurrent
attempts are serialized; an exact replay is safe and emits no duplicate audit
event. Reusing the same key with changed tenant, admin, scope or note evidence
is refused with `provision_idempotency_conflict`; a different request after the
registry is initialized is refused with `tenant_registry_already_initialized`.
After this one bootstrap, use the authenticated platform-tenant API for every
additional tenant. Do not temporarily switch production to `claims_only` to
work around the admission boundary.

The local Compose stack includes persistent Valkey on port `6379` for
integration testing. Customer deployments should use a monitored, redundant
Redis or Valkey service with authentication and TLS appropriate to their
availability requirements.

## Scope

The baseline covers:

- API deployment and service.
- Web console deployment and service.
- ConfigMap for public-safe runtime configuration.
- Kubernetes Secret reference for sensitive runtime values.
- Example Secret template disabled by default.
- Optional External Secrets Operator `ExternalSecret` template that syncs the
  same runtime Secret name from an operator-managed `SecretStore` or
  `ClusterSecretStore`.
- Optional Kubernetes `Ingress` template for routing web and API hosts, with
  TLS secret references supplied by the operator.
- Optional cert-manager ingress-shim annotations for operator-managed TLS
  certificate issuance.
- Helm `values.schema.json` schema validation for tenancy modes, egress modes,
  ExternalSecret policies, cert-manager issuer kind and availability knobs.
- Optional `HorizontalPodAutoscaler` and `PodDisruptionBudget` templates for
  API and web console workloads.
- A TLS readiness rehearsal script and runbook for Ingress, TLS Secret,
  cert-manager Certificate, DNS, TLS handshake and HTTPS reachability checks
  against operator-selected hosts.
- Deployment rollout controls for API and web console workloads, including
  `RollingUpdate` strategy values, `revisionHistoryLimit`,
  `terminationGracePeriodSeconds` and optional container `lifecycle`
  pass-through hooks.
- A rollout rehearsal script and runbook for `helm upgrade --install`,
  `kubectl rollout status`, optional API `/ready` polling and `helm rollback`
  against an operator-selected Kubernetes context.
- A HA restart rehearsal script and runbook for sequential API/web
  `kubectl rollout restart`, `kubectl rollout status`,
  `kubectl wait --for=condition=available`, optional HPA/PDB checks, optional
  API `/ready` polling and `helm test`.
- A bounded load rehearsal script and runbook that creates short-lived Fortio
  Kubernetes Jobs, waits for completion, captures `kubectl logs` evidence and
  cleans up Jobs against operator-selected API and web targets.
- A Helm smoke test hook that runs with `helm test` and checks the API `/ready`
  endpoint plus the web console service from inside the cluster.
- A production backup rehearsal plan for in-cluster Postgres `pg_dump` capture
  and `pg_restore --list` restore-catalog validation without printing database
  connection secrets.
- A production restore rehearsal plan for restoring a captured Postgres dump
  into a separately configured isolated restore target without printing target
  connection secrets.
- A TypeDB recovery rehearsal plan that exports the runtime graph with
  `database export` and imports it into a separately configured isolated
  restore target with `database import` without printing TypeDB credentials.
- An object storage recovery rehearsal plan that writes a bounded S3-compatible
  probe object, copies it to a separately configured isolated restore bucket
  with MinIO Client and verifies the restored bytes by checksum without
  printing S3 credentials.
- A Temporal recovery rehearsal plan that uses Temporal CLI from an isolated
  non-root Pod to capture cluster health, namespace metadata, workflow list
  and a replay-compatible workflow history JSON without printing Temporal
  credential material.
- A secret rotation rehearsal plan that compares the active runtime Secret
  with a separately staged Secret, captures redacted fingerprint evidence and
  checks key parity without printing secret values.
- Service account and pod security context.
- Initial NetworkPolicy for ingress, egress shaping, restricted CIDR allowlists
  and offline mode.
- Public-safe install notes and local readiness checks.
- Local API and web Dockerfile baselines.
- GHCR container release workflow with SBOM, keyless signing, provenance
  attestations, build-only checks and a GitHub Environment reviewer protection
  hook for manually approved publish runs.
- Container vulnerability scanning policy baseline for API and web images.
- Vulnerability management baseline with SARIF publication and expiring
  exception policy.
- Public-safe production support-readiness configuration for SLO response
  targets, escalation channel classes, customer runbook presence, status page
  presence and required incident review.
- Public-safe production disaster-recovery procedure readiness configuration for
  approved runbook presence, RPO/RTO definition, rehearsal evidence, restore
  ownership and customer approval.
- Public-safe network egress readiness configuration for restricted mode,
  offline mode and explicit destination allowlist evidence.
- Public-safe deployment tenancy profile readiness configuration for
  `saas_multi_tenant`, `single_tenant_managed`, `private_cloud` and `on_prem`
  paths, with explicit isolation, data-residency, operator-access and
  break-glass evidence gates.

The baseline does not yet cover:

- Sustained customer-profile high availability validation under load.
- Full load testing, capacity planning and rollout-drain validation.
- Customer-specific NetworkPolicy destination ownership review and service-mesh
  or firewall enforcement outside the chart.
- Automated TLS certificate issuance operations, DNS ownership attestation,
  renewal drills and HSTS/CDN/WAF policy.
- Production secret-manager rotation drills, access reviews, workload restart
  validation, KMS policy review and incident procedures.
- Full production backup, restore and disaster recovery operations execution
  across Postgres, TypeDB, Temporal persistence and object storage beyond the
  public-safe procedure readiness gate.
- S3-compatible object storage with object lock, legal hold operations and
  provider KMS policy.
- Cluster observability, alerting, global abuse throttling and on-call runbooks.
- Signed customer SLAs, named staffing commitments and customer-specific
  incident operations.
- A complete customer-specific single-tenant managed, private-cloud or on-prem
  reference architecture. The current chart exposes readiness gates for those
  paths, but does not yet package every customer infrastructure pattern.

## Dependencies

Axis remains self-hostable and does not require managed services, but the Helm
chart expects production-grade dependencies to be provided outside the chart:

- external Postgres with `AXIS_POSTGRES_DSN` stored in a Kubernetes Secret.
- TypeDB reachable through `AXIS_TYPEDB_ADDRESS`. Required only when the
  ontology query or mutation paths are enabled (see below); otherwise the
  deferred runtimes serve the persisted reference graph and no TypeDB
  connection is used.
- Temporal OSS reachable through `AXIS_TEMPORAL_ADDRESS`.
- OIDC provider, normally Keycloak or an enterprise IdP, with issuer, audience
  and JWKS URL configured.
- S3-compatible object storage for governed export paths.
- Kubernetes Ingress controller when `ingress.enabled=true`.
- Optional cert-manager installation and issuer when
  `ingress.certManager.enabled=true`.

The chart does not create Postgres, TypeDB, Temporal, MinIO or Keycloak. The
Docker Compose stack remains the local demo path; Kubernetes production
operators should bring hardened dependencies that match their infrastructure
policy.

## Ontology Graph Mutation

Connector ontology promotions can write governed entities into TypeDB. The live
path is off by default; existing deployments are unaffected until it is enabled.

- **Flags.** `AXIS_ONTOLOGY_MUTATIONS_ENABLED` gates real TypeDB writes and
  `AXIS_ONTOLOGY_QUERIES_ENABLED` gates TypeDB reads. Both default `false` and
  are process-global (there is no per-tenant enablement). Enable them together
  so promoted nodes can be read back; enabling mutations alone writes nodes that
  the ontology read API will not serve.
- **TypeDB requirement.** When mutations are enabled, a reachable TypeDB
  (`AXIS_TYPEDB_ADDRESS`, `AXIS_TYPEDB_USERNAME`/`PASSWORD`,
  `AXIS_TYPEDB_DATABASE`) is required. Load the `axis_` meta-ontology schema once
  per environment before the first promotion:

  ```
  cd services/api && uv run python -m axis_api.ontology.bootstrap
  ```

  The command is idempotent and creates the database if absent.
- **Safety.** Each promotion is one atomic TypeDB write transaction using an
  idempotent `put` pipeline keyed on `axis_id`, followed by a read-back that must
  observe the node before the proposal is marked `promoted_to_graph`. TypeDB
  unavailability or a failed read-back is fail-closed (`type_db_mutation_unavailable`
  / `type_db_mutation_failed`); the proposal stays promotable and retries are
  safe. See [Platform Connectors](platform-connectors.md) for the full gate list.
- **Readiness.** `GET /deployment/readiness` includes an
  `ontology_graph_mutation_posture` check that flags mutations enabled without a
  TypeDB address or without reads enabled. `GET /ready` reports
  `typedb_mutations` and `typedb_queries`.

## Worker Deployment

The Temporal worker (`services/worker`) is deployed as its own workload
alongside the API and web Deployments. It hosts the approval workflow plus the
scheduled maintenance workflows and their DB-owning activities, and on startup it
reconciles the Temporal Schedules for periodic maintenance (see
[Platform Scheduled Jobs](platform-scheduled-jobs.md)).

- **Helm**: `templates/worker-deployment.yaml` renders a `worker` Deployment
  (enabled by default via `worker.enabled`) that shares the platform ConfigMap
  and runtime Secret, so it reads the same `AXIS_POSTGRES_DSN` and
  `AXIS_TEMPORAL_ADDRESS` as the API. Schedule intervals and the master enable
  flag live under `worker.scheduledJobs` in `values.yaml`. A single replica is
  used so schedule reconciliation is not duplicated; the schedule overlap policy
  guards against overlapping runs regardless of replica count.
- **Approval delivery**: the transactional approval-decision outbox has
  separate API enqueue and worker dispatch gates. Both are off by default. Use
  the worker-first rollout and drain-first rollback in
  [Approval Decision Outbox](approval-decision-outbox.md); it does not depend on
  the scheduled-maintenance master switch.
- **Docker Compose**: the `worker` service is built from
  `services/worker/Dockerfile` and depends on `postgres` (healthy) and
  `temporal`.
- **Local**: `make worker` runs `python -m axis_worker` against the dev stack.
- **Images**: `make container-build-worker` builds `limes-axis-worker:local`.

Scheduled maintenance jobs are opt-in (`AXIS_SCHEDULED_JOBS_ENABLED=false` by
default): the worker always reconciles the schedules and forces them paused while
the flag is disabled. Enabling the flag does not reactivate schedules that an
operator has explicitly paused.

Approval-decision dispatch is configured independently through
`worker.approvalDecisionOutbox` in Helm. Keep
`api.env.AXIS_APPROVAL_DECISION_OUTBOX_ENABLED=false` until the compatible
worker is deployed and `worker.approvalDecisionOutbox.dispatchEnabled=true` is
healthy.

## Ingress And TLS

The chart can render a Kubernetes `networking.k8s.io/v1` `Ingress` when
`ingress.enabled=true`. Ingress is disabled by default. When enabled, each host
entry routes paths to either the web console service or the API service by name.
TLS is configured through `ingress.tls[]` entries and references an existing
Kubernetes TLS Secret through `secretName`.

When a cluster already runs cert-manager, operators can set
`ingress.certManager.enabled=true` and provide `issuerName`, `issuerKind` and
`issuerGroup`. The chart then emits ingress-shim annotations so cert-manager can
create a `Certificate` for each configured `ingress.tls[].secretName`. Built-in
`ClusterIssuer` and `Issuer` values use the standard cert-manager annotations;
external issuers also emit issuer kind and issuer group annotations.

The chart does not install an Ingress controller, cert-manager, DNS records or
certificate issuers. Operators must provision those resources according to
their cluster policy and verify DNS ownership, certificate renewal and secure
host routing against the final public hostnames before production use.
`/deployment/readiness` separately gates secure OIDC browser-session posture.

## TLS Readiness Rehearsal

The repository includes a TLS readiness rehearsal tool:

```bash
make deployment-tls-readiness-plan
AXIS_KUBE_CONTEXT=production-eu make deployment-tls-readiness
```

The detailed runbook lives in
[`docs/deployment-tls-readiness.md`](./deployment-tls-readiness.md). The script
is intentionally split into plan and execute modes. Plan mode prints the exact
`kubectl`, `dig +short`, `openssl s_client` and `curl` commands. Execute mode
runs against the operator-provided Kubernetes context and externally reachable
HTTPS hosts.

This verifies observable Ingress, TLS Secret, cert-manager Certificate, DNS,
TLS handshake and HTTPS reachability behavior. It is not certificate
automation, DNS ownership proof, renewal validation, HSTS/CDN/WAF validation,
penetration testing or production certification.

## Availability Controls

The chart can render Kubernetes `autoscaling/v2` `HorizontalPodAutoscaler`
objects and `policy/v1` `PodDisruptionBudget` objects for both the API and web
console. They are disabled by default and can be enabled independently with
`api.autoscaling.enabled`, `web.autoscaling.enabled`, `api.pdb.enabled` and
`web.pdb.enabled`.

When an autoscaler is enabled for a workload, the corresponding Deployment does
not render a fixed `replicas` value; the HPA owns replica count inside the
configured `minReplicas` and `maxReplicas` bounds. PDBs use `minAvailable` and
select the same component labels as the API and web Deployments.

These controls are a chart-level availability baseline. They do not replace
load testing, capacity planning, cluster resource quotas, node failure tests,
upgrade rollback drills or production SLO review.

## Rollout Controls

The API and web Deployments expose per-workload rollout controls. By default,
both workloads use a Kubernetes `RollingUpdate` strategy with
`maxUnavailable: 0`, `maxSurge: 1`, `revisionHistoryLimit: 5` and
`terminationGracePeriodSeconds: 30`. The chart also exposes a container-level
`lifecycle` pass-through for each workload so operators can add pre-stop or
other lifecycle hooks that match their image, ingress and workload-draining
policy.

The default lifecycle value is empty. Axis does not assume a shell, sidecar or
cluster-specific drain endpoint inside the container image. Operators should
configure lifecycle hooks only after validating the deployed image and ingress
behavior, then test rollouts, readiness gates, connection draining, rollback
criteria and interrupted in-flight requests in their target cluster.

## Rollout Rehearsal

The repository includes a real rollout rehearsal tool:

```bash
make deployment-rollout-rehearsal-plan
AXIS_KUBE_CONTEXT=production-eu make deployment-rollout-rehearsal
```

The detailed runbook lives in
[`docs/deployment-rollout-rehearsal.md`](./deployment-rollout-rehearsal.md).
The script is intentionally split into plan and execute modes. Plan mode prints
the exact `helm` and `kubectl` commands. Execute mode runs against the
operator-provided Kubernetes context, waits for API and web Deployment rollout,
can poll an externally reachable API `/ready` URL and can run `helm rollback`
when the rehearsal includes rollback validation.

This is an operational rehearsal baseline. It is not a production
certification and does not replace cluster-specific load, failover,
backup/restore, SSO, secret-rotation or incident-response drills.

## HA Restart Rehearsal

The repository includes a real HA restart rehearsal tool:

```bash
make deployment-ha-rehearsal-plan
AXIS_KUBE_CONTEXT=production-eu make deployment-ha-rehearsal
```

The detailed runbook lives in
[`docs/deployment-ha-rehearsal.md`](./deployment-ha-rehearsal.md). The script
is intentionally split into plan and execute modes. Plan mode prints the exact
`kubectl` and `helm test` commands. Execute mode runs against the
operator-provided Kubernetes context, captures workload and pod inventory,
optionally requires HPA and PDB resources, restarts API and web Deployments one
at a time, waits for rollout status and Kubernetes availability, can poll an
externally reachable API `/ready` URL after each restart and can run the Helm
smoke test hook.

This verifies controlled restart mechanics. It is not a load test, node
failover test, zone failover test, production SLO proof or disaster recovery
certification.

## Load Rehearsal

The repository includes a bounded load rehearsal tool:

```bash
make deployment-load-rehearsal-plan
AXIS_KUBE_CONTEXT=production-eu make deployment-load-rehearsal
```

The detailed runbook lives in
[`docs/deployment-load-rehearsal.md`](./deployment-load-rehearsal.md). The
script is intentionally split into plan and execute modes. Plan mode prints the
exact `kubectl create job`, `kubectl wait`, `kubectl logs` and cleanup
commands. Execute mode runs against the operator-provided Kubernetes context
and creates short-lived `fortio` Jobs for the configured targets.

By default, the script targets the in-cluster API `/ready` endpoint and the web
home service URL for the Helm release. Operators can provide explicit
`--target name=url` values to rehearse ingress, service mesh or customer-like
paths.

This verifies bounded Job-based request execution and service reachability. It
is not a sustained capacity plan, autoscaler-tuning proof, node failover test,
zone failover test, denial-of-service test or production SLO certification.

## Helm Smoke Tests

The chart includes an optional `helm test` smoke pod. It uses the pinned
`busybox` image configured under `tests.smoke.image`, runs with a restricted
container security context and checks both in-cluster services:

- `http://<release>-api:<api.service.port>/ready`
- `http://<release>-web:<web.service.port>/`

The hook is enabled by default with `tests.smoke.enabled=true` and is not run
during `helm upgrade --install`. Run it explicitly after an install or during a
rollout rehearsal:

```bash
helm test limes-axis --namespace limes-axis --timeout 10m
```

The chart NetworkPolicy includes a narrow same-release egress rule for the
smoke test path so the hook can reach the API and web pods without opening a
generic egress path. Operators can disable the hook with
`--set tests.smoke.enabled=false` if their cluster provides a separate
post-install validation path.

This test verifies service reachability and basic application readiness from
inside the cluster. It is not a load test, dependency failover test, SSO test,
connector execution test or production certification.

## Network Egress Modes

The chart exposes `networkPolicy.egressMode` with three modes:

- `port_allowlist`: preserves the initial chart behavior by allowing configured
  ports through `networkPolicy.allowedEgressPorts` without destination binding.
  This is useful during evaluation, but `/deployment/readiness` reports
  `network_egress_restricted` as action-required for production.
- `restricted`: renders `ipBlock` rules for each CIDR in
  `networkPolicy.allowedEgressCidrs`, limited to the configured
  `networkPolicy.allowedEgressPorts`.
- `offline`: renders no generic external egress rule. DNS and the optional
  same-release Helm smoke-test rule remain the only chart-managed egress paths.

The API receives the public-safe posture through
`AXIS_DEPLOYMENT_NETWORK_POLICY_ENABLED`,
`AXIS_DEPLOYMENT_NETWORK_EGRESS_MODE` and
`AXIS_DEPLOYMENT_NETWORK_EGRESS_ALLOWLIST_CONFIGURED`. The readiness endpoint
does not expose destination CIDRs, customer network names, firewall policy IDs
or private endpoint names. Restricted mode is production-ready only when at
least one CIDR allowlist is configured; offline mode is production-ready without
external destination allowlists.

## Deployment Tenancy Profiles

The chart exposes `AXIS_DEPLOYMENT_TENANCY_MODE` so operators can identify the
deployment path being evaluated:

- `saas_multi_tenant`: shared SaaS control plane with tenant isolation controls.
- `single_tenant_managed`: dedicated customer runtime managed by the operator.
- `private_cloud`: customer-dedicated runtime in a private cloud environment.
- `on_prem`: customer-operated or jointly operated runtime inside customer
  infrastructure.

The deployment readiness endpoint reports this as
`deployment_tenancy_profile`. It is action-required until the selected profile
has public-safe evidence configured through
`AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED`,
`AXIS_DEPLOYMENT_DATA_RESIDENCY_CONFIGURED`,
`AXIS_DEPLOYMENT_OPERATOR_ACCESS_RUNBOOK_CONFIGURED` and
`AXIS_DEPLOYMENT_BREAK_GLASS_APPROVAL_CONFIGURED`.

These fields are intentionally boolean/public-safe. They do not expose customer
names, tenant identifiers, network details, staff names, access procedures or
legal terms. They are readiness gates for the deployment conversation, not a
complete single-tenant managed, private cloud or on-prem implementation.

The chart also includes public-safe values overlays for the first dedicated
deployment paths:

- `profiles/single-tenant-managed.yaml`
- `profiles/private-cloud.yaml`
- `profiles/on-prem-offline.yaml`

Render or install them with the normal chart plus `-f`:

```bash
helm template limes-axis infra/helm/limes-axis -f infra/helm/limes-axis/profiles/single-tenant-managed.yaml
helm template limes-axis infra/helm/limes-axis -f infra/helm/limes-axis/profiles/private-cloud.yaml
helm template limes-axis infra/helm/limes-axis -f infra/helm/limes-axis/profiles/on-prem-offline.yaml
helm upgrade --install limes-axis infra/helm/limes-axis -f infra/helm/limes-axis/profiles/single-tenant-managed.yaml
helm upgrade --install limes-axis infra/helm/limes-axis -f infra/helm/limes-axis/profiles/private-cloud.yaml
helm upgrade --install limes-axis infra/helm/limes-axis -f infra/helm/limes-axis/profiles/on-prem-offline.yaml
```

`make deployment-profile-render-check` is the local profile render gate. It
executes `helm template` for every dedicated deployment overlay and checks that
the rendered manifests still contain the expected tenancy mode, egress mode,
ExternalSecret, HPA/PDB, NetworkPolicy, profile annotation and public-safe
customer-evidence defaults. Dedicated profile renders must not include a local
Kubernetes `Secret` or `REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE` placeholder;
secret material must come from the configured external secret manager boundary.

The overlays enable enterprise-shaped defaults such as required OIDC,
Secure-session cookies, ExternalSecret usage, HPA/PDB availability controls,
profile annotations and restricted or offline NetworkPolicy posture. They do
not set customer-specific evidence gates to `true`; operators must explicitly
set isolation, data-residency, operator-access and break-glass evidence only
after the real customer environment has been reviewed.

## Production Backup Rehearsal

The repository includes a production backup rehearsal helper for Kubernetes
clusters:

```bash
make deployment-backup-rehearsal-plan
```

The plan creates a short-lived Kubernetes Job that reads
`AXIS_POSTGRES_DSN` from the configured runtime Secret through `envFrom`,
runs `pg_dump "$AXIS_POSTGRES_DSN" --format=custom --no-owner`, validates the
dump catalog with `pg_restore --list`, captures a SHA-256 checksum and copies
`postgres.dump`, `postgres.restore.list` and `postgres.dump.sha256` to a local
evidence directory. The plan prints the Secret reference and Kubernetes
commands, but does not print the DSN value or other secret material. The Job
uses an explicit non-root security context, a short-lived `emptyDir` mounted at
`/backup` and configurable `--run-as-user` / `--run-as-group` values for
Postgres client images that use a UID/GID different from `postgres:16-alpine`.

To execute against a selected cluster context:

```bash
AXIS_KUBE_CONTEXT=prod-eu make deployment-backup-rehearsal
```

Operators can pass additional script arguments with
`AXIS_PRODUCTION_BACKUP_ARGS`, for example `--namespace`, `--runtime-secret`,
`--backup-id`, `--local-backup-dir`, `--image`, `--timeout`, `--run-as-user`,
`--run-as-group` or `--keep-job`.

This is a backup-capture and restore-catalog rehearsal for the current
Postgres operational store. It is not a full production disaster recovery
procedure: Temporal state policy, object-store retention, RPO/RTO evidence,
offsite retention and customer-specific approval gates remain hardening work.

## Production Restore Rehearsal

The repository also includes a production restore rehearsal helper for
Kubernetes clusters:

```bash
make deployment-restore-rehearsal-plan
```

The plan creates a temporary non-root Pod, copies a local `postgres.dump` and
`postgres.dump.sha256` into an in-cluster `emptyDir`, verifies the checksum,
validates the restore catalog with `pg_restore --list`, restores the dump with
`pg_restore --clean --if-exists --no-owner` and writes local evidence files for
the restore catalog, target probe and calculated checksum.

The restore target must be a separate Kubernetes Secret from the Axis runtime
Secret. It must contain `AXIS_POSTGRES_RESTORE_DSN` and carry the annotation
`limes-axis.io/restore-target=isolated`. The script checks the annotation and
the presence of the restore DSN key without printing the DSN value. The script
also refuses common runtime Secret names such as `limes-axis-runtime` for the
restore target.

To execute against a selected cluster context:

```bash
AXIS_KUBE_CONTEXT=prod-eu make deployment-restore-rehearsal
```

Operators can pass additional script arguments with
`AXIS_PRODUCTION_RESTORE_ARGS`, for example `--namespace`,
`--restore-target-secret`, `--restore-id`, `--dump-path`, `--checksum-path`,
`--local-evidence-dir`, `--image`, `--timeout`, `--run-as-user`,
`--run-as-group` or `--keep-pod`.

This is an isolated Postgres restore rehearsal for a captured Axis dump. It is
not a full production disaster recovery procedure: it does not restore
Temporal state or object storage, does not validate customer-specific retention
or legal-hold policy and does not establish RPO/RTO commitments.

## TypeDB Recovery Rehearsal

The repository includes a TypeDB recovery rehearsal helper for Kubernetes
clusters:

```bash
make deployment-typedb-recovery-rehearsal-plan
```

The plan creates a temporary non-root Pod using an operator-supplied container
image that includes TypeDB Console. It reads the Axis runtime TypeDB connection
values from the runtime Secret, first verifies `console --help`, runs TypeDB
Console `database export` to write `typedb.schema.typeql` and `typedb.data`,
records `typedb.sha256`, then imports the export into an isolated target using
`database import`.

The runtime Secret must provide `AXIS_TYPEDB_ADDRESS`,
`AXIS_TYPEDB_USERNAME`, `AXIS_TYPEDB_PASSWORD` and `AXIS_TYPEDB_DATABASE`. The
restore target must be a separate Kubernetes Secret from the Axis runtime
Secret. It must provide `AXIS_TYPEDB_RESTORE_ADDRESS`,
`AXIS_TYPEDB_RESTORE_USERNAME`, `AXIS_TYPEDB_RESTORE_PASSWORD` and
`AXIS_TYPEDB_RESTORE_DATABASE`, and it must carry the annotation
`limes-axis.io/typedb-restore-target=isolated`. The script checks the
annotation and required keys without printing connection values or password
material. The restore database should be an isolated, empty target chosen for
the rehearsal.

To execute against a selected cluster context:

```bash
AXIS_KUBE_CONTEXT=prod-eu \
AXIS_TYPEDB_RECOVERY_IMAGE=registry.example.com/platform/typedb-console:3.11.5 \
make deployment-typedb-recovery-rehearsal
```

`AXIS_TYPEDB_RECOVERY_IMAGE` must point to an image that contains TypeDB
Console for the target TypeDB version. The local TypeDB server image is not
assumed to include Console. Operators can pass additional script arguments with
`AXIS_TYPEDB_RECOVERY_ARGS`, for example `--namespace`, `--runtime-secret`,
`--restore-target-secret`, `--recovery-id`, `--local-evidence-dir`,
`--timeout`, `--run-as-user`, `--run-as-group` or `--keep-pod`. Runtime
environments that intentionally run TypeDB without TLS can set
`AXIS_TYPEDB_TLS_DISABLED=true` or `AXIS_TYPEDB_RESTORE_TLS_DISABLED=true`
inside the relevant Kubernetes Secret.

This is an export/import recovery rehearsal for the Axis TypeDB graph. It is
not a full production disaster recovery procedure: it does not coordinate
write quiescence across API, worker and connector processes, does not restore
Temporal state or object storage, does not establish retention policy, and does
not prove RPO/RTO commitments.

## Temporal Recovery Rehearsal

The repository includes a Temporal recovery rehearsal helper for Kubernetes
clusters:

```bash
make deployment-temporal-recovery-rehearsal-plan
```

The plan creates a temporary non-root Pod using an operator-supplied image that
contains Temporal CLI. It reads `AXIS_TEMPORAL_ADDRESS` and
`AXIS_TEMPORAL_NAMESPACE` from the Axis runtime ConfigMap, reads optional
Temporal auth settings from the runtime Secret and recovery Secret, first
verifies `temporal --help`, then captures:

- `temporal.cluster-health.json` with `operator cluster health`;
- `temporal.namespace.json` with `operator namespace describe`;
- `temporal.namespace-list.json` with `operator namespace list`;
- `temporal.workflow-list.json` with `workflow list`;
- `temporal.workflow-history.json` with `workflow show --output json`;
- `temporal.sha256` with checksums for the captured evidence.

The recovery Secret must be separate from the Axis runtime Secret. It must
provide `AXIS_TEMPORAL_RECOVERY_WORKFLOW_ID`, and it must carry the annotation
`limes-axis.io/temporal-recovery-target=isolated`. It may also provide
`AXIS_TEMPORAL_RECOVERY_RUN_ID`, `AXIS_TEMPORAL_RECOVERY_WORKFLOW_LIMIT`,
`AXIS_TEMPORAL_API_KEY` and `AXIS_TEMPORAL_TLS_ENABLED=true` when the target
Temporal service requires TLS or API-key auth. The script checks required keys
and the isolation annotation without printing API keys or other credential
material.

To execute against a selected cluster context:

```bash
AXIS_KUBE_CONTEXT=prod-eu \
AXIS_TEMPORAL_RECOVERY_IMAGE=registry.example.com/platform/temporal-cli:stable \
make deployment-temporal-recovery-rehearsal
```

`AXIS_TEMPORAL_RECOVERY_IMAGE` must point to an image that contains Temporal
CLI. Operators can pass additional script arguments with
`AXIS_TEMPORAL_RECOVERY_ARGS`, for example `--namespace`,
`--runtime-config-map`, `--runtime-secret`, `--recovery-secret`,
`--recovery-id`, `--local-evidence-dir`, `--timeout`, `--run-as-user`,
`--run-as-group` or `--keep-pod`.

This is a bounded read-only recovery evidence probe for Temporal. It proves
that an isolated operator path can reach the configured Temporal namespace,
capture replay-compatible workflow history for a selected workflow and produce
checksummed evidence. It does not restore Temporal persistence, does not replay
workflow code, does not validate history archival, does not coordinate
quiescence and does not establish RPO/RTO commitments.

## Scheduling Controls

The API and web Deployments expose Kubernetes scheduling pass-through values:
`nodeSelector`, `affinity`, `tolerations` and `topologySpreadConstraints`.
They are empty by default and can be configured independently for each
workload. This lets operators target dedicated node pools, tolerate tainted
nodes, express pod affinity or anti-affinity, and spread replicas across
failure domains such as zones or hosts.

The chart does not infer cluster topology. Operators must set selectors and
`topologySpreadConstraints` that match their cluster labels, capacity model and
availability targets, then verify scheduling behavior during load tests,
rollout drains and node-failure exercises.

The chart also does not install External Secrets Operator or create a
`SecretStore`/`ClusterSecretStore`. When `secrets.externalSecret.enabled=true`,
the chart renders an `ExternalSecret` that targets `secrets.existingSecret`;
cluster operators remain responsible for installing the operator, binding it to
their secret manager and reviewing the underlying KMS, access and rotation
policy.

## Observability (OpenTelemetry)

OpenTelemetry distributed tracing and metrics for the API and worker are off by
default (`observability.otel.enabled=false`, env `AXIS_OTEL_ENABLED=false`), so
existing deployments and the test suite are unaffected — no provider is
installed and instrumented code paths are no-ops. To enable, set
`observability.otel.enabled=true` and point `observability.otel.exporterOtlpEndpoint`
(env `AXIS_OTEL_EXPORTER_OTLP_ENDPOINT`) at an OTLP/HTTP collector; `/v1/traces`
and `/v1/metrics` are appended per signal. The chart wires these into the shared
ConfigMap for both the API and worker Deployments. `GET /deployment/readiness`
reports the observability posture under
`capabilities.otel_*` and the non-blocking `observability_instrumentation`
check. Span attributes record only tenant and actor ids and follow the same
privacy rules as audit payloads: no tokens, secrets, or client IPs. See
[`platform-observability.md`](./platform-observability.md) for what is traced,
the exporter setup and how to point at a Jaeger/Tempo collector.

## Object Storage

Governed connector evidence materializations use the object-store adapter
configured on the API service.

For local demos, keep the default filesystem adapter:

- `AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ADAPTER=local_filesystem`
- `AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ROOT=.axis/object-store`

For S3-compatible evaluation or production-style deployments, configure:

- `AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ADAPTER=s3_compatible`
- `AXIS_CONNECTOR_EXPORT_S3_ENDPOINT`
- `AXIS_CONNECTOR_EXPORT_S3_REGION`
- `AXIS_CONNECTOR_EXPORT_S3_BUCKET`
- `AXIS_CONNECTOR_EXPORT_S3_SECURE_TRANSPORT=true`
- `AXIS_CONNECTOR_EXPORT_S3_OBJECT_LOCK_ENABLED=true`
- `AXIS_CONNECTOR_EXPORT_S3_RETENTION_MODE=GOVERNANCE` or `COMPLIANCE`
- `AXIS_CONNECTOR_EXPORT_S3_RETENTION_DAYS=<positive integer>`
- `AXIS_CONNECTOR_EXPORT_S3_LEGAL_HOLD_ENABLED=true` when legal hold should be
  applied to written objects.

**The bucket must be created with S3 object-lock enabled.** Object-lock can only
be turned on at bucket creation (`make_bucket(..., object_lock=True)` /
`mc mb --with-lock`). COMPLIANCE-mode retention silently no-ops on a bucket that
was not created with object-lock, so the platform verifies the bucket
object-lock configuration at bootstrap and fails closed when COMPLIANCE is
configured against a non-object-lock bucket. GOVERNANCE and the local-filesystem
adapter are unaffected by this gate; the local adapter cannot provide WORM and
is not valid for COMPLIANCE.

`AXIS_CONNECTOR_EXPORT_S3_ACCESS_KEY` and
`AXIS_CONNECTOR_EXPORT_S3_SECRET_KEY` must come from `secrets.existingSecret`
or an external secret manager integration. They are not rendered into the
ConfigMap and are not returned by readiness or support diagnostics.

The readiness endpoint reports the object-store gate as ready only when the
S3-compatible adapter has endpoint, bucket, credentials, secure transport,
object lock and positive retention days configured. For COMPLIANCE mode it
additionally requires a verified object-lock bucket
(`object_store_object_lock_bucket_verified` /
`object_store_compliance_enforceable`); when unverified the gate reports the
missing requirement `verified object-lock bucket`. This proves the Axis adapter
is configured to write retained objects and, in COMPLIANCE mode, that the bucket
can actually enforce WORM; it does not replace customer bucket provisioning
review, KMS policy, restore drills, legal operations or external compliance
review.

Object-store legal holds on materialized export artifacts are applied and
released through `POST /demo/manufacturing/audit/object-legal-holds` and
`.../object-legal-holds/release` (permission-gated on `audit:legal_hold:write`,
audited). This is distinct from the DB-level audit legal hold that blocks
physical retention deletion of ledger rows.

## Object Storage Recovery Rehearsal

The repository includes an object storage recovery rehearsal helper for
S3-compatible deployments:

```bash
make deployment-object-storage-recovery-rehearsal-plan
```

The plan creates a temporary non-root Pod using an operator-supplied image that
contains MinIO Client. It reads source endpoint and bucket settings from the
Axis runtime ConfigMap, reads source credentials from the Axis runtime Secret,
and reads the isolated restore endpoint, bucket and credentials from a separate
restore target Secret. The script first runs a MinIO Client preflight, then
uses `mc alias set`, writes a small recovery probe object to the source bucket,
uses `mc cp` to copy that object into the isolated restore bucket, uses
`mc cat` to read the restored object back, and compares the restored checksum
with the original `object-store.sha256`.

The restore target Secret must be separate from the Axis runtime Secret. It
must provide `AXIS_CONNECTOR_EXPORT_S3_RESTORE_ENDPOINT`,
`AXIS_CONNECTOR_EXPORT_S3_RESTORE_BUCKET`,
`AXIS_CONNECTOR_EXPORT_S3_RESTORE_ACCESS_KEY` and
`AXIS_CONNECTOR_EXPORT_S3_RESTORE_SECRET_KEY`, and it must carry the annotation
`limes-axis.io/object-store-restore-target=isolated`. The script checks the
annotation and required keys without printing access keys or secret keys.

To execute against a selected cluster context:

```bash
AXIS_KUBE_CONTEXT=prod-eu \
AXIS_OBJECT_STORAGE_RECOVERY_IMAGE=registry.example.com/platform/minio-mc:stable \
make deployment-object-storage-recovery-rehearsal
```

`AXIS_OBJECT_STORAGE_RECOVERY_IMAGE` must point to an image that contains MinIO
Client (`mc` or `mcli`). Operators can pass additional script arguments with
`AXIS_OBJECT_STORAGE_RECOVERY_ARGS`, for example `--namespace`,
`--runtime-config-map`, `--runtime-secret`, `--restore-target-secret`,
`--recovery-id`, `--probe-prefix`, `--local-evidence-dir`, `--timeout`,
`--run-as-user`, `--run-as-group` or `--keep-pod`.

This is a bounded object storage recovery probe for governed Axis evidence. It
does not mirror a full bucket, does not validate provider-specific KMS,
does not review customer bucket policies, does not prove legal-hold operations
and does not establish RPO/RTO commitments. The probe intentionally writes a
small object under the configured probe prefix so the recovery path exercises a
real source-to-isolated-target copy instead of a dry-run-only plan.

## Container Images

The repository includes local container image baselines:

```bash
make container-check
make container-build-api
make container-build-web
```

`services/api/Dockerfile` builds the FastAPI service with `uv`, installs only
production Python dependencies, runs as UID `10001`, exposes port `8000` and
uses the API `/health` route as a container healthcheck.

`apps/web/Dockerfile` builds the Next.js console with `pnpm`, installs
production Node dependencies for runtime, runs as UID `10001`, exposes port
`3000` and uses the web home route as a container healthcheck. The runtime
stage removes the bundled `npm` and `npx` package-manager surface because the
production command does not require them.

These local builds are useful for hardening the Helm path and for evaluation
clusters. They are not image provenance, signing, SBOM publication or registry
release automation.

## Container Release Workflow

The repository includes a real release supply-chain baseline in
`.github/workflows/container-release.yml`.

The workflow builds both public images:

- `ghcr.io/${{ github.repository_owner }}/limes-axis-api`
- `ghcr.io/${{ github.repository_owner }}/limes-axis-web`

It runs on `v*` Git tags and can also be started manually with
`workflow_dispatch`. Tag pushes and default manual runs execute the
`build-images` job only; they do not publish images to GHCR.

Publishing is split into a separate governed path. The
`validate-promotion-evidence` job runs only for a manual run where `push=true`
and checks that the operator supplied a release approval issue, the required
rollback plan issue evidence, a rollback drill identifier and
`rollback_plan_acknowledged=true`. The
gate checks that the approval and rollback issue URLs belong to
`Limes-Labs/limes-axis`, verifies them with `gh issue view`, requires a
non-empty rollback drill id and blocks publication if the rollback plan has not
been explicitly acknowledged.

The `publish-images` job depends on the evidence gate and declares the
`axis-container-release` GitHub Environment. Repository administrators must
configure required reviewers on that environment before production use; the
workflow declaration provides the hook for GitHub Environment reviewer
protection without forcing reviewer approval for build-only tag checks.
Published images use GitHub OIDC for keyless signing through cosign, BuildKit
`sbom: true`, BuildKit `provenance: mode=max`, and GitHub registry-backed build
provenance attestations.

Validate the release workflow contract locally with:

```bash
make container-release-check
```

This baseline is intended to make release artifacts inspectable and
repeatable. It is not a production certification: GitHub environment reviewer
settings, registry retention policy, vulnerability exception lifecycle,
long-term SBOM archival, periodic rollback drill operations and
customer-specific deployment gates still need production hardening.

## Container Vulnerability Scanning

The repository includes a container security workflow in
`.github/workflows/container-security.yml`. It builds the API and web images
from the repository Dockerfiles and scans both with Trivy.

The first blocking policy is intentionally narrow and repeatable:

- scan API and web images on relevant pull requests, pushes to `main` and
  manual runs;
- scan OS and library vulnerabilities;
- block fixed `CRITICAL` vulnerabilities;
- use `ignore-unfixed` so the gate focuses on issues with an available upgrade
  path;
- pinned to the v0.36.0 commit for `aquasecurity/trivy-action`:
  `ed142fd0673e97e23eac54620cfb913e5ce36c25`;
- run Trivy `v0.71.2`.

Validate the workflow contract locally with:

```bash
make container-security-check
```

Run the same critical fixed-vulnerability policy against local images with:

```bash
make container-scan-local
```

The local scan writes machine-readable JSON reports under
`.axis/trivy-reports/`, which is ignored by git with the rest of the local Axis
runtime state.

The workflow also generates `HIGH` and `CRITICAL` vulnerability SARIF reports
for each image and uploads them to GitHub code scanning with
`github/codeql-action/upload-sarif` pinned to
`8aad20d150bbac5944a9f9d289da16a4b0d87c1e`. This requires the workflow-scoped
`security-events: write` permission. SARIF upload is skipped for pull requests
from forks because GitHub does not grant the same code-scanning write capability
to untrusted fork contexts.

The repository tracks vulnerability exceptions in
`.github/vulnerability-exceptions.json`. The first policy requires owner roles,
review tickets, promotion review and exception expiry. `HIGH` exceptions may
last at most 45 days and `CRITICAL` exceptions may last at most 14 days. There
are no approved vulnerability exceptions in the current baseline.

Validate the vulnerability management baseline with:

```bash
make vulnerability-management-check
```

This is a real vulnerability scan gate, but it is not a production
certification. Enterprise hardening still needs GitHub environment reviewer
settings, operational exception review meetings, registry retention, release
rollback criteria and customer-specific deployment gates.

## Runtime Secrets

The chart uses `secrets.existingSecret` for sensitive values. The default name
is `limes-axis-runtime`.

Required keys:

- `AXIS_POSTGRES_DSN`
- `AXIS_TYPEDB_USERNAME`
- `AXIS_TYPEDB_PASSWORD`
- `AXIS_AUDIT_LEDGER_SIGNING_SECRET`
- `AXIS_OIDC_CLIENT_SECRET`
- `AXIS_OIDC_SESSION_COOKIE_SIGNING_SECRET`
- `AXIS_OIDC_REFRESH_TOKEN_ENCRYPTION_KEY` (at least 32 characters; the API
  fails to start when it is set but shorter)
- `AXIS_CONNECTOR_EXPORT_S3_ACCESS_KEY`
- `AXIS_CONNECTOR_EXPORT_S3_SECRET_KEY`

Optional connector live-read secret keys:

- `AXIS_EXTERNAL_DB_LIVE_QUERY_DSN`

Only set `AXIS_EXTERNAL_DB_LIVE_QUERY_DSN` for governed live-read rehearsals or
customer-approved deployments where `AXIS_EXTERNAL_DB_LIVE_QUERY_EXECUTION_ENABLED=true`.
The runtime returns public-safe profile/read-count evidence only and never
returns this DSN through readiness, diagnostics, audit or connector responses.
Non-sensitive live-read profile controls belong in the runtime ConfigMap:
`AXIS_EXTERNAL_DB_LIVE_QUERY_PROFILE_ID`,
`AXIS_EXTERNAL_DB_LIVE_QUERY_SCHEMA`, `AXIS_EXTERNAL_DB_LIVE_QUERY_TABLE`,
`AXIS_EXTERNAL_DB_LIVE_QUERY_COLUMNS` and
`AXIS_EXTERNAL_DB_LIVE_QUERY_ROW_LIMIT`,
`AXIS_EXTERNAL_DB_LIVE_QUERY_PRIVATE_ENDPOINT_REF`. The tenant-scoped egress
policy for that profile must include an
`approved_endpoint_target_sha256` policy-document field. It is the SHA-256
digest of the approved Postgres network target (`host:port`) and lets the
runtime prove that the secret DSN is bound to the approved private endpoint
without exposing the host or DSN in ConfigMaps, audit payloads, readiness
responses or diagnostics.

Do not put customer secrets in `values.yaml`. Use an external secret manager,
sealed secret workflow or platform-specific KMS integration before production
use. The disabled example Secret uses
`REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE` placeholders so accidental demo
secrets are not shipped as chart defaults.

For clusters that already run External Secrets Operator, enable
`secrets.externalSecret.enabled=true`. The rendered `ExternalSecret` uses
`external-secrets.io/v1`, references `secretStoreRef`, writes to
`secrets.existingSecret`, and maps each Axis runtime key through
`data[].remoteRef`. The placeholder `remoteKey` values in `values.yaml` must be
replaced with the customer's real secret-manager paths before installation.

## OIDC Authorization-Code Session

Axis supports an API-owned OIDC authorization-code entrypoint for browser SSO:

- `GET /identity/oidc/authorize` creates a PKCE authorization request and
  redirects to the configured provider.
- `GET /identity/oidc/callback` verifies the state cookie, exchanges the code
  at the token endpoint, validates the provider `id_token` signature, issuer,
  Axis client audience and login nonce, then sets an HTTP-only Axis session
  cookie.
- `GET /identity/oidc/logout` revokes the local Axis browser session, clears
  the Axis cookie and redirects the browser to the configured OIDC end-session
  endpoint.
- `GET /identity/oidc/onboarding` returns a public-safe IdP onboarding report
  with the configured issuer, discovery URL, OIDC endpoints, exact redirect
  URIs, post-logout redirect URIs, scopes, claim mappings, recommended IdP
  controls and remaining readiness action items.
- `GET /identity/session` validates the signed Axis session cookie and returns
  only public-safe actor, tenant, scope and posture metadata.
- `POST /identity/session/logout` revokes the persisted Axis browser session,
  writes audit evidence and clears the browser cookie without a federated IdP
  redirect.
- `POST /identity/session/refresh` performs a server-side refresh-token grant
  at the configured token endpoint, rotates the Axis session id and refresh
  token, extends the sliding session inside the absolute lifetime cap and
  revokes the session when the provider rejects the refresh.
- `GET /identity/sessions` lists the calling actor's browser sessions as
  opaque session references with status, creation, expiry and refresh-count
  metadata plus the device metadata captured at login and refresh (bounded
  user agent, client IP and a derived `device_label` such as
  "Safari on macOS"); `tenant_wide=true` requires the
  `identity:sessions:admin` scope. The listing is cursor-paginated:
  `page_size` (default 20, max 100) bounds the page, and the response
  reports `has_more` plus an opaque `next_cursor` to fetch the next page in
  stable newest-first order. Callers that never send a cursor keep getting
  the first page with the same response shape.
- `POST /identity/sessions/{session_ref}/revoke` revokes a session by opaque
  reference. Actors revoke their own sessions; revoking another actor's
  session requires the `identity:sessions:admin` scope, and lookups are
  tenant-isolated. Active and in-flight refreshing sessions are revocable; the
  row is locked for the transaction so a concurrent refresh cannot resurrect a
  session after revocation.

Configure non-sensitive client and endpoint values in the chart ConfigMap:

- `AXIS_OIDC_CLIENT_ID`
- `AXIS_OIDC_AUTHORIZATION_URL`
- `AXIS_OIDC_TOKEN_URL`
- `AXIS_OIDC_REDIRECT_URI`
- `AXIS_OIDC_END_SESSION_URL`
- `AXIS_OIDC_POST_LOGOUT_REDIRECT_URI`
- `AXIS_OIDC_SCOPES`, which must include `openid` so compliant providers
  issue an ID token for browser SSO.
- `AXIS_OIDC_SESSION_COOKIE_TTL_SECONDS`
- `AXIS_OIDC_SESSION_COOKIE_SECURE=true`
- `AXIS_OIDC_SESSION_COOKIE_HOST_PREFIX=true`, which renames the session and
  CSRF cookies to `__Host-`-prefixed names whenever Secure cookies are enabled
  so the browser binds them to the exact host and the `/` path.
- `AXIS_OIDC_SESSION_IDLE_TIMEOUT_SECONDS` (default 1800): sessions with no
  authenticated request inside this window are revoked with
  `idle_timeout` audit evidence.
- `AXIS_OIDC_SESSION_ABSOLUTE_TIMEOUT_SECONDS` (default 28800): the hard cap
  on a login's total lifetime; refresh rotation extends sessions only inside
  this cap.
- `AXIS_OIDC_SESSION_MAX_CONCURRENT` (default 5): the newest login revokes the
  oldest active sessions above this per-actor cap with
  `concurrent_session_limit` audit evidence; `0` disables the cap. PostgreSQL
  admission is serialized per tenant and actor with a transaction-scoped
  advisory lock, so the cap remains exact across concurrent callbacks and API
  replicas.
- `AXIS_IDENTITY_SESSION_TRUSTED_PROXY_ENABLED` (default `false`): controls
  the trust model for the client IP recorded as session device metadata.
  When false the API records the direct socket peer address and ignores
  `X-Forwarded-For` entirely, because any client can forge that header.
  Set it to `true` only when every client connection reaches the API
  through EXACTLY ONE trusted reverse proxy or ingress (the standard Helm
  ingress topology). Standard proxies append the peer they observed to
  `X-Forwarded-For` (e.g. nginx `$proxy_add_x_forwarded_for`), so the API
  then records the LAST (rightmost) hop - the address that single trusted
  proxy actually saw the connection from - and falls back to the socket peer
  when the header is missing or malformed. Every entry to the left of the
  rightmost hop is client-attested and forgeable, so it is never recorded.
  Never enable the flag when clients can bypass the proxy and reach the API
  directly. This assumes exactly one trusted proxy; a multi-proxy chain would
  need a configurable trusted-hop count to skip the extra proxy-added hops,
  which is a documented follow-up and not yet implemented.
- `AXIS_OIDC_REFRESH_CLAIM_STALENESS_SECONDS` (default 120): a session stuck in
  the `refreshing` state longer than this window (the refreshing process
  crashed between the claim and its completion) is revoked with
  `refresh_claim_orphaned` audit evidence the next time the cookie is
  presented. Keep it well above the IdP token-exchange timeout so an in-flight
  refresh is never mistaken for an orphaned claim.

The Docker Compose demo imports `infra/docker/keycloak/axis-realm.json` for a
local Keycloak walkthrough. That realm, its `axis-operator` user, the
`axis-demo` password and the `axis-local-dev-secret` client secret are
local-only demo credentials. They must not be reused as production IdP
configuration, Helm values, customer credentials or enterprise SSO evidence.

Keep `AXIS_OIDC_CLIENT_SECRET` and
`AXIS_OIDC_SESSION_COOKIE_SIGNING_SECRET` in `secrets.existingSecret` or an
external secret manager. The callback does not return token material to the web
console. The callback requires the token response to include a signed
`id_token`; Axis validates it through the configured JWKS, checks the issuer,
requires an expiry, checks the Axis client audience and authorized party when
present, compares the ID-token nonce to the signed login-state cookie nonce and
requires the access-token subject to match the ID-token subject. The Axis
session cookie stores only API-owned actor, tenant, scope, expiry and
session-id claims; the `oidc_browser_sessions` table stores only a keyed
session-id hash plus actor, tenant, scopes, expiry, lifecycle and revocation
metadata, providing server-side session revocation without storing raw provider
tokens. Each session row also stores the device metadata captured at login and
re-captured on refresh rotation: the `User-Agent` header truncated to 256
characters, the client IP resolved under the
`AXIS_IDENTITY_SESSION_TRUSTED_PROXY_ENABLED` trust model, and a compact
device label derived by a deterministic in-process parser (major browser and
OS families only; anything unrecognized becomes "Unknown device"). The
metadata is returned only by the owner/admin-scoped `GET /identity/sessions`
listing, never enters audit payloads (the client IP in particular stays out of
the audit ledger), and lives and dies with the session row - there is no
separate retention store for it. When the provider issues a refresh token and
`AXIS_OIDC_REFRESH_TOKEN_ENCRYPTION_KEY` is configured, Axis stores the refresh
token only as AES-GCM ciphertext bound to the session row; the AES key is
HKDF-derived (SHA-256, fixed salt and context) from the operator-supplied key,
which must be at least 32 characters or the API refuses to start. Without the
key the refresh token is discarded and `POST /identity/session/refresh` returns
`refresh_not_available`. Refresh rotates both the Axis session id and the
stored refresh credential; the transition is guarded by an atomic
`active` -> `refreshing` claim so two concurrent refreshes with the same cookie
cannot both mint a child session, the IdP token exchange runs outside the open
database transaction, and the superseded session row is marked `rotated` with
its ciphertext cleared so a replayed pre-rotation cookie is rejected. A failed
provider refresh revokes the session and forces a fresh login. If the API
crashes between the refresh claim and its completion, the row stays in
`refreshing` (fail closed); the lifecycle validator recovers such orphaned
claims lazily - the same way idle and absolute timeouts are enforced - by
revoking any `refreshing` session older than
`AXIS_OIDC_REFRESH_CLAIM_STALENESS_SECONDS` with `refresh_claim_orphaned`
audit evidence when its cookie is next presented, so the user gets a clean
401 and the row reaches a terminal state.

CSRF protection is enforced centrally by `BrowserSessionCsrfMiddleware` on every
state-changing request (POST/PUT/PATCH/DELETE), not just the identity
endpoints, so cookie-authenticated mutations across the API (approvals,
actions, audit retention and legal holds, connector and policy authoring,
notification acknowledgements, and session management) all require a matching
`X-Axis-Csrf-Token` header. The callback sets a JavaScript-readable CSRF cookie
whose value is an HMAC of the session id under the cookie-signing key; the
middleware recomputes and compares it per request with a constant-time check,
so no CSRF state is stored server-side. Safe methods (GET/HEAD/OPTIONS) and
requests that authenticate with an `Authorization` bearer header are exempt
because they carry no ambient cookie authority, which keeps bearer-only clients
and the GET-based OIDC callback and federated-logout navigations working.

The web console adopts this session lifecycle in its shared API request layer
(`apps/web/lib/axis-api.ts`), not per page. Every state-changing console
request that runs in cookie-session mode reads the readable CSRF cookie
(`axis_csrf`, or the `__Host-` prefixed variant on secure profiles) and
attaches it as the `X-Axis-Csrf-Token` header; bearer-bridge requests stay
CSRF-free because the API exempts them. When a cookie-session request returns
`401` the console calls `POST /identity/session/refresh` exactly once - a
single in-flight refresh is shared by concurrent `401`s - and retries the
original request once with the rotated CSRF cookie. A failed refresh is never
retried: the console announces the signed-out state, live queries re-run and
`GET /identity/session` reports the public state, so no browser-local session
truth is synthesized. Anonymous `401`s (no CSRF cookie) never trigger refresh
attempts. The console session view at `/settings/sessions` lists the actor's
sessions from `GET /identity/sessions` with status, creation, last-seen,
expiry and refresh-count metadata, revokes non-current sessions through
`POST /identity/sessions/{session_ref}/revoke`, offers the tenant-wide listing
toggle only when the identity read model exposes `identity:sessions:admin`,
and treats revoking the current session as logout by navigating to
`GET /identity/oidc/logout`.

The federated logout redirect uses `client_id` and `post_logout_redirect_uri`;
Axis does not persist or forward `id_token_hint`, access tokens or raw refresh
tokens. The IdP onboarding report never returns confidential client material,
cookie-signing material, provider tokens or raw JWKS material. Login, refresh,
revocation and logout lifecycle transitions - including failed code exchanges
and failed refreshes - append `identity.oidc_login.failed`,
`identity.oidc_session.created`, `identity.oidc_session.refreshed`,
`identity.oidc_session.refresh_failed` and `identity.oidc_session.revoked`
audit events that reference sessions only by keyed hash. Customer-specific
production SSO operations runbooks remain Enterprise onboarding work.

`GET /deployment/readiness` reports `oidc_secure_cookie_session` as a
production blocker unless browser sessions use the Secure cookie flag, an
operator-provided signing secret, a bounded TTL and HTTPS API/public/redirect URLs.
The gate checks `AXIS_API_BASE_URL`, `AXIS_PUBLIC_BASE_URL`,
`AXIS_OIDC_REDIRECT_URI`, the effective post-logout redirect URI,
`AXIS_OIDC_SESSION_COOKIE_TTL_SECONDS`,
`AXIS_OIDC_SESSION_COOKIE_SECURE=true` and the presence of
`AXIS_OIDC_SESSION_COOKIE_SIGNING_SECRET`. The readiness response exposes only
booleans and bounded TTL metadata; it does not print cookie-signing material or
client secrets.

## API Rate Limiting

Axis includes configurable in-process API rate limiting for public and sensitive
routes. It is disabled by default for local demos and enabled in the Helm
production values for:

- `GET /identity/oidc/authorize`
- `GET /identity/oidc/callback`
- `GET /identity/oidc/logout`
- `POST /identity/session/logout`
- `GET /deployment/readiness`
- `GET /support/diagnostics`

Configure the limiter with:

- `AXIS_API_RATE_LIMIT_ENABLED`
- `AXIS_API_RATE_LIMIT_REQUESTS`
- `AXIS_API_RATE_LIMIT_WINDOW_SECONDS`
- `AXIS_API_RATE_LIMIT_PATHS`

When a client exceeds the configured budget, the API returns `429` with
`Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining` and
`X-RateLimit-Reset`. The deployment readiness endpoint reports
`api_rate_limiting` as a production blocker when the limiter is not enabled.

This is a self-hostable baseline, not a complete global abuse-control system.
For multi-replica or internet-facing production deployments, operators should
pair it with ingress, gateway or edge-level throttling, alerting and incident
runbooks.

## Disaster Recovery Procedure Readiness

The chart exposes public-safe disaster-recovery procedure settings used by
`/deployment/readiness`:

- `AXIS_DR_RUNBOOK_CONFIGURED`
- `AXIS_DR_RPO_RTO_DEFINED`
- `AXIS_DR_REHEARSAL_EVIDENCE_CONFIGURED`
- `AXIS_DR_RESTORE_OWNER_CONFIGURED`
- `AXIS_DR_CUSTOMER_APPROVAL_CONFIGURED`

The readiness endpoint returns only booleans. It does not expose customer
runbook URLs, owner names, approval records, incident contacts, RPO/RTO values or
customer-specific evidence locations. `production_dr_procedures` is ready only
when all five gates are configured.

This gate complements the Postgres, TypeDB, object storage and Temporal
recovery rehearsal tools above. It is not a disaster-recovery certification by
itself; operators still need customer-specific restore execution, offsite
retention, legal review and recurring rehearsal evidence.

## Support Readiness Configuration

The chart exposes public-safe support model settings used by
`/support/diagnostics`:

- `AXIS_SUPPORT_MODEL_ENABLED`
- `AXIS_SUPPORT_COVERAGE`
- `AXIS_SUPPORT_S1_RESPONSE_MINUTES`
- `AXIS_SUPPORT_S2_RESPONSE_MINUTES`
- `AXIS_SUPPORT_S3_RESPONSE_MINUTES`
- `AXIS_SUPPORT_S4_RESPONSE_MINUTES`
- `AXIS_SUPPORT_ESCALATION_CHANNELS`
- `AXIS_SUPPORT_CUSTOMER_RUNBOOK_URL`
- `AXIS_SUPPORT_STATUS_PAGE_URL`
- `AXIS_SUPPORT_INCIDENT_REVIEW_REQUIRED`
- `AXIS_SUPPORT_SIGNED_COMMITMENT_CONFIGURED`
- `AXIS_SUPPORT_NAMED_STAFFING_MODEL_CONFIGURED`
- `AXIS_SUPPORT_CUSTOMER_INCIDENT_OPERATIONS_CONFIGURED`
- `AXIS_SUPPORT_LEGAL_SLA_TERMS_CONFIGURED`

The diagnostics endpoint returns support readiness booleans, response target
minutes, escalation channel classes and support commitment booleans. It does
not echo customer runbook URLs, status page URLs, contract text, staffing
details or personal contact details. `production_support_ready=true` requires
production deployment readiness plus a configured `24x7` support model,
positive ordered S1-S4 response targets, at least two escalation channel
classes, HTTPS runbook/status-page configuration, required incident review and
`production_support_commitments` readiness for signed commitment, named
staffing, customer incident operations and legal SLA term configuration.

This is a readiness contract for operators and design partners. It is not a
signed SLA, staffing commitment or compliance attestation by itself.

## Secret Rotation Rehearsal

The repository includes a Kubernetes secret rotation rehearsal helper:

```bash
make deployment-secret-rotation-rehearsal-plan
```

The plan creates a temporary non-root Pod that mounts the active runtime Secret
read-only at `/rotation/active`, mounts a separately staged Secret read-only at
`/rotation/staged`, compares required Axis secret keys with `cmp -s`, records
redacted key status in `secret-rotation.keys`, records SHA-256 fingerprints in
`secret-rotation.sha256` and writes `secret-rotation.summary.json`. The helper
does not use `envFrom`, so secret values are not placed into process
environment variables, and the plan does not print raw secret values.

The staged Secret must be separate from the active runtime Secret and must
carry `limes-axis.io/secret-rotation-target=staged`. Both Secrets must contain
the required runtime keys listed above. By default, execution fails if no
required key differs between active and staged Secrets; operators can pass
`--allow-unchanged` through `AXIS_SECRET_ROTATION_ARGS` only for dry validation
of key parity.

To execute against a selected cluster context:

```bash
AXIS_KUBE_CONTEXT=prod-eu \
AXIS_SECRET_ROTATION_IMAGE=registry.example.com/platform/busybox-coreutils:stable \
make deployment-secret-rotation-rehearsal
```

`AXIS_SECRET_ROTATION_IMAGE` must point to an image that includes `sh`, `cmp`
and `sha256sum`. Operators can pass additional script arguments with
`AXIS_SECRET_ROTATION_ARGS`, for example `--namespace`, `--active-secret`,
`--staged-secret`, `--rotation-id`, `--local-evidence-dir`, `--timeout`,
`--run-as-user`, `--run-as-group`, `--allow-unchanged` or `--keep-pod`.

This is a rotation readiness rehearsal, not an automatic production rotation.
It does not update the active Secret, does not restart workloads, does not
validate the upstream secret manager or KMS policy and does not replace access
review, rollback, incident-response or customer approval procedures. Treat the
fingerprint evidence as operator-confidential even though it does not contain
raw secret values.

## Install

Create or sync the runtime Secret before installing the chart:

```bash
kubectl create namespace limes-axis
kubectl -n limes-axis create secret generic limes-axis-runtime \
  --from-literal=AXIS_POSTGRES_DSN='REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE' \
  --from-literal=AXIS_TYPEDB_USERNAME='REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE' \
  --from-literal=AXIS_TYPEDB_PASSWORD='REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE' \
  --from-literal=AXIS_AUDIT_LEDGER_SIGNING_SECRET='REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE' \
  --from-literal=AXIS_OIDC_CLIENT_SECRET='REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE' \
  --from-literal=AXIS_OIDC_SESSION_COOKIE_SIGNING_SECRET='REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE' \
  --from-literal=AXIS_CONNECTOR_EXPORT_S3_ACCESS_KEY='REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE' \
  --from-literal=AXIS_CONNECTOR_EXPORT_S3_SECRET_KEY='REPLACE_WITH_EXTERNAL_SECRET_MANAGER_VALUE'
```

If the cluster uses External Secrets Operator instead, preinstall the operator,
create the appropriate `SecretStore` or `ClusterSecretStore`, then let the
chart render the synchronization object:

```bash
helm upgrade --install limes-axis infra/helm/limes-axis \
  --namespace limes-axis \
  --create-namespace \
  --set secrets.externalSecret.enabled=true \
  --set secrets.externalSecret.secretStoreRef.name=production-secrets \
  --set secrets.externalSecret.secretStoreRef.kind=ClusterSecretStore
```

Install or upgrade the release:

```bash
helm upgrade --install limes-axis infra/helm/limes-axis \
  --namespace limes-axis \
  --create-namespace \
  --set api.image.repository=ghcr.io/limes-labs/limes-axis-api \
  --set api.image.tag=0.1.0 \
  --set web.image.repository=ghcr.io/limes-labs/limes-axis-web \
  --set web.image.tag=0.1.0 \
  --set api.env.AXIS_PUBLIC_BASE_URL=https://axis.example.com \
  --set api.env.AXIS_API_BASE_URL=https://api.axis.example.com \
  --set web.env.NEXT_PUBLIC_AXIS_API_BASE_URL=https://api.axis.example.com \
  --set api.env.AXIS_OIDC_ISSUER=https://keycloak.example.com/realms/axis \
  --set api.env.AXIS_OIDC_JWKS_URL=https://keycloak.example.com/realms/axis/protocol/openid-connect/certs \
  --set api.env.AXIS_OIDC_CLIENT_ID=limes-axis-web \
  --set api.env.AXIS_OIDC_AUTHORIZATION_URL=https://keycloak.example.com/realms/axis/protocol/openid-connect/auth \
  --set api.env.AXIS_OIDC_TOKEN_URL=https://keycloak.example.com/realms/axis/protocol/openid-connect/token \
  --set api.env.AXIS_OIDC_REDIRECT_URI=https://api.axis.example.com/identity/oidc/callback \
  --set api.env.AXIS_OIDC_END_SESSION_URL=https://keycloak.example.com/realms/axis/protocol/openid-connect/logout \
  --set api.env.AXIS_OIDC_POST_LOGOUT_REDIRECT_URI=https://axis.example.com/signed-out \
  --set api.env.AXIS_OIDC_SESSION_COOKIE_SECURE=true
```

Enable Ingress routing only when the cluster has an Ingress controller and TLS
Secret ready:

```bash
helm upgrade --install limes-axis infra/helm/limes-axis \
  --namespace limes-axis \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set 'ingress.tls[0].secretName=axis-tls' \
  --set 'ingress.tls[0].hosts[0]=axis.example.com' \
  --set 'ingress.tls[0].hosts[1]=api.axis.example.com'
```

When cert-manager is already installed, the chart can request certificate
issuance through ingress-shim annotations while still referencing the same TLS
Secret:

```bash
helm upgrade --install limes-axis infra/helm/limes-axis \
  --namespace limes-axis \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.certManager.enabled=true \
  --set ingress.certManager.issuerName=letsencrypt-prod \
  --set ingress.certManager.issuerKind=ClusterIssuer \
  --set 'ingress.tls[0].secretName=axis-tls' \
  --set 'ingress.tls[0].hosts[0]=axis.example.com' \
  --set 'ingress.tls[0].hosts[1]=api.axis.example.com'
```

The repository includes local Dockerfiles, but production image coordinates
should point to images built, scanned, signed and published by the operator or
a future Axis release pipeline.

## Verification

Run the static repository deployment checks:

```bash
make deployment-check
make deployment-profile-render-check
helm lint infra/helm/limes-axis
make deployment-rollout-rehearsal-plan
make deployment-backup-rehearsal-plan
make deployment-restore-rehearsal-plan
make deployment-typedb-recovery-rehearsal-plan
make deployment-object-storage-recovery-rehearsal-plan
make deployment-temporal-recovery-rehearsal-plan
make deployment-secret-rotation-rehearsal-plan
make deployment-ha-rehearsal-plan
make deployment-load-rehearsal-plan
make deployment-tls-readiness-plan
make container-check
make container-release-check
make container-security-check
make vulnerability-management-check
```

After a cluster install, verify Kubernetes state, Helm smoke tests and API
readiness:

```bash
helm test limes-axis --namespace limes-axis --timeout 10m
kubectl -n limes-axis get pods,svc
kubectl -n limes-axis port-forward svc/limes-axis-api 8000:8000
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/deployment/readiness
```

The readiness endpoint should be shared honestly during enterprise evaluation.
It may report `production_ready=false` until OIDC, rate limiting, audit signing,
OIDC secure-cookie/session posture, connector execution, object storage,
network egress restrictions, disaster-recovery procedures, customer bucket
operations and support operations are hardened.

## Promotion Gate

Before customer production use, the deployment package must add and verify:

- release approval issue and reviewer settings for production image release.
- registry retention and long-term SBOM archive.
- enforced release promotion approvals and recurring rollback drills.
- operational review cadence for high-severity findings and expiring
  vulnerability exceptions.
- cert-manager issuer policy, DNS ownership checks, certificate renewal
  evidence and HSTS/CDN/WAF policy.
- high availability, scheduling/topology, autoscaling and upgrade rollback
  tests, including rollout-drain validation.
- customer-specific NetworkPolicy, firewall or service-mesh egress review beyond
  the chart's restricted/offline baseline.
- backup restore drills against isolated Postgres, TypeDB and object-storage
  targets plus Temporal namespace/history evidence, disaster recovery runbooks,
  RPO/RTO evidence, restore ownership and customer approval.
- production secret-manager rotation drills, access reviews, workload restart
  validation and incident procedures.
- S3/MinIO bucket-policy review, restore drills and KMS-backed audit signing.
- global abuse throttling, production observability and incident response
  runbooks.
- cluster-specific threat review and penetration test scope.

Until those items are complete, this chart is an evaluation and hardening
baseline, not a production-ready enterprise deployment.
