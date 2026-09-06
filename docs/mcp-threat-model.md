# MCP gateway threat model

This model accompanies the [gateway specification](mcp-gateway.md) and
[ADR 0010](adr/0010-mcp-gateway-boundary.md). It covers the planned remote HTTP
adapter, its clients and domain dispatch. **The gateway is not implemented.**
Existing Axis tests support only the controls they actually exercise; all MCP
wire, identity-provider deployment and adversarial client cases remain NOT RUN.

## Assets, actors and trust boundaries

Protect tenant data and its existence, identity and scope grants, connector/model
credentials, source provenance, approvals, workflow effects, append-only audit,
availability and usage budgets. A legitimate client can be compromised or request
more authority than its user intended. Source documents, search results, model
output, prompt arguments, tool names and metadata are untrusted. A tenant's
authorized content author does not thereby become an Axis operator or approver.

The host is trusted to honor its user's consent and protect content after receipt;
Axis cannot retract data already disclosed to it. The IdP and configured issuer
keys are trusted to issue correct access tokens. API/domain policy, persistence
and worker runtimes are the trusted enforcement base. A fully compromised host,
IdP, application process or database administrator is outside this adapter's
containment claim and remains part of deployment/security operations.

Review these crossings independently: host to HTTP transport; bearer to principal;
principal to tenant/object; retrieved content to model context; model arguments to
domain command; domain command to external effect; durable handle back to a new
request; audit/telemetry back to an operator. The adapter must not widen authority
at any crossing. The upstream
[authorization security guidance](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations)
also requires resource binding and forbids token passthrough.

## Threats and required controls

This table defines defensive acceptance cases, not a claim of completed testing.
Tests use synthetic local tenants, content and credentials and stub external
effects. No production customer data or third-party target is needed.

| ID / threat | Required control and owner | Gateway acceptance evidence required before enablement |
| --- | --- | --- |
| M01 — Direct or retrieved prompt injection changes intended authority | Treat source text, descriptions and tool output as data. Operator-owned prompt templates cannot be replaced by retrieved instructions. API validates arguments and resolves the registered domain command; domain checks policy, risk, relationship scopes and approval independently of model text. | Insert conflicting instructions into a local source fixture; authorized read preserves provenance, and subsequent proposal cannot expand its scope, execute an action, approve it or select a new egress destination. |
| M02 — Confused deputy or token passthrough uses a more privileged downstream identity | Dedicated resource audience and issuer/client binding at API admission; explicit OAuth grants intersect Axis policy. External credentials stay behind the existing credential, egress and execution owners with originating principal attribution. | Wrong API audience, wrong issuer/client profile and substituted identity are rejected before a domain read. Spy runtimes observe no inbound bearer in provider/worker arguments, evidence or logs. A low-scope caller cannot borrow operator authority. |
| M03 — Cross-tenant capability or object discovery | Filter catalog, names, descriptions, counts, snippets and resource templates by current principal and tenant before pagination. Resolve opaque object IDs through tenant-scoped queries; recheck relationships and schema visibility. | Two tenants with different integrations/objects receive disjoint authorized projections. Guessing a foreign identifier has the same sanitized result as an unknown one; nested input tenant fields, cursor reuse and task handles never change the tenant. |
| M04 — Exfiltration through search, links, errors, schemas or model output | Metadata-only allowlisted projections with response budgets and source references; resource URIs are internal identifiers. No raw source rows, signed object-store URLs, credentials, arbitrary URL fetching or remote schema references. Host/client consent covers what is disclosed. | Synthetic secret markers stay absent from names, descriptions, output, errors and telemetry. Link/schema resolution makes no network request. A requested output destination outside the approved domain path is refused. |
| M05 — OAuth discovery, redirect or issuer confusion | Trusted issuer configuration, pre-registered clients, PKCE/state and exact redirect URIs; issuer validation before code redemption. Metadata is static public configuration, never a URL selected by tool input. | Local IdP/client conformance verifies resource-bound tokens and mismatched issuer/redirect refusal. Unexpected registration/metadata URLs do not produce outbound requests. |
| M06 — Cached discovery, cursors or handles retain revoked authority | No-store/private-zero-TTL baseline. Bind cursors to principal/client/tenant/grant fingerprint and revision; bind tasks to creator/operation. Check token and registered active tenant again on every call. | Scope reduction, client change, tenant suspension, cursor expiry and policy revision invalidate access. Fresh tokens for the same authorized identity can resume their own task; unrelated callers cannot. |
| M07 — Duplicate proposal or task retry repeats an effect | Explicit idempotency key scoped to domain tenant/action, durable intent and existing transaction/outbox ownership. Proposal capability cannot directly use an executor. Human decisions stay in the governed approval path. | Concurrent duplicate calls, crash after commit, delayed dispatch and conflicting payload reuse produce one intended operation and append-only evidence. `tasks/update` cannot decide an approval. |
| M08 — Resource exhaustion through discovery, JSON, searches, SSE or polling | Bound bytes, schema/nesting, page/query work, synchronous time, shared rate/concurrency and task count before work. Fail closed on quota backend failure. Release admission reservations on all paths. | Local load/fault run measures bounds across at least two API replicas; oversized/deep input, disconnect, fast polling and backend outage cause bounded refusal without unbounded work or leaked slots. |
| M09 — Proxy/header disagreement or browser origin abuse | Transport compares required header metadata to the parsed body; validates Origin. Proxy forwards the Authorization header only to the configured API resource, with body/header limits and TLS. | Conformance cases show one interpretation of method/version/name, refusal of mismatches or invalid Origin, and no domain dispatch when transport validation fails. |
| M10 — Task lifecycle or response misrepresents execution | API task projection reads durable domain state, checks creator permissions and emits typed/redacted output. Cancellation acknowledgement is distinct from domain cancellation. Audit retains evidence beyond handle expiry. | API/worker restart preserves the result; completion/cancellation race does not fabricate rollback. Business errors use completed tool errors; protocol failure uses failed. Hidden/expired task and unknown task responses do not reveal existence. |

