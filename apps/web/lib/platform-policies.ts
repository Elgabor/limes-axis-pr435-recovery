import {
  AxisApiError,
  axisFetch,
  axisFetchParsedJson,
  axisResponseRequestId,
  decodeAxisJson,
  type AxisOperatorError,
  type AxisFetchOptions,
} from "./axis-api";
import {
  parsePlatformPolicyDecision,
  parsePlatformPolicyDetail,
  parsePlatformPolicyRecord,
} from "./runtime-contracts/policies";

export type PlatformPolicyScope = "action_execution" | "approval_requirement";

export type PlatformPolicyEffect = "deny" | "require_approval" | "allow_with_evidence";

export type PlatformPolicyRuleConditions = {
  action_domains?: string[];
  risk_levels?: string[];
  autonomy_levels?: string[];
  requested_amount_at_least?: number | null;
};

export type PlatformPolicyRecord = {
  tenant_id: string;
  policy_id: string;
  revision_number: number;
  policy_version: string;
  display_name: string;
  description: string;
  scope: PlatformPolicyScope;
  effect: PlatformPolicyEffect;
  conditions: PlatformPolicyRuleConditions;
  status: string;
  notes?: string[];
  created_by: string;
  created_at: string;
  required_authoring_scope: string;
  revises_revision_number?: number | null;
  replaced_by_revision_number?: number | null;
  revision_idempotency_key?: string | null;
  idempotent_replay?: boolean;
  audit_event_type: string;
  audit_event_id?: string | null;
  permission_decision: {
    allowed: boolean;
    reason: string;
  };
};

export type PlatformPolicyRegistry = {
  tenant_id: string;
  policy_count: number;
  active_policy_count: number;
  policies?: PlatformPolicyRecord[];
  policy_notes?: string[];
};

export type PlatformPolicyDetail = {
  tenant_id: string;
  policy_id: string;
  current_revision: PlatformPolicyRecord;
  revisions: PlatformPolicyRecord[];
};

export type PlatformPolicyMatch = {
  policy_id: string;
  revision_number: number;
  policy_version: string;
  effect: PlatformPolicyEffect;
  matched_constraints: Record<string, unknown>;
};

export type PlatformPolicyDecision = {
  tenant_id: string;
  scope: PlatformPolicyScope;
  effect: string;
  matched: boolean;
  matched_policy_id?: string | null;
  matched_policy_version?: string | null;
  matched_revision_number?: number | null;
  matched_policies?: PlatformPolicyMatch[];
  evaluated_policy_count: number;
  precedence_rule?: string;
  evidence?: Record<string, unknown>;
};

export type PlatformPolicyEvaluationContextPayload = {
  action_domain?: string;
  risk_level?: string;
  autonomy_level?: string;
  requested_amount?: number;
};

export type PlatformPolicyEvaluationRequestPayload = {
  tenant_id: string;
  actor_id: string;
  actor_scopes: string[];
  scope: PlatformPolicyScope;
  context: PlatformPolicyEvaluationContextPayload;
};

export type PlatformPolicyRegistryFilters = {
  scope: PlatformPolicyScope | typeof allPolicyFilter;
  status: string;
};

export const allPolicyFilter = "all";

export const platformPolicyScopes: PlatformPolicyScope[] = [
  "action_execution",
  "approval_requirement",
];

export const platformPolicyStatuses = ["active", "superseded"];

export const platformPolicyRiskLevels = ["low", "medium", "high", "critical"];

export const platformPolicyAutonomyLevels = ["L0", "L1", "L2", "L3", "L4"];

export const platformPolicyEffects: PlatformPolicyEffect[] = [
  "deny",
  "require_approval",
  "allow_with_evidence",
];

export const platformPolicyEvaluateScope = "platform:policy:evaluate";

export const platformPolicyEvaluateActorId = "platform-policy-reviewer-role";

export const platformPolicyAuthorScope = "platform:policy:author";

export const platformPolicyReviseScope = "platform:policy:revise";

export const platformPolicyAuthorActorId = "platform-governance-owner-role";

export const platformPolicyIdPattern = "^[a-z0-9][a-z0-9_-]*$";

const platformPolicyIdRegex = new RegExp(platformPolicyIdPattern);

export const platformPoliciesPath = "/platform/policies";

export const platformPolicyEvaluatePath = "/platform/policies/evaluate";

