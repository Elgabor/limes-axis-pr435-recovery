import {
  AxisApiError,
  axisFetch,
  axisResponseRequestId,
  decodeAxisJson,
  type AxisFetchOptions,
  type AxisOperatorError,
} from "./axis-api";
import {
  parseTenantQuotaSet,
  parseTenantRecord,
  parseTenantRegistry,
  parseTenantVocabularySet,
} from "./runtime-contracts/tenants";

export type TenantLifecycleStatus = "active" | "suspended" | "pending_deletion";

export type TenantPermissionDecision = {
  allowed: boolean;
  reason: string;
};

export type TenantRecord = {
  tenant_id: string;
  display_name: string;
  description: string;
  status: TenantLifecycleStatus;
  created_by: string;
  bootstrap_admin_actor_id?: string | null;
  provision_idempotency_key?: string | null;
  suspended_at?: string | null;
  suspended_by?: string | null;
  suspension_reason?: string | null;
  reactivated_at?: string | null;
  reactivated_by?: string | null;
  permission_decision?: TenantPermissionDecision | null;
  audit_event_id?: string | null;
  audit_event_type: string;
  idempotent_replay?: boolean;
  notes?: string[];
  created_at: string;
  updated_at: string;
};

export type TenantRegistry = {
  tenant_count: number;
  active_tenant_count: number;
  tenants?: TenantRecord[];
  has_more?: boolean;
  next_cursor?: string | null;
  tenant_notes?: string[];
};

export type TenantQuotaChange = {
  quota_key: string;
  previous_value?: number | null;
  new_value?: number | null;
  audit_event_id?: string | null;
  audit_event_type: string;
};

export type TenantQuotaSet = {
  tenant_id: string;
  quotas?: Record<string, number>;
  changes?: TenantQuotaChange[];
  quota_notes?: string[];
};

export type TenantQuotaValues = {
  api_requests_per_window?: number | null;
  max_concurrent_sessions?: number | null;
  max_connector_sync_rows_per_run?: number | null;
};

export type TenantVocabulary = {
  site_singular: string;
  site_plural: string;
  workspace_label: string;
  domain_labels: Record<string, string>;
};

export type TenantVocabularyChange = {
  previous_value?: TenantVocabulary | null;
  new_value: TenantVocabulary;
  audit_event_id?: string | null;
  audit_event_type: string;
};

export type TenantVocabularySet = {
  tenant_id: string;
  vocabulary: TenantVocabulary;
  configured: boolean;
  changes?: TenantVocabularyChange[];
  vocabulary_notes?: string[];
};

export type TenantVocabularyUpdateRequestPayload = {
  requested_by: string;
  actor_scopes: string[];
  vocabulary: TenantVocabulary;
  notes: string[];
};

export type TenantBootstrapAdminPayload = {
  actor_id: string;
  display_name: string;
  scopes: string[];
};

export type TenantProvisionRequestPayload = {
  tenant_id: string;
  display_name: string;
  description: string;
  requested_by: string;
  actor_scopes: string[];
  idempotency_key: string;
  bootstrap_admin?: TenantBootstrapAdminPayload;
  notes: string[];
};

export type TenantSuspendRequestPayload = {
  requested_by: string;
  actor_scopes: string[];
  reason: string;
  notes: string[];
};

export type TenantReactivateRequestPayload = {
  requested_by: string;
  actor_scopes: string[];
  reason: string;
  notes: string[];
};

export type TenantQuotaUpdateRequestPayload = {
  requested_by: string;
  actor_scopes: string[];
  quotas: TenantQuotaValues;
  notes: string[];
};

export type TenantRegistryFilters = {
  status: TenantLifecycleStatus | typeof allTenantFilter;
};

export const allTenantFilter = "all";

// The lifecycle route binds requested_by / actor_scopes from the authenticated
// OIDC principal server-side. The console sends a fixed operator role id (which
// the server overwrites with the principal, or rejects on mismatch) mirroring
// the platform-policy authoring surface. This keeps the offline / demo path
// (no principal) working while the operator scopes gate real authority.
export const platformTenantOperatorActorId = "platform-tenant-operator-role";

export const platformTenantOperatorScope = "platform:tenant:operator";

export const platformTenantProvisionScope = "platform:tenant:provision";

export const platformTenantSuspendScope = "platform:tenant:suspend";

export const platformTenantQuotaScope = "platform:tenant:quota";

export const platformTenantConfigureScope = "platform:tenant:configure";