## Current Axis evidence and gaps

The following suites are executable today. Run them on the PR's exact revision;
a reference to a test is not evidence that it was run. They establish reusable
owner behavior, **not** the MCP-specific controls in the table above.

| Control foundation | Existing executable evidence | Remaining gateway work |
| --- | --- | --- |
| Verified issuer/audience and body actor binding | [Identity tests](../services/api/tests/test_identity.py), [authenticated read gate](../services/api/tests/test_identity_session_gate.py) | Dedicated MCP audience/client profile, required access-token claims, OAuth discovery/PKCE and explicit-grant intersection. Generic verification has no MCP resource registration. |
| Tenant admission and isolation | [Tenant isolation](../services/api/tests/test_tenant_isolation.py), [tenant lifecycle](../services/api/tests/test_platform_tenants.py) | Authenticated filtered catalogs, no demo fallbacks, tenant/client-bound URI/cursor/task resolution. |
| Scope and relationship checks | [Permission tests](../services/api/tests/test_permissions.py), [ontology authorization](../services/api/tests/test_ontology_authorization.py) | Shared checks before every MCP projection; no broad graph or metadata fallback after an entity denial. |
| Typed action payload, policy, idempotency and approvals | [Action runs](../services/api/tests/test_action_runs.py), [agent proposals](../services/api/tests/test_agent_runs.py), [approval outbox](../services/api/tests/test_approval_decision_outbox_contract.py) | Proposal-only command seam and transport-neutral authority reuse; task creation/recovery cannot bypass the existing boundary. |
| Credential redaction and egress | [Connector egress](../services/api/tests/test_connector_egress_policies.py), [credential disclosure isolation](../services/api/tests/test_tenant_isolation.py) | MCP content/schema/error/log redaction and no passthrough proof at the actual adapter. |
| Shared fail-closed rate admission | [Rate-limit tests](../services/api/tests/test_rate_limit.py) | MCP-specific keys, concurrency/task reservations, response/query budgets and multi-replica load/soak evidence. |

The anonymous paths in `bind_request_actor` and `authorize_principal_scopes` are
intentional demo compatibility; MCP admission must not call them with `None`.
Current generic tenant reads do not all impose a domain read scope, so the new
explicit MCP read grants are additional admission requirements. Current action
creation can signal a workflow; substituting it for proposal creation fails M07.
Current REST cursors and Temporal IDs are not proof of bound MCP handles.

## Review and residual risk

The API owner owns M02–M06 and M09; domain/worker owners own M01, M07 and M10;
API/deployment owners jointly own M08. Each implementation PR records the exact
cases exercised, local/CI/deployed evidence, unresolved findings and release state.
An unimplemented control keeps the affected capability disabled and undiscoverable.
Revisit this model when the protocol pin, IdP/client registration policy,
capability effects, resource projections, cache policy or task lifecycle changes.

Residual risks include a host leaking legitimately disclosed data, misleading
source content despite provenance, compromised identity or infrastructure, and
capacity limits not yet measured under production load. Operator-reviewed
client consent, minimal disclosure, provenance, deployment hardening and incident
response address these outside the adapter. This design accepts no bypass of
tenant binding, consent, least privilege, approvals, egress or audit to reduce
those integration costs. Production conformance and penetration testing are NOT RUN.
