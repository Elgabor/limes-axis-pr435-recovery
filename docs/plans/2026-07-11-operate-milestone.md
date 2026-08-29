# Limes Axis — Operate Milestone Plan

Last updated: 2026-07-11
Status: proposed
Tracking: umbrella issue plus one child issue per workstream, GitHub milestone `Operate`, label `operate`.

## Summary

Foundation built the skeleton. Platform built the governed capabilities. Enterprise
made Axis deployable for demanding environments. **Operate** is the milestone where
organizations work with Axis every day: they search their connected data, get
grounded and cited answers, converse with their operational ontology, rehearse
decisions before making them, install packaged verticals, and onboard in minutes
instead of weeks — all inside the governance, audit, tenancy and sovereignty
boundaries the platform already enforces.

Operate also closes every remaining open item from the Platform and Enterprise
milestones, and establishes the boundary between the private commercial source
of truth and a future OSS edition, so both can grow without undermining each
other.

Everything in this plan follows the existing product principles: no external
data egress by default, self-hosted models only, fail-closed permissions,
append-only audit, human approval for risky actions, and durable inspectable
workflows.

## What Operate adds

Four capability tracks, three enablement tracks, and two structural tracks:

| Track | Workstream | One-line goal |
| --- | --- | --- |
| Capability | WS-C Axis Search | Permission-aware search and grounded, cited answers over connected data |
| Capability | WS-D Axis Assistant | Governed natural-language conversation with the ontology, proposing typed actions |
| Capability | WS-E Axis Scenarios | Deterministic what-if simulation on the replay foundation |
| Capability | WS-F Axis for Manufacturing | The finished reference vertical and the reusable vertical template |
| Enablement | WS-A Console redesign | Complete the in-flight governance console redesign |
| Enablement | WS-B Connector framework | Broader source coverage and per-tenant enablement |
| Enablement | WS-G SME enablement | Guided onboarding, single-node profile, default model stack, Italian localization |
| Structural | WS-H Hardening | Close all open Enterprise items, billing-ready metering, repo hygiene |
| Structural | WS-I Editions | Repository restructuring, editions boundary, prospect sandbox design |

## Workstreams

### WS-A — Console redesign completion

**Goal.** Finish the governance console redesign currently in flight on the
`redesign/foundation` branch (design spec and phased plan under
`docs/superpowers/` on that branch). Phase 1 foundation work (test harness,
unified state panels, primitive wrappers, stale-while-revalidate data layer,
centralized strings/glossary) is committed; phases 2–6 remain.

**Deliverables.**

- [ ] Phase 2: action-first overview and decision-first approvals.
- [ ] Phase 3: agents and workflows surfaces rebuilt on the new primitives.
- [ ] Phase 4: connector console decomposition and ontology entity slide-over.
- [ ] Phase 5: audit, policies, simulation and models pages.
- [ ] Phase 6: guided onboarding checklist and first-class demo-data switch.
- [ ] Sync the redesign plan checkboxes with the work already committed.

**Approach.** Execute the existing redesign plan as written; it is grounded
against the verified API surface. All later console work in this milestone
(search page, assistant panel, scenarios tab) renders through the primitives
this workstream ships, which is why it leads the phase ordering.

**Dependencies.** None inbound. WS-C/D/E console surfaces and WS-G
localization depend on it.

### WS-B — Connector framework completion

**Goal.** Close the open Platform item: build the full connector framework
beyond preview-only manifests, with broader source coverage and per-tenant
enablement.

**Deliverables.**

- [ ] Object-storage drop ingestion (S3/MinIO bucket sources) reusing the
      existing object-store adapter (`services/api/src/axis_api/object_storage.py`).
- [ ] Generic REST-pull connector type behind the existing egress policy and
      credential lease machinery.
- [ ] Additional external database profile (MySQL/MariaDB) behind the existing
      execution adapter boundary.
- [ ] Per-tenant connector enablement records with console controls.
- [ ] A documented connector-authoring contract so vertical packs (WS-F) can
      ship connector definitions.

