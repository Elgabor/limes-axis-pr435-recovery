import { afterEach, describe, expect, it, vi } from "vitest";

import { AxisApiDecodeError } from "./axis-api";

import {
  buildPlatformPolicyRevisionsPath,
  buildPolicyConditionsPayload,
  buildPolicyCreatePayload,
  buildPolicyRevisePayload,
  comparePolicyRevisions,
  createPlatformPolicy,
  draftConditionsMatchContext,
  draftFromPolicyRecord,
  emptyPolicyDraft,
  parseActionDomains,
  parsePolicyNotes,
  parsePolicyWriteFailure,
  platformPolicyIdPattern,
  revisePlatformPolicy,
  validatePolicyDraft,
  validatePolicyId,
  type PlatformPolicyRecord,
  type PolicyDraftFormState,
} from "./platform-policies";

function buildDraft(overrides: Partial<PolicyDraftFormState> = {}): PolicyDraftFormState {
  return {
    ...emptyPolicyDraft(),
    policyId: "deny_critical_actions",
    displayName: "Deny critical actions",
    description: "Blocks critical-risk action execution.",
    conditions: {
      actionDomainsText: "",
      riskLevels: ["critical"],
      autonomyLevels: [],
      requestedAmount: "",
    },
    ...overrides,
  };
}

function buildRecord(overrides: Partial<PlatformPolicyRecord> = {}): PlatformPolicyRecord {
  return {
    tenant_id: "tenant_demo_manufacturing",
    policy_id: "deny_critical_actions",
    revision_number: 1,
    policy_version: "1.0.0",
    display_name: "Deny critical actions",
    description: "Blocks critical-risk action execution.",
    scope: "action_execution",
    effect: "deny",
    conditions: { risk_levels: ["critical"] },
    status: "active",
    notes: [],
    created_by: "platform-governance-owner-role",
    created_at: "2026-07-01T08:00:00Z",
    required_authoring_scope: "platform:policy:author",
    revises_revision_number: null,
    replaced_by_revision_number: null,
    revision_idempotency_key: null,
    idempotent_replay: false,
    audit_event_type: "platform.policy.authored",
    audit_event_id: null,
    permission_decision: { allowed: true, reason: "authoring_scope_present" },
    ...overrides,
  };
}

describe("policy id validation", () => {
  it("accepts ids matching the API pattern", () => {
    expect(validatePolicyId("deny_critical_actions")).toBeNull();
    expect(validatePolicyId("a")).toBeNull();
    expect(validatePolicyId("0-gate_2")).toBeNull();
  });

  it("rejects ids the API pattern rejects", () => {
    for (const invalid of ["", "Deny", "_leading", "-leading", "has space", "café", "UPPER"]) {
      expect(validatePolicyId(invalid), invalid).toContain("^[a-z0-9][a-z0-9_-]*$");
    }
  });

  it("rejects ids longer than the 180 character API limit", () => {
    expect(validatePolicyId("a".repeat(180))).toBeNull();
    expect(validatePolicyId("a".repeat(181))).toContain("180");
  });

  it("exports the exact HTML pattern the API enforces", () => {
    expect(platformPolicyIdPattern).toBe("^[a-z0-9][a-z0-9_-]*$");
  });
});

