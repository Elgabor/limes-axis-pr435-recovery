# Axis capability layers and extension contracts

Axis is a sector-independent operational intelligence platform delivered through
one governed product. Seven capability layers assign accountable ownership;
they are not seven new services or an instruction to copy another vendor's
implementation. Layer responsibilities define the target contract; the port
status and linked code distinguish current behavior from planned extensions. [Current runtime architecture](architecture.md) remains the
source of truth for what is implemented. The
[edition matrix](editions.md) separately controls product disposition and export.

[ADR 0015](adr/0015-layered-capability-ownership.md) and the machine-readable
[layer registry](architecture-layers.json) define this contract. The generated
[component and issue inventory](architecture-layers-inventory.md) maps every
current service/package and all 52 issues open on **2026-09-07** to exactly one
owner plus explicit dependencies. A closed issue retains its historical owner;
new work needs a new assignment. This is a dated snapshot, not a live backlog.

## Ownership and failure boundaries

The accountable layer owns its capability contract and reviews changes to it.
Deployment components can host multiple capabilities without becoming their
semantic owner. For example, the control API is assigned to trust for its
principal-binding/composition responsibility; its catalog module belongs to data,
its ontology ports to operational model and its model runtime to intelligence.
Nested evidence paths locate these distinct responsibilities; this inventory is
not a per-file import classifier or a directory-to-edition export policy.

The current Compose backend services also have one capability owner: `postgres`
and `valkey` belong to deployment for shared persistence/cache infrastructure;
`typedb` to operational model; `temporal` to workflow; `temporal-ui` to experience;
`minio` to data; and `keycloak` to trust. The Compose `worker` is the same workflow
service inventoried above. Deployment owns installation/recovery of every backend;
domain owners retain their schemas, grants, keys and consistency contracts. The
core service/package manifest coverage is checked automatically; this backend
mapping must be reviewed when the Compose topology changes.

| Layer | Owns | Failure and tenant boundary | Deployment boundary |
| --- | --- | --- | --- |
| Deployment and delivery | Packaging, configuration, upgrades, rollback, readiness and recovery | Required dependencies block readiness/promotion; operators require explicit scope. Physical separation does not replace tenant checks. | Same versioned product for managed, private-cloud and on-prem profiles; each environment needs its own TLS, capacity and recovery evidence. |
| Trust | Identity, tenancy, authorization, policy, audit, evidence lineage and secrets | Unknown identity/tenant/grant/policy/lease denies governed operations; append-only evidence and tenant scope survive retries. Demo exceptions remain explicitly configured. | No edition or pack may disable mandatory governance; key custody and identity integration are deployment-specific. |
| Data | Connectors, raw ingestion, transformations, quality, catalog and source provenance | Bind resource/schema/generation and claims to tenant. Refuse stale or incomplete work; raw rows remain outside audit/API metadata. | Postgres metadata plus private object sink; source connectivity is independently gated. |
| Operational model | Versioned objects, relationships, logic, action definitions and their permission requirements | Preserve object IDs, schema versions and preconditions. Trust evaluates the declared permissions; graph data does not grant itself access. | Persisted reference state and optional TypeDB adapters retain separate readiness/mutation gates. |
| Workflow | Durable runs, approvals, automations, schedules, scenarios and writeback orchestration | Tenant-bound IDs, idempotency, transaction/outbox ownership and fenced claims; ambiguous delivery needs recovery. | Temporal behind Axis ports; database commit and runtime signal are separate durability boundaries. |
| Intelligence | Search, models, evaluations, agents and global assistant routing | Tenant/principal filtering precedes retrieval/generation. Missing evidence or unapproved egress refuses; proposals do not grant write permission. | Replaceable local/approved model providers; broader search and assistant capabilities remain planned. |
| Experience | Applications, dashboards, vertical packs, SDKs and future low/pro-code tools | Authenticate through public ports, invalidate stale principal state, expose refusal and approval explicitly. | Same API contract across delivery profiles; pack/SDK publication and support need separate evidence. |

Cross-cutting work still has one coordinator. Architecture, performance and code
health umbrellas are assigned to deployment/delivery because they govern release
acceptance; individual data, workflow and intelligence work retains its domain
owner. The product umbrella is assigned to experience. This does not move domain
logic, permissions or production code into deployment scripts.

Dependencies in the registry name collaborating layers, not a strict stack or a
DAG of Python imports. Trust is cross-cutting; approved workflow effects can feed
data/operational state and produce audit evidence. Transport composition and
existing legacy reference dependencies are visible rather than hidden behind a
claim that the code is already cleanly separated.

## Public ports between layers