export const platformPolicyPrecedenceSteps = [
  "deny beats require_approval, which beats allow_with_evidence.",
  "Ties on effect are broken by the lexicographically smallest policy id.",
  "When no active policy matches the context, the decision is default allow.",
];

export function buildPlatformPoliciesPath(
  filters: PlatformPolicyRegistryFilters,
  tenantId?: string,
): string {
  const params = new URLSearchParams();

  if (tenantId) {
    params.set("tenant_id", tenantId);
  }

  if (filters.scope !== allPolicyFilter) {
    params.set("scope", filters.scope);
  }

  if (filters.status !== allPolicyFilter) {
    params.set("status", filters.status);
  }

  const query = params.toString();
  return query ? `${platformPoliciesPath}?${query}` : platformPoliciesPath;
}

export function buildPlatformPolicyDetailPath(policyId: string, tenantId?: string): string {
  const path = `${platformPoliciesPath}/${encodeURIComponent(policyId)}`;
  return tenantId ? `${path}?${new URLSearchParams({ tenant_id: tenantId })}` : path;
}

export function buildPlatformPolicyRevisionsPath(policyId: string): string {
  return `${buildPlatformPolicyDetailPath(policyId)}/revisions`;
}

export function policyScopeLabel(scope: PlatformPolicyScope): string {
  return scope === "action_execution" ? "Action execution" : "Approval requirement";
}

export function policyEffectLabel(effect: string): string {
  if (effect === "deny") {
    return "Deny";
  }

  if (effect === "require_approval") {
    return "Require approval";
  }

  if (effect === "allow_with_evidence") {
    return "Allow with evidence";
  }

  return effect === "allow" ? "Allow (default)" : effect;
}

export function policyEffectClass(effect: string): string {
  if (effect === "deny") {
    return "signal-action-required";
  }

  return effect === "require_approval" ? "signal-watch" : "signal-ready";
}

export function policyStatusLabel(status: string): string {
  return status === "active" ? "Active" : status === "superseded" ? "Superseded" : status;
}

export function policyStatusClass(status: string): string {
  return status === "active" ? "signal-ready" : "status-checking";
}

export function summarizePolicyConditions(conditions: PlatformPolicyRuleConditions): string {
  const parts: string[] = [];
  const actionDomains = conditions.action_domains ?? [];
  const riskLevels = conditions.risk_levels ?? [];
  const autonomyLevels = conditions.autonomy_levels ?? [];

  if (actionDomains.length > 0) {
    parts.push(`domains ${actionDomains.join(", ")}`);
  }

  if (riskLevels.length > 0) {
    parts.push(`risk ${riskLevels.join(", ")}`);
  }

  if (autonomyLevels.length > 0) {
    parts.push(`autonomy ${autonomyLevels.join(", ")}`);
  }

  if (conditions.requested_amount_at_least != null) {
    parts.push(`amount >= ${conditions.requested_amount_at_least}`);
  }

  return parts.length > 0 ? parts.join(" / ") : "Any evaluation context";
}

export function countPoliciesByEffect(
  policies: PlatformPolicyRecord[],
  effect: PlatformPolicyEffect,
): number {
  return policies.filter((policy) => policy.effect === effect).length;
}

export type RequestedAmountParseResult =
  | { ok: true; amount: number | null }
  | { ok: false; message: string };

export function parseRequestedAmount(value: string): RequestedAmountParseResult {
  const trimmed = value.trim();

  if (trimmed.length === 0) {
    return { ok: true, amount: null };
  }

  const amount = Number(trimmed);

  if (!Number.isFinite(amount) || amount < 0) {
    return { ok: false, message: "Requested amount must be a non-negative number." };
  }

  return { ok: true, amount };
}

export type PolicyEvaluationFormState = {
  scope: PlatformPolicyScope;
  actionDomain: string;
  riskLevel: string;
  autonomyLevel: string;
  requestedAmount: number | null;
};

export function buildPolicyEvaluationPayload(
  tenantId: string,
  form: PolicyEvaluationFormState,
): PlatformPolicyEvaluationRequestPayload {
  const context: PlatformPolicyEvaluationContextPayload = {};
  const actionDomain = form.actionDomain.trim();

  if (actionDomain.length > 0) {
    context.action_domain = actionDomain;
  }

  if (form.riskLevel.length > 0) {
    context.risk_level = form.riskLevel;
  }

  if (form.autonomyLevel.length > 0) {
    context.autonomy_level = form.autonomyLevel;
  }

  if (form.requestedAmount !== null) {
    context.requested_amount = form.requestedAmount;
  }

  return {
    tenant_id: tenantId,
    actor_id: platformPolicyEvaluateActorId,
    actor_scopes: [platformPolicyEvaluateScope],
    scope: form.scope,
    context,
  };
}