**Approach.** Every new source type slots behind the same fail-closed gate
chain that already governs connector execution: manifests
(`connector_manifests.py`), governed runs (`connector_runs.py`), execution
adapters (`connector_execution.py`), credential leases
(`connector_credential_leases.py`), egress policies
(`connector_egress_policies.py`) and ontology promotion
(`connector_ontology_promotions.py`). No new trust paths.

**Dependencies.** None inbound. WS-C indexing consumes connector sync output;
WS-F consumes the authoring contract.

### WS-C — Axis Search: permission-aware search and grounded answers

**Goal.** Tenant-scoped semantic search across connected data, the ontology,
uploaded documents and governance artifacts — and grounded answers that cite
their sources and refuse when grounding is missing. Self-hosted models only,
through the existing model router.

**Deliverables.**

- [ ] Search foundation: `workplace_search.py` behind a search adapter port —
      Postgres full-text search first, exactly as the architecture default
      prescribes ("search starts from Postgres and remains behind an adapter").
- [ ] Indexing pipeline: `workplace_indexing.py` with tenant-scoped
      `search_documents`, `search_chunks` and `search_index_jobs` tables,
      content-hash idempotency, a scheduled Temporal sweep in the worker, and
      an inline re-index hook where connector ontology promotions land.
- [ ] Source coverage, phased: connector-synced records and ontology entities
      first; uploaded documents next; audit and governance artifacts last.
- [ ] Document upload subsystem: PDF/DOCX/office text extraction with size and
      type limits, stored through the object-store adapter.
- [ ] Embedding support: a `capability` field on model endpoints
      (`model_endpoints.py`) so embedding models route through the same
      governed invocation boundary (`model_invocations.py`) — metered,
      audited, external egress blocked by default.
- [ ] Hybrid retrieval behind an explicit flag: Postgres FTS fused with
      pgvector cosine similarity (reciprocal-rank fusion). Requires the
      pgvector-enabled Postgres image in Compose and Helm, a gated
      `CREATE EXTENSION` migration and a deployment readiness check. Without
      an embedding endpoint, search degrades gracefully to FTS-only — that is
      the shipped v1, not a failure mode.
- [ ] Grounded answers: `workplace_answers.py` — retrieval, prompt assembly,
      model invocation, citation binding. Answers must cite retrieved
      documents; when retrieval is empty the endpoint refuses instead of
      generating.
- [ ] Permission filtering: tenant scoping in SQL plus fail-closed
      post-filtering through the existing relationship-aware authorization
      (`ontology_authorization.py`). A document with unresolvable access refs
      is never returned. Dedicated permission-matrix tests, and new rows in
      the tenant isolation suite.
- [ ] Console: a search page with cited answer view, plus a "search
      everything" entry in the command menu. Citations open the ontology
      entity sheet or the raw-payload inspector.
- [ ] Audit events (`workplace.search.executed`, `workplace.answer.generated`
      — bounded query representation, never raw text in the ledger) and usage
      metrics (search queries, embedding tokens) through `usage_metering.py`.
- [ ] Feature flags off by default, consistent with every execution boundary.

**Dependencies.** WS-B (indexing hook), existing model router. Console page
after WS-A phase 4.

### WS-D — Axis Assistant: governed ontology conversation

**Goal.** Converse with the tenant's operational ontology in natural
language. The assistant reads only what the signed-in principal may read,
cites everything it asserts, and when asked to act it proposes a typed action
through the existing agent-run machinery — never a new execution path.

**Deliverables.**

- [ ] Conversation persistence: `assistant_conversations.py` with append-only
      conversation and message tables, wired into tenant deletion/export
      (WS-H) from day one.
- [ ] Grounding layer: `assistant_grounding.py` — a bounded, read-only,
      pre-governed tool surface: ontology queries through the existing query
      runtime filtered by relationship scopes, Axis Search retrieval (WS-C),
      and registry reads (workflows, approvals, connectors). No raw database
      access, no write tools. Tool availability per turn is gated by the
      principal's scopes — the assistant can never read more than its user.