export const tenantVocabularyLabelMaxLength = 100;

export const tenantVocabularyDomainLimit = 50;

export const tenantLifecycleStatuses: TenantLifecycleStatus[] = [
  "active",
  "suspended",
  "pending_deletion",
];

// Mirrors the server pattern on TenantProvisionRequest.tenant_id.
export const tenantIdPattern = "^[a-z0-9][a-z0-9_-]*$";

const tenantIdRegex = new RegExp(tenantIdPattern);

const TENANT_ID_MAX_LENGTH = 80;

export const platformTenantsPath = "/platform/tenants";

// Page size for the tenant listing. The list route is a keyset-cursor surface
// ordered by tenant_id ascending; the console requests the server maximum per
// page (le=200) and follows next_cursor to page beyond it (see
// fetchTenantRegistry / mergeTenantRegistryPage), so there is no listing cap.
export const tenantRegistryLimit = 200;

export type TenantQuotaField = keyof TenantQuotaValues;

export type TenantQuotaFieldDescriptor = {
  field: TenantQuotaField;
  label: string;
  min: number;
  max: number;
  detail: string;
};

// Bounds mirror the server ge/le constraints on TenantQuotaValues.
export const tenantQuotaFields: TenantQuotaFieldDescriptor[] = [
  {
    field: "api_requests_per_window",
    label: "API requests per window",
    min: 1,
    max: 1_000_000,
    detail: "Overrides the global API rate limit on protected paths.",
  },
  {
    field: "max_concurrent_sessions",
    label: "Max concurrent sessions",
    min: 0,
    max: 10_000,
    detail: "Overrides the global concurrent browser-session cap.",
  },
  {
    field: "max_connector_sync_rows_per_run",
    label: "Max connector sync rows per run",
    min: 1,
    max: 1_000_000,
    detail: "Caps governed live-sync row limits per connector run.",
  },
];

export function buildPlatformTenantsPath(
  filters: TenantRegistryFilters,
  limit: number = tenantRegistryLimit,
  cursor?: string | null,
): string {
  const params = new URLSearchParams();

  if (filters.status !== allTenantFilter) {
    params.set("status", filters.status);
  }

  // Request a full page (the server maximum); pagination continues via cursor.
  params.set("limit", String(limit));

  if (cursor) {
    params.set("cursor", cursor);
  }

  return `${platformTenantsPath}?${params.toString()}`;
}

/**
 * Append a fetched page to the accumulated registry for cursor pagination.
 *
 * Tenant and active counts are recomputed over the merged tenant list so the
 * headline metrics reflect everything loaded so far, while has_more/next_cursor
 * always track the most recently fetched page.
 */
export function mergeTenantRegistryPage(
  existing: TenantRegistry | null,
  page: TenantRegistry,
): TenantRegistry {
  const tenants = [...(existing?.tenants ?? []), ...(page.tenants ?? [])];

  return {
    tenant_count: tenants.length,
    active_tenant_count: tenants.filter((tenant) => tenant.status === "active").length,
    tenants,
    has_more: page.has_more ?? false,
    next_cursor: page.next_cursor ?? null,
    tenant_notes: page.tenant_notes ?? existing?.tenant_notes,
  };
}

export function buildPlatformTenantDetailPath(tenantId: string): string {
  return `${platformTenantsPath}/${encodeURIComponent(tenantId)}`;
}

export function buildPlatformTenantQuotasPath(tenantId: string): string {
  return `${buildPlatformTenantDetailPath(tenantId)}/quotas`;
}

export function buildPlatformTenantVocabularyPath(tenantId: string): string {
  return `${buildPlatformTenantDetailPath(tenantId)}/vocabulary`;
}

export function buildPlatformTenantSuspendPath(tenantId: string): string {
  return `${buildPlatformTenantDetailPath(tenantId)}/suspend`;
}

export function buildPlatformTenantReactivatePath(tenantId: string): string {
  return `${buildPlatformTenantDetailPath(tenantId)}/reactivate`;
}

export function tenantStatusLabel(status: TenantLifecycleStatus | string): string {
  if (status === "active") {
    return "Active";
  }

  if (status === "suspended") {
    return "Suspended";
  }

  return status === "pending_deletion" ? "Pending deletion" : status;
}

export function tenantStatusClass(status: TenantLifecycleStatus | string): string {
  if (status === "active") {
    return "signal-ready";
  }

  if (status === "suspended") {
    return "signal-action-required";
  }

  return status === "pending_deletion" ? "signal-watch" : "status-checking";
}