export type PlatformPolicyCreateRequestPayload = {
  tenant_id: string;
  policy_id: string;
  policy_version: string;
  display_name: string;
  description: string;
  scope: PlatformPolicyScope;
  effect: PlatformPolicyEffect;
  conditions: PlatformPolicyRuleConditions;
  created_by: string;
  actor_scopes: string[];
  notes: string[];
};

export type PlatformPolicyReviseRequestPayload = {
  tenant_id: string;
  policy_id: string;
  policy_version: string;
  display_name: string;
  description: string;
  effect: PlatformPolicyEffect;
  conditions: PlatformPolicyRuleConditions;
  updated_by: string;
  actor_scopes: string[];
  idempotency_key: string;
  notes: string[];
};

export type PolicyConditionsFormState = {
  actionDomainsText: string;
  riskLevels: string[];
  autonomyLevels: string[];
  requestedAmount: string;
};

export type PolicyDraftFormState = {
  policyId: string;
  policyVersion: string;
  displayName: string;
  description: string;
  scope: PlatformPolicyScope;
  effect: PlatformPolicyEffect;
  conditions: PolicyConditionsFormState;
  notesText: string;
};

export type PolicyDraftFieldErrors = Partial<
  Record<
    "policyId" | "policyVersion" | "displayName" | "description" | "conditions" | "requestedAmount",
    string
  >
>;

export function emptyPolicyConditionsForm(): PolicyConditionsFormState {
  return {
    actionDomainsText: "",
    riskLevels: [],
    autonomyLevels: [],
    requestedAmount: "",
  };
}

export function emptyPolicyDraft(): PolicyDraftFormState {
  return {
    policyId: "",
    policyVersion: "1.0.0",
    displayName: "",
    description: "",
    scope: "action_execution",
    effect: "require_approval",
    conditions: emptyPolicyConditionsForm(),
    notesText: "",
  };
}

export function draftFromPolicyRecord(record: PlatformPolicyRecord): PolicyDraftFormState {
  return {
    policyId: record.policy_id,
    policyVersion: record.policy_version,
    displayName: record.display_name,
    description: record.description,
    scope: record.scope,
    effect: record.effect,
    conditions: {
      actionDomainsText: (record.conditions.action_domains ?? []).join(", "),
      riskLevels: [...(record.conditions.risk_levels ?? [])],
      autonomyLevels: [...(record.conditions.autonomy_levels ?? [])],
      requestedAmount:
        record.conditions.requested_amount_at_least != null
          ? String(record.conditions.requested_amount_at_least)
          : "",
    },
    notesText: (record.notes ?? []).join("\n"),
  };
}

export function parseActionDomains(text: string): string[] {
  return text
    .split(",")
    .map((domain) => domain.trim())
    .filter((domain) => domain.length > 0);
}

export function parsePolicyNotes(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((note) => note.trim())
    .filter((note) => note.length > 0);
}

const policyIdErrorMessage =
  "Policy id must match ^[a-z0-9][a-z0-9_-]*$ (lowercase letters, digits, _ or -).";

const emptyConditionsErrorMessage =
  "Declare at least one condition; the API rejects empty rules.";

export function validatePolicyId(policyId: string): string | null {
  if (!platformPolicyIdRegex.test(policyId)) {
    return policyIdErrorMessage;
  }

  return policyId.length > 180 ? "Policy id must be at most 180 characters." : null;
}

type ValidatePolicyDraftOptions = {
  requirePolicyId?: boolean;
};