describe("policy draft validation", () => {
  it("passes a complete draft", () => {
    expect(validatePolicyDraft(buildDraft())).toEqual({});
  });

  it("mirrors the server required-field rules", () => {
    const errors = validatePolicyDraft(
      buildDraft({ policyId: "BAD", policyVersion: " ", displayName: "", description: "" }),
    );

    expect(errors.policyId).toBeDefined();
    expect(errors.policyVersion).toBeDefined();
    expect(errors.displayName).toBeDefined();
    expect(errors.description).toBeDefined();
  });

  it("enforces the server field length ceilings", () => {
    const errors = validatePolicyDraft(
      buildDraft({
        policyVersion: "v".repeat(81),
        displayName: "n".repeat(201),
        description: "d".repeat(601),
      }),
    );

    expect(errors.policyVersion).toBeDefined();
    expect(errors.displayName).toBeDefined();
    expect(errors.description).toBeDefined();
  });

  it("rejects empty rules the way the server does", () => {
    const errors = validatePolicyDraft(
      buildDraft({
        conditions: {
          actionDomainsText: "  , ",
          riskLevels: [],
          autonomyLevels: [],
          requestedAmount: "",
        },
      }),
    );

    expect(errors.conditions).toContain("at least one condition");
  });

  it("accepts any single condition as sufficient", () => {
    const base = {
      actionDomainsText: "",
      riskLevels: [] as string[],
      autonomyLevels: [] as string[],
      requestedAmount: "",
    };

    for (const conditions of [
      { ...base, actionDomainsText: "Operations" },
      { ...base, riskLevels: ["high"] },
      { ...base, autonomyLevels: ["L4"] },
      { ...base, requestedAmount: "0" },
    ]) {
      expect(validatePolicyDraft(buildDraft({ conditions }))).toEqual({});
    }
  });

  it("rejects malformed amounts with the shared finite non-negative rule", () => {
    for (const requestedAmount of ["-1", "NaN", "Infinity", "abc"]) {
      const errors = validatePolicyDraft(
        buildDraft({
          conditions: {
            actionDomainsText: "",
            riskLevels: [],
            autonomyLevels: [],
            requestedAmount,
          },
        }),
      );

      expect(errors.requestedAmount, requestedAmount).toBeDefined();
    }
  });

  it("skips the policy id check when revising an existing policy", () => {
    expect(
      validatePolicyDraft(buildDraft({ policyId: "" }), { requirePolicyId: false }),
    ).toEqual({});
  });
});

describe("condition and payload builders", () => {
  it("parses comma separated action domains into trimmed values", () => {
    expect(parseActionDomains(" Operations , Finance ,,")).toEqual(["Operations", "Finance"]);
    expect(parseActionDomains("")).toEqual([]);
  });

  it("parses newline separated notes", () => {
    expect(parsePolicyNotes("first note\n\n  second note  \r\n")).toEqual([
      "first note",
      "second note",
    ]);
  });

  it("omits unset condition fields so the API payload stays minimal", () => {
    expect(
      buildPolicyConditionsPayload({
        actionDomainsText: "",
        riskLevels: [],
        autonomyLevels: [],
        requestedAmount: "",
      }),
    ).toEqual({});

    expect(
      buildPolicyConditionsPayload({
        actionDomainsText: "Operations",
        riskLevels: ["high", "critical"],
        autonomyLevels: ["L3"],
        requestedAmount: "10000",
      }),
    ).toEqual({
      action_domains: ["Operations"],
      risk_levels: ["high", "critical"],
      autonomy_levels: ["L3"],
      requested_amount_at_least: 10000,
    });
  });

  it("builds the exact create request the API schema requires", () => {
    const draft = buildDraft({ notesText: "reviewed with governance\n" });

    expect(buildPolicyCreatePayload("tenant_demo_manufacturing", draft)).toEqual({
      tenant_id: "tenant_demo_manufacturing",
      policy_id: "deny_critical_actions",
      policy_version: "1.0.0",
      display_name: "Deny critical actions",
      description: "Blocks critical-risk action execution.",
      scope: "action_execution",
      effect: "require_approval",
      conditions: { risk_levels: ["critical"] },
      created_by: "platform-governance-owner-role",
      actor_scopes: ["platform:policy:author"],
      notes: ["reviewed with governance"],
    });
  });

  it("builds the exact revise request including the idempotency key", () => {
    const draft = buildDraft({ policyVersion: "1.1.0", effect: "deny" });

    expect(
      buildPolicyRevisePayload(
        "tenant_demo_manufacturing",
        "deny_critical_actions",
        draft,
        "idem-key-1",
      ),
    ).toEqual({
      tenant_id: "tenant_demo_manufacturing",
      policy_id: "deny_critical_actions",
      policy_version: "1.1.0",
      display_name: "Deny critical actions",
      description: "Blocks critical-risk action execution.",
      effect: "deny",
      conditions: { risk_levels: ["critical"] },
      updated_by: "platform-governance-owner-role",
      actor_scopes: ["platform:policy:revise"],
      idempotency_key: "idem-key-1",
      notes: [],
    });
  });

  it("round-trips a record into a pre-filled revision draft", () => {
    const record = buildRecord({
      conditions: {
        action_domains: ["Operations"],
        risk_levels: ["high"],
        autonomy_levels: ["L2", "L3"],
        requested_amount_at_least: 2500,
      },
      notes: ["first", "second"],
    });
    const draft = draftFromPolicyRecord(record);

    expect(draft).toEqual({
      policyId: "deny_critical_actions",
      policyVersion: "1.0.0",
      displayName: "Deny critical actions",
      description: "Blocks critical-risk action execution.",
      scope: "action_execution",
      effect: "deny",
      conditions: {
        actionDomainsText: "Operations",
        riskLevels: ["high"],
        autonomyLevels: ["L2", "L3"],
        requestedAmount: "2500",
      },
      notesText: "first\nsecond",
    });
    expect(buildPolicyConditionsPayload(draft.conditions)).toEqual(record.conditions);
  });
});

