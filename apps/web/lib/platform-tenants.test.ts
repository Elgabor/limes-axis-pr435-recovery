import { afterEach, describe, expect, it, vi } from "vitest";

import { AxisApiDecodeError } from "./axis-api";
import {
  allTenantFilter,
  buildPlatformTenantDetailPath,
  buildPlatformTenantQuotasPath,
  buildPlatformTenantVocabularyPath,
  buildPlatformTenantsPath,
  buildQuotaValues,
  buildTenantProvisionPayload,
  buildTenantQuotaUpdatePayload,
  buildTenantSuspendPayload,
  buildTenantVocabularyUpdatePayload,
  emptyTenantProvisionForm,
  fetchTenantDetail,
  fetchTenantQuotas,
  fetchTenantRegistry,
  fetchTenantVocabulary,
  mergeTenantRegistryPage,
  parseQuotaValue,
  platformTenantOperatorActorId,
  platformTenantsPath,
  provisionTenant,
  quotaFormFromQuotaSet,
  reactivateTenant,
  suspendTenant,
  tenantQuotaFields,
  tenantStatusClass,
  tenantStatusLabel,
  updateTenantQuotas,
  updateTenantVocabulary,
  validateQuotaForm,
  validateTenantId,
  validateTenantProvisionForm,
  type TenantProvisionFormState,
  type TenantQuotaFormState,
  type TenantRecord,
} from "./platform-tenants";

function buildRecord(overrides: Partial<TenantRecord> = {}): TenantRecord {
  return {
    tenant_id: "tenant_acme",
    display_name: "Acme",
    description: "",
    status: "active",
    created_by: "platform-tenant-operator-role",
    bootstrap_admin_actor_id: null,
    provision_idempotency_key: "idem-key-1",
    suspended_at: null,
    suspended_by: null,
    suspension_reason: null,
    reactivated_at: null,
    reactivated_by: null,
    permission_decision: { allowed: true, reason: "operator_scope_present" },
    audit_event_id: "11111111-1111-4111-8111-111111111111",
    audit_event_type: "platform.tenant.provisioned",
    idempotent_replay: false,
    notes: [],
    created_at: "2026-07-01T08:00:00Z",
    updated_at: "2026-07-01T08:00:00Z",
    ...overrides,
  };
}

function buildProvisionForm(
  overrides: Partial<TenantProvisionFormState> = {},
): TenantProvisionFormState {
  return { ...emptyTenantProvisionForm(), tenantId: "tenant_acme", displayName: "Acme", ...overrides };
}

function buildQuotaForm(overrides: Partial<TenantQuotaFormState> = {}): TenantQuotaFormState {
  return {
    api_requests_per_window: "",
    max_concurrent_sessions: "",
    max_connector_sync_rows_per_run: "",
    ...overrides,
  };
}

describe("tenant path builders", () => {
  it("always requests the server maximum limit for the all filter", () => {
    expect(buildPlatformTenantsPath({ status: allTenantFilter })).toBe(
      `${platformTenantsPath}?limit=200`,
    );
  });

  it("encodes the status filter alongside the limit", () => {
    expect(buildPlatformTenantsPath({ status: "suspended" })).toBe(
      "/platform/tenants?status=suspended&limit=200",
    );
  });

  it("encodes tenant ids in detail and quota paths", () => {
    expect(buildPlatformTenantDetailPath("weird/../id")).toBe(
      "/platform/tenants/weird%2F..%2Fid",
    );
    expect(buildPlatformTenantQuotasPath("tenant_acme")).toBe(
      "/platform/tenants/tenant_acme/quotas",
    );
    expect(buildPlatformTenantVocabularyPath("weird/../id")).toBe(
      "/platform/tenants/weird%2F..%2Fid/vocabulary",
    );
  });
});

describe("tenant status presentation", () => {
  it("labels and classes each lifecycle status", () => {
    expect(tenantStatusLabel("active")).toBe("Active");
    expect(tenantStatusLabel("suspended")).toBe("Suspended");
    expect(tenantStatusLabel("pending_deletion")).toBe("Pending deletion");
    expect(tenantStatusClass("active")).toBe("signal-ready");
    expect(tenantStatusClass("suspended")).toBe("signal-action-required");
    expect(tenantStatusClass("pending_deletion")).toBe("signal-watch");
  });
});