const tenantIdErrorMessage =
  "Tenant id must match ^[a-z0-9][a-z0-9_-]*$ (start with a lowercase letter or digit, then lowercase letters, digits, _ or -).";

export function validateTenantId(tenantId: string): string | null {
  if (!tenantIdRegex.test(tenantId)) {
    return tenantIdErrorMessage;
  }

  return tenantId.length > TENANT_ID_MAX_LENGTH
    ? `Tenant id must be at most ${TENANT_ID_MAX_LENGTH} characters.`
    : null;
}

export function parseTenantNotes(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((note) => note.trim())
    .filter((note) => note.length > 0);
}

export function parseBootstrapScopes(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((scope) => scope.trim())
    .filter((scope) => scope.length > 0);
}

export type TenantProvisionFormState = {
  tenantId: string;
  displayName: string;
  description: string;
  bootstrapEnabled: boolean;
  bootstrapActorId: string;
  bootstrapDisplayName: string;
  bootstrapScopesText: string;
  notesText: string;
};

export type TenantProvisionFieldErrors = Partial<
  Record<
    | "tenantId"
    | "displayName"
    | "description"
    | "bootstrapActorId"
    | "bootstrapDisplayName",
    string
  >
>;

export function emptyTenantProvisionForm(): TenantProvisionFormState {
  return {
    tenantId: "",
    displayName: "",
    description: "",
    bootstrapEnabled: false,
    bootstrapActorId: "",
    bootstrapDisplayName: "",
    bootstrapScopesText: "",
    notesText: "",
  };
}

export function validateTenantProvisionForm(
  form: TenantProvisionFormState,
): TenantProvisionFieldErrors {
  const errors: TenantProvisionFieldErrors = {};

  const tenantIdError = validateTenantId(form.tenantId.trim());
  if (tenantIdError) {
    errors.tenantId = tenantIdError;
  }

  const displayName = form.displayName.trim();
  if (displayName.length === 0 || displayName.length > 200) {
    errors.displayName = "Display name must be 1-200 characters.";
  }

  if (form.description.trim().length > 600) {
    errors.description = "Description must be at most 600 characters.";
  }

  if (form.bootstrapEnabled) {
    const bootstrapActorId = form.bootstrapActorId.trim();
    if (bootstrapActorId.length === 0 || bootstrapActorId.length > 120) {
      errors.bootstrapActorId = "Bootstrap admin actor id must be 1-120 characters.";
    }

    const bootstrapDisplayName = form.bootstrapDisplayName.trim();
    if (bootstrapDisplayName.length === 0 || bootstrapDisplayName.length > 200) {
      errors.bootstrapDisplayName = "Bootstrap admin display name must be 1-200 characters.";
    }
  }

  return errors;
}

export function buildTenantProvisionPayload(
  form: TenantProvisionFormState,
  idempotencyKey: string,
): TenantProvisionRequestPayload {
  const payload: TenantProvisionRequestPayload = {
    tenant_id: form.tenantId.trim(),
    display_name: form.displayName.trim(),
    description: form.description.trim(),
    requested_by: platformTenantOperatorActorId,
    actor_scopes: [platformTenantOperatorScope, platformTenantProvisionScope],
    idempotency_key: idempotencyKey,
    notes: parseTenantNotes(form.notesText),
  };

  if (form.bootstrapEnabled) {
    payload.bootstrap_admin = {
      actor_id: form.bootstrapActorId.trim(),
      display_name: form.bootstrapDisplayName.trim(),
      scopes: parseBootstrapScopes(form.bootstrapScopesText),
    };
  }

  return payload;
}

export function buildTenantSuspendPayload(
  reason: string,
  notes: string[] = [],
): TenantSuspendRequestPayload {
  return {
    requested_by: platformTenantOperatorActorId,
    actor_scopes: [platformTenantOperatorScope, platformTenantSuspendScope],
    reason: reason.trim(),
    notes,
  };
}

export function buildTenantReactivatePayload(
  reason: string,
  notes: string[] = [],
): TenantReactivateRequestPayload {
  return {
    requested_by: platformTenantOperatorActorId,
    actor_scopes: [platformTenantOperatorScope, platformTenantSuspendScope],
    reason: reason.trim(),
    notes,
  };
}

export type TenantQuotaFormState = {
  api_requests_per_window: string;
  max_concurrent_sessions: string;
  max_connector_sync_rows_per_run: string;
};