Here, public means a supported consumer contract inside Axis or its documented
client/authoring surface; it does not mean anonymously callable or OSS-licensed.
The registry records each port's owner, current/planned status, input, output,
failure, compatibility and exact source/document evidence.

| Port | Owner / consumers | Contract and migration rule |
| --- | --- | --- |
| Delivery/readiness | Deployment / all deployed capabilities | Versioned image/chart/config inputs produce dependency readiness and rehearsal evidence. Upgrade and rollback retain ordered migrations; liveness cannot certify durability. |
| Authorization and audit | Trust / all governed callers | `ScopePrincipal`, tenant/scopes and `PermissionRequest` yield decisions or typed denial. Persist required redacted audit with its domain transition; preserve reason codes and append-only history. |
| Connector authoring and sink | Data / adapters, workflows, intelligence | Negotiated read 1.0 or opt-in event 1.1 produces bounded data/checkpoint candidates. Host gates and durable acceptance remain mandatory; imports do not register sources. |
| Catalog and provenance | Data / operational model, intelligence, experience | Tenant-scoped metadata/lineage results retain IDs, cursors, source fingerprints and explicit incompleteness. Source provenance belongs here; audit/evidence policy belongs to trust. |
| Ontology query/mutation | Operational model / workflows, data, intelligence | Typed requests/results and permission metadata through current Axis ports. Existing manufacturing-shaped payloads are legacy compatibility, not the future pack model. Sector-neutral changes need versioned migration. |
| Action definitions | Operational model / workflows, intelligence, experience | Current strict definitions declare parameters and required permissions; they have no per-definition version field yet. Versioning needs a reviewed migration. Registration is neither approval nor external write permission. |
| Workflow runtime and signals | Workflow / data, intelligence, experience | Typed requests/results and stable idempotency keys; retain `axis.approval-decision.v1` signals. Only the existing host owns outbox, claims, retries and requeue. |
| Model invocation | Intelligence / workflows and experience | `ModelInvocationRuntimeRequest` → `ModelInvocationRuntimeResult` after endpoint/egress checks; provider replacement preserves redaction and evidence. |
| Search and assistant | Intelligence / experience; planned | Authenticated query/context → scoped source evidence, refusal or typed proposal. FTS precedes hybrid/answers; future schemas and authorization integration need their own reviewed implementation. |
| Client API and vertical packs | Experience / applications and pack authors | OpenAPI/SDK compatibility applies to current clients. Planned packs declare versioned dependencies and installation plans; no dynamic pack loader or installer ships here. |

General port rules:

- Bind tenant/actor from verified host identity, never client configuration.
  Carry schema/version, operation/idempotency and source evidence where needed.
- Bound rows, bytes, time, concurrency and retention at the owning host. Define
  cancellation and retry semantics explicitly; a timeout is not proof of rollback.
- Use owner-provided contracts, not another layer's tables, driver sessions,
  secrets, private routes or provider payloads. Avoid raw SQL/TypeQL in clients.
- Commit business state and required evidence before external dispatch where
  the existing outbox contract applies. Do not create a new transaction owner
  or claim cross-store atomicity. Remaining external-await debt is tracked in
  [the existing inventory](performance-external-await-boundaries.md).
- Additive protocol changes require explicit version support. Breaking shape,
  permission, cursor or effect semantics need a versioned migration and retained
  compatibility under the [API policy](api-compatibility.md).

## Vertical dependency direction and current debt

A future pack contains declarative, versioned source mappings, object/action
schemas, workflow/scenario definitions and experience configuration. Pack code,
if later supported, belongs in a separate `verticals/` distribution and uses
`axis_verticals` / `axis_packs` namespaces. It consumes core ports. Shared core
must not import pack modules, inspect sector names to choose policy, or obtain
credentials/permissions from pack configuration. No unreviewed-code sandbox or
plugin loader is provided by this contract.

Current shared Python roots are API, worker and SDK; additional service/package
`src` roots are discovered by the check. The checker parses imports without
executing application code and rejects new imports into reserved pack namespaces
or existing manufacturing/reference modules. It covers absolute, relative,
aliased and TYPE_CHECKING imports, exact symbol occurrence counts, and ordinary
importlib / `__import__` loading entry points. New vertical modules inside shared
core roots are rejected; tests and the checker itself are outside runtime roots.

There are **212 existing import occurrences across 29 core files** into historical
reference modules. They include public DTOs in `demo.py`, metadata helpers and
reference readers. Their exact symbols/counts are inventoried and retained for
compatibility. This slice does not rename those DTOs, rewrite persisted IDs or
remove routes. The check prevents growth and requires deleting stale budget
entries when an import disappears; `--write` only regenerates documentation and
cannot discover/approve a new exception automatically.