describe("tenant id validation", () => {
  it("accepts ids matching the server pattern", () => {
    expect(validateTenantId("tenant_acme-1")).toBeNull();
    expect(validateTenantId("0abc")).toBeNull();
  });

  it("rejects ids that break the pattern", () => {
    expect(validateTenantId("Bad Tenant")).toContain("must match");
    expect(validateTenantId("-leading")).toContain("must match");
    expect(validateTenantId("UPPER")).toContain("must match");
  });

  it("rejects ids over the length bound", () => {
    expect(validateTenantId("a".repeat(81))).toContain("at most");
  });
});

describe("provision form validation and payload", () => {
  it("passes a minimal valid form", () => {
    expect(validateTenantProvisionForm(buildProvisionForm())).toEqual({});
  });

  it("flags a bad tenant id and empty display name", () => {
    const errors = validateTenantProvisionForm(
      buildProvisionForm({ tenantId: "Bad Id", displayName: "" }),
    );
    expect(errors.tenantId).toContain("must match");
    expect(errors.displayName).toContain("1-200");
  });

  it("requires bootstrap fields only when bootstrap is enabled", () => {
    const withoutBootstrap = validateTenantProvisionForm(
      buildProvisionForm({ bootstrapEnabled: false }),
    );
    expect(withoutBootstrap.bootstrapActorId).toBeUndefined();

    const withBootstrap = validateTenantProvisionForm(
      buildProvisionForm({ bootstrapEnabled: true }),
    );
    expect(withBootstrap.bootstrapActorId).toContain("1-120");
    expect(withBootstrap.bootstrapDisplayName).toContain("1-200");
  });

  it("shapes the provision payload with the operator actor and scopes", () => {
    const payload = buildTenantProvisionPayload(
      buildProvisionForm({
        description: " desc ",
        notesText: "line one\n\n line two ",
      }),
      "idem-key-1",
    );

    expect(payload).toEqual({
      tenant_id: "tenant_acme",
      display_name: "Acme",
      description: "desc",
      requested_by: platformTenantOperatorActorId,
      actor_scopes: ["platform:tenant:operator", "platform:tenant:provision"],
      idempotency_key: "idem-key-1",
      notes: ["line one", "line two"],
    });
    expect(payload.bootstrap_admin).toBeUndefined();
  });

  it("includes a bootstrap admin block with parsed scopes", () => {
    const payload = buildTenantProvisionPayload(
      buildProvisionForm({
        bootstrapEnabled: true,
        bootstrapActorId: " acme-admin ",
        bootstrapDisplayName: " Acme Admin ",
        bootstrapScopesText: "platform:tenant:read, audit:read\nidentity:sessions:admin",
      }),
      "idem-key-2",
    );

    expect(payload.bootstrap_admin).toEqual({
      actor_id: "acme-admin",
      display_name: "Acme Admin",
      scopes: ["platform:tenant:read", "audit:read", "identity:sessions:admin"],
    });
  });
});

describe("suspend payload", () => {
  it("shapes the suspend payload with the suspend scope", () => {
    expect(buildTenantSuspendPayload(" abuse detected ")).toEqual({
      requested_by: platformTenantOperatorActorId,
      actor_scopes: ["platform:tenant:operator", "platform:tenant:suspend"],
      reason: "abuse detected",
      notes: [],
    });
  });
});

describe("quota parsing and shaping", () => {
  const apiField = tenantQuotaFields[0];
  const sessionsField = tenantQuotaFields[1];

  it("treats an empty input as a clear (null)", () => {
    expect(parseQuotaValue("", apiField)).toEqual({ ok: true, value: null });
    expect(parseQuotaValue("   ", apiField)).toEqual({ ok: true, value: null });
  });

  it("parses an in-bounds integer", () => {
    expect(parseQuotaValue("500", apiField)).toEqual({ ok: true, value: 500 });
  });

  it("allows zero only where the server bound permits it", () => {
    expect(parseQuotaValue("0", sessionsField)).toEqual({ ok: true, value: 0 });
    expect(parseQuotaValue("0", apiField)).toMatchObject({ ok: false });
  });

  it("rejects non-integers and out-of-range values", () => {
    expect(parseQuotaValue("12.5", apiField)).toMatchObject({ ok: false });
    expect(parseQuotaValue("abc", apiField)).toMatchObject({ ok: false });
    expect(parseQuotaValue("2000000", apiField)).toMatchObject({ ok: false });
  });

  it("hydrates the form from a quota set and back to a null-clearing payload", () => {
    const form = quotaFormFromQuotaSet({
      tenant_id: "tenant_acme",
      quotas: { api_requests_per_window: 1000, max_concurrent_sessions: 5 },
    });
    expect(form).toEqual({
      api_requests_per_window: "1000",
      max_concurrent_sessions: "5",
      max_connector_sync_rows_per_run: "",
    });

    // Every typed key is present; a blank field becomes an explicit null clear.
    expect(buildQuotaValues(form)).toEqual({
      api_requests_per_window: 1000,
      max_concurrent_sessions: 5,
      max_connector_sync_rows_per_run: null,
    });
  });

  it("validates the whole quota form", () => {
    expect(validateQuotaForm(buildQuotaForm({ api_requests_per_window: "10" }))).toEqual({});
    const errors = validateQuotaForm(buildQuotaForm({ api_requests_per_window: "-1" }));
    expect(errors.api_requests_per_window).toBeDefined();
  });

  it("shapes the full quota update payload", () => {
    const payload = buildTenantQuotaUpdatePayload(
      buildQuotaForm({ api_requests_per_window: "1000" }),
    );
    expect(payload).toEqual({
      requested_by: platformTenantOperatorActorId,
      actor_scopes: ["platform:tenant:operator", "platform:tenant:quota"],
      quotas: {
        api_requests_per_window: 1000,
        max_concurrent_sessions: null,
        max_connector_sync_rows_per_run: null,
      },
      notes: [],
    });
  });
});