describe("advisory draft condition matcher", () => {
  it("matches when every declared condition is satisfied", () => {
    const conditions = {
      action_domains: ["Operations"],
      risk_levels: ["high", "critical"],
      requested_amount_at_least: 1000,
    };

    expect(
      draftConditionsMatchContext(conditions, {
        action_domain: "Operations",
        risk_level: "critical",
        requested_amount: 1000,
      }),
    ).toBe(true);
    expect(
      draftConditionsMatchContext(conditions, {
        action_domain: "Operations",
        risk_level: "critical",
        requested_amount: 999,
      }),
    ).toBe(false);
    expect(
      draftConditionsMatchContext(conditions, {
        risk_level: "critical",
        requested_amount: 1000,
      }),
    ).toBe(false);
  });

  it("treats empty condition lists as matching any value", () => {
    expect(draftConditionsMatchContext({ autonomy_levels: ["L4"] }, { autonomy_level: "L4" })).toBe(
      true,
    );
    expect(draftConditionsMatchContext({ autonomy_levels: ["L4"] }, {})).toBe(false);
    expect(draftConditionsMatchContext({ risk_levels: ["low"] }, { risk_level: "low" })).toBe(true);
  });
});

describe("revision compare", () => {
  it("detects changed scalars and added/removed list items", () => {
    const base = buildRecord({
      conditions: { risk_levels: ["high", "critical"], action_domains: ["Operations"] },
      effect: "require_approval",
      notes: ["old note"],
    });
    const target = buildRecord({
      revision_number: 2,
      policy_version: "1.1.0",
      effect: "deny",
      conditions: {
        risk_levels: ["critical", "medium"],
        requested_amount_at_least: 500,
      },
      notes: [],
    });

    const diffs = comparePolicyRevisions(base, target);
    const byLabel = Object.fromEntries(diffs.map((diff) => [diff.label, diff]));

    expect(byLabel["Display name"]).toMatchObject({ kind: "scalar", changed: false });
    expect(byLabel["Policy version"]).toMatchObject({
      kind: "scalar",
      changed: true,
      base: "1.0.0",
      target: "1.1.0",
    });
    expect(byLabel["Effect"]).toMatchObject({
      changed: true,
      base: "Require approval",
      target: "Deny",
    });
    expect(byLabel["Risk levels"]).toMatchObject({
      kind: "list",
      changed: true,
      added: ["medium"],
      removed: ["high"],
      unchanged: ["critical"],
    });
    expect(byLabel["Action domains"]).toMatchObject({
      changed: true,
      added: [],
      removed: ["Operations"],
    });
    expect(byLabel["Amount threshold"]).toMatchObject({
      changed: true,
      base: "No amount gate",
      target: ">= 500",
    });
    expect(byLabel["Notes"]).toMatchObject({ changed: true, removed: ["old note"] });
  });

  it("reports identical revisions as fully unchanged", () => {
    const record = buildRecord();

    expect(
      comparePolicyRevisions(record, buildRecord({ revision_number: 2 })).every(
        (diff) => !diff.changed,
      ),
    ).toBe(true);
  });
});