The rule forbids new coupling; the inventory makes the existing exception debt
explicit. Removing it requires caller/registration/serialization and tenant
behavior evidence, then a compatible extraction into owner-provided contracts.
Current manufacturing names, hard-coded defaults and embedded reference schema
still require that migration. AST checks are a development guard, not proof of
complete sector independence or a security sandbox: arbitrary reflection, runtime
code generation and semantic coupling need code review. New extension namespaces
or loading mechanisms require an ADR and updated guard/tests before adoption.

## Build versus adopt

These are repository architecture decisions, with status and adoption gates;
they do not install new services or certify a vendor/backend.

| Capability | Decision and current evidence | Consequences and next gate |
| --- | --- | --- |
| TypeDB | Retain the adopted, optional TypeDB backend behind Axis query/mutation ports. Axis owns tenant checks, operational contracts and action semantics; do not build a new graph database. [Current ports](../services/api/src/axis_api/ontology/queries.py) coexist with the persisted reference graph. | TypeDB's typed graph/query model fits schema and relationship semantics, but does not supply Axis authorization or workflow ownership. Driver/schema upgrades require pinned-version integration and recovery evidence; current docs for newer TypeDB are not runtime certification. [TypeDB model reference](https://typedb.com/docs/typeql-reference/data-model/). |
| OpenFGA | Retain the current Axis permission evaluator. Defer OpenFGA adoption behind a future permission port until relationship-scale evidence justifies it. No OpenFGA client/service is installed in the current runtime. | OpenFGA models are immutable and should be pinned by ID. Any adoption needs tenant/store mapping, current-grant consistency, outage refusal, tuple lifecycle, dual evaluation and migration/revocation tests. Never replace Axis identity/ABAC/approval rules with an implicit default model. [OpenFGA model versioning](https://openfga.dev/docs/getting-started/immutable-models). |
| Temporal | Keep adopted Temporal OSS through Axis workflow/worker ports; build domain orchestration and governance, not another durable scheduler. [Current adapter](../services/worker/src/axis_worker/temporal_adapter.py). | Workflow history/replay supports durable execution. Activities and external effects still need idempotency, claim fencing and governed retry; Axis audit is separate from workflow history. Runtime upgrades require replay and recovery tests. [Temporal workflow execution](https://docs.temporal.io/workflow-execution). |
| Search | Select PostgreSQL full-text primitives for the first permission-safe FTS slice; build Axis ingestion, source/grant binding and result contracts. Defer separate search/vector engines until measured need; search APIs remain planned in #343–#345. | PostgreSQL provides lexical indexing/ranking. Axis still owns ACL filtering, deletion/reindex consistency and citation evidence. Benchmark corpus size/languages/freshness before adding an engine or semantic adapter; no claim that existing catalog filters are global search. [PostgreSQL FTS](https://www.postgresql.org/docs/16/textsearch-intro.html). |
| Metadata/catalog | Build the narrow Axis asset/provenance/quality contracts on adopted Postgres/object storage. Reuse the [current catalog](platform-data-assets.md) and [lineage owner](../services/api/src/axis_api/data_asset_lineage.py). Defer an external metadata platform integration. | Avoid a second source of truth or a general metadata-management product. An eventual integration must preserve tenant scope, IDs, deletion/retention, provenance and reconciliation; evaluate interoperable export/import before runtime coupling. |

## Verification and unresolved decisions

```sh
make architecture-check
python3 scripts/check_architecture_layers.py --write
# Optional live issue-coverage check; this reads GitHub metadata only.
gh issue list --repo Limes-Labs/limes-axis --state open --limit 200 --json number,title > /tmp/axis-open-issues.json
python3 scripts/check_architecture_layers.py --issues-snapshot /tmp/axis-open-issues.json
```

`make docs-check` and existing CI execute the offline guard. Tests prove duplicate
owners/missing services, issue omissions, stale renders, invalid ports and new
absolute/relative/dynamic vertical imports are rejected. The gate checks the
recorded snapshot offline; it does not silently claim current GitHub coverage.
The PR records a fresh issue comparison, exact revision, full local checks and CI.

Unresolved/NOT RUN: removal of legacy coupling, a production pack installer and
sector-neutral contract migration; OpenFGA adoption/consistency design; search
corpus benchmarks and engine choice beyond initial FTS; external metadata mapping;
per-deployment performance, TLS/HA/recovery certification and live backend upgrade
interoperability. These remain explicit delivery decisions, not new enabled
capabilities or reasons to duplicate identity, audit, credentials or execution.