export function quotaFormFromQuotaSet(quotaSet: TenantQuotaSet | null): TenantQuotaFormState {
  const quotas = quotaSet?.quotas ?? {};
  const valueFor = (field: TenantQuotaField): string =>
    quotas[field] != null ? String(quotas[field]) : "";

  return {
    api_requests_per_window: valueFor("api_requests_per_window"),
    max_concurrent_sessions: valueFor("max_concurrent_sessions"),
    max_connector_sync_rows_per_run: valueFor("max_connector_sync_rows_per_run"),
  };
}

export type TenantQuotaFieldError = Partial<Record<TenantQuotaField, string>>;

export type QuotaValueParseResult =
  | { ok: true; value: number | null }
  | { ok: false; message: string };

export function parseQuotaValue(
  raw: string,
  descriptor: TenantQuotaFieldDescriptor,
): QuotaValueParseResult {
  const trimmed = raw.trim();

  // An empty input clears the quota: PUT null-clear semantics.
  if (trimmed.length === 0) {
    return { ok: true, value: null };
  }

  if (!/^-?\d+$/.test(trimmed)) {
    return { ok: false, message: `${descriptor.label} must be a whole number.` };
  }

  const value = Number(trimmed);

  if (!Number.isInteger(value) || value < descriptor.min || value > descriptor.max) {
    return {
      ok: false,
      message: `${descriptor.label} must be between ${descriptor.min} and ${descriptor.max}.`,
    };
  }

  return { ok: true, value };
}

export function validateQuotaForm(form: TenantQuotaFormState): TenantQuotaFieldError {
  const errors: TenantQuotaFieldError = {};

  for (const descriptor of tenantQuotaFields) {
    const parsed = parseQuotaValue(form[descriptor.field], descriptor);
    if (!parsed.ok) {
      errors[descriptor.field] = parsed.message;
    }
  }

  return errors;
}

/**
 * Shape the typed quota values for the PUT request. Every key is always
 * present: a numeric value upserts, an empty input maps to `null` which the
 * API treats as a clear. This makes PUT a full replacement over the typed keys.
 */
export function buildQuotaValues(form: TenantQuotaFormState): TenantQuotaValues {
  const values: TenantQuotaValues = {};

  for (const descriptor of tenantQuotaFields) {
    const parsed = parseQuotaValue(form[descriptor.field], descriptor);
    values[descriptor.field] = parsed.ok ? parsed.value : null;
  }

  return values;
}

export function buildTenantQuotaUpdatePayload(
  form: TenantQuotaFormState,
  notes: string[] = [],
): TenantQuotaUpdateRequestPayload {
  return {
    requested_by: platformTenantOperatorActorId,
    actor_scopes: [platformTenantOperatorScope, platformTenantQuotaScope],
    quotas: buildQuotaValues(form),
    notes,
  };
}

export type TenantWriteFailure =
  | { kind: "conflict"; reason: string; message: string; requestId: string | null }
  | { kind: "notFound"; message: string; requestId: string | null }
  | {
      kind: "invalid";
      message: string;
      fieldErrors: Record<string, string>;
      requestId: string | null;
    }
  | {
      kind: "forbidden";
      message: string;
      requiredPermission?: string;
      requestId: string | null;
    }
  | { kind: "failed"; status: number; message: string; requestId: string | null };

export type TenantProvisionResult<T> =
  | { kind: "created"; record: T }
  | { kind: "replayed"; record: T }
  | TenantWriteFailure;

export type TenantUpdateResult<T> =
  | { kind: "updated"; record: T }
  | TenantWriteFailure;

const tenantWriteStatusByKind = {
  conflict: 409,
  forbidden: 403,
  invalid: 422,
  notFound: 404,
} as const;

/** Convert an HTTP write failure to the safe metadata accepted by mutation UIs. */
export function tenantWriteOperatorError(
  failure: TenantWriteFailure,
  message: string = failure.message,
): AxisOperatorError {
  return {
    code: null,
    message,
    requestId: failure.requestId,
    status: failure.kind === "failed" ? failure.status : tenantWriteStatusByKind[failure.kind],
  };
}

type TenantWriteErrorDetail = {
  code?: string;
  message?: string;
  reason?: string;
  required_permission?: string;
};

