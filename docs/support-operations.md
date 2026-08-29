# Support Operations Runbook

This runbook defines the current public-safe support and operations baseline for
Limes Axis demo, design-partner evaluation and production-readiness review
environments. It is not a signed customer support contract, SLA, SOC process or
compliance attestation.

## Scope

In scope:

- Local Docker Compose demo support.
- SME feedback and enterprise evaluation walkthrough support.
- Public-safe diagnostic capture through `/support/diagnostics`.
- Readiness posture review through `/ready`, `/identity/oidc/readiness`,
  `/deployment/readiness`, `make demo-check-live` and `make security-check`.
- Production support-readiness review through a configured support model,
  severity response targets, escalation channel classes and customer runbook
  presence checks.
- Triage of API, web console, persistence, workflow and connector-boundary
  issues in the private commercial repository.

Out of scope:

- Customer incident response ownership.
- Signed SLAs, RPO/RTO commitments, warranty terms or customer-specific legal
  commitments.
- Managed Cloud, Enterprise private deployment support and customer-specific
  connector execution.
- Handling customer credentials, production datasets or private infrastructure
  access in repository issues or committed files.

## Public-Safe Diagnostic Bundle

Before a support or design-partner session, capture:

```bash
curl -s http://127.0.0.1:8000/support/diagnostics | python3 -m json.tool
make demo-check
make security-check
make demo-check-live
```

The support diagnostics endpoint is designed to be safe to share in public
issues or design-partner notes. It reports:

- service and environment profile;
- demo-support and production-support readiness booleans;
- deployment posture summary;
- identity readiness summary;
- model egress, connector execution, audit signing and object-store posture;
- support model readiness, severity response targets and escalation channel
  classes;
- support blockers;
- links to the relevant runbooks and threat model.

It must not return bearer tokens, raw JWKS, credential material, signing
material, database DSNs, customer runbook URLs, status page URLs or personal
contact details.

## Production Support Readiness Contract

`/support/diagnostics` reports `production_support_ready=true` only when the
deployment is production-ready, the public-safe support model is configured
and the customer-facing support commitment gates are explicitly set. The
support model is intentionally operational rather than contractual: it proves
that the environment has support controls wired, but it does not create a
signed SLA.

Required configuration:

- `AXIS_SUPPORT_MODEL_ENABLED=true`
- `AXIS_SUPPORT_COVERAGE=24x7`
- positive response targets for `AXIS_SUPPORT_S1_RESPONSE_MINUTES`,
  `AXIS_SUPPORT_S2_RESPONSE_MINUTES`, `AXIS_SUPPORT_S3_RESPONSE_MINUTES` and
  `AXIS_SUPPORT_S4_RESPONSE_MINUTES`, ordered from shortest to longest;
- at least two non-personal escalation channel classes in
  `AXIS_SUPPORT_ESCALATION_CHANNELS`, for example
  `["customer_success_manager","platform_engineering_on_call"]`;
- HTTPS `AXIS_SUPPORT_CUSTOMER_RUNBOOK_URL`;
- HTTPS `AXIS_SUPPORT_STATUS_PAGE_URL`;
- `AXIS_SUPPORT_INCIDENT_REVIEW_REQUIRED=true`.
- `AXIS_SUPPORT_SIGNED_COMMITMENT_CONFIGURED=true`;
- `AXIS_SUPPORT_NAMED_STAFFING_MODEL_CONFIGURED=true`;
- `AXIS_SUPPORT_CUSTOMER_INCIDENT_OPERATIONS_CONFIGURED=true`;
- `AXIS_SUPPORT_LEGAL_SLA_TERMS_CONFIGURED=true`.

The diagnostics response returns only booleans for customer runbook and status
page configuration. It does not echo the configured URLs. Escalation channel
values must be role or function labels, not personal names, phone numbers,
emails or private chat handles.

The commitment gates are also public-safe booleans. They confirm that the
operator has configured the environment as having signed support commitments,
a named staffing model, customer-specific incident operations and legal SLA
terms. They do not expose contract text, personal staffing details, legal
documents or customer contact data.

## Triage Flow

