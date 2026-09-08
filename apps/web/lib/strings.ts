/*
 * Centralized console copy — every new user-facing string lives here so pages
 * stay plain-first and copy stays consistent (and i18n-ready). Raw identifiers,
 * scopes and hashes never appear in this module: they belong in Inspect
 * drawers and secondary mono details.
 */

export interface GlossaryEntry {
  label: string;
  definition: string;
}

/** Plain-English definitions for platform terms, rendered by `<Term />` tooltips. */
export const glossary = {
  ontology: {
    label: "Ontology",
    definition:
      "The shared vocabulary of business objects — machines, orders, materials — that connects your data, agents, and policies. It keeps every system talking about the same things.",
  },
  autonomy_level: {
    label: "Autonomy level",
    definition:
      "How much an agent may do on its own. Lower levels only suggest actions for humans to carry out; higher levels can act directly, with policies and approvals still applying.",
  },
  egress: {
    label: "Egress",
    definition:
      "Data leaving the platform for an outside system or provider. Egress is blocked by default and only opens through an explicit policy.",
  },
  evidence: {
    label: "Evidence",
    definition:
      "The recorded proof behind a decision or action: who acted, what they saw, and which rules applied. Evidence is written to the audit ledger and cannot be edited afterwards.",
  },
  dry_run: {
    label: "Dry run",
    definition:
      "A rehearsal of an action that computes the outcome without changing anything. Use it to check what would happen before committing.",
  },
  replay: {
    label: "Replay",
    definition:
      "Re-running past decisions against a different set of policies to compare outcomes. Nothing in production changes during a replay.",
  },
  idempotency: {
    label: "Idempotency",
    definition:
      "A guarantee that repeating the same request has no additional effect. It makes retries safe after a timeout or network failure.",
  },
  connector_manifest: {
    label: "Connector manifest",
    definition:
      "The reviewed description of a connector: where its data comes from, how fields map to the ontology, and which rules govern each sync.",
  },
  policy_scope: {
    label: "Policy scope",
    definition:
      "The part of the platform a policy applies to — an entire tenant, a domain, or a specific type of action.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof glossary;

export interface PageStrings {
  eyebrow: string;
  title: string;
  description: string;
}

const nav = {
  operate: "Operate",
  dataAndModels: "Data & Models",
  governance: "Governance",
  platform: "Platform",
  help: "Help",
  /* Shown in the sidebar account row when the identity API has not named an
     actor or tenant — never a blank line, which reads as a rendering fault. */
  signedOut: "Not signed in",
  noTenant: "No tenant selected",
} as const;

/**
 * The enforced-SSO entry gate. Shown instead of console surfaces when the API
 * requires sign-in and no verified session exists. Reason copy is keyed by the
 * API's public unauthenticated_reason classes; anything unknown falls back to
 * the generic verification message rather than leaking internals.
 */
const scopeDenial = {
  title: "Your roles do not include this permission",
  bodyPrefix: "Axis verified your session, but the",
  bodySuffix:
    "surface requires a permission your assigned roles do not grant. Ask an identity administrator to grant it, then reload.",
  permissionLabel: "Required permission",
} as const;

const identityGate = {
  eyebrow: "Enterprise access",
  title: "Sign in to Limes Axis",
  description:
    "This deployment requires an authenticated operator session through your organization's identity provider.",
  signIn: "Sign in with SSO",
  returnHint: "You will return to the page you opened.",
  reasons: {
    missing_authorization: "No active session was found for this browser.",
    invalid_session_cookie: "Your session is no longer valid. Sign in again to continue.",
    revoked_session_cookie: "Your session was revoked. Sign in again to continue.",
    expired_session_cookie: "Your session expired. Sign in again to continue.",
    idle_session_timeout:
      "You were signed out after a period of inactivity. Sign in again to continue.",
    fallback: "Your credentials could not be verified. Sign in again to continue.",
  },
} as const;

/** Per-route header copy, keyed by route segment (`overview` for `/`). */
const pages = {
  overview: {
    eyebrow: nav.operate,
    title: "Overview",
    description:
      "Turn connected business data into actions your team can review and track.",
  },
  approvals: {
    eyebrow: nav.operate,
    title: "Approvals",
    description:
      "Review proposed actions and follow their reported outcomes.",
  },
  workflows: {
    eyebrow: nav.operate,
    title: "Workflows",
    description:
      "Track workflow progress and resolve blockers.",
  },
  agents: {
    eyebrow: nav.operate,
    title: "Agents",
    description:
      "Check what each agent can do and review its runs.",
  },
  ontology: {
    eyebrow: nav.dataAndModels,
    title: "Ontology",
    description:
      "Explore business objects, such as orders and machines, and their connections.",
  },
  connectors: {
    eyebrow: nav.dataAndModels,
    title: "Connectors",
    description:
      "Connect your data sources and monitor their imports.",
  },
  data: {
    eyebrow: nav.dataAndModels,
    title: "Data",
    description:
      "Find data assets, inspect their evidence, and assign ownership.",
  },
  "model-routing": {
    eyebrow: nav.dataAndModels,
    title: "Models",
    description:
      "Review model selection rules and recorded AI calls.",
  },
  policies: {
    eyebrow: nav.governance,
    title: "Policies",
    description:
      "Set rules for actions, data access, and human approval.",
  },
  audit: {
    eyebrow: nav.governance,
    title: "Audit",
    description:
      "Trace recorded actions, decisions, and the evidence behind them.",
  },
  simulation: {
    eyebrow: nav.governance,
    title: "Simulation",
    description:
      "Compare policy outcomes before applying changes.",
  },
  tenants: {
    eyebrow: nav.platform,
    title: "Tenants",
    description:
      "Manage organizations and their resource limits.",
  },
  settings: {
    eyebrow: nav.platform,
    title: "Settings",
    description: "Check that the platform is healthy, connected, and ready for your team.",
  },
} satisfies Record<string, PageStrings>;

export type PageKey = keyof typeof pages;

/** Route-level boundaries: render error, unmatched URL, root-layout failure. */
const routeError = {
  eyebrow: "Console",
  title: "Something went wrong",
  subtitle: "This screen stopped responding. The rest of the console still works.",
  panelTitle: "This screen could not be displayed",
  detail:
    "Axis stopped rendering this page to avoid showing an incomplete or misleading view. Retrying reloads just this screen.",
} as const;

const notFound = {
  eyebrow: "Console",
  title: "Page not found",
  subtitle: "That address does not match anything on this deployment.",
  panelTitle: "Nothing lives at this address",
  detail:
    "The link may be out of date, or the record may belong to a different tenant. Start again from the overview.",
  action: "Go to overview",
} as const;

const globalError = {
  title: "Axis Console could not start",
  detail:
    "The console failed before it could load. Reload the page; if this keeps happening, quote the reference below to your platform team.",
  action: "Reload the console",
} as const;

const commandMenu = {
  placeholder: "Search pages, entities, actions",
  empty: "No matching command.",
  apiStatus: "API status",
  actionsHeading: "Actions",
  entitiesHeading: "Entities",
  refresh: {
    label: "Refresh live state",
    detail: "Re-fetch every API-backed console.",
  },
  toggleTheme: {
    label: "Toggle color theme",
    detail: "Switch between light and dark.",
  },
  docs: {
    label: "Open product docs",
    detail: "Architecture, platform and acceptance documentation.",
    href: "https://github.com/Limes-Labs/limes-axis/tree/main/docs",
  },
} as const;

/** Approval inbox copy: decision flow, empty queue, and API-down states. */
const approvals = {
  queue: {
    eyebrow: "Queue",
    title: "Approval inbox",
    filters: "Approval queue filters",
    search: "Search approvals",
    searchPlaceholder: "Action, owner or workflow…",
    risk: "Risk",
    allRisks: "All risks",
    domain: "Domain",
    allDomains: "All domains",
    clear: "Clear filters",
    noMatches: "No pending approvals match these filters. Try another search or clear the filters.",
    review: "Approval review",
    back: "Back to approval inbox",
    select: "Select an approval to review",
    selectDetail: "Choose a matching action from the queue to see its evidence and decision options.",
  },
  history: {
    eyebrow: "History",
    title: "Decision history",
    description:
      "Terminal decisions recorded with the audit ledger. Decided approvals no longer appear in the queue above.",
    empty: "No terminal decisions recorded yet.",
    followThrough: "Follow-through:",
    actorUnknown: "unknown actor",
  },
  decision: {
    eyebrow: "Decision",
    pending: "Pending review",
    confirmTitle: "Confirm decision",
    rationaleLabel: "Rationale (optional)",
    rationalePlaceholder: "Why you are deciding this way — recorded with the audit evidence.",
    confirm: "Confirm decision",
    cancel: "Cancel",
    persisting: "Recording decision…",
    persisted: "Recorded as evidence",
    auditLink: "View audit event",
    toastTitle: "Decision recorded",
    ssoGate: "Sign in with SSO to record approval decisions.",
    alreadyRecorded: "A terminal decision was already recorded for this approval.",
  },
  sections: {
    evidence: "Evidence",
    risksAlternatives: "Risks & alternatives",
    dataAccessed: "Data accessed",
    inspect: "Inspect raw record",
  },
  metrics: {
    pending: "Pending",
    pendingDetail: "Waiting on a human decision",
    highRisk: "High risk",
    highRiskDetail: "Cannot execute without owner approval",
    decided: "Decided",
    decidedDetail: "Recorded as audit evidence",
  },
  error: {
    title: "Approval API unavailable",
    detail:
      "Axis did not receive API-backed approval records. Local fallback approval records are disabled.",
  },
  empty: {
    title: "No approvals waiting",
    detail:
      "When an agent proposes an action that needs a human decision, it will appear here for review.",
  },
  requestedMissing: {
    title: "Requested approval is not in this queue",
    detail:
      "The linked action run does not have an approval in the current queue. It may have already been decided or belongs to another tenant.",
  },
  lookupError: {
    title: "Linked approval could not be verified",
    detail:
      "Axis could not resolve the action run through the audit ledger, so the console will not show a different approval.",
  },
  followThrough: {
    eyebrow: "Follow-through",
    title: "After the decision",
    detail:
      "Axis records the decision and displays what external executors report. Axis does not execute or retry approved actions.",
    sourceSubject: "action follow-through",
    awaiting: {
      title: "Awaiting external execution",
      detail:
        "Approved actions with no reported outcome, longest wait first. Each remains here until an external executor reports back.",
      status: "Waiting for external executor",
      waited: (duration: string) => `Waiting ${duration}`,
      emptyTitle: "Nothing awaiting external execution",
      emptyDetail: "No approved action is currently waiting for an external executor to report back.",
    },
    reported: {
      title: "Reported outcomes",
      detail: "What external executors reported to Axis after an approval.",
      emptyTitle: "No outcomes reported",
      emptyDetail: "No external executor has reported an outcome for an approved action yet.",
    },
    empty: {
      title: "No approved actions yet",
      detail:
        "Approved action runs and executor-reported outcomes will appear here after a decision is recorded.",
    },
    error: {
      title: "Action run API unavailable",
      detail:
        "Axis could not load approved action runs or executor-reported outcomes. No follow-through state is inferred.",
    },
    stale: "Live refresh failed. Showing the last validated action follow-through data.",
    links: {
      approval: "Open authorising approval",
      auditEvidence: "Open audit evidence",
    },
    fields: {
      approved: "Approved",
      reported: "Reported",
      workflow: "Workflow",
      run: "Run",
      noWorkflow: "No workflow recorded",
      noApproval: "No authorising approval recorded",
      noAuditEvidence: "No audit evidence references reported",
    },
  },
} as const;

/** Agent registry copy: list, detail tabs, runs, and state panels. */
const agents = {
  list: {
    eyebrow: "Registry",
    title: "Agents",
  },
  tabs: {
    overview: "Overview",
    permissions: "Permissions & Guardrails",
    runs: "Runs",
    evidence: "Evidence",
  },
  overview: {
    owner: "Owner",
    boundary: "Operating boundary",
    modelPolicy: "Model policy",
    connectedSystems: "Connected systems",
    dataAccess: "Data access",
  },
  permissions: {
    required: "Required permissions",
    guardrails: "Guardrails",
    allowed: "Allowed actions",
    blocked: "Blocked actions",
  },
  evidence: {
    proposals: "Action proposals",
    proposalsDetail: "Read-only proposals recorded by this agent; execution needs approval.",
    workflows: "Workflow links",
    approvals: "Approval references",
    audit: "Audit links",
    lastAudit: "Last audit event",
    approvalRequired: "Needs approval",
    noApproval: "No approval needed",
    empty: "No proposals, workflow links, or approval references are recorded for this agent.",
  },
  runs: {
    title: "Live executed runs",
    detail: "Persisted run records; steps, model links and proposals are recorded values.",
    liveBadge: "Live executed",
    dryRun: "Dry run",
    linkedInvocations: "Linked model invocations",
    noInvocations: "No model invocations are linked to this run.",
    openActionRun: "Open proposed action run in approvals",
    noActionRun: "No action run was created by this run.",
    openRunAudit: "Open run audit event",
    openAudit: "Open audit",
    auditPending: "audit pending",
    empty: {
      title: "No runs recorded yet",
      detail:
        "No runs are recorded for this agent. Agent run execution is deferred by default until the execution flag is enabled on the API; run rows are never fabricated.",
    },
    error: {
      title: "Agent runs API unavailable",
      detail:
        "Axis did not receive persisted run records for this agent. Run timelines are never fabricated.",
    },
    detailError: {
      title: "Agent run detail unavailable",
      detail:
        "Axis did not receive the persisted step records for this run. Step timelines are never fabricated.",
    },
  },
  inspect: "Inspect raw record",
  error: {
    title: "Agent API unavailable",
    detail:
      "Axis did not receive API-backed agent records. Local fallback agent records are disabled.",
  },
  empty: {
    title: "No agents registered yet",
    detail:
      "Register an agent through the platform API and it will appear here with its policy boundary and run history.",
  },
  noMatch: {
    title: "No agents match the current filters",
    detail: "Adjust or reset the domain, autonomy and status filters to see registered agents.",
    reset: "Reset filters",
  },
} as const;

/** Workflow console copy: list, blocker banner, timeline, and state panels. */
const workflows = {
  list: {
    eyebrow: "Runs",
  },
  filters: {
    state: "State",
    allStates: "All states",
    domain: "Domain",
    allDomains: "All domains",
  },
  blocker: {
    title: "Waiting on a human decision",
    linkNamed: "Review blocking approval",
    linkGeneric: "Open approvals",
  },
  timeline: {
    eyebrow: "Timeline",
    title: "Runtime timeline",
    waiting: "waiting",
    columns: {
      step: "Step",
      result: "Result",
      when: "When",
      summary: "Summary",
    },
  },
  sections: {
    inputs: "Inputs",
    outputs: "Proposed outputs",
    context: "Related context",
  },
  detail: {
    runtime: "Runtime",
    owner: "Owner",
    autonomy: "Autonomy",
    started: "Started",
    expected: "Expected",
    auditScope: "Audit scope",
    replay: "Replay",
    replayReady: "Ready to replay",
    replayNotReady: "Not replay-ready yet",
    signals: "Pending signals",
    noSignals: "Nothing is waiting on this workflow.",
    controls: "Controls",
  },
  inspect: "Inspect raw record",
  error: {
    title: "Workflow API unavailable",
    detail:
      "Axis did not receive API-backed workflow records. Local fallback workflow records are disabled.",
  },
  empty: {
    title: "No workflow runs yet",
    detail:
      "When a governed workflow starts, its run will appear here with a step-by-step timeline.",
  },
  noMatch: {
    title: "No workflows match the current filters",
    detail: "Adjust or reset the state and domain filters to see workflow runs.",
    reset: "Reset filters",
  },
} as const;

/** Connector console copy: list, detail tabs, wizard, and preview-sync runs. */
const connectors = {
  partialCsvPreview: (included: number, total: number) =>
    `Preview includes ${included.toLocaleString("en")} of ${total.toLocaleString("en")} records. ${(total - included).toLocaleString("en")} records are not included.`,
  list: {
    eyebrow: "Registry",
    neverSampled: "Never sampled",
    previewSample: "Preview sample",
    observedRecords: (count: number) => `${count.toLocaleString("en")} records observed`,
    successfulSync: (completedAt: string, runId: string) =>
      `Successful sync · ${completedAt} · run ${runId}`,
  },
  header: {
    addConnector: "Add connector",
    updated: "Updated",
  },
  manifestImport: {
    eyebrow: "Manifest portability",
    title: "Import connector manifests",
    description:
      "Paste one registration document or an array, or upload a JSON file. Check the whole batch before anything is written.",
    access:
      "Required scope: none. The API instead requires the tenant and registered actor to match your signed-in session.",
    validationEndpoint: "Dry run endpoint",
    applyEndpoint: "Apply endpoints",
    applyEndpointPaths: (endpoint: string) =>
      `POST ${endpoint}; PUT ${endpoint}/{connector_id}`,
    inputLabel: "Registration document JSON",
    inputPlaceholder: "Paste one registration document or an array of documents",
    fileLabel: "Upload JSON file",
    fileReadError: "The selected JSON file could not be read.",
    check: "Check",
    checking: "Checking…",
    reviewApply: "Review apply",
    apply: "Apply manifests",
    applying: "Applying…",
    cancel: "Cancel",
    confirmation: (count: number) =>
      `Apply ${count} checked ${count === 1 ? "manifest" : "manifests"} sequentially? Writes cannot be rolled back as a batch.`,
    ssoGate: "Sign in with SSO to check or apply connector manifests.",
    errors: {
      malformed: "This is not valid JSON. Fix the syntax before checking.",
      shape: "Provide one JSON object or a non-empty array of JSON objects.",
      tooMany: (count: number, maximum: number) =>
        `${count} documents were provided. Check at most ${maximum} at a time.`,
      validationRequest: "The manifest dry run could not be completed.",
      replacementRevisionRequest:
        "The current connector revision could not be verified, so replacement stays disabled.",
      tenantMismatch: "The dry-run response belongs to a different tenant.",
      resultCountMismatch: "The dry-run response did not include one result per document.",
    },
    summary: {
      title: "Dry-run summary",
      wouldRegister: "Would register",
      wouldReplace: "Would replace",
      invalid: "Invalid",
    },
    table: {
      document: "Document",
      connector: "Connector id",
      outcome: "Outcome",
      applyResult: "Apply result",
      unknownConnector: "Not available",
      replacesRevision: (revision: number) => `Replaces revision ${revision}`,
    },
    outcomes: {
      would_register: "Would register",
      would_replace: "Would replace",
      invalid: "Invalid",
    },
    applyResults: {
      landed: "Applied",
      failed: "Failed",
      conflict: "Concurrent change",
      notAttempted: "Not applied",
      pending: "Pending",
    },
    applyability: (invalid: number, total: number) => invalid === 0
      ? `0 of ${total} will be rejected. Every checked document can be applied.`
      : `${invalid} of ${total} will be rejected as invalid. Apply stays disabled until every document is valid.`,
    applySuccess: (count: number) =>
      `${count} of ${count} manifests were applied.`,
    applyFailure: (landed: number, total: number) =>
      `${landed} of ${total} manifests were applied. The remaining documents were not applied.`,
    concurrentConflict: (connectorId: string) =>
      `Apply stopped because someone else changed ${connectorId}. Check the batch again before replacing it.`,
    toast: {
      success: "Connector manifests applied",
      partial: "Connector manifest apply stopped",
    },
  },
  manifestExport: {
    action: "Export manifest",
    title: "Registration document",
    description:
      "This formatted JSON includes the manifest, runtime policy, optional preview sample and notes required for replay.",
    jsonLabel: "Registration document JSON",
    copy: "Copy JSON",
    copied: "Registration document copied",
    copyFailed: "The registration document could not be copied.",
    download: "Download JSON",
    close: "Close export",
  },
  lifecycle: {
    eyebrow: "Lifecycle",
    title: "Activation state",
    ssoGate: "Sign in with SSO to change connector activation.",
    /* Each state line says what the connector can do right now, in operator
       terms, so the next safe action is obvious without reading the API. */
    stateDetail: {
      registered_preview_only:
        "Registered for previews only. Validate mappings and inspect schema; governed syncs and ontology proposals stay blocked until this connector is activated.",
      active_preview:
        "Activated for preview operations. Governed runs, credential leases and ontology proposals are available; external systems are still not touched.",
      active_live:
        "Live operation enabled under the reviewed egress boundary. Scheduled and live syncs may reach the connected system within policy.",
      deprecated:
        "Deprecated. The connector keeps its history and evidence, but no further transitions or runs are possible.",
    },
    unknownState:
      "The activation state of this connector could not be determined from the registry record.",
    activateAction: "Activate for previews",
    activating: "Activating…",
    activateReason: "Activated from the connector console.",
    enableLiveAction: "Enable live sync…",
    enablingLive: "Enabling live sync…",
    enableLiveReason: "Live operation enabled from the connector console.",
    deprecateAction: "Deprecate connector",
    confirmDeprecate: "Confirm deprecation",
    deprecating: "Deprecating…",
    deprecateReason: "Deprecated from the connector console.",
    deprecatedHint: "Deprecated connectors cannot be reactivated.",
    enableLiveTitle: "Enable live operation",
    enableLiveDetail:
      "Live operation lets governed syncs reach the connected system inside the approved boundary. Every requirement below is enforced again by the API when you submit.",
    requirements: {
      title: "Live-enablement requirements",
      liveSyncMode: "Manifest declares a live sync mode",
      liveOperationsAllowed: "Runtime policy allows live query and external egress",
      egressBoundaryNamed: "A reviewed egress boundary is named",
    },
    requirementMet: "Met",
    requirementUnmet: "Missing",
    /* Two distinct trails, two distinct questions:
       - Revision history answers "how did the manifest content change?"
         (registration, replacement) — one row per persisted revision.
       - Transition history answers "which governed activation changes were
         recorded?" — one row per lifecycle transition, from its own
         server-side per-connector projection. */
    history: {
      title: "Revision history",
      events: {
        registered: "Registration recorded",
        replaced: "Manifest updated",
      },
      unknownEvent: "Revision recorded",
    },
    transitions: {
      title: "Transition history",
      events: {
        active_preview: "Activated for previews",
        active_live: "Live operation enabled",
        deprecated: "Connector deprecated",
      },
      unknownEvent: "Transition recorded",
    },
    evidenceLabel: "Evidence references",
    evidencePlaceholder: "approval: …, policy: …, credential: … (one per line)",
    evidenceDetail:
      "Live enablement requires one approval reference, one policy reference and one credential or secret reference.",
    evidenceMissing: (categories: string[]) =>
      `Still missing ${categories.join(", ")} evidence for live enablement.`,
    conflict: "The connector changed while you were working. Review its current state and retry.",
    /* Scope denials name exactly which grant is absent and who can fix it, so
       an operator never has to guess which of the two lifecycle scopes failed. */
    deniedLifecycleScope:
      "Your session is missing the connector lifecycle scope (connectors:manifest:lifecycle) for this tenant. A tenant admin can grant it.",
    deniedLiveScope:
      "Enabling live operation additionally requires the enable-live scope (connectors:manifest:enable_live), which your session does not have for this tenant. A tenant admin can grant it.",
    forbidden: "Your session does not carry the connector lifecycle scope for this tenant.",
    validationFailed: "The API rejected this transition. Complete the missing requirements first.",
    genericError: "The lifecycle transition could not be recorded.",
    successToast: { title: "Lifecycle updated", detail: "The transition was recorded with audit evidence." },
  },
  sourceDiscovery: {
    eyebrow: "Source",
    title: "Verify & discover",
    /* What this panel is for, in one sentence an operator can act on. */
    detail:
      "Check connectivity to the external Postgres source, then list its base tables as catalog evidence. Discovery reads table and column names only — never row data.",
    ssoGate: "Sign in with SSO to verify or discover the source.",
    prerequisites: {
      title: "What you need before starting",
      lease: "An active credential lease for this connector",
      policy: "An active egress policy approving the source endpoint",
      scope: "The source discovery scope (connectors:source:discover) for this tenant",
    },
    prerequisiteMet: "Ready",
    prerequisiteMissing: "Missing",
    tableColumn: "Table",
    columnsColumn: "Columns",
    driftColumn: "Catalog drift",
    profileLabel: "Connection profile ID",
    schemaLabel: "Schema to discover",
    leaseLabel: "Credential lease ID",
    policyLabel: "Egress policy ID",
    verifyAction: "Verify connection",
    verifying: "Verifying…",
    discoverAction: "Discover tables",
    discovering: "Discovering…",
    verifiedTitle: "Connection verified",
    verifiedDetail: (database: string) =>
      `Connected read-only to database “${database}”. The pinned endpoint hash matched the egress policy.`,
    discoveredTitle: (count: number) => `Discovered ${count} ${count === 1 ? "table" : "tables"}`,
    truncatedDetail:
      "Discovery stopped at its bounded limit; more tables or columns exist than were listed here.",
    columnsTruncated: "column list truncated",
    drift: {
      added: "New",
      changed: "Changed",
      unchanged: "Unchanged",
    },
    emptySource: {
      title: "No base tables found",
      detail:
        "The schema exists but holds no base tables. Views are not discovered yet.",
    },
    blocked: {
      title: "Verification blocked",
      /* Keys mirror the API's block_reason values one-for-one so a new
         runtime reason fails safe onto `generic` instead of inventing copy. */
      source_unreachable:
        "The source did not answer within its timeout. Check that the host and port are reachable from Axis.",
      auth_denied:
        "The source rejected the credentials behind your credential lease. Rotate the secret and request a new lease.",
      permission_denied:
        "The connected role lacks permission to inspect this schema. Grant read access on the schema, then retry.",
      source_database_missing:
        "The database named by the connection profile does not exist on the source.",
      schema_not_allowlisted:
        "That schema is not on the discovery allowlist for this deployment. An administrator must add it.",
      profile_not_configured:
        "No source profile is configured on this deployment yet. Set the discovery DSN or endpoint pin first.",
      runtime_egress_target_mismatch:
        "The resolved connection target does not match the approved egress boundary. Nothing was sent to the wrong host.",
      generic:
        "Axis blocked this operation at the runtime boundary. Review the evidence in the audit ledger.",
    },
    deniedScope:
      "Your session is missing the source discovery scope (connectors:source:discover) for this tenant. A tenant admin can grant it.",
    forbidden: "Your session cannot operate this connector's source for this tenant.",
    validationFailed: "One of the referenced records does not match this connector. Check the IDs above.",
    notFound: "A referenced lease or egress policy does not exist for this tenant.",
    genericError: "The source operation could not be recorded.",
    observationNote:
      "Every completed discovery records catalog observations with audit evidence; repeat runs track added, changed and unchanged tables automatically.",
  },
  sourceActivation: {
    eyebrow: "Activate",
    title: "Activate selected tables",
    /* One sentence an operator can act on: what activation is and is not. */
    detail:
      "Bind the selected discovered tables as durable governed sources for ingestion. Activation records evidence only — no data has been read from the source yet.",
    selectColumn: "Activate",
    selectHint: "Select discovered tables to bind them for ingestion.",
    selectedCount: (count: number) =>
      `${count} ${count === 1 ? "table" : "tables"} selected`,
    reasonLabel: "Activation reason",
    reasonPlaceholder: "Why are these tables being activated?",
    action: (count: number) => `Activate ${count} ${count === 1 ? "table" : "tables"}`,
    activating: "Activating…",
    successTitle: (count: number) =>
      `Activated ${count} ${count === 1 ? "binding" : "bindings"}`,
    pendingIngestionPill: "Pending ingestion",
    activePill: "Active",
    replayedNote:
      "An identical earlier activation already covered these tables; nothing was duplicated.",
    honestNote:
      "These bindings are ready for ingestion. Axis has not read any row data yet — ingestion runs through a governed boundary once enabled.",
    blocked: {
      schema_fingerprint_stale:
        "A selected table's schema changed since it was discovered. Run discovery again, review the new schema, then activate.",
      binding_already_active:
        "One of the selected tables already has an active binding. Reload the bindings list to see it.",
      binding_id_in_use:
        "A binding ID in this submission already names a different table. Retry to generate fresh IDs.",
      resource_not_observed:
        "One of the selected tables was never observed by discovery. Discover the schema first.",
      selection_too_large: "Too many tables selected. Activate fewer at once.",
      duplicate_resource_name: "Each table may be selected only once.",
      unsafe_resource_name: "A selected name is not a safe qualified table name.",
      credential_lease_not_found: "The referenced credential lease does not exist for this tenant.",
      egress_policy_not_found: "The referenced egress policy does not exist for this tenant.",
      credential_lease_not_executed:
        "The referenced lease was never executed by a credential broker. Request and execute a new lease.",
      generic:
        "Axis could not record the activation. Review the audit ledger and retry.",
    },
    reasonRequired: "An activation reason is required for the audit trail.",
    deniedScope:
      "Your session is missing the source activation scope (connectors:source:activate) for this tenant. A tenant admin can grant it.",
    forbidden: "Your session cannot activate sources for this tenant.",
    notFound: "A referenced lease or egress policy does not exist for this tenant.",
    genericError: "The activation could not be recorded.",
  },
  sourceJourney: {
    title: "From connection to validated data",
    detail:
      "Four steps take one table from a verified source to governed ingestion. Axis records durable evidence at every step; this guide only reports what the API confirms.",
    steps: {
      verifyDiscover: {
        label: "Verify & discover",
        done: "Source verified and schema observed.",
        todo: "Verify the connection and discover the schema in Verify & discover below. Discovery is read-only: Axis records what it sees without touching your data.",
        consequence:
          "Without discovery there is no fingerprint, so nothing can be activated or ingested.",
      },
      activate: {
        label: "Activate tables",
        done: "{count} bound table(s) ready for ingestion.",
        todo: "Activate the discovered tables you want governed. Activation pins the observed schema fingerprint as the baseline for validation.",
        consequence:
          "Only activated tables can enter a governed ingestion request.",
      },
      requestIngestion: {
        label: "Request ingestion",
        done: "{count} governed request(s) raised.",
        todo: "Raise a governed ingestion request for pending bindings. A required governance reason is recorded with every ask.",
        consequence:
          "Requests are dispatched by the worker; nothing runs while ingestion stays default-off on this deployment.",
      },
      validate: {
        label: "Validate & review evidence",
        done: "{completed} completed · {failed} need attention.",
        doneClean: "{completed} completed — fingerprints re-checked against fresh observations.",
        todo: "Wait for dispatch to validate pinned fingerprints, then open a request to review its batch evidence and storage state.",
        remediation:
          "Dead-lettered requests stay failed until you remediate: re-discover, re-activate, then use Re-dispatch after remediation inside the request.",
        consequence:
          "Validation never reads rows; extraction only runs when explicitly enabled and bounded.",
      },
    } as Record<string, Record<string, string>>,
    unavailable:
      "The journey needs API-backed bindings and request data. Nothing here is invented; retry after checking the API status.",
    nextActionLabel: "Next",
    nextActions: {
      verifyDiscover: "Use Verify & discover below.",
      activate: "Select tables to activate below.",
      requestIngestion: "Raise a governed ingestion request below.",
      validate: "Open a request to review evidence.",
    } as Record<string, string>,
  },
  sourceBindings: {
    eyebrow: "Bindings",
    title: "Active source bindings",
    emptyDetail:
      "No discovered table is bound for ingestion yet. Verify the source, discover its tables, then activate the ones you need.",
    tableColumn: "Table",
    fingerprintColumn: "Schema fingerprint",
    stateColumn: "State",
    ingestionPendingPill: "Pending ingestion",
    activePill: "Active",
    activatedByLabel: "Activated by",
    unavailableTitle: "Bindings unavailable",
    unavailableDetail:
      "Axis could not load the active bindings. Nothing shown here is invented; retry after checking the API status.",
  },
  sourceIngestion: {
    eyebrow: "Ingestion requests",
    title: "Governed ingestion requests",
    validationOnlyNote:
      "Validation stage only. Axis re-checks each bound table's schema fingerprint against its own observations. No source is dialed and no rows are read or stored.",
    overviewTitle: "Operations at a glance",
    overviewUnavailable: "Overview unavailable — retry after checking the API status.",
    overviewNeedsAttention: "{count} dead-lettered request(s) need a decision",
    overviewWorking: "{count} working right now",
    overviewPending: "{count} waiting for dispatch",
    overviewQuiet: "All clear — no ingestion activity needs attention.",
    overviewTotals: "{total} request(s) overall · {extract} extraction · last activity {activity}",
    overviewNever: "No activity recorded yet.",
    attemptsLabel: "Dispatch attempt timeline (metadata only)",
    attemptsTruncatedNotice:
      "Showing the latest 50 recorded dispatch attempts. Older attempts remain in durable evidence but are not listed here.",
    attemptOutcome: {
      completed: "Completed",
      retried: "Retried after an operational failure",
      dead_lettered: "Dead-lettered",
    } as Record<string, string>,
    attemptSelectionValidated: "validated",
    attemptSelectionFailed: "failed",
    emptyDetail:
      "No governed ingestion request exists yet. Request ingestion for pending bindings to run schema validation against Axis' own observations.",
    eligibilityTitle: "Ingestion eligibility",
    selectColumn: "Select",
    tableColumn: "Table",
    fingerprintColumn: "Fingerprint",
    stateColumn: "State",
    requestColumn: "Request",
    attemptsColumn: "Attempts",
    stageHeader: "Stage",
    reasonHeader: "Reason",
    lastErrorLabel: "Last error code",
    selectionsLabel: "Bound tables in this request",
    eligiblePill: "Eligible",
    blockedPill: "Blocked",
    blockedReasons: {
      stale_fingerprint: "Stale fingerprint",
      binding_not_pending_ingestion: "Not awaiting ingestion",
    } as Record<string, string>,
    requestIdLabel: "Request ID",
    reasonLabel: "Governance reason",
    reasonPlaceholder:
      "Why this ingestion request is being raised (stored as evidence).",
    formHint:
      "Schema fingerprints are pinned by Axis from the active bindings; you never supply one. Re-submitting the same request ID replays the existing request.",
    createAction: "Request ingestion",
    creatingAction: "Requesting ingestion…",
    createdStatus: {
      created: "Ingestion request accepted and queued for validation.",
      replayed: "That request ID already exists; the existing request was returned unchanged.",
    },
    ssoGate:
      "Sign in to raise governed ingestion requests. Eligibility stays visible either way.",
    statusPills: {
      pending: "Pending dispatch",
      dispatching: "Working",
      completed: "Completed",
      failed: "Failed",
      cancelled: "Cancelled",
    } as Record<string, string>,
    stageLabels: {
      validate: "Validate only",
      extract: "Validate + extract",
    } as Record<string, string>,
    extractionAvailableNote:
      "Extraction is enabled here: requests may run one bounded, read-only read per bound table. Rows go to the governed object store; Axis stores counts, digests and watermarks only.",
    plannedLimitsLabel: "Planned limits",
    cancelAction: "Cancel request",
    redispatchAction: "Re-dispatch after remediation",
    redispatchingAction: "Re-dispatching…",
    redispatchReasonLabel: "Remediation reason",
    requeuedStatus: "Request requeued for dispatch.",
    redispatchHint:
      "Only dead-lettered requests can be re-dispatched. Remediate first (fresh discovery + activation); execution still revalidates fingerprints.",
    cancellingAction: "Cancelling…",
    cancelledStatus: "Request cancelled before dispatch.",
    conflictMessage:
      "Axis refused this change because the request already moved past pending.",
    batchesLabel: "Extraction batches (metadata only — no row payloads here)",
    batchRowsLabel: "Rows",
    batchDigestLabel: "Digest",
    batchTruncatedLabel: "Truncated",
    yesPill: "Yes",
    noPill: "No",
    batchesTitle: "Extraction batch evidence",
    batchColumn: "Batch",
    rowsLabel: "Rows",
    truncatedLabel: "Truncated",
    orderingLabel: "Ordering",
    watermarkPresent: "Watermark present",
    noWatermark: "No watermark (single pass)",
    digestLabel: "Digest",
    classificationLabel: "Classification",
    provenanceLabel: "Executed by",
    checkStorageAction: "Check storage",
    checkingStorageAction: "Checking…",
    reconciliationTitle: "Storage vs metadata (dry-run)",
    reconLabels: {
      clean_match: "Clean matches",
      digest_mismatch: "Digest mismatches",
      missing_object: "Missing objects",
      orphaned_object: "Orphaned objects",
    } as Record<string, string>,
    reconUnsupported:
      "Reconciliation currently supports the local filesystem object-store adapter only.",
    preflightTitle: "Extraction readiness",
    preflightExtractOn: "Bounded extraction available for new requests",
    preflightExtractOff: "Validation only — extraction is default-off here",
    preflightReasonReady: "A governance reason is required for every request",
    deadLetteredPill: "Dead-lettered",
    deniedScope:
      "Your actor lacks the connectors:source:ingest scope required to raise governed ingestion requests.",
    forbidden: "Axis refused this action for your actor.",
    conflict:
      "That request ID already names a different ingestion request. Pick a new ID instead of overriding durable evidence.",
    validationFailed:
      "Axis rejected the request: a selected binding must exist, be active, await ingestion, and carry a still-current schema fingerprint.",
    notFound: "That ingestion request does not exist.",
    genericError: "Axis could not record this ingestion request. Nothing was invented; try again after checking the API status.",
    unavailableTitle: "Ingestion requests unavailable",
    unavailableDetail:
      "Axis could not load ingestion requests. Nothing shown here is invented; retry after checking the API status.",
  },
  requestedMissing: {
    title: "Requested connector is not in this registry",
    detail:
      "The connector named in the URL is not present in the current tenant registry.",
  },
  snapshot: {
    eyebrow: "Evidence snapshot",
    title: "Requested evidence snapshot",
    id: "Snapshot",
    connector: "Connector",
    findings: "Invariant findings",
    reason: "Reason",
    digest: "Report digest",
    inspect: "Inspect snapshot record",
    missingTitle: "Requested snapshot is not available",
    missingDetail:
      "The snapshot named in the URL is not in this tenant and connector result set. It may have been removed or the link may target another tenant.",
    errorTitle: "Snapshot history unavailable",
    errorDetail:
      "Axis could not verify the evidence snapshot named in the URL, so the console will not show a different record.",
  },
  metrics: {
    stripLabel: "Connector metrics",
    connectors: { label: "Connectors", detail: "Registered data sources" },
    runs: { label: "Runs", detail: "Up to 100 recent sync runs" },
    pendingProposals: {
      label: "Pending proposals",
      detail: "Unpromoted among 100 recent proposals",
    },
    egressPolicies: {
      label: "Egress policies",
      detail: "Up to 100 recent policy records",
    },
    evidenceIssues: {
      label: "Evidence issues",
      detail: "Findings across 100 recent records per evidence type",
    },
    unavailable: "—",
  },
  tabs: {
    overview: "Overview",
    dataSchema: "Data & Schema",
    runs: "Runs",
    governance: "Governance & Evidence",
  },
  overview: {
    type: "Type",
    version: "Version",
    source: "Source",
    syncModes: "Sync modes",
    boundary: "Runtime boundary",
    credentials: "Credentials",
    payloadPolicy: "Payload policy",
    egressPolicy: "Egress boundary",
    permissions: "Required permissions",
    blocked: "Blocked operations",
    manifest: "Registered manifest",
    manifestMissing: "No manifest registered yet — registering one records audit evidence.",
    manifestRegisteredBy: "Registered by",
    manifestStatus: "Status",
    currentRevision: "Current revision",
    revisionHistory: "Revision history",
    revisionHistoryDetail: "Ordered record of every manifest version recorded for this connector.",
    revisionHistoryUnavailable: "Revision history unavailable",
    revisionHistoryUnavailableDetail:
      "Axis could not verify which manifest revision is live for this connector.",
    revisionColumns: {
      revision: "Revision",
      version: "Manifest version",
      status: "Status",
      registeredBy: "Registered by",
      createdAt: "Recorded at",
    },
  },
  schema: {
    mappingTitle: "Field mapping",
    mappingDetail: "How source columns map to the shared ontology.",
    columns: {
      source: "Source column",
      target: "Target field",
      ontology: "Ontology target",
      type: "Type",
      required: "Required",
    },
    requiredYes: "Required",
    requiredNo: "Optional",
    sampleTitle: "Sample rows",
    sampleDetail: "Reference sample used for preview and validation.",
    neverSampled: "This connector has never been sampled.",
    sampleEmpty: "No sample rows are recorded for this connector.",
  },
  governance: {
    handles: {
      title: "Credential handles",
      detail: "References to secrets held in the vault — never raw values.",
      empty: "No credential handles are registered for this connector.",
      error: "Credential handle records could not be loaded.",
    },
    leases: {
      title: "Credential leases",
      detail: "Time-boxed grants that let a governed run use a credential handle.",
      empty: "No credential leases are recorded for this connector.",
      error: "Credential lease records could not be loaded.",
    },
    egress: {
      title: "Egress policies",
      detail: "Outbound data boundaries approved for this connector.",
      empty: "No egress policies are recorded for this connector.",
      error: "Egress policy records could not be loaded.",
    },
    invariants: {
      title: "Evidence invariants",
      detail: "Findings where governed records are missing audit evidence.",
      allClear: "All evidence invariants hold — every governed record has audit evidence.",
      error: "Evidence invariant findings could not be loaded.",
    },
  },
  runs: {
    title: "Governed runs",
    detail: "Recorded sync runs for this connector; every stage writes audit evidence.",
    empty: "No runs are recorded for this connector yet.",
    error: "Connector run records could not be loaded.",
    columns: {
      run: "Run",
      status: "Status",
      mode: "Mode",
      when: "When",
      evidence: "Evidence",
    },
    openAudit: "Open audit",
    auditPending: "audit pending",
    validate: {
      action: "Validate",
      running: "Validating…",
      readyTitle: "Validation passed",
      blockedTitle: "Validation found issues",
      rows: "rows checked",
      accepted: "accepted",
      rejected: "rejected",
      columnsChecked: "columns checked",
      error: "The preview endpoint could not validate this connector.",
    },
    sync: {
      action: "Run sync (preview)",
      running: "Running…",
      ssoGate: "Sign in with SSO to run governed syncs.",
      leaseMissing:
        "Preview sync needs an active credential lease for this connector before it can run.",
      manifestMissing:
        "Preview sync needs a registered manifest in the active preview state before it can run.",
      activateFirst:
        "This connector is registered but not activated yet. Activate it from the Overview tab, then governed syncs become available.",
      stages: {
        create: {
          title: "Create run record",
          detail: "Records the governed run and its schedule evidence.",
        },
        dispatch: {
          title: "Dispatch sync",
          detail: "Hands the scheduled run to the sync dispatcher.",
        },
        execute: {
          title: "Execute sync",
          detail: "Runs the governed sync within the preview boundary.",
        },
      },
      pending: "Waiting",
      success: "Completed",
      failure: "Failed",
      auditTrail: "Audit evidence",
    },
  },
  wizard: {
    title: "Add connector",
    description: "Register a governed data source. Registration records audit evidence and never starts a live sync.",
    back: "Back",
    next: "Next",
    cancel: "Cancel",
    submit: "Register connector",
    submitting: "Registering…",
    ssoGate: "Sign in with SSO to register connectors.",
    typeStep: {
      title: "What are you connecting?",
      csvTitle: "CSV file",
      csvDetail: "Upload a file, preview its rows, and map columns to the ontology.",
      dbTitle: "External database",
      dbDetail: "Register a read-only database source by connection profile — metadata only.",
    },
    csvStep: {
      template: "Mapping template",
      templateDetail: "Previews validate your file against this connector's field mapping.",
      file: "CSV file",
      preview: "Preview file",
      previewing: "Previewing…",
      noTemplates:
        "No CSV mapping templates are available from the connector registry, so the file cannot be previewed.",
      readyTitle: "Preview ready",
      blockedTitle: "Preview blocked",
      issuesTitle: "Validation issues",
      rows: "rows",
      accepted: "accepted",
      rejected: "rejected",
      entitiesTitle: "Proposed entities",
      previewError: "The CSV preview endpoint is unavailable.",
      fileReadError: "The selected file could not be read.",
    },
    dbStep: {
      profile: "Connection profile",
      profileDetail: "Named, pre-approved profile — never a raw connection string.",
      schema: "Schema",
      table: "Table",
      credentialHandle: "Credential handle",
      template: "Connector template",
      preview: "Preview metadata",
      previewing: "Previewing…",
      noTemplates:
        "No external database connector templates are available from the connector registry.",
      readyTitle: "Metadata preview ready",
      blockedTitle: "Metadata preview blocked",
      columnsTitle: "Mapped columns",
      previewError: "The external database preview endpoint is unavailable.",
    },
    reviewStep: {
      title: "Review and register",
      connectorId: "Connector id",
      displayName: "Display name",
      type: "Type",
      records: "Sample records",
      conflict: "A connector with this id already exists. Choose a different connector id.",
      forbidden: "Your session is not allowed to register connectors for this tenant.",
      validationFailed: "The manifest was rejected by the API.",
      genericError: "The connector manifest could not be registered.",
      toastTitle: "Connector registered",
      toastDetail: "The manifest was recorded with audit evidence.",
    },
  },
  error: {
    title: "Connector API unavailable",
    detail:
      "Axis did not receive API-backed connector records. Local fallback connector records are disabled.",
  },
  empty: {
    title: "No connectors yet",
    detail:
      "Connect a file or an external system and its governed syncs will appear here.",
    action: "Add your first connector",
  },
} as const;

/** Overview control-room copy: hero, needs-attention strip, posture, feed. */
const overview = {
  hero: {
    /* Used when the tenant has recorded no scenario name. Must stay
       vertical-neutral: this console is not manufacturing-only. */
    fallbackTitle: "Operations overview",
    error: {
      title: "Operations data could not be loaded",
      detail:
        "Axis only shows records it has actually recorded, so nothing is displayed until the connection to the platform recovers.",
    },
    /* Each label names the persisted dataset the number is read from, so an
       operator can tell what is being counted without opening the page. */
    facts: {
      openWorkflows: "Open workflows",
      pendingApprovals: "Pending approvals",
      operationRecords: "Operation records",
      recentAudit: "Audit events (latest)",
    },
  },
  needsAttention: {
    eyebrow: "Needs attention",
    review: "Review & decide",
    openWorkflows: "Open workflows",
    viewRecordedRuns: "View recorded runs",
    exampleWorkflow: "Example workflow",
    openAudit: "Open audit",
    openApproval: "Open approval",
    approvalsUnavailable: "Pending approvals could not be loaded from the approval API.",
    overviewUnavailable: "Workflow and risk signals could not be loaded from the overview API.",
    actionRunsUnavailable:
      "Approved actions awaiting an external executor could not be loaded from the action run API.",
    stalledAction: {
      /* Names the party that has not reported. Axis records the approval and
         waits: it never executes an approved action and never retries one. */
      noOutcome: "No outcome reported by an external executor",
    },
    allClear: {
      title: "All clear — nothing waiting on you",
      detail:
        "No pending approvals, blocked workflows, risk signals, or approved actions waiting on an external executor right now.",
    },
    error: {
      title: "Attention items unavailable",
      detail:
        "Axis did not receive API-backed approval, workflow, or risk records. Local fallback records are disabled.",
    },
  },
  posture: {
    agents: { label: "Agents", link: "Manage agents" },
    workflows: { label: "Workflows", link: "Open workflows" },
    connectors: {
      label: "Connector activity",
      link: "Manage connectors",
      detail: "Connector events in the latest audit window",
    },
    policies: { label: "Policies", link: "Review policies" },
    models: { label: "Models", link: "View routing" },
    unavailable: "Unavailable",
  },
  evidenceFeed: {
    eyebrow: "Evidence feed",
    title: "Recent audit evidence",
    openAudit: "Open audit",
    viewEvent: "View event",
    sparklineCaption: "Recent audit events by category",
    error: {
      title: "Audit evidence API unavailable",
      detail:
        "Axis did not receive API-backed audit events. Local fallback audit records are disabled.",
    },
    empty: {
      title: "No audit evidence yet",
      detail: "Governed actions write append-only evidence that will appear here.",
    },
  },
  sideRail: {
    health: "System health",
    quickActions: "Quick actions",
    error: {
      title: "System health unavailable",
      detail: "Axis did not receive the API-backed records that drive the health radar.",
    },
  },
  artifact: {
    eyebrow: "Operations artifact runtime",
    title: "Generate governed evidence",
    description:
      "Each action calls the live Axis API, persists a tenant-scoped artifact, and writes audit evidence.",
    ssoTitle: "Browser SSO required for artifact generation",
    ssoDetail:
      "Sign in with the API-owned OIDC session before creating daily briefs or risk scenarios.",
    signIn: "Sign in with SSO",
    error: {
      title: "Operations snapshot API unavailable",
      detail:
        "Artifact generation needs the persisted operations snapshot. Local fallback operations records are disabled.",
    },
  },
} as const;

/** Audit explorer copy: plain-first integrity summary and export action. */
const audit = {
  integrity: {
    eyebrow: "Integrity & Export",
    title: "Export bundle",
    download: "Download export bundle",
    inspect: "Inspect raw proofs",
    ledger: {
      verified: "Ledger verified — hash chain intact",
      unverified: "Ledger verification failed — hash chain not confirmed",
      detail: "Every event is hashed and chained; tampering breaks the chain.",
    },
    retention: {
      enforced: "Retention enforced",
      notEnforced: "Retention not enforced for this export",
      legalHold: "Retention paused — legal hold active",
      legalHoldDetail: "Records are excluded from disposal while the legal hold stands.",
    },
    signature: {
      verified: "Ledger signature verified",
      verifiedDetail: "The export manifest and hash chain are signed.",
      notConfigured: "Signature: not configured",
      notConfiguredDetail:
        "The hash-chain proof is present, but no signing key is configured.",
    },
    error: {
      title: "Audit export API unavailable",
      detail:
        "Axis did not receive an API-backed audit export manifest. Local export manifests are disabled.",
    },
  },
  error: {
    title: "Audit API unavailable",
    detail:
      "Axis did not receive API-backed audit records. Local fallback audit records are disabled.",
  },
  noRecords: {
    title: "Audit API returned no records",
    detail: "The audit API responded without ledger records for this tenant.",
  },
} as const;

/** Models page copy: the reference-vs-live distinction and tab labels. */
const models = {
  explainer:
    "Reference routing shows the governed routing design; live invocations are the calls the platform actually executed.",
  tabs: {
    reference: "Reference routing",
    live: "Live invocations",
  },
  reference: {
    error: {
      title: "Routing API unavailable",
      detail:
        "Axis did not receive API-backed model routing records. Local fallback routing records are disabled.",
    },
    noRecords: {
      title: "No model routes yet",
      detail: "Governed model routes will appear here after they are configured for this tenant.",
    },
    noMatch: {
      title: "No routes match the current filters",
      detail: "Adjust or reset the domain, provider and decision filters to see routing telemetry.",
      reset: "Reset filters",
    },
  },
  live: {
    invocationsError: {
      title: "Model invocation API unavailable",
      detail:
        "Axis did not receive persisted model invocation records. Live invocation rows are never fabricated.",
    },
    endpointsError: {
      title: "Model endpoint API unavailable",
      detail:
        "Axis did not receive the model endpoint registry. Endpoint cards are never fabricated.",
    },
  },
} as const;

/** Policy pages copy: detail tabs and plain-first authoring-scope lines. */
const policyDetail = {
  tabs: {
    conditions: "Conditions",
    revisions: "Revisions",
    evaluate: "Evaluate",
  },
  authorAccess: {
    summary: "You need policy author access to create policies.",
    detail: "Authoring creates revision 1 and records audit evidence.",
    ssoGate: "Sign in with SSO to author platform policies.",
  },
  reviseAccess: {
    summary: "You need policy author access to append revisions.",
    detail:
      "Revisions are append-only and safe to retry; the policy scope is fixed at authoring time.",
    ssoGate: "Sign in with SSO to append policy revisions.",
  },
  error: {
    title: "Policy API unavailable",
    registryDetail:
      "Axis did not receive API-backed platform policy records. Local fallback policy records are disabled.",
    detailDetail:
      "Axis did not receive an API-backed platform policy. Local fallback policy records are disabled.",
  },
} as const;

/** Simulation console copy: run-replay form and baseline-vs-simulated result. */
const simulation = {
  run: {
    eyebrow: "Run replay",
    title: "Compare policy outcomes over recorded history",
    description:
      "Re-run recorded decisions against a policy set and see what would change. Nothing in production changes during a replay.",
    fields: {
      workflow: "Workflow id (optional)",
      workflowPlaceholder: "All recorded workflows",
      limit: "History window (events)",
      retentionDays: "Retention window (days)",
      legalHold: "Apply legal hold",
      baselineSet: "Baseline policy set (optional)",
      candidateSet: "Candidate policy set (optional)",
      connector: "Connector id (optional)",
      comparisonHint:
        "Leave the policy-set fields empty to replay against the recorded policy history.",
    },
    submit: "Run replay",
    running: "Running replay…",
    error: {
      title: "Replay run failed",
      detail: "The replay API rejected this run. Adjust the parameters and try again.",
    },
    result: {
      eyebrow: "Replay result",
      baseline: "Baseline",
      simulated: "Simulated",
      changed: "Changed",
      unchanged: "Unchanged",
      decisionsTitle: "Decision comparison",
      policySetTitle: "Policy-set comparison",
      inspect: "Inspect raw result",
      empty: {
        title: "No decisions to compare",
        detail:
          "The replay window returned no policy decisions. Widen the history window or clear the workflow filter.",
      },
    },
  },
  error: {
    title: "Replay API unavailable",
    detail:
      "Axis did not receive API-backed replay artifacts. Local fallback replay records are disabled.",
  },
  noArtifacts: {
    title: "No replay history yet",
    detail: "Replay previews will appear after this tenant has governed workflow history.",
  },
  noPolicyResult: "No policy result recorded for this replay.",
} as const;

/** Guided-setup checklist copy for empty and partially onboarded tenants. */
const onboarding = {
  eyebrow: "Guided setup",
  title: "Set up your governed platform",
  description:
    "Five steps take you from an empty tenant to a governed workflow with recorded audit evidence.",
  progressLabel: "Setup progress",
  stepsComplete: "setup steps complete",
  exploreDemo: {
    label: "Explore with demo data",
    comingSoon: "Coming with demo provisioning",
    pending: "Loading demo data…",
    toastTitle: "Demo data loaded",
    errorFallback: "Axis could not load the demo scenario. The bootstrap API request failed.",
  },
  compact: {
    show: "Show setup steps",
    hide: "Hide setup steps",
  },
  stepDone: "Done",
  steps: {
    connectors: {
      title: "Connect a system",
      why: "Register a file or external source, then activate it so governed syncs can run.",
      cta: "Open connectors",
    },
    ontology: {
      title: "Import ontology entities",
      why: "Give agents and policies a shared vocabulary for your business objects.",
      cta: "Open ontology",
    },
    policies: {
      title: "Define a policy",
      why: "Set the rules that decide what agents may do and when a human steps in.",
      cta: "Open policies",
    },
    agents: {
      title: "Register an agent",
      why: "Register an agent with an explicit autonomy level and permission boundary.",
      cta: "Open agents",
    },
    workflows: {
      title: "Run a governed workflow",
      why: "See a workflow run end to end with evidence recorded at every step.",
      cta: "Open workflows",
    },
  },
} as const;

/**
 * System status (settings) copy: tabs, per-panel state copy, and the
 * plain-English what-to-do line behind every "Action required" pill.
 */
const settingsPanelUnavailable = "Local fallback settings records are disabled.";

const settings = {
  pageTitle: "System status",
  source: {
    live: "Live system status",
    loading: "Loading system status",
    stale: "Stale system status",
    required: "API required",
  },
  stale:
    "Live refresh failed. Showing the last validated system status for this panel.",
  tabs: {
    readiness: "Readiness",
    identity: "Identity",
    deployment: "Deployment",
    support: "Support",
  },
  inspect: "Inspect raw report",
  ready: {
    eyebrow: "Runtime dependencies",
    title: "Axis API boundary",
    dependencyReachable: "reachable",
    dependencyNotConfigured: "not configured",
    egressTitle: "External model egress",
    egressDetail:
      "Reported live by the platform API; egress stays blocked unless a policy opens it.",
    error: {
      title: "Readiness API unavailable",
      detail: `Axis did not receive the API readiness report. ${settingsPanelUnavailable}`,
    },
  },
  gates: {
    eyebrow: "Deployment readiness",
    title: "Production gates",
    demoSafe: "Demo safe",
    productionReady: "Production ready",
    blockersTitle: "Production blockers",
    noBlockers: "All production gates are clear.",
  },
  oidc: {
    eyebrow: "Identity and SSO",
    title: "OIDC readiness",
    issuer: "Issuer",
    audience: "Audience",
    authRequired: "Auth required",
    actorClaim: "Actor claim",
    error: {
      title: "Identity readiness API unavailable",
      detail: `Axis did not receive the OIDC readiness report. ${settingsPanelUnavailable}`,
    },
  },
  session: {
    eyebrow: "Browser session",
    title: "Your session",
    actor: "Actor",
    tenant: "Tenant",
    mode: "Mode",
    authenticated: "Authenticated",
    publicActor: "Public evaluation",
    manageSessions: "Manage browser sessions",
    error: {
      title: "Session API unavailable",
      detail: `Axis did not receive the identity session read model. ${settingsPanelUnavailable}`,
    },
  },
  deployment: {
    eyebrow: "Deployment posture",
    environment: "Environment",
    demoSafe: "Demo safe",
    productionReady: "Production ready",
    objectStore: "Object store",
    wormRetention: "WORM retention",
    retentionMode: "Retention mode",
    retentionDays: "Retention days",
    error: {
      title: "Deployment readiness API unavailable",
      detail: `Axis did not receive the deployment readiness report. ${settingsPanelUnavailable}`,
    },
  },
  support: {
    eyebrow: "Support diagnostics",
    title: "Public-safe support bundle",
    safeToShare: "Safe to share",
    demoSupport: "Demo support",
    productionSupport: "Production support",
    objectRetention: "Object retention",
    retentionActionRequired: "Action required",
    error: {
      title: "Support diagnostics API unavailable",
      detail: `Axis did not receive the support diagnostics report. ${settingsPanelUnavailable}`,
    },
  },
  /**
   * One-line plain-English guidance per readiness check id, shown next to
   * every "Action required" pill. The raw API detail stays as secondary mono
   * text. Keys mirror the check ids emitted by the platform API.
   */
  guidance: {
    // OIDC readiness checks (/identity/oidc/readiness)
    auth_required:
      "Turn on required OIDC verification for the API before moving past local demos.",
    https_issuer: "Use an HTTPS issuer URL from your enterprise IdP before production.",
    explicit_jwks_url:
      "Configure the JWKS URL explicitly from your IdP instead of deriving it from the issuer.",
    asymmetric_algorithms:
      "Allow only asymmetric signing algorithms (for example RS256) for token verification.",
    openid_scope:
      "Add the openid scope to the OIDC client configuration so ID tokens can be issued.",
    tenant_claim: "Set the token claim that carries the tenant so sessions bind to the right tenant.",
    actor_claim: "Set the token claim that identifies the acting user.",
    authorization_code_client:
      "Register a browser SSO client with your IdP and configure its client id.",
    authorization_endpoint: "Point the authorization endpoint at an HTTPS URL from your IdP.",
    token_endpoint: "Point the token endpoint at an HTTPS URL from your IdP.",
    end_session_endpoint:
      "Configure an HTTPS end-session endpoint so signing out also ends the IdP session.",
    post_logout_redirect:
      "Set an HTTPS post-logout redirect so sign-out returns people to the console.",
    session_cookie_signing:
      "Provide an operator-managed signing secret for browser session cookies.",
    secure_session_cookie:
      "Enable the Secure attribute so session cookies only travel over HTTPS.",
    host_prefixed_session_cookie:
      "Enable Secure cookies with the __Host- prefix so sessions bind to this host.",
    refresh_credential_encryption:
      "Provide a refresh-credential encryption key of at least 32 characters.",
    session_idle_timeout: "Set an idle timeout above zero so unattended sessions expire.",
    session_absolute_timeout:
      "Set an absolute session lifetime above zero so sessions always expire.",
    // Deployment readiness checks (/deployment/readiness)
    oidc_enterprise_sso:
      "Resolve the identity checks on the Identity tab to make SSO enterprise-ready.",
    oidc_secure_cookie_session:
      "Serve the API and console over HTTPS with Secure, signed, time-boxed session cookies.",
    external_model_egress_disabled:
      "Keep external model egress off, or govern it with tenant policy and audit controls.",
    api_rate_limiting:
      "Enable API rate limiting before exposing the platform to production traffic.",
    network_egress_restricted:
      "Restrict outbound network traffic with a network policy and an explicit allowlist.",
    deployment_tenancy_profile:
      "Declare the tenancy mode plus isolation, data-residency, and operator-access evidence.",
    live_connector_execution_disabled:
      "Keep live connector execution off until provider policies and runbooks are in place.",
    ontology_graph_mutation_posture:
      "Configure a TypeDB address and enable ontology reads before promoting graph nodes.",
    audit_ledger_signing_configured:
      "Configure an audit ledger signing key so evidence exports are signed.",
    production_object_store_adapter:
      "Configure S3-compatible object storage with credentials, TLS, and WORM retention.",
    observability_instrumentation:
      "Enable OpenTelemetry and point the exporter at your collector to emit traces.",
    production_dr_procedures:
      "Document backup and disaster-recovery runbooks with RPO/RTO targets and rehearsal evidence.",
    // Support diagnostics checks (/support/diagnostics)
    demo_support_ready:
      "Resolve the deployment posture issues so a demo walkthrough is safe to run.",
    production_support_model:
      "Define a 24x7 support model with response targets, escalation paths, and a status page.",
    production_support_commitments:
      "Put signed support commitments, a staffing model, and legal SLA terms in place.",
    support_slo_targets: "Set S1-S4 response targets ordered from shortest to longest.",
    support_escalation_channels:
      "Configure at least two escalation channel classes for production support.",
  } satisfies Record<string, string>,
  guidanceFallback: "Review the technical detail below and update the platform configuration.",
} as const;

const ontology = {
  legend: {
    label: "Ontology graph legend",
    entity: "Entity",
    selected: "Selected",
    relation: "Relation",
    hint: "Click or press Enter on a node to open its entity detail",
  },
  graph: {
    controlsLabel: "Ontology graph controls",
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    resetView: "Reset view",
  },
  sheet: {
    eyebrow: "Ontology entity",
    openFullPage: "Open full page",
    error: {
      title: "Entity API unavailable",
      detail:
        "Axis did not receive an API-backed ontology entity. Local fallback entity records are disabled.",
    },
    notFound: {
      title: "Entity not found",
      detail:
        "No ontology entity exists with this id. It may have been renamed or removed from the graph.",
    },
  },
} as const;

/** Topbar pill marking a tenant that runs the bootstrapped demo scenario. */
const demoBadge = {
  label: "Demo",
  tooltip: "This tenant runs the demo manufacturing scenario",
} as const;

const tenantVocabulary = {
  eyebrow: "Tenant vocabulary",
  title: "Console terminology",
  description:
    "Choose the words this tenant sees for locations, its workspace and operational domains.",
  requiredScope: (scope: string) => `Saving requires the ${scope} scope.`,
  endpoint: "Vocabulary API endpoint",
  source: {
    loading: "Loading tenant vocabulary",
    api: "Vocabulary API",
    missing: "Tenant not found",
    unavailable: "Vocabulary API unavailable",
  },
  mode: {
    defaults: "Using defaults",
    defaultsDetail:
      "This tenant has not configured vocabulary yet. Saving creates tenant-specific terminology.",
    configured: "Tenant configured",
    configuredDetail: "These values override the industry-neutral defaults for this tenant.",
  },
  fields: {
    siteSingular: "Location singular",
    siteSingularDetail: "The singular word used for one operational location.",
    sitePlural: "Location plural",
    sitePluralDetail: "The plural word used for operational locations.",
    workspaceLabel: "Workspace label",
    workspaceLabelDetail: "The tenant-specific name for its operational workspace.",
    domainLabels: "Domain labels",
    domainLabelsDetail:
      "Map each domain key stored on operational records to the label operators should see.",
    domainKey: "Domain key",
    domainKeyPlaceholder: "supply",
    domainLabel: "Display label",
    domainLabelPlaceholder: "Pharmacy supply",
  },
  actions: {
    addDomain: "Add domain label",
    removeDomain: "Remove domain label",
    review: "Review vocabulary update",
    saving: "Saving",
    confirm: "Confirm vocabulary update",
    cancel: "Cancel",
  },
  validation: {
    fix: "Fix the highlighted fields; nothing was sent.",
    labelTooLong: (limit: number) => `Must be at most ${limit} characters.`,
    domainLimit: (limit: number) => `This API accepts at most ${limit} domain labels.`,
    missingDomainKey: "Enter a domain key or remove this row.",
    duplicateDomainKey: "Each domain key can appear only once.",
  },
  confirmation:
    "Confirm this tenant vocabulary update. Existing operational records keep their stored domain keys.",
  errors: {
    prefix: "Vocabulary update failed:",
    unavailable: "Tenant vocabulary API is unavailable.",
    generic: "Vocabulary update failed.",
    requiredPermission: (message: string, permission: string) =>
      `${message} Required permission: ${permission}.`,
  },
  success: "Vocabulary update applied.",
} as const;

export const strings = {
  clarity: {
    objectSummary: "Summary",
    entityPurpose: "Inspect this object, its relationships, and who can access it.",
    policyPurpose: "Review the rule, compare revisions, and test its effect.",
    tenantPurpose: "Manage this organization's access, resource limits, and activity.",
    auditEventIdUnavailable: "Audit event ID unavailable",
    recordedActivity: "Recorded activity",
    advancedConnectorImport: "Advanced: import connector configuration",
    actionCatalog: "Action catalog: available actions and permissions",
    agentDetails: "Agent registry details",
    modelMonitoring: "Model monitoring details",
    businessObjects: "Business objects",
    relationships: "Relationships",
    ontologySources: "Sources and access details",
    ontologyObjects: "Business objects and connections",
    graphRegion: "Scrollable ontology graph",
    createPolicy: "Create policy",
    createOrganization: "Create organization",
    activity: {
      title: "Activity by category",
      window: (count: number) => `Share of ${count} events in the latest window (up to 25).`,
      errorTitle: "Activity breakdown unavailable",
      errorDetail: "Refresh to load the recent audit window.",
      emptyTitle: "No activity to compare",
      emptyDetail: "Recorded events will appear here.",
    },
  },
  scopeDenial,
  nav,
  identityGate,
  commandMenu,
  routeError,
  notFound,
  globalError,
  demoBadge,
  agents,
  approvals,
  audit,
  dataCatalog: {
    searchLabel: "Search data assets",
    searchPlaceholder: "Search by name or connector",
    evidenceFilterLabel: "Filter by evidence",
    evidence: {
      all: "All evidence",
      sync_observed: "Sync observed",
      preview_only: "Preview only",
      declared_only: "Declared only",
    },
    governance: {
      declared: "Governance declared",
      partial: "Governance partial",
      not_declared: "Governance not declared",
    },
    listTitle: "Assets",
    detail: {
      assetId: "Asset ID",
      connector: "Connector",
      kind: "Asset kind",
      evidence: "Evidence",
      governance: "Governance",
      sourceType: "Source type",
      runtimeBoundary: "Runtime boundary",
      egressPolicy: "Egress policy",
      payloadPolicy: "Payload policy",
      syncModes: "Sync modes",
      lastSync: "Last successful sync",
      manifestRevision: "Manifest revision",
      registryOrigin: "Registry origin",
      schemaTitle: "Declared schema mapping",
      schemaEmpty: "This source has no declared field mapping yet.",
      ontologyTargets: "Ontology targets",
      notes: "Catalog notes",
      columns: {
        source: "Source column",
        target: "Target field",
        ontology: "Ontology target",
        type: "Type",
        required: "Required",
      },
    },
    stewardship: {
      title: "Stewardship",
      description:
        "Declared ownership and handling constraints for this asset. Declarations are revisioned and idempotent.",
      fields: {
        owner: "Owner",
        classification: "Classification",
        residency: "Residency",
        retention: "Retention",
        revision: "Revision",
        declaredBy: "Declared by",
        declaredAt: "Declared at",
      },
      classificationLabels: {
        public: "Public",
        internal: "Internal",
        confidential: "Confidential",
        restricted: "Restricted",
      },
      form: {
        title: "Declare stewardship",
        description:
          "Declare an owner and handling constraints for this asset. The first declaration creates revision 1; later updates go through the same endpoint.",
        submit: "Declare stewardship",
        submitting: "Declaring…",
        success: "Stewardship declared.",
        errors: {
          ownerRequired: "Owner is required.",
          ownerTooLong: (limit: number) => `Owner must be at most ${limit} characters.`,
          residencyRequired: "Residency is required.",
          residencyTooLong: (limit: number) =>
            `Residency must be at most ${limit} characters.`,
          retentionRequired: "Retention is required.",
          retentionTooLong: (limit: number) =>
            `Retention must be at most ${limit} characters.`,
          declareFailed: "The stewardship declaration was not applied.",
          conflict:
            "Someone else updated this asset's stewardship while you were editing. Reload the asset and try again with the current record.",
        },
      },
      states: {
        error: {
          title: "Stewardship unavailable",
          detail:
            "Axis could not load this asset's stewardship record. Nothing is shown rather than showing a stale or invented declaration.",
        },
      },
    },
    contract: {
      title: "Data contract",
      description:
        "Declared expectations evaluated against observed evidence at read time. Undeclared or unobserved assets are unknown, never green.",
      status: {
        pass: "Pass",
        warn: "Warn",
        fail: "Fail",
        unknown: "Unknown",
        notDeclared: "No contract declared",
      },
      checks: {
        presence: "Presence",
        schema: "Schema",
        freshness: "Freshness",
      },
      fields: {
        expectedResource: "Expected resource",
        expectedFingerprint: "Expected schema fingerprint",
        warnHours: "Freshness warn threshold (hours)",
        failHours: "Freshness fail threshold (hours)",
        revision: "Revision",
        declaredBy: "Declared by",
        declaredAt: "Declared at",
      },
      form: {
        title: "Declare a data contract",
        description:
          "State the resource this asset must keep observing, optionally the exact header fingerprint it must carry and how fresh the last observation must be.",
        submit: "Declare contract",
        submitting: "Declaring…",
        success: "Contract declared. Evaluation now runs against real observations.",
        errors: {
          resourceRequired: "The expected resource name is required.",
          fingerprintInvalid: (limit: number) =>
            `The schema fingerprint must be ${limit} hexadecimal characters.`,
          hoursInvalid: "Thresholds must be whole numbers of at least 1 hour.",
          orderingInvalid: "The warn threshold cannot exceed the fail threshold.",
          declareFailed: "The data contract declaration was not applied.",
          conflict:
            "Someone else updated this asset's contract while you were editing. Reload the asset and try again with the current record.",
        },
      },
      states: {
        error: {
          title: "Data contract unavailable",
          detail:
            "Axis could not load this asset's contract. Nothing is shown rather than showing a stale or invented declaration.",
        },
      },
    },
    resources: {
      title: "Observed resources",
      description:
        "Source files Axis actually observed through governed preview boundaries. Metadata only — header names and fingerprints, never row values.",
      countSummary: (count: number) =>
        count === 1 ? "1 resource observed" : `${count} resources observed`,
      empty: {
        title: "No observed resources yet",
        detail:
          "Run a successful connector preview to record the first observation for this asset.",
      },
      drift: {
        added: "Added",
        changed: "Changed",
        unchanged: "Unchanged",
      },
      observations: (count: number) =>
        count === 1 ? "1 observation" : `${count} observations`,
      notesTitle: "How observation works",
      states: {
        error: {
          title: "Resource observations unavailable",
          detail:
            "Axis could not load this asset's observed resources. Nothing is shown rather than showing a stale or invented list.",
        },
      },
    },
    states: {
      error: {
        title: "Data catalog unavailable",
        detail:
          "Axis did not receive a valid data asset catalog. Nothing is shown rather than showing stale or invented assets.",
      },
      empty: {
        title: "No data assets yet",
        detail:
          "Register and sync a connector to project its first governed data asset into the catalog.",
      },
      noMatches: {
        title: "No assets match the current filters",
        detail: "Adjust the search or evidence filter to see the rest of the catalog.",
      },
      unknownAsset: {
        title: "This data asset does not exist in the catalog",
        detail:
          "The requested asset ID is not part of this tenant's catalog. Axis does not substitute a different asset for an unknown deep link.",
      },
    },
  },
  connectors,
  models,
  onboarding,
  ontology,
  overview,
  policyDetail,
  settings,
  simulation,
  tenantVocabulary,
  workflows,
  states: {
    loading: "Loading…",
    retry: "Try again",
    technicalDetails: "Technical details",
    /** Correlation id an operator can quote to support. */
    reference: "Reference",
    error: {
      title: "This data could not be loaded",
      detail: "The console could not reach the platform API. Check your connection and try again.",
      retry: "Try again",
    },
    empty: {
      title: "Nothing here yet",
      detail: "Records will appear here as soon as they exist.",
    },
    requestedRecord: {
      title: "Requested record is not in this view",
      detail:
        "The record named in the URL is not present in the current result set. Clear the selection or adjust the filters.",
    },
  },
  pages,
} as const;