type TenantValidationIssue = {
  loc?: unknown[];
  msg?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function extractErrorDetail(
  body: unknown,
): TenantWriteErrorDetail | TenantValidationIssue[] | null {
  if (!isRecord(body) || !("detail" in body)) {
    return null;
  }

  const detail = body.detail;

  if (Array.isArray(detail)) {
    return detail as TenantValidationIssue[];
  }

  return isRecord(detail) ? (detail as TenantWriteErrorDetail) : null;
}

function mapValidationIssues(
  issues: TenantValidationIssue[],
  fieldByRequestField: Record<string, string>,
): Record<string, string> {
  const fieldErrors: Record<string, string> = {};

  for (const issue of issues) {
    const location = issue.loc ?? [];
    const requestField = location.find(
      (segment): segment is string =>
        typeof segment === "string" && segment in fieldByRequestField,
    );

    if (requestField && issue.msg) {
      fieldErrors[fieldByRequestField[requestField]] = issue.msg;
    }
  }

  return fieldErrors;
}

const provisionFieldByRequestField: Record<string, string> = {
  tenant_id: "tenantId",
  display_name: "displayName",
  description: "description",
  bootstrap_admin: "bootstrapActorId",
};

function parseTenantWriteFailure(
  response: Response,
  body: unknown,
  fieldByRequestField: Record<string, string> = {},
): TenantWriteFailure {
  const { status } = response;
  const requestId = axisResponseRequestId(response);
  const detail = extractErrorDetail(body);
  const detailObject = Array.isArray(detail) ? null : detail;
  const message = detailObject?.message ?? `Tenant request failed with ${status}.`;

  if (status === 409) {
    return {
      kind: "conflict",
      reason: detailObject?.reason ?? "conflict",
      message,
      requestId,
    };
  }

  if (status === 404) {
    return { kind: "notFound", message, requestId };
  }

  if (status === 422) {
    if (Array.isArray(detail)) {
      return {
        kind: "invalid",
        message: "The tenant request failed API validation.",
        fieldErrors: mapValidationIssues(detail, fieldByRequestField),
        requestId,
      };
    }

    return { kind: "invalid", message, fieldErrors: {}, requestId };
  }

  if (status === 403) {
    return {
      kind: "forbidden",
      message,
      requiredPermission: detailObject?.required_permission,
      requestId,
    };
  }

  return { kind: "failed", status, message, requestId };
}

async function readJsonBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function fetchTenantRegistry(
  filters: TenantRegistryFilters,
  options: AxisFetchOptions = {},
  cursor?: string | null,
): Promise<TenantRegistry> {
  const path = buildPlatformTenantsPath(filters, tenantRegistryLimit, cursor);
  const response = await axisFetch(path, options);

  if (!response.ok) {
    throw new AxisApiError(path, response.status, {
      requestId: axisResponseRequestId(response),
    });
  }

  return decodeAxisJson(
    path,
    await response.json(),
    parseTenantRegistry,
    axisResponseRequestId(response),
  );
}

export type TenantDetailResult =
  | { kind: "found"; record: TenantRecord }
  | { kind: "notFound" };

/**
 * Read a single tenant from the dedicated GET /platform/tenants/{tenant_id}
 * route. A 404 is authoritative — the tenant does not exist — so the detail
 * view no longer depends on scanning a capped registry listing, and can resolve
 * tenants regardless of how many exist.
 */
export async function fetchTenantDetail(
  tenantId: string,
  options: AxisFetchOptions = {},
): Promise<TenantDetailResult> {
  const path = buildPlatformTenantDetailPath(tenantId);
  const response = await axisFetch(path, options);

  if (response.status === 404) {
    return { kind: "notFound" };
  }

  if (!response.ok) {
    throw new AxisApiError(path, response.status, {
      requestId: axisResponseRequestId(response),
    });
  }

  return {
    kind: "found",
    record: decodeAxisJson(
      path,
      await response.json(),
      parseTenantRecord,
      axisResponseRequestId(response),
    ),
  };
}

export async function fetchTenantQuotas(
  tenantId: string,
  options: AxisFetchOptions = {},
): Promise<TenantQuotaSet | null> {
  const path = buildPlatformTenantQuotasPath(tenantId);
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
    parseTenantQuotaSet,
    axisResponseRequestId(response),
  );
}

export async function fetchTenantVocabulary(
  tenantId: string,
  options: AxisFetchOptions = {},
): Promise<TenantVocabularySet | null> {
  const path = buildPlatformTenantVocabularyPath(tenantId);
  const response = await axisFetch(path, options);

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    const body = await readJsonBody(response);
    throw new AxisApiError(path, response.status, {
      body,
      requestId: axisResponseRequestId(response),
    });
  }

  return decodeAxisJson(
    path,
    await response.json(),
    parseTenantVocabularySet,
    axisResponseRequestId(response),
  );
}

