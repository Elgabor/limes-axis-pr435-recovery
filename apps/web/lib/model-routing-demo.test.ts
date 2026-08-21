import { describe, expect, it } from "vitest";

import {
  allModelRoutingFilter,
  countBlockedModelRoutes,
  filterModelRoutes,
  findModelRouteById,
  formatEuroCost,
  formatModelRoutingLabel,
  sumEstimatedModelCost,
  type ManufacturingModelRouting,
} from "./model-routing-demo";

const modelRoutingFixture: ManufacturingModelRouting = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-06-22T09:00:00+02:00",
  routing_status: "watch",
  metrics: [],
  filter_options: {
    domains: ["Quality", "Operations"],
    providers: ["external-general-llm", "local-vllm"],
    model_policies: ["no-external-egress", "local-only"],
    egress_decisions: ["blocked_by_default", "local_allowed"],
    statuses: ["action_required", "ready"],
  },
  provider_options: [
    {
      provider_id: "local-vllm",
      display_name: "Local vLLM",
      provider_type: "self-hosted",
      hosting_boundary: "tenant",
      status: "ready",
      egress_mode: "none",
      cost_basis: "infrastructure",
      allowed_policies: ["local-only"],
      notes: ["Fixture provider."],
    },
  ],
  routes: [
    {
      route_id: "route_quality_blocked_fixture",
      agent_id: "agent_quality_fixture",
      agent_name: "Quality Fixture Agent",
      domain: "Quality",
      provider_id: "external-general-llm",
      provider_name: "External General LLM",
      model: "general-large",
      model_policy: "no-external-egress",
      prompt_classification: "restricted",
      data_boundary: "tenant",
      external_egress_requested: true,
      external_egress_allowed: false,
      egress_decision: "blocked_by_default",
      decision_reason: "Policy denies external egress.",
      route_status: "action_required",
      input_tokens: 1200,
      output_tokens: 200,
      estimated_cost_eur: 0,
      latency_ms: 0,
      cost_center: "quality",
      required_permissions: ["models:route"],
      evidence_refs: ["risk_quality_fixture"],
      audit_event_id: "audit_egress_fixture",
      observability_events: ["model.route.blocked"],
    },
    {
      route_id: "route_ops_local_fixture",
      agent_id: "agent_ops_fixture",
      agent_name: "Operations Fixture Agent",
      domain: "Operations",
      provider_id: "local-vllm",
      provider_name: "Local vLLM",
      model: "local-small",
      model_policy: "local-only",
      prompt_classification: "internal",
      data_boundary: "tenant",
      external_egress_requested: false,
      external_egress_allowed: false,
      egress_decision: "local_allowed",
      decision_reason: "Local model selected.",
      route_status: "ready",
      input_tokens: 700,
      output_tokens: 100,
      estimated_cost_eur: 0.42,
      latency_ms: 320,
      cost_center: "operations",
      required_permissions: ["operations:read"],
      evidence_refs: ["asset_fixture_line"],
      audit_event_id: "audit_route_fixture",
      observability_events: ["model.route.completed"],
    },
  ],
  budget_notes: ["Fixture data is scoped to tests."],
  observability_notes: ["Fixture data is scoped to tests."],
};

describe("model routing helpers", () => {
  it("filters route telemetry by domain, provider and decision", () => {
    const routes = filterModelRoutes(modelRoutingFixture, {
      domain: "Quality",
      provider: "external-general-llm",
      decision: "blocked_by_default",
    });

    expect(routes).toHaveLength(1);
    expect(routes[0].route_id).toBe("route_quality_blocked_fixture");
  });

  it("keeps all routes when filters are set to all", () => {
    expect(
      filterModelRoutes(modelRoutingFixture, {
        domain: allModelRoutingFilter,
        provider: allModelRoutingFilter,
        decision: allModelRoutingFilter,
      }),
    ).toHaveLength(modelRoutingFixture.routes.length);
  });

  it("finds routes by id with a safe fallback", () => {
    expect(findModelRouteById(modelRoutingFixture, "route_ops_local_fixture").agent_name).toBe(
      "Operations Fixture Agent",
    );
    expect(findModelRouteById(modelRoutingFixture, "missing").agent_name).toBe(
      "Quality Fixture Agent",
    );
  });

  it("counts blocked routes and formats labels and cost", () => {
    expect(countBlockedModelRoutes(modelRoutingFixture)).toBe(1);
    expect(sumEstimatedModelCost(modelRoutingFixture)).toBeCloseTo(0.42);
    expect(formatModelRoutingLabel("approved_private_endpoint")).toBe(
      "Approved Private Endpoint",
    );
    expect(formatEuroCost(0)).toBe("EUR 0.00");
  });
});