export function validatePolicyDraft(
  draft: PolicyDraftFormState,
  options: ValidatePolicyDraftOptions = {},
): PolicyDraftFieldErrors {
  const errors: PolicyDraftFieldErrors = {};
  const requirePolicyId = options.requirePolicyId ?? true;

  if (requirePolicyId) {
    const policyIdError = validatePolicyId(draft.policyId);

    if (policyIdError) {
      errors.policyId = policyIdError;
    }
  }

  const policyVersion = draft.policyVersion.trim();

  if (policyVersion.length === 0 || policyVersion.length > 80) {
    errors.policyVersion = "Policy version must be 1-80 characters.";
  }

  const displayName = draft.displayName.trim();

  if (displayName.length === 0 || displayName.length > 200) {
    errors.displayName = "Display name must be 1-200 characters.";
  }

  const description = draft.description.trim();

  if (description.length === 0 || description.length > 600) {
    errors.description = "Description must be 1-600 characters.";
  }

  const parsedAmount = parseRequestedAmount(draft.conditions.requestedAmount);

  if (!parsedAmount.ok) {
    errors.requestedAmount = parsedAmount.message;
  } else if (
    parseActionDomains(draft.conditions.actionDomainsText).length === 0
    && draft.conditions.riskLevels.length === 0
    && draft.conditions.autonomyLevels.length === 0
    && parsedAmount.amount === null
  ) {
    errors.conditions = emptyConditionsErrorMessage;
  }

  return errors;
}

export function buildPolicyConditionsPayload(
  conditions: PolicyConditionsFormState,
): PlatformPolicyRuleConditions {
  const payload: PlatformPolicyRuleConditions = {};
  const actionDomains = parseActionDomains(conditions.actionDomainsText);
  const parsedAmount = parseRequestedAmount(conditions.requestedAmount);

  if (actionDomains.length > 0) {
    payload.action_domains = actionDomains;
  }

  if (conditions.riskLevels.length > 0) {
    payload.risk_levels = [...conditions.riskLevels];
  }

  if (conditions.autonomyLevels.length > 0) {
    payload.autonomy_levels = [...conditions.autonomyLevels];
  }

  if (parsedAmount.ok && parsedAmount.amount !== null) {
    payload.requested_amount_at_least = parsedAmount.amount;
  }

  return payload;
}

export function buildPolicyCreatePayload(
  tenantId: string,
  draft: PolicyDraftFormState,
): PlatformPolicyCreateRequestPayload {
  return {
    tenant_id: tenantId,
    policy_id: draft.policyId,
    policy_version: draft.policyVersion.trim(),
    display_name: draft.displayName.trim(),
    description: draft.description.trim(),
    scope: draft.scope,
    effect: draft.effect,
    conditions: buildPolicyConditionsPayload(draft.conditions),
    created_by: platformPolicyAuthorActorId,
    actor_scopes: [platformPolicyAuthorScope],
    notes: parsePolicyNotes(draft.notesText),
  };
}

export function buildPolicyRevisePayload(
  tenantId: string,
  policyId: string,
  draft: PolicyDraftFormState,
  idempotencyKey: string,
): PlatformPolicyReviseRequestPayload {
  return {
    tenant_id: tenantId,
    policy_id: policyId,
    policy_version: draft.policyVersion.trim(),
    display_name: draft.displayName.trim(),
    description: draft.description.trim(),
    effect: draft.effect,
    conditions: buildPolicyConditionsPayload(draft.conditions),
    updated_by: platformPolicyAuthorActorId,
    actor_scopes: [platformPolicyReviseScope],
    idempotency_key: idempotencyKey,
    notes: parsePolicyNotes(draft.notesText),
  };
}

/**
 * Client-side advisory mirror of the server's condition matcher, used by the
 * draft preview. It never replaces the dry-run endpoint: the server decision
 * stays authoritative, this only reports whether the drafted (not yet
 * persisted) conditions would match the sampled context.
 */
export function draftConditionsMatchContext(
  conditions: PlatformPolicyRuleConditions,
  context: PlatformPolicyEvaluationContextPayload,
): boolean {
  const actionDomains = conditions.action_domains ?? [];
  const riskLevels = conditions.risk_levels ?? [];
  const autonomyLevels = conditions.autonomy_levels ?? [];

  if (actionDomains.length > 0) {
    if (context.action_domain === undefined || !actionDomains.includes(context.action_domain)) {
      return false;
    }
  }

  if (riskLevels.length > 0) {
    if (context.risk_level === undefined || !riskLevels.includes(context.risk_level)) {
      return false;
    }
  }

  if (autonomyLevels.length > 0) {
    if (
      context.autonomy_level === undefined
      || !autonomyLevels.includes(context.autonomy_level)
    ) {
      return false;
    }
  }

  if (conditions.requested_amount_at_least != null) {
    if (
      context.requested_amount === undefined
      || context.requested_amount < conditions.requested_amount_at_least
    ) {
      return false;
    }
  }

  return true;
}

export type PolicyRevisionScalarDiff = {
  kind: "scalar";
  label: string;
  base: string;
  target: string;
  changed: boolean;
};