- [ ] Cite-or-refuse composer: assertions about tenant data must carry
      grounding references or the turn is rejected, following the same
      fail-closed philosophy as the agent-run proposal parser.
- [ ] Action proposals through existing machinery: an action request creates
      an agent run in propose mode (`agent_runs.py`), subject to the L0-L4
      autonomy ceilings, the typed action registry, the approval inbox and
      the audit ledger — unchanged. Chat is a surface, not a new authority.
- [ ] Prompt-injection posture as a design invariant: retrieved content is
      data-fenced in prompts, the assistant holds zero write tools, and every
      action requires human approval.
- [ ] Console: a global context-aware assistant panel openable from every
      page (aware of the current page and entity) plus a dedicated assistant
      page for long conversations. Citation chips open the entity sheet;
      proposal cards reuse the approvals pattern.
- [ ] Bounded tool calls and query depth per turn to control graph query
      cost; audit events and usage metrics for every turn; flag off by
      default.
- [ ] A fixture-based grounding evaluation suite in the API tests, since
      grounding quality on small self-hosted models is the main quality risk.

**Dependencies.** WS-C retrieval; existing agent-run and approval machinery.
Console surfaces after WS-A.

### WS-E — Axis Scenarios: what-if simulation

**Goal.** Forward-looking decision rehearsal on the replay foundation. The
existing replay module answers "what would have happened under different
policies" over historical windows; scenarios answer "what would happen if" —
same governed, deterministic engine philosophy, forward direction.

**Deliverables.**

- [ ] `scenario_simulation.py`, structurally parallel to
      `replay_simulation.py`: typed query models, permission checks,
      deterministic evaluation, hashed inputs, persisted governed outputs
      with the same retention and legal-hold semantics.
- [ ] A generic typed-perturbation contract: scenario vocabularies are
      registered by vertical packs, not hard-coded. The manufacturing pack
      ships first: supplier lead-time delta, demand multiplier, capacity
      outage window, policy-set override.
- [ ] Scenario definitions and runs as tenant-scoped records with
      idempotency, baseline hashing and result digests.
- [ ] Console: a scenario builder as a second tab on the simulation surface,
      reusing the baseline-versus-simulated diff view.
- [ ] Optional, flagged: model-generated narration of a scenario diff
      (plain-language summary through the model router). Never
      model-generated scenarios — the engine stays deterministic.

**Positioning.** Governed decision rehearsal, not prediction. No forecasting
claims.

**Dependencies.** None hard; console tab after WS-A phase 5. Vocabulary
registration contract shared with WS-F.

### WS-F — Axis for Manufacturing and the vertical template

**Goal.** Close the open Platform item (the manufacturing operations
reference demo) and productize it as the first packaged vertical, defining
the reusable template every future vertical follows.

**Deliverables.**

- [ ] Finish the manufacturing reference: live workflow execution through the
      Temporal adapter and connector-backed production actions, closing the
      full loop — connector sync, ontology promotion, agent proposal, human
      approval, action run, audit.
- [ ] Extract the vertical template: a versioned, tenant-installable pack
      containing an ontology pack (schema fragment plus reference graph), an
      agent pack (registered agents with autonomy defaults), a workflow pack,
      a connector pack (manifests), a scenario vocabulary pack (WS-E) and a
      demo dataset.
- [ ] Wire pack installation into the demo-data switch shipped by the console
      redesign, and upgrade `examples/manufacturing-plant` to install the
      pack end to end.
- [ ] `docs/verticals.md`: the template contract.
- [ ] Validate the template shape on paper against a second vertical —
      logistics and supply chain — chosen for its ontology overlap with
      manufacturing (suppliers, orders, shipments, warehouses, delays).
      Design-level only; no second vertical is built in this milestone.

**Dependencies.** WS-B (connector-backed actions), WS-C/D/E (the demo
showcases them), WS-A phase 6 (demo switch). This workstream is the
milestone's integration finale.

### WS-G — SME enablement