describe("write failure mapping", () => {
  it("maps 409 conflicts with the API reason", () => {
    expect(
      parsePolicyWriteFailure(409, {
        detail: {
          code: "POLICY_VIOLATION",
          message: "The platform policy already exists.",
          reason: "policy_already_exists",
        },
      }, "request-policy-conflict"),
    ).toEqual({
      kind: "conflict",
      reason: "policy_already_exists",
      message: "The platform policy already exists.",
      requestId: "request-policy-conflict",
    });
  });

  it("maps rule-condition 422s onto the conditions field", () => {
    const result = parsePolicyWriteFailure(422, {
      detail: {
        code: "VALIDATION_FAILED",
        message: "Platform policy rule conditions are malformed.",
        reason: "invalid_rule_conditions",
      },
    });

    expect(result).toEqual({
      kind: "invalid",
      message: "Platform policy rule conditions are malformed.",
      fieldErrors: { conditions: "Platform policy rule conditions are malformed." },
    });
  });

  it("maps schema-level 422 issue arrays onto known request fields", () => {
    const result = parsePolicyWriteFailure(422, {
      detail: [
        { loc: ["body", "policy_id"], msg: "String should match pattern" },
        { loc: ["body", "display_name"], msg: "String should have at least 1 character" },
        { loc: ["body", "unknown_field"], msg: "ignored" },
      ],
    });

    expect(result).toMatchObject({
      kind: "invalid",
      fieldErrors: {
        policyId: "String should match pattern",
        displayName: "String should have at least 1 character",
      },
    });
  });

  it("maps 403 onto a forbidden result with the required permission", () => {
    expect(
      parsePolicyWriteFailure(403, {
        detail: {
          code: "PERMISSION_DENIED",
          message: "The actor cannot author platform policies.",
          required_permission: "platform:policy:author",
          reason: "missing_required_scope",
        },
      }),
    ).toEqual({
      kind: "forbidden",
      message: "The actor cannot author platform policies.",
      requiredPermission: "platform:policy:author",
    });
  });

  it("falls back to a generic failure for other statuses and bodies", () => {
    expect(parsePolicyWriteFailure(503, null)).toEqual({
      kind: "failed",
      status: 503,
      message: "Policy write failed with 503.",
    });
    expect(parsePolicyWriteFailure(404, { detail: { message: "Not found." } })).toEqual({
      kind: "failed",
      status: 404,
      message: "Not found.",
    });
  });
});

