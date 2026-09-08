# Console clarity review — issue #433

The console should help an operations team move from connected business data to a reviewable decision and its recorded outcome. This delivery revises presentation across the existing console; it does not establish new execution, deployment, compliance, or market capabilities.

## Design references

Reviewed the supplied eight dashboard images and public previews from [Board UI](https://www.boardui.com/components) and [Efferd dashboards](https://efferd.com/blocks/dashboard). No commercial component source or new library is imported.

- Board UI bar list: directly label categories, counts and shares; use one visible denominator. Applied to the returned audit window. The alternate combo view pairs per-date event counts with the share marked Watch or Action required. Hover or keyboard focus previews a date; click, tap or Enter pins it, and Reset/Escape restores the window summary. Both axes remain visible for up to seven dates; denser windows scroll internally.
- Board UI revenue, funnel, heatmap and combo previews: select a visual only when the underlying measures justify it. Axis has no complete revenue series, conversion cohort or hourly activity matrix in this view; revenue or conversion graphics would imply unsupported business measurements here. The audit page can support an original seven-date/six-hour heatmap, and model routing can support a provider-to-model flow weighted by configured route counts. Those are now implemented from existing response contracts. Selecting a heatmap interval filters the audit events with the existing tenant/event/scope filters. Selecting a provider or model highlights its dependencies and offers an explicit route-inspection action. These diagrams do not represent observed model traffic.
- Efferd dashboard 6: put attention items and their next action ahead of supporting detail. Keep cards aligned and use whitespace to separate tasks.
- The [Palantir application-building documentation](https://www.palantir.com/docs/foundry/app-building/overview/) connects data exploration with operational applications and actions. [Quantexa supply-chain intelligence](https://www.quantexa.com/solutions/supply-chain-intelligence/) emphasizes connected supplier context; [ChapsVision manufacturing](https://www.chapsvision.com/fr/secteurs/industrie-manufacturiere/) emphasizes connected industrial data. Our design inference is to prioritize business objects, decisions and traceability for SME/enterprise operators. These sources do not establish feature parity or substantiate the supplied European contract estimates.

## Page-by-page decisions

All 17 routes below were reviewed at 1440 × 1000 and 390 × 844 in the in-app browser against an isolated local PostgreSQL/API fixture. Shared page headers now state the page's purpose once; the decorative topbar slogan and repeated navigation category are removed. The API, demo and data-source indicators remain. The dark theme keeps the Axis navy palette with a plain background so decorative dots and glow no longer show through data cards.

| Page | Before | After | Why |
| --- | --- | --- | --- |
| Overview | Large scenario hero and setup preceded decisions; radar encoded statuses as arbitrary numbers; unlabeled category sparkbars | Compact persisted counts, attention alongside labeled category bars, setup below decisions, one recent-event list | Show the next decision early and make quantities interpretable |
| Approvals | Long header; flex metrics stretched the final card | Short purpose statement; equal-width metric columns | Preserve the decision, risks, evidence, permission gate and external-executor boundary |
| Workflows | Verbose purpose statement; a blocking-approval link opened the generic inbox | Short purpose and direct link to the recorded blocking approval; retain the accurate empty state | Reach the decision that blocks this run without selecting an unrelated approval |
| Agents | Agent registry and action catalog competed on one page | Agent registry first; action catalog and registry notes expandable | Operators can inspect an agent before opening technical action definitions |
| Data | Sidebar destination returned 404; filter changes could retain an excluded selected asset | Route renders the tenant-bound catalog; changing search or evidence clears the previous selection | Make the capability reachable and show the matching asset instead of a false no-results detail |
| Connectors | Manifest JSON import above the registry | Registry first; advanced import below it in an explicit disclosure | Standard connection and monitoring remain the primary path; partial CSV previews report included and excluded counts without labeling valid over-limit rows as invalid |
| Ontology | Generic title, graph labels shrank on phones, adapter identifiers displayed as headings | Business-object title, mobile object cards by default and optional full-size scrollable graph with 13px labels; sources/access details expandable | Keep relationships readable and technical inspection available |
| Entity detail | Dense but relevant business attributes and relationships | Short purpose and object summary before metrics; preserve relationship and history detail | These facts explain the selected object and its evidence |
| Models | Verbose purpose; monitoring implementation named as a main section | Short purpose; separate agent and model metadata lines; expandable monitoring details and a provider-to-model configuration flow | Preserve example/live distinction, cost basis and routing boundaries |
| Policies | Creation form always open below the registry | Explicit create-policy disclosure; registry remains first | Reading and authoring are separate tasks; evaluation semantics remain available |
| Policy detail | Revision, conditions and comparison | Short purpose; preserve revision and comparison controls | Rules and historical differences are necessary to assess a change |
| Audit | Database engine and replay capability presented as numeric KPIs | Operational event metrics and readable event labels; separate metadata lines; keep raw inspection and replay/export details; add an interactive temporal heatmap | Backend implementation is not an operational measurement |
| Simulation | Long header plus empty replay history | Short purpose; retain accurate empty history | Do not manufacture comparison results |
| Tenants | Provisioning form always open | Explicit create-organization disclosure below registry | Keep lifecycle status and operator scope visible before authoring |
| Tenant detail | Lifecycle, quotas and terminology controls mixed with endpoints and repeated implementation notes | Keep fields, review actions and blank-field semantics visible; move access and methodology into named disclosures | These settings describe real administrative effects |
| Settings | Repeated category header; guidance mixed with raw check messages | Action guidance remains visible; technical check details expand on demand | Make remediation readable while retaining support evidence |
| Sessions | Access gate and session management | Shared header cleanup; preserve sign-in/scope gate | A simpler page must not imply session-management permission |

## Measurement and access rules

The category bars count every event in the returned audit window, with a maximum requested size of 25; this is neither lifetime activity nor a time trend. Visible text exposes counts and rounded percentages independently of decorative bars. The source pill preserves live/reference provenance. Empty and unavailable sources have different states. The removed radar also inferred connector health from event presence, which cannot establish service health.

Attention cards keep the full title above their actions; reference workflows are explicitly labeled and link to recorded runs. Graph labels use deterministic free-space placement with full accessible names; crowded labels appear on focus/hover while all objects remain available in List. Explicit zoom enables touch panning and Reset restores native scrolling.

Native disclosures retain form drafts while collapsed and remain keyboard-operable. Their children keep existing identity/tenant/query and mutation gates. The graph has a bounded scroll region so its full-size content does not overflow the page; mouse view navigation and explicit zoom controls remain. Keyboard focus includes disclosure summaries and focusable regions. No schema, authentication, transaction, egress or backend execution behavior changes.

## Validation

The pull request records final local, browser and CI results separately. Local `make verify` passed: API 2,560 passed / 43 skipped, worker 64 passed / 3 skipped, SDK 278 passed, web 992 passed, schema and repository contract gates passed. The skipped integration lanes require their own live services. Browser fixtures are synthetic and local; they are not hosted deployment proof. Workflow and simulation were reviewed in their empty runtime states, sessions in the unauthenticated gate, and policies/tenant/entity detail with seeded records.

A bounded synthetic load exercise used the unchanged API through ASGI and a separate PostgreSQL database: 3,978 measured requests with four clients, zero contract mismatches, CSV tiers of 100/1,000/5,000 rows. Ten-second preview windows measured p95 64.05/95.06/147.49 ms. The mapping cap remains 500 rows; all input rows are validated, but excess valid rows are not mapped. Five invalid/schema variants per tier were blocked as expected. This is preview/query evidence with fixture identity, not bulk ingestion, network, IdP, saturation or production-capacity proof. The UI now states partial preview coverage in the wizard and Runs. The local evidence bundle retains the exact fixtures, results, manifest and reproduction script.

For a future scouter, the existing discovery/read ports, schema observations, reviewed source activation and checkpoint/evidence owners are reusable. A semantic mapping proposal must remain distinct from an observed schema and require review before activation or ontology promotion. Sparse-data analysis must distinguish observed, derived, proposed and unknown values; interpolation cannot fill missing production facts. No crawler or semantic inference is implemented by this UI revision.

## Platform layers and product completeness

The [seven-layer contract](layered-architecture.md) assigns ownership within the existing product. These are capability boundaries, not seven separate services. This source review distinguishes implemented paths from reference data and planned extensions; it adds no runtime capability or deployment evidence.

| Layer | Implemented | Current boundary |
| --- | --- | --- |
| Deployment and delivery | Versioned configuration, service packaging and dependency readiness | Each installation still needs its own capacity and recovery evidence. |
| Trust | OIDC identity, tenant binding, scope and relationship checks, policies, approvals and audit | Domain transitions retain their permission and evidence owners; infrastructure separation does not replace tenant checks. |
| Data | Governed CSV, Postgres and S3/MinIO ingestion, catalog and source provenance | Raw payloads belong in object storage; SQL stores metadata. CDC, production event ingress and source writeback remain absent. |
| Operational model | Persisted reference graph, optional TypeDB query/mutation adapters and typed action definitions | Existing manufacturing contracts and core/reference dependencies need compatible migration; action definitions have no individual version field. |
| Workflow | Axis runtime ports, Temporal execution, approval signals, outbox and fenced ingestion claims | External calls and database commits have distinct durability boundaries; some request paths still retain a transaction across external waits. |
| Intelligence | Governed model invocation and L1/L2 agent recommendation/proposal runs | Execution is opt-in. Global search and assistant routing are planned; the agent registry remains a reference surface. |
| Experience | Next.js console, public API contracts, runtime response validation and Python SDK | Vertical pack installation and low-code tools are planned. Presentation must preserve reference, configured runtime and planned states. |

The [current architecture](architecture.md), [connector matrix](connector-capabilities.md), [agent contract](platform-agents.md) and [model invocation contract](platform-model-routing.md) locate the owning code and its limits. Three bounded follow-up priorities emerge for SME and enterprise use:

1. **Prove a second operational scenario through shared contracts.** Select one object/action contract for compatible extraction and versioning, preserving IDs, tenant behavior and public aliases. The [architecture inventory](architecture-layers-inventory.md) records existing reference coupling; its guard prevents growth but does not establish full sector independence.
2. **Complete one customer-validated decision path.** Trace an activated source through business objects and provenance to a proposal, approval and recorded outcome. Choose the next missing capability from that use case: for example, permission-safe search or one governed source writeback. The [layer contract](layered-architecture.md) marks search as planned; the [connector matrix](connector-capabilities.md) distinguishes internal ontology promotion from external writes.
3. **Resolve one remaining external-wait and recovery boundary.** Start with an agent or action path, defining durable intent, replay and handling of an unknown outcome. The [transaction inventory](performance-external-await-boundaries.md) identifies remaining paths; the [model contract](platform-model-routing.md) records the current manual recovery limit. Verify interruptions and duplicate delivery before extending execution claims.

The visual review also includes isolated schema-checked JSON scenarios (typical, sparse, empty and dense) rendered with the actual three chart components and product CSS. A separate ontology JSON exercise preserved all node/relationship identities at 18/60/200 nodes; the dense graph intentionally defers labels to focus and the complete list. These are synthetic visualization checks, not customer data, measured business outcomes or production browser capacity.

## Interactive review status

The latest interaction pass revisited the live Board UI combo and data-table previews: selecting May changed its displayed count/rate and emphasized its mark; searching for Aspen reduced the table from 48 to one result. Efferd dashboard previews were also reopened for comparison. In Axis, changing the selected approval updated its URL and evidence; the risks disclosure and request-changes dialog were checked without submitting a decision.

The resumed browser pass verified chart selection and reset, UTC heatmap/event filter composition, catalog selection after filtering, agent tabs, graph/list/entity navigation, CSV validation and a 1,000-row preview, policy filters/revision/dry-run evaluation, tenant quota review/cancel, vocabulary add/remove, settings tabs and support inspection. Workflow and simulation remained empty; session security showed its unauthenticated gate. No lifecycle mutation or approval decision was submitted.

Two further inconsistencies found through these interactions were corrected: onboarding now counts persisted workflow runs instead of reference definitions, and the blocked-model count follows the visible routes. Tenant access, endpoints and methodology remain available in named disclosures below the operational controls. The review bundle records each capture's actual revision and dimensions; earlier screenshots are retained as earlier evidence, not relabeled.

After browser recovery, the interactive chart revision passed 1,035 web tests plus build and lint. The onboarding correction passed 16 focused tests, model filtering 10 and tenant controls 24, with lint. Final consolidated checks and responsive screenshots are recorded against the final revision in the pull request and evidence bundle. No hosted deployment or merge is established by these local results.