1. Confirm the environment profile from `/support/diagnostics`.
2. Confirm `/health` and `/ready` return HTTP 200.
3. Run `make demo-check` to validate static repository expectations.
4. Run `make security-check` to validate threat-model and posture contracts.
5. Run `make demo-check-live` while API and web are running.
6. If the issue is browser-visible, run `pnpm --filter @limes-axis/web test:e2e`
   and capture the failing route or console surface.
7. If the issue involves live services, run `make test-integration` with Docker
   services up.
8. For Kubernetes evaluation environments, run `make deployment-ha-rehearsal-plan`
   before restart or availability validation and
   `make deployment-load-rehearsal-plan` before bounded load evidence. Run
   `make deployment-tls-readiness-plan` before DNS, Ingress or certificate
   troubleshooting. Execute `make deployment-ha-rehearsal`,
   `make deployment-load-rehearsal` or `make deployment-tls-readiness` only
   against an approved `AXIS_KUBE_CONTEXT`.
9. Record the failing check name, route, command and timestamp in the issue or
   customer note.

## Severity Guidance

| Severity | Example | Response Goal |
| --- | --- | --- |
| S1 | Data exposure, cross-tenant access, audit evidence tampering | Stop demo/customer use, preserve evidence, open security review immediately |
| S2 | API unavailable, migration failure, broken demo readiness gate | Restore demo path or document blocker before the next walkthrough |
| S3 | Single console page degraded while API evidence is healthy | Triage with route-specific tests and browser evidence |
| S4 | Documentation mismatch, wording issue, missing checklist item | Fix through normal PR review |

## Evidence To Preserve

- Command output from the failed check.
- API route and HTTP status.
- Browser route and screenshot when UI is involved.
- Current git SHA.
- Docker Compose service status.
- Whether the issue appears in local demo, production-like evaluation or both.
- Any relevant audit event id, workflow run id or connector run id.

Do not paste customer credentials, raw tokens, private JWKS, database DSNs,
connector secrets or private production records into public issues.

## Escalation Boundaries

Escalate immediately when:

- `/support/diagnostics` reports unexpected production support readiness.
- `/deployment/readiness` omits known production blockers.
- `make security-check` fails.
- A tenant mismatch, actor impersonation or permission bypass is suspected.
- Audit integrity, legal hold or retention controls appear inconsistent.
- Connector credential handles, leases or external egress controls expose
  sensitive material.

## Current Production Gaps

- The production support-readiness contract now checks escalation channel
  classes, SLO targets, signed support commitments, named staffing model,
  customer-specific incident operations and legal SLA term configuration.
  Actual signed agreements, personal staffing assignments and legal documents
  remain external commercial artifacts and must not be stored in the public
  diagnostics payload.
- Production backup, restore, retention, HA and disaster recovery are not
  complete across every stateful dependency.
- Enterprise SSO now has readiness/profile reporting, IdP onboarding, a PKCE
  authorization-code session-cookie API boundary, secure browser-session
  deployment gating and server-side local/federated logout revocation, but
  refresh-token rotation and production SSO operations are not complete.
- S3/MinIO WORM adapter readiness and a bounded object-store recovery
  rehearsal are implemented, but production bucket provisioning review, KMS
  policy, legal operations and full-bucket restore drills remain Enterprise
  work.
- A bounded Temporal namespace/history evidence rehearsal is implemented, but
  Temporal persistence restore, deterministic replay operations, archival
  policy review and RPO/RTO evidence remain Enterprise work.
- A bounded Secret rotation rehearsal is implemented, but upstream
  secret-manager rotation, access reviews, secret-driven workload restart
  validation, rollback criteria and incident procedures remain Enterprise work.
- Bounded HA restart and load rehearsals are implemented for API/web workloads,
  but sustained customer-profile load testing, node failure, zone failure,
  capacity planning and production SLO proof remain Enterprise work.
- A TLS readiness rehearsal is implemented for Ingress, cert-manager, DNS and
  HTTPS reachability checks, but automated certificate issuance operations,
  renewal drills and HSTS/CDN/WAF policy remain Enterprise work.
- Live customer connector execution remains gated and should not be enabled
  without provider policy bundles, audit evidence and customer approval.