**Goal.** A small or medium enterprise can evaluate and adopt Axis without a
platform team.

**Deliverables.**

- [ ] Guided onboarding: the redesign's onboarding checklist extended with a
      one-command demo tenant — a single script that provisions a tenant
      (through the existing tenant lifecycle machinery in
      `platform_tenants.py`) and installs the manufacturing vertical pack.
- [ ] Single-node deployment profile: a fourth Helm profile plus a slimmed
      Compose profile for one-server installs, with render checks and
      deployment readiness gates. The deferred ontology runtime (Postgres-
      served reference graph) makes the graph store optional at this tier.
- [ ] Default model stack in the demo runtime: a documented, swappable
      default pairing — a small multilingual embedding model and a small
      European open-weight multilingual instruct model — served self-hosted
      through the existing router, so search and the assistant work out of
      the box without model expertise. Operators can replace both freely.
- [ ] Internationalization with Italian first: extract the centralized
      console strings layer into a message-catalog framework with Italian as
      the first non-English locale. **Sequencing rule:** localization starts
      only after WS-A fully merges — translating copy while every page is
      being rewritten guarantees churn; the centralized strings discipline
      the redesign enforces is precisely what makes localization cheap
      afterwards.

**Dependencies.** Onboarding depends on WS-A phase 6; the single-node profile
is independent; localization depends on WS-A completion.

### WS-H — SaaS and enterprise hardening

**Goal.** Close every remaining open Platform and Enterprise checkbox in
`plan.md`, make usage metering billing-ready, and bring the repository's
community hygiene up to the standard the rest of the project already meets.

**Deliverables.**

- [ ] Tenant deletion and data-export pipelines with approval-gated lifecycle
      transitions (open Enterprise item), reusing the object-store export,
      manifest and checksum patterns. Assistant conversations and search
      indexes participate from day one.
- [ ] Billing-ready metering: extend `usage_metering.py` with model tokens,
      search queries, embedding tokens and assistant turns, and add an
      exportable, signed per-tenant usage statement.
- [ ] Sustained production HA validation under customer-profile load and TLS
      (open Platform item), extending the existing rehearsal runbooks.
- [ ] Production backup, restore, retention and disaster recovery composed
      into one drilled procedure across all stateful services (open item).
- [ ] Enterprise audit export beyond current retention and WORM controls:
      provider-specific KMS signing, richer legal operations, deterministic
      workflow replay (open item).
- [ ] Enterprise identity and SSO hardening beyond the current OIDC baseline
      (open item).
- [ ] Complete single-tenant managed and private-cloud/on-prem reference
      architectures (open items).
- [ ] External security review, penetration testing and production threat
      model validation (open item) — scheduled **last**, after the new search
      and assistant surface exists, so the review covers it.
- [ ] Repository hygiene: CHANGELOG, an architecture decision record
      directory with the first records, CODEOWNERS, a code of conduct,
      SUPPORT.md and automated dependency updates.

**Dependencies.** Metering extensions depend on WS-C/D landing their choke
points; the security review depends on everything else stabilizing.

### WS-I — Editions: repository restructuring, boundary and prospect sandbox

**Goal.** Establish a clear, honest boundary between the private commercial
source of truth and a future OSS edition, define the publication gate, and
design the hosted prospect sandbox. This is the first workstream to execute.

**Deliverables.**

- [x] Repository-topology decision: keep `Limes-Labs/limes-axis` private as the
      complete commercial source of truth. Any future `limes-axis-oss` is a
      files-only, allowlisted export into a new repository with fresh history;
      it is not a fork, upstream or automatic synchronization target.
- [x] Editions audit: a feature-by-feature disposition against a written
      boundary rule — *single-tenant self-hosting stays fully usable in the
      open-source edition; operating many tenants, compliance-as-a-service
      and bespoke enterprise deployment engineering belong to the commercial
      edition.* Candidate areas for commercial-edition ownership: the SaaS
      operator machinery, compliance-grade audit internals and
      enterprise deployment profiles. Where moving a capability would break
      self-hosting usability, the future OSS edition keeps a simplified,
      always-usable baseline. Nothing already shipped is erased; this is a
      forward-shipping boundary, stated transparently.