export type PolicyRevisionListDiff = {
  kind: "list";
  label: string;
  added: string[];
  removed: string[];
  unchanged: string[];
  changed: boolean;
};

export type PolicyRevisionDiff = PolicyRevisionScalarDiff | PolicyRevisionListDiff;

function scalarDiff(label: string, base: string, target: string): PolicyRevisionScalarDiff {
  return { kind: "scalar", label, base, target, changed: base !== target };
}

function listDiff(label: string, base: string[], target: string[]): PolicyRevisionListDiff {
  const baseSet = new Set(base);
  const targetSet = new Set(target);
  const added = target.filter((item) => !baseSet.has(item));
  const removed = base.filter((item) => !targetSet.has(item));

  return {
    kind: "list",
    label,
    added,
    removed,
    unchanged: target.filter((item) => baseSet.has(item)),
    changed: added.length > 0 || removed.length > 0,
  };
}

function amountThresholdLabel(conditions: PlatformPolicyRuleConditions): string {
  return conditions.requested_amount_at_least != null
    ? `>= ${conditions.requested_amount_at_least}`
    : "No amount gate";
}

export function comparePolicyRevisions(
  base: PlatformPolicyRecord,
  target: PlatformPolicyRecord,
): PolicyRevisionDiff[] {
  return [
    scalarDiff("Display name", base.display_name, target.display_name),
    scalarDiff("Description", base.description, target.description),
    scalarDiff("Policy version", base.policy_version, target.policy_version),
    scalarDiff("Effect", policyEffectLabel(base.effect), policyEffectLabel(target.effect)),
    listDiff(
      "Action domains",
      base.conditions.action_domains ?? [],
      target.conditions.action_domains ?? [],
    ),
    listDiff(
      "Risk levels",
      base.conditions.risk_levels ?? [],
      target.conditions.risk_levels ?? [],
    ),
    listDiff(
      "Autonomy levels",
      base.conditions.autonomy_levels ?? [],
      target.conditions.autonomy_levels ?? [],
    ),
    scalarDiff(
      "Amount threshold",
      amountThresholdLabel(base.conditions),
      amountThresholdLabel(target.conditions),
    ),
    listDiff("Notes", base.notes ?? [], target.notes ?? []),
  ];
}

export type PlatformPolicyWriteResult =
  | { kind: "created"; record: PlatformPolicyRecord }
  | { kind: "replayed"; record: PlatformPolicyRecord }
  | { kind: "conflict"; reason: string; message: string; requestId?: string }
  | {
      kind: "invalid";
      message: string;
      fieldErrors: PolicyDraftFieldErrors;
      requestId?: string;
    }
  | { kind: "forbidden"; message: string; requiredPermission?: string; requestId?: string }
  | { kind: "failed"; status: number; message: string; requestId?: string };

export type PlatformPolicyWriteFailure = Exclude<
  PlatformPolicyWriteResult,
  { kind: "created" | "replayed" }
>;

/** Creation never produces the revision endpoint's idempotent replay variant. */
export type PlatformPolicyCreateResult = Exclude<
  PlatformPolicyWriteResult,
  { kind: "replayed" }
>;

/** Project a parsed write result into the same safe mutation-error shape as thrown failures. */
export function policyWriteOperatorError(
  result: PlatformPolicyWriteFailure,
  message: string = result.message,
): AxisOperatorError {
  return {
    code: null,
    message,
    requestId: result.requestId ?? null,
    status: result.kind === "failed" ? result.status : null,
  };
}

type PolicyWriteErrorDetail = {
  code?: string;
  message?: string;
  reason?: string;
  required_permission?: string;
};

type PolicyValidationIssue = {
  loc?: unknown[];
  msg?: string;
};