export async function provisionTenant(
  payload: TenantProvisionRequestPayload,
  options: AxisFetchOptions = {},
): Promise<TenantProvisionResult<TenantRecord>> {
  const response = await axisFetch(platformTenantsPath, {
    ...options,
    method: "POST",
    body: payload,
  });
  const body = await readJsonBody(response);

  if (response.status === 201) {
    return {
      kind: "created",
      record: decodeAxisJson(
        platformTenantsPath,
        body,
        parseTenantRecord,
        axisResponseRequestId(response),
      ),
    };
  }

  if (response.status === 200) {
    // Idempotent replay: same idempotency key + matching request.
    return {
      kind: "replayed",
      record: decodeAxisJson(
        platformTenantsPath,
        body,
        parseTenantRecord,
        axisResponseRequestId(response),
      ),
    };
  }

  return parseTenantWriteFailure(response, body, provisionFieldByRequestField);
}

export async function suspendTenant(
  tenantId: string,
  payload: TenantSuspendRequestPayload,
  options: AxisFetchOptions = {},
): Promise<TenantUpdateResult<TenantRecord>> {
  const response = await axisFetch(buildPlatformTenantSuspendPath(tenantId), {
    ...options,
    method: "POST",
    body: payload,
  });
  const body = await readJsonBody(response);

  if (response.ok) {
    return {
      kind: "updated",
      record: decodeAxisJson(
        buildPlatformTenantSuspendPath(tenantId),
        body,
        parseTenantRecord,
        axisResponseRequestId(response),
      ),
    };
  }

  return parseTenantWriteFailure(response, body);
}

export async function reactivateTenant(
  tenantId: string,
  payload: TenantReactivateRequestPayload,
  options: AxisFetchOptions = {},
): Promise<TenantUpdateResult<TenantRecord>> {
  const response = await axisFetch(buildPlatformTenantReactivatePath(tenantId), {
    ...options,
    method: "POST",
    body: payload,
  });
  const body = await readJsonBody(response);

  if (response.ok) {
    return {
      kind: "updated",
      record: decodeAxisJson(
        buildPlatformTenantReactivatePath(tenantId),
        body,
        parseTenantRecord,
        axisResponseRequestId(response),
      ),
    };
  }

  return parseTenantWriteFailure(response, body);
}

export async function updateTenantQuotas(
  tenantId: string,
  payload: TenantQuotaUpdateRequestPayload,
  options: AxisFetchOptions = {},
): Promise<TenantUpdateResult<TenantQuotaSet>> {
  const response = await axisFetch(buildPlatformTenantQuotasPath(tenantId), {
    ...options,
    method: "PUT",
    body: payload,
  });
  const body = await readJsonBody(response);

  if (response.ok) {
    return {
      kind: "updated",
      record: decodeAxisJson(
        buildPlatformTenantQuotasPath(tenantId),
        body,
        parseTenantQuotaSet,
        axisResponseRequestId(response),
      ),
    };
  }

  return parseTenantWriteFailure(response, body);
}

const vocabularyFieldByRequestField: Record<string, string> = {
  site_singular: "siteSingular",
  site_plural: "sitePlural",
  workspace_label: "workspaceLabel",
  domain_labels: "domainLabels",
};

export function buildTenantVocabularyUpdatePayload(
  vocabulary: TenantVocabulary,
  notes: string[] = [],
): TenantVocabularyUpdateRequestPayload {
  return {
    requested_by: platformTenantOperatorActorId,
    actor_scopes: [platformTenantOperatorScope, platformTenantConfigureScope],
    vocabulary,
    notes,
  };
}

export async function updateTenantVocabulary(
  tenantId: string,
  payload: TenantVocabularyUpdateRequestPayload,
  options: AxisFetchOptions = {},
): Promise<TenantUpdateResult<TenantVocabularySet>> {
  const path = buildPlatformTenantVocabularyPath(tenantId);
  const response = await axisFetch(path, {
    ...options,
    method: "PUT",
    body: payload,
  });
  const body = await readJsonBody(response);

  if (response.ok) {
    return {
      kind: "updated",
      record: decodeAxisJson(
        path,
        body,
        parseTenantVocabularySet,
        axisResponseRequestId(response),
      ),
    };
  }

  return parseTenantWriteFailure(response, body, vocabularyFieldByRequestField);
}