- [x] `docs/editions.md`: the public editions statement — what the
      open-source edition includes, and the commercial edition's value by
      category: managed European model endpoints, a maintained premium
      connector pack for major enterprise systems, a compliance pack
      (managed key signing, retention operations, recovery drills, signed
      reports) and an organization administration pack (multi-organization
      management, user provisioning, advanced SSO federation). Categories
      only; no pricing in this repository.
- [ ] Prospect sandbox design: invite-based dedicated demo tenants with the
      manufacturing vertical pre-loaded, automatic reset and time-boxed
      access, as the first hosted-edition deliverable. Self-serve trials are
      explicitly deferred until billing and abuse prevention exist.

**Dependencies.** None inbound — this executes first. The sandbox build
happens in the commercial repository once WS-F's vertical pack exists.

## Phase ordering

No dates; sequencing and dependency order only.

**Phase 1 — close and clear the ground.** WS-I (restructuring record,
editions audit, editions doc, sandbox design) leads. In parallel: WS-A phases
2–4, WS-B, WS-C part one (indexing plus FTS-only search API over connector
and ontology sources), WS-H tenant lifecycle/HA/metering groundwork and repo
hygiene, WS-G single-node profile. These tracks touch largely disjoint areas
(console components, connector modules, new search modules, tenant and infra
work), so pull requests proceed in parallel without collisions.

**Phase 2 — capabilities land.** WS-C part two (hybrid retrieval, document
upload, grounded answers, search page), then WS-D (the assistant grounds on
retrieval). WS-E engine and API. WS-A phases 5–6. WS-G onboarding and the
default model stack. WS-H disaster recovery, audit export and SSO hardening.
Hosted sandbox build begins in the private repository.

**Phase 3 — package, localize, prove.** WS-F finishes the manufacturing
reference and extracts the vertical template (and the audit-artifact search
source lands). WS-G Italian localization begins after the console redesign
has fully merged. WS-H reference architectures, then the external security
review last — so it covers the full new surface.

## Risk register

| Risk | Mitigation |
| --- | --- |
| pgvector not present in stock Postgres images | Vector search is an upgrade behind the adapter port, never a prerequisite; FTS-only is the shipped baseline; image swap gated by migration and readiness checks |
| Embedding/model operations burden for small teams | Documented default model pairing in the demo runtime; graceful FTS-only degradation; models swappable through the router |
| Access-control leak through search | Fail-closed post-filtering, dedicated permission-matrix tests, tenant isolation suite rows, in scope for the external security review |
| Grounding quality on small self-hosted models | Cite-or-refuse composer, fail-closed proposal parsing, fixture-based grounding evaluation suite |
| Prompt injection via connected content | Data-fenced retrieved content, zero write tools, human approval on every action — stated as a design invariant |
| Graph query cost per assistant turn | Bounded tool calls and query depth per turn, preference for the Postgres-served reference runtime where enabled |
| Scenario results read as predictions | Deterministic engine, no forecasting claims, "decision rehearsal" framing throughout |
| Localization churn | Italian localization starts only after the console redesign merges; centralized strings layer is the single extraction point |
| Editions boundary erodes community trust | Public boundary rule, no removal of shipped self-hosting capability, simplified always-usable baselines, transparent editions doc |

## Future directions (out of scope for Operate)

Public-sector and government deployments are a natural future direction for a
sovereign control plane — candidate ideas include validated air-gapped
deployment paths, alignment with European security frameworks such as NIS2
and national qualification schemes, and public-sector connector categories.
None of this is committed in Operate; it is recorded here only so the
direction is visible.

## Non-goals

- No external model providers and no data egress by default — unchanged.
- No predictive or forecasting claims for scenarios.
- No government commitments in this milestone.
- No pricing, commercial terms or customer-specific material in this
  repository.
- No second vertical implementation (logistics is validated at design level
  only).
- No self-serve trial signup in this milestone.