describe("policy write bindings", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_AXIS_API_BASE_URL;
  });

  function stubFetch(status: number, body: unknown, requestId?: string) {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify(body), {
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

  it("posts the create payload and returns the created record on 201", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const record = buildRecord();
    const fetchMock = stubFetch(201, record);
    const payload = buildPolicyCreatePayload("tenant_demo_manufacturing", buildDraft());

    await expect(createPlatformPolicy(payload)).resolves.toEqual({
      kind: "created",
      record,
    });

    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    const headers = new Headers(init?.headers);

    expect(url).toBe("http://axis-api.test/platform/policies");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual(payload);
  });

  it("rejects a malformed successful policy create response", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(201, { tenant_id: "tenant_demo_manufacturing", policy_id: 42 });

    await expect(
      createPlatformPolicy(buildPolicyCreatePayload("tenant_demo_manufacturing", buildDraft())),
    ).rejects.toBeInstanceOf(AxisApiDecodeError);
  });

  it("returns a conflict result for a 409 duplicate policy", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(409, {
      detail: {
        code: "POLICY_VIOLATION",
        message: "The platform policy already exists.",
        reason: "policy_already_exists",
      },
    }, "request-policy-create-409");

    await expect(
      createPlatformPolicy(buildPolicyCreatePayload("tenant_demo_manufacturing", buildDraft())),
    ).resolves.toMatchObject({
      kind: "conflict",
      reason: "policy_already_exists",
      requestId: "request-policy-create-409",
    });
  });

  it("encodes the policy id into the revisions path", () => {
    expect(buildPlatformPolicyRevisionsPath("deny_critical_actions")).toBe(
      "/platform/policies/deny_critical_actions/revisions",
    );
    expect(buildPlatformPolicyRevisionsPath("weird/../id")).toBe(
      "/platform/policies/weird%2F..%2Fid/revisions",
    );
  });

  it("returns created for a 201 revision append", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const record = buildRecord({ revision_number: 2, policy_version: "1.1.0" });
    const fetchMock = stubFetch(201, record);
    const payload = buildPolicyRevisePayload(
      "tenant_demo_manufacturing",
      "deny_critical_actions",
      buildDraft({ policyVersion: "1.1.0" }),
      "idem-key-1",
    );

    await expect(revisePlatformPolicy("deny_critical_actions", payload)).resolves.toEqual({
      kind: "created",
      record,
    });

    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(url).toBe("http://axis-api.test/platform/policies/deny_critical_actions/revisions");
    expect(JSON.parse(String(init?.body)).idempotency_key).toBe("idem-key-1");
  });

  it("returns replayed for a 200 idempotent revision replay", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const record = buildRecord({
      revision_number: 2,
      idempotent_replay: true,
      revision_idempotency_key: "idem-key-1",
    });
    stubFetch(200, record);

    await expect(
      revisePlatformPolicy(
        "deny_critical_actions",
        buildPolicyRevisePayload(
          "tenant_demo_manufacturing",
          "deny_critical_actions",
          buildDraft(),
          "idem-key-1",
        ),
      ),
    ).resolves.toEqual({ kind: "replayed", record });
  });

  it("rejects a malformed successful revision replay response", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(200, { tenant_id: "tenant_demo_manufacturing", revisions: [] });

    await expect(
      revisePlatformPolicy(
        "deny_critical_actions",
        buildPolicyRevisePayload(
          "tenant_demo_manufacturing",
          "deny_critical_actions",
          buildDraft(),
          "idem-key-1",
        ),
      ),
    ).rejects.toBeInstanceOf(AxisApiDecodeError);
  });

  it("returns a conflict result for a 409 idempotency key reuse", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(409, {
      detail: {
        code: "POLICY_VIOLATION",
        message: "The revision idempotency key already exists with a different payload.",
        reason: "revision_idempotency_conflict",
      },
    });

    await expect(
      revisePlatformPolicy(
        "deny_critical_actions",
        buildPolicyRevisePayload(
          "tenant_demo_manufacturing",
          "deny_critical_actions",
          buildDraft(),
          "idem-key-1",
        ),
      ),
    ).resolves.toMatchObject({ kind: "conflict", reason: "revision_idempotency_conflict" });
  });

  it("returns an invalid result with field errors for a 422 rejection", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(422, {
      detail: {
        code: "VALIDATION_FAILED",
        message: "Platform policy rule conditions are malformed.",
        reason: "invalid_rule_conditions",
      },
    });

    await expect(
      createPlatformPolicy(buildPolicyCreatePayload("tenant_demo_manufacturing", buildDraft())),
    ).resolves.toMatchObject({
      kind: "invalid",
      fieldErrors: { conditions: "Platform policy rule conditions are malformed." },
    });
  });

  it("returns a forbidden result for a 403 permission denial", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(403, {
      detail: {
        code: "PERMISSION_DENIED",
        message: "The actor cannot revise platform policies.",
        required_permission: "platform:policy:revise",
        reason: "missing_required_scope",
      },
    });

    await expect(
      revisePlatformPolicy(
        "deny_critical_actions",
        buildPolicyRevisePayload(
          "tenant_demo_manufacturing",
          "deny_critical_actions",
          buildDraft(),
          "idem-key-1",
        ),
      ),
    ).resolves.toEqual({
      kind: "forbidden",
      message: "The actor cannot revise platform policies.",
      requiredPermission: "platform:policy:revise",
    });
  });
});