const writeFieldByRequestField: Record<string, keyof PolicyDraftFieldErrors> = {
  policy_id: "policyId",
  policy_version: "policyVersion",
  display_name: "displayName",
  description: "description",
  conditions: "conditions",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function extractErrorDetail(body: unknown): PolicyWriteErrorDetail | PolicyValidationIssue[] | null {
  if (!isRecord(body) || !("detail" in body)) {
    return null;
  }

  const detail = body.detail;

  if (Array.isArray(detail)) {
    return detail as PolicyValidationIssue[];
  }

  return isRecord(detail) ? (detail as PolicyWriteErrorDetail) : null;
}

function mapValidationIssues(issues: PolicyValidationIssue[]): PolicyDraftFieldErrors {
  const fieldErrors: PolicyDraftFieldErrors = {};

  for (const issue of issues) {
    const location = issue.loc ?? [];
    const requestField = location.find(
      (segment): segment is string =>
        typeof segment === "string" && segment in writeFieldByRequestField,
    );

    if (requestField && issue.msg) {
      fieldErrors[writeFieldByRequestField[requestField]] = issue.msg;
    }
  }

  return fieldErrors;
}

export function parsePolicyWriteFailure(
  status: number,
  body: unknown,
  requestId?: string | null,
): PlatformPolicyWriteFailure {
  const detail = extractErrorDetail(body);
  const detailObject = Array.isArray(detail) ? null : detail;
  const message = detailObject?.message ?? `Policy write failed with ${status}.`;
  const reference = requestId ? { requestId } : {};

  if (status === 409) {
    return {
      kind: "conflict",
      reason: detailObject?.reason ?? "conflict",
      message,
      ...reference,
    };
  }

  if (status === 422) {
    if (Array.isArray(detail)) {
      return {
        kind: "invalid",
        message: "The policy request failed API validation.",
        fieldErrors: mapValidationIssues(detail),
        ...reference,
      };
    }

    const fieldErrors: PolicyDraftFieldErrors = {};

    if (detailObject?.reason === "invalid_rule_conditions") {
      fieldErrors.conditions = message;
    } else if (detailObject?.reason === "policy_id_mismatch") {
      fieldErrors.policyId = message;
    }

    return { kind: "invalid", message, fieldErrors, ...reference };
  }

  if (status === 403) {
    return {
      kind: "forbidden",
      message,
      requiredPermission: detailObject?.required_permission,
      ...reference,
    };
  }

  return { kind: "failed", status, message, ...reference };
}

async function readJsonBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function createPlatformPolicy(
  payload: PlatformPolicyCreateRequestPayload,
  options: AxisFetchOptions = {},
): Promise<PlatformPolicyCreateResult> {
  const response = await axisFetch(platformPoliciesPath, {
    ...options,
    method: "POST",
    body: payload,
  });
  const body = await readJsonBody(response);

  if (response.status === 201) {
    return {
      kind: "created",
      record: decodeAxisJson(
        platformPoliciesPath,
        body,
        parsePlatformPolicyRecord,
        axisResponseRequestId(response),
      ),
    };
  }

  return parsePolicyWriteFailure(response.status, body, axisResponseRequestId(response));
}

export async function revisePlatformPolicy(
  policyId: string,
  payload: PlatformPolicyReviseRequestPayload,
  options: AxisFetchOptions = {},
): Promise<PlatformPolicyWriteResult> {
  const path = buildPlatformPolicyRevisionsPath(policyId);
  const response = await axisFetch(path, {
    ...options,
    method: "POST",
    body: payload,
  });
  const body = await readJsonBody(response);

  if (response.status === 201) {
    return {
      kind: "created",
      record: decodeAxisJson(
        path,
        body,
        parsePlatformPolicyRecord,
        axisResponseRequestId(response),
      ),
    };
  }

  if (response.status === 200) {
    return {
      kind: "replayed",
      record: decodeAxisJson(
        path,
        body,
        parsePlatformPolicyRecord,
        axisResponseRequestId(response),
      ),
    };
  }

  return parsePolicyWriteFailure(response.status, body, axisResponseRequestId(response));
}

export async function fetchPlatformPolicyDetail(
  policyId: string,
  options: AxisFetchOptions = {},
  tenantId?: string,
): Promise<PlatformPolicyDetail | null> {
  const path = buildPlatformPolicyDetailPath(policyId, tenantId);
  const response = await axisFetch(path, options);

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new AxisApiError(path, response.status, {
      requestId: axisResponseRequestId(response),
    });
  }

  return decodeAxisJson(
    path,
    await response.json(),
    parsePlatformPolicyDetail,
    axisResponseRequestId(response),
  );
}

export async function evaluatePlatformPolicy(
  payload: PlatformPolicyEvaluationRequestPayload,
  options: AxisFetchOptions = {},
): Promise<PlatformPolicyDecision> {
  return axisFetchParsedJson<PlatformPolicyDecision>(
    platformPolicyEvaluatePath,
    parsePlatformPolicyDecision,
    {
      ...options,
      method: "POST",
      body: payload,
    },
  );
}