describe("tenant API bindings", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_AXIS_API_BASE_URL;
  });

  function stubFetch(status: number, body: unknown, requestId?: string) {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(body === null ? null : JSON.stringify(body), {
        headers: {
          "Content-Type": "application/json",
          ...(requestId ? { "x-request-id": requestId } : {}),
        },
        status,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("posts the provision payload and returns created on 201", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const record = buildRecord();
    const fetchMock = stubFetch(201, record);
    const payload = buildTenantProvisionPayload(buildProvisionForm(), "idem-key-1");

    await expect(provisionTenant(payload)).resolves.toEqual({ kind: "created", record });

    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(url).toBe("http://axis-api.test/platform/tenants");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(JSON.parse(String(init?.body))).toEqual(payload);
  });

  it("returns replayed on an idempotent 200", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const record = buildRecord({ idempotent_replay: true });
    stubFetch(200, record);

    await expect(
      provisionTenant(buildTenantProvisionPayload(buildProvisionForm(), "idem-key-1")),
    ).resolves.toEqual({ kind: "replayed", record });
  });

  it("rejects a malformed successful provision response", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(201, { tenant_id: "tenant_acme", status: "active" });

    await expect(
      provisionTenant(buildTenantProvisionPayload(buildProvisionForm(), "idem-key-1")),
    ).rejects.toBeInstanceOf(AxisApiDecodeError);
  });

  it("returns a conflict result for a 409 duplicate tenant", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(409, {
      detail: {
        code: "CONFLICT",
        message: "The tenant provisioning request conflicts with persisted state.",
        reason: "tenant_already_exists",
      },
    });

    await expect(
      provisionTenant(buildTenantProvisionPayload(buildProvisionForm(), "idem-key-1")),
    ).resolves.toMatchObject({ kind: "conflict", reason: "tenant_already_exists" });
  });

  it("maps 422 validation issues to form fields", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(422, {
      detail: [{ loc: ["body", "tenant_id"], msg: "string does not match pattern" }],
    });

    const result = await provisionTenant(
      buildTenantProvisionPayload(buildProvisionForm(), "idem-key-1"),
    );
    expect(result).toMatchObject({ kind: "invalid" });
    if (result.kind === "invalid") {
      expect(result.fieldErrors.tenantId).toBe("string does not match pattern");
    }
  });

  it("returns forbidden with the required permission on 403", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(403, {
      detail: {
        code: "PERMISSION_DENIED",
        message: "The actor cannot provision tenants.",
        required_permission: "platform:tenant:provision",
      },
    }, "req-tenant-provision-403");

    await expect(
      provisionTenant(buildTenantProvisionPayload(buildProvisionForm(), "idem-key-1")),
    ).resolves.toMatchObject({
      kind: "forbidden",
      requiredPermission: "platform:tenant:provision",
      requestId: "req-tenant-provision-403",
    });
  });

  it("retains correlation metadata without carrying arbitrary response fields", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(
      503,
      { debug: "internal-token-must-not-enter-ui-state" },
      "req-tenant-provision-503",
    );

    const result = await provisionTenant(
      buildTenantProvisionPayload(buildProvisionForm(), "idem-key-1"),
    );

    expect(result).toEqual({
      kind: "failed",
      status: 503,
      message: "Tenant request failed with 503.",
      requestId: "req-tenant-provision-503",
    });
    expect(JSON.stringify(result)).not.toContain("internal-token-must-not-enter-ui-state");
  });

  it("posts a suspend request and returns updated", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const record = buildRecord({ status: "suspended", suspended_by: "operator" });
    const fetchMock = stubFetch(200, record);

    await expect(
      suspendTenant("tenant_acme", buildTenantSuspendPayload("abuse")),
    ).resolves.toEqual({ kind: "updated", record });

    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(url).toBe("http://axis-api.test/platform/tenants/tenant_acme/suspend");
    expect(init?.method).toBe("POST");
  });

  it("surfaces a lifecycle conflict from suspend", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(409, {
      detail: { code: "CONFLICT", message: "Not active.", reason: "tenant_not_active" },
    });

    await expect(
      suspendTenant("tenant_acme", buildTenantSuspendPayload("abuse")),
    ).resolves.toMatchObject({ kind: "conflict", reason: "tenant_not_active" });
  });

  it("reactivates a tenant", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const record = buildRecord({ status: "active", reactivated_by: "operator" });
    const fetchMock = stubFetch(200, record);

    await expect(
      reactivateTenant("tenant_acme", buildTenantSuspendPayload("")),
    ).resolves.toEqual({ kind: "updated", record });
    const [url] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(url).toBe("http://axis-api.test/platform/tenants/tenant_acme/reactivate");
  });

  it("gets a quota set and PUTs an update with the null-clearing payload", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const quotaSet = {
      tenant_id: "tenant_acme",
      quotas: { api_requests_per_window: 1000 },
      quota_notes: ["note"],
    };
    const getMock = stubFetch(200, quotaSet);
    await expect(fetchTenantQuotas("tenant_acme")).resolves.toEqual(quotaSet);
    expect((getMock.mock.calls[0] as [RequestInfo | URL])[0]).toBe(
      "http://axis-api.test/platform/tenants/tenant_acme/quotas",
    );

    const putMock = stubFetch(200, { ...quotaSet, changes: [] });
    const payload = buildTenantQuotaUpdatePayload(
      buildQuotaForm({ api_requests_per_window: "2000" }),
    );
    await expect(updateTenantQuotas("tenant_acme", payload)).resolves.toMatchObject({
      kind: "updated",
    });
    const [, putInit] = putMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(putInit?.method).toBe("PUT");
    expect(JSON.parse(String(putInit?.body)).quotas).toEqual({
      api_requests_per_window: 2000,
      max_concurrent_sessions: null,
      max_connector_sync_rows_per_run: null,
    });
  });

  it("gets and updates the vocabulary with the configure scope", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const vocabularySet = {
      tenant_id: "tenant_acme",
      vocabulary: {
        site_singular: "Store",
        site_plural: "Stores",
        workspace_label: "Pharmacy",
        domain_labels: { supply: "Pharmacy supply" },
      },
      configured: true,
      changes: [],
      vocabulary_notes: [],
    };
    const getMock = stubFetch(200, vocabularySet);

    await expect(fetchTenantVocabulary("tenant_acme")).resolves.toEqual(vocabularySet);
    expect((getMock.mock.calls[0] as [RequestInfo | URL])[0]).toBe(
      "http://axis-api.test/platform/tenants/tenant_acme/vocabulary",
    );

    const payload = buildTenantVocabularyUpdatePayload(vocabularySet.vocabulary);
    expect(payload.actor_scopes).toEqual([
      "platform:tenant:operator",
      "platform:tenant:configure",
    ]);

    const putMock = stubFetch(200, vocabularySet);
    await expect(updateTenantVocabulary("tenant_acme", payload)).resolves.toMatchObject({
      kind: "updated",
      record: vocabularySet,
    });
    const [, putInit] = putMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(putInit?.method).toBe("PUT");
    expect(JSON.parse(String(putInit?.body)).vocabulary.domain_labels).toEqual({
      supply: "Pharmacy supply",
    });
  });

  it("surfaces vocabulary validation details from the server", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(422, {
      detail: [
        {
          loc: ["body", "vocabulary", "domain_labels"],
          msg: "Must contain at most 50 entries.",
        },
      ],
    }, "req-tenant-vocabulary-422");

    const result = await updateTenantVocabulary(
      "tenant_acme",
      buildTenantVocabularyUpdatePayload({
        site_singular: "Site",
        site_plural: "Sites",
        workspace_label: "Operations",
        domain_labels: {},
      }),
    );

    expect(result).toEqual({
      kind: "invalid",
      message: "The tenant request failed API validation.",
      fieldErrors: { domainLabels: "Must contain at most 50 entries." },
      requestId: "req-tenant-vocabulary-422",
    });
  });

  it("rejects a malformed successful quota update response", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(200, { quotas: { api_requests_per_window: "many" } });

    await expect(
      updateTenantQuotas(
        "tenant_acme",
        buildTenantQuotaUpdatePayload(buildQuotaForm({ api_requests_per_window: "2000" })),
      ),
    ).rejects.toBeInstanceOf(AxisApiDecodeError);
  });

  it("returns null for a 404 quota lookup", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(404, { detail: { message: "not found" } });
    await expect(fetchTenantQuotas("missing")).resolves.toBeNull();
  });

  it("retains the request id for a failed quota lookup", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(503, {}, "request-tenant-quotas-503");
    await expect(fetchTenantQuotas("tenant_acme")).rejects.toMatchObject({
      requestId: "request-tenant-quotas-503",
      status: 503,
    });
  });

  it("throws AxisApiError for a failed detail read", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(503, {}, "request-tenant-detail-503");
    await expect(fetchTenantDetail("tenant_acme")).rejects.toMatchObject({
      requestId: "request-tenant-detail-503",
      status: 503,
    });
  });

  it("reads the detail record from the dedicated single-tenant route", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const record = buildRecord();
    const fetchMock = stubFetch(200, record);
    await expect(fetchTenantDetail("tenant_acme")).resolves.toEqual({
      kind: "found",
      record,
    });
    // Resolved via GET /platform/tenants/{id}, not by scanning the list.
    expect((fetchMock.mock.calls[0] as [RequestInfo | URL])[0]).toBe(
      "http://axis-api.test/platform/tenants/tenant_acme",
    );
  });

  it("treats a 404 from the detail route as an authoritative not-found", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(404, { detail: { message: "not found" } });
    await expect(fetchTenantDetail("missing")).resolves.toEqual({
      kind: "notFound",
    });
  });

  it("requests a full page and forwards the cursor when fetching the registry", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const record = buildRecord();
    const fetchMock = stubFetch(200, {
      tenant_count: 1,
      active_tenant_count: 1,
      tenants: [record],
      has_more: true,
      next_cursor: "cursor-2",
    });

    await expect(
      fetchTenantRegistry({ status: allTenantFilter }, {}, "cursor-1"),
    ).resolves.toMatchObject({ has_more: true, next_cursor: "cursor-2" });

    expect((fetchMock.mock.calls[0] as [RequestInfo | URL])[0]).toBe(
      "http://axis-api.test/platform/tenants?limit=200&cursor=cursor-1",
    );
  });

  it("throws AxisApiError for a failed registry read", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(503, {}, "request-tenant-registry-503");
    await expect(
      fetchTenantRegistry({ status: allTenantFilter }),
    ).rejects.toMatchObject({
      requestId: "request-tenant-registry-503",
      status: 503,
    });
  });
});

