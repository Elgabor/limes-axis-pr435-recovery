import { afterEach, describe, expect, it, vi } from "vitest";

import { AxisApiError } from "./axis-api";
import {
  allPolicyFilter,
  buildPlatformPoliciesPath,
  buildPlatformPolicyDetailPath,
  buildPolicyEvaluationPayload,
  countPoliciesByEffect,
  evaluatePlatformPolicy,
  fetchPlatformPolicyDetail,
  parseRequestedAmount,
  policyEffectClass,
  policyEffectLabel,
  policyScopeLabel,
  policyStatusClass,
  policyStatusLabel,
  summarizePolicyConditions,
  type PlatformPolicyDecision,
  type PlatformPolicyDetail,
  type PlatformPolicyRecord,
  type PlatformPolicyRuleConditions,
} from "./platform-policies";

function buildConditions(
  overrides: Partial<PlatformPolicyRuleConditions> = {},
): PlatformPolicyRuleConditions {
  return {
    action_domains: [],
    risk_levels: [],
    autonomy_levels: [],
    requested_amount_at_least: null,
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
    conditions: buildConditions({ risk_levels: ["critical"] }),
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

describe("platform policy path builders", () => {
  it("returns the bare registry path when no filters are applied", () => {
    expect(
      buildPlatformPoliciesPath({ scope: allPolicyFilter, status: allPolicyFilter }),
    ).toBe("/platform/policies");
  });

  it("encodes scope and status filters as query parameters", () => {
    expect(buildPlatformPoliciesPath({ scope: "action_execution", status: allPolicyFilter })).toBe(
      "/platform/policies?scope=action_execution",
    );
    expect(
      buildPlatformPoliciesPath({ scope: "approval_requirement", status: "superseded" }),
    ).toBe("/platform/policies?scope=approval_requirement&status=superseded");
    expect(
      buildPlatformPoliciesPath(
        { scope: "approval_requirement", status: "superseded" },
        "tenant acme",
      ),
    ).toBe("/platform/policies?tenant_id=tenant+acme&scope=approval_requirement&status=superseded");
  });

  it("encodes the policy id in the detail path", () => {
    expect(buildPlatformPolicyDetailPath("deny_critical_actions")).toBe(
      "/platform/policies/deny_critical_actions",
    );
    expect(buildPlatformPolicyDetailPath("weird/../id")).toBe(
      "/platform/policies/weird%2F..%2Fid",
    );
    expect(buildPlatformPolicyDetailPath("deny_critical_actions", "tenant acme")).toBe(
      "/platform/policies/deny_critical_actions?tenant_id=tenant+acme",
    );
  });
});

describe("platform policy display helpers", () => {
  it("labels scopes, effects and statuses for the console", () => {
    expect(policyScopeLabel("action_execution")).toBe("Action execution");
    expect(policyScopeLabel("approval_requirement")).toBe("Approval requirement");
    expect(policyEffectLabel("deny")).toBe("Deny");
    expect(policyEffectLabel("require_approval")).toBe("Require approval");
    expect(policyEffectLabel("allow_with_evidence")).toBe("Allow with evidence");
    expect(policyEffectLabel("allow")).toBe("Allow (default)");
    expect(policyStatusLabel("active")).toBe("Active");
    expect(policyStatusLabel("superseded")).toBe("Superseded");
  });

  it("maps effects and statuses to existing console signal classes", () => {
    expect(policyEffectClass("deny")).toBe("signal-action-required");
    expect(policyEffectClass("require_approval")).toBe("signal-watch");
    expect(policyEffectClass("allow_with_evidence")).toBe("signal-ready");
    expect(policyEffectClass("allow")).toBe("signal-ready");
    expect(policyStatusClass("active")).toBe("signal-ready");
    expect(policyStatusClass("superseded")).toBe("status-checking");
  });

  it("summarizes typed conditions and marks unconstrained rules", () => {
    expect(
      summarizePolicyConditions(
        buildConditions({
          action_domains: ["Operations"],
          risk_levels: ["high", "critical"],
          autonomy_levels: ["L3", "L4"],
          requested_amount_at_least: 10000,
        }),
      ),
    ).toBe("domains Operations / risk high, critical / autonomy L3, L4 / amount >= 10000");
    expect(summarizePolicyConditions(buildConditions())).toBe("Any evaluation context");
  });

  it("survives a conditions payload that omits the optional arrays", () => {
    // The OpenAPI contract does not mark the condition arrays as required, so a
    // server that omits unset fields must still summarize cleanly.
    expect(summarizePolicyConditions({})).toBe("Any evaluation context");
    expect(summarizePolicyConditions({ risk_levels: ["critical"] })).toBe("risk critical");
  });

  it("counts policies by effect for registry metrics", () => {
    const policies = [
      buildRecord(),
      buildRecord({ policy_id: "gate_high_risk", effect: "require_approval" }),
      buildRecord({ policy_id: "evidence_low_risk", effect: "allow_with_evidence" }),
    ];

    expect(countPoliciesByEffect(policies, "deny")).toBe(1);
    expect(countPoliciesByEffect(policies, "require_approval")).toBe(1);
    expect(countPoliciesByEffect(policies, "allow_with_evidence")).toBe(1);
  });
});

describe("dry-run evaluation payload builder", () => {
  it("parses requested amounts and rejects malformed values", () => {
    expect(parseRequestedAmount("")).toEqual({ ok: true, amount: null });
    expect(parseRequestedAmount("  ")).toEqual({ ok: true, amount: null });
    expect(parseRequestedAmount("12500.5")).toEqual({ ok: true, amount: 12500.5 });
    expect(parseRequestedAmount("-5")).toEqual({
      ok: false,
      message: "Requested amount must be a non-negative number.",
    });
    expect(parseRequestedAmount("not-a-number").ok).toBe(false);
    expect(parseRequestedAmount("Infinity").ok).toBe(false);
  });

  it("builds a typed evaluation request and omits unset context fields", () => {
    expect(
      buildPolicyEvaluationPayload("tenant_demo_manufacturing", {
        scope: "action_execution",
        actionDomain: " Operations ",
        riskLevel: "high",
        autonomyLevel: "L3",
        requestedAmount: 10000,
      }),
    ).toEqual({
      tenant_id: "tenant_demo_manufacturing",
      actor_id: "platform-policy-reviewer-role",
      actor_scopes: ["platform:policy:evaluate"],
      scope: "action_execution",
      context: {
        action_domain: "Operations",
        risk_level: "high",
        autonomy_level: "L3",
        requested_amount: 10000,
      },
    });

    expect(
      buildPolicyEvaluationPayload("tenant_demo_manufacturing", {
        scope: "approval_requirement",
        actionDomain: "  ",
        riskLevel: "",
        autonomyLevel: "",
        requestedAmount: null,
      }).context,
    ).toEqual({});
  });
});

describe("platform policy API bindings", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_AXIS_API_BASE_URL;
  });

  it("returns the typed policy detail from the API", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const detail: PlatformPolicyDetail = {
      tenant_id: "tenant_demo_manufacturing",
      policy_id: "deny_critical_actions",
      current_revision: buildRecord(),
      revisions: [buildRecord()],
    };
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify(detail), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchPlatformPolicyDetail("deny_critical_actions")).resolves.toEqual(detail);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://axis-api.test/platform/policies/deny_critical_actions",
      expect.objectContaining({
        cache: "no-store",
        credentials: "include",
        method: "GET",
      }),
    );
  });

  it("maps a 404 detail response to null instead of throwing", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}", { status: 404 })),
    );

    await expect(fetchPlatformPolicyDetail("missing_policy")).resolves.toBeNull();
  });

  it("throws a typed AxisApiError on non-404 detail failures", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}", {
        headers: { "x-request-id": "request-policy-detail-503" },
        status: 503,
      })),
    );

    const caught = await fetchPlatformPolicyDetail("deny_critical_actions").catch(
      (error: unknown) => error,
    );

    expect(caught).toBeInstanceOf(AxisApiError);
    expect((caught as AxisApiError).status).toBe(503);
    expect((caught as AxisApiError).path).toBe("/platform/policies/deny_critical_actions");
    expect((caught as AxisApiError).requestId).toBe("request-policy-detail-503");
  });

  it("posts the evaluation payload as JSON and returns the typed decision", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const decision: PlatformPolicyDecision = {
      tenant_id: "tenant_demo_manufacturing",
      scope: "action_execution",
      effect: "deny",
      matched: true,
      matched_policy_id: "deny_critical_actions",
      matched_policy_version: "1.0.0",
      matched_revision_number: 1,
      matched_policies: [
        {
          policy_id: "deny_critical_actions",
          revision_number: 1,
          policy_version: "1.0.0",
          effect: "deny",
          matched_constraints: { risk_levels: ["critical"] },
        },
      ],
      evaluated_policy_count: 1,
      precedence_rule: "effect_severity_then_policy_id",
      evidence: { risk_level: "critical" },
    };
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify(decision), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const payload = buildPolicyEvaluationPayload("tenant_demo_manufacturing", {
      scope: "action_execution",
      actionDomain: "Operations",
      riskLevel: "critical",
      autonomyLevel: "",
      requestedAmount: null,
    });

    await expect(evaluatePlatformPolicy(payload)).resolves.toEqual(decision);

    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    const headers = new Headers(init?.headers);

    expect(url).toBe("http://axis-api.test/platform/policies/evaluate");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual(payload);
  });

  it("parses a decision that omits the optional (non-required) fields", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    // Only the OpenAPI-required PlatformPolicyDecision fields are present.
    const minimalDecision = {
      tenant_id: "tenant_demo_manufacturing",
      scope: "action_execution",
      effect: "allow",
      matched: false,
      evaluated_policy_count: 0,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        new Response(JSON.stringify(minimalDecision), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        }),
      ),
    );

    const decision = await evaluatePlatformPolicy(
      buildPolicyEvaluationPayload("tenant_demo_manufacturing", {
        scope: "action_execution",
        actionDomain: "",
        riskLevel: "",
        autonomyLevel: "",
        requestedAmount: null,
      }),
    );

    expect(decision.matched_policies).toBeUndefined();
    expect(decision.evidence).toBeUndefined();
    expect(decision.precedence_rule).toBeUndefined();
    expect(decision.matched).toBe(false);
    // Guard the access sites the way the console does.
    expect((decision.matched_policies ?? []).length).toBe(0);
    expect(Object.keys(decision.evidence ?? {})).toEqual([]);
  });

  it("propagates evaluation failures as typed AxisApiError values", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}", { status: 403 })),
    );

    const payload = buildPolicyEvaluationPayload("tenant_demo_manufacturing", {
      scope: "action_execution",
      actionDomain: "",
      riskLevel: "",
      autonomyLevel: "",
      requestedAmount: null,
    });
    const caught = await evaluatePlatformPolicy(payload).catch((error: unknown) => error);

    expect(caught).toBeInstanceOf(AxisApiError);
    expect((caught as AxisApiError).status).toBe(403);
    expect((caught as AxisApiError).path).toBe("/platform/policies/evaluate");
  });
});