describe("registry page merging", () => {
  it("appends a fetched page and recomputes counts over the merged list", () => {
    const first = {
      tenant_count: 1,
      active_tenant_count: 1,
      tenants: [buildRecord({ tenant_id: "tenant_a", status: "active" as const })],
      has_more: true,
      next_cursor: "cursor-1",
      tenant_notes: ["first page note"],
    };
    const second = {
      tenant_count: 1,
      active_tenant_count: 0,
      tenants: [buildRecord({ tenant_id: "tenant_b", status: "suspended" as const })],
      has_more: false,
      next_cursor: null,
    };

    const merged = mergeTenantRegistryPage(first, second);

    expect(merged.tenants?.map((tenant) => tenant.tenant_id)).toEqual([
      "tenant_a",
      "tenant_b",
    ]);
    expect(merged.tenant_count).toBe(2);
    // Only tenant_a is active across the merged list.
    expect(merged.active_tenant_count).toBe(1);
    // has_more / next_cursor track the most recently fetched page.
    expect(merged.has_more).toBe(false);
    expect(merged.next_cursor).toBeNull();
    // Notes from the first page are retained when a later page omits them.
    expect(merged.tenant_notes).toEqual(["first page note"]);
  });

  it("seeds the accumulator from a null existing registry", () => {
    const page = {
      tenant_count: 1,
      active_tenant_count: 1,
      tenants: [buildRecord({ tenant_id: "tenant_a" })],
      has_more: true,
      next_cursor: "cursor-1",
    };

    const merged = mergeTenantRegistryPage(null, page);

    expect(merged.tenants?.map((tenant) => tenant.tenant_id)).toEqual(["tenant_a"]);
    expect(merged.tenant_count).toBe(1);
    expect(merged.has_more).toBe(true);
    expect(merged.next_cursor).toBe("cursor-1");
  });
});
