import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import type { ManufacturingModelRouting } from "@/lib/model-routing-demo";
import { DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-identity-session", () => ({
  useIdentitySession: () => mocks.useAxisQuery("/identity/session"),
}));

import { ModelRoutingConsole } from "./model-routing-console";

const publicIdentity: IdentitySessionReadModel = {
  authenticated: false,
  mode: "public_demo",
  actor_id: null,
  tenant_id: null,
  scopes: [],
  expires_at: null,
  api_auth_required: false,
  enterprise_sso_ready: false,
  readiness_status: "ready",
  issuer: "",
  audience: "",
  jwks_source: "disabled",
  session_boundary: "public_demo",
  capabilities: [],
  limitations: [],
  notes: [],
  unauthenticated_reason: null,
};

function unavailableResult() {
  return {
    data: null,
    source: "unavailable",
    error: "Axis API request failed.",
    isLoading: false,
    isRefreshing: false,
    isUnavailable: true,
  };
}

function mockIdentity(identity: IdentitySessionReadModel = publicIdentity) {
  mocks.useAxisQuery.mockImplementation((path: string) =>
    path === "/identity/session"
      ? {
          data: identity,
          source: "api",
          error: null,
          isLoading: false,
          isRefreshing: false,
          isUnavailable: false,
        }
      : unavailableResult(),
  );
}

describe("ModelRoutingConsole tabs", () => {
  beforeEach(() => {
    mocks.useAxisQuery.mockReset();
    mockIdentity();
  });

  it("scopes reference and live reads to authenticated and public-demo tenants", async () => {
    const authenticatedIdentity: IdentitySessionReadModel = {
      ...publicIdentity,
      authenticated: true,
      mode: "oidc",
      actor_id: "operator_acme",
      tenant_id: "tenant_acme",
    };
    mockIdentity(authenticatedIdentity);
    const user = userEvent.setup();

    const { unmount } = render(<ModelRoutingConsole />);

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/model-routing?tenant_id=tenant_acme`,
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_acme" }),
    );

    await user.click(screen.getByRole("tab", { name: "Live invocations" }));
    expect(window.location.search).toBe("?tab=live");
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      "/platform/models/routing/telemetry?tenant_id=tenant_acme&limit=100",
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_acme" }),
    );
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      "/platform/models/invocations?tenant_id=tenant_acme&page_size=50",
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_acme" }),
    );
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      "/platform/models/endpoints?tenant_id=tenant_acme&limit=100",
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_acme" }),
    );

    unmount();
    window.history.replaceState(null, "", "/model-routing");
    mocks.useAxisQuery.mockReset();
    mockIdentity();
    render(<ModelRoutingConsole />);
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/model-routing?tenant_id=${DEMO_TENANT_ID}`,
      expect.objectContaining({ enabled: true, expectedTenantId: DEMO_TENANT_ID }),
    );
  });

  it("fails closed when identity cannot be verified", () => {
    mocks.useAxisQuery.mockImplementation((path: string) =>
      path === "/identity/session"
        ? unavailableResult()
        : {
            ...unavailableResult(),
            source: "loading",
            isLoading: true,
            isUnavailable: false,
          },
    );

    render(<ModelRoutingConsole />);

    expect(screen.getByRole("heading", { name: "Identity API unavailable" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Reference routing" })).not.toBeInTheDocument();
  });

  it("shows one header strip with the reference-vs-live explanation and tabs", () => {
    render(<ModelRoutingConsole />);

    expect(
      screen.getByText(
        "Reference routing shows the governed routing design; live invocations are the calls the platform actually executed.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Reference routing" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Live invocations" })).toBeInTheDocument();
  });

  it("renders the reference tab by default and switches to live invocations", async () => {
    const user = userEvent.setup();
    render(<ModelRoutingConsole />);

    // Reference tab active: its error panel renders, live panels do not.
    expect(
      screen.getByRole("heading", { name: "Routing API unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Model invocation API unavailable" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Live invocations" }));

    expect(
      screen.getByRole("heading", { name: "Model invocation API unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Model endpoint API unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Routing API unavailable" }),
    ).not.toBeInTheDocument();
  });

  it("does not show the Live executed badge while the invocation API is unavailable", async () => {
    const user = userEvent.setup();
    render(<ModelRoutingConsole />);

    await user.click(screen.getByRole("tab", { name: "Live invocations" }));

    // The badge used to render unconditionally, so a green "Live executed"
    // claim could sit directly above "Model invocation API unavailable".
    expect(screen.queryByText("Live executed")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Model invocation API unavailable" }),
    ).toBeInTheDocument();
  });
});

describe("ModelRoutingConsole no-match filter state", () => {
  const authenticatedIdentity: IdentitySessionReadModel = {
    ...publicIdentity,
    authenticated: true,
    mode: "oidc",
    actor_id: "operator_acme",
    tenant_id: "tenant_acme",
  };

  // Two routes with non-overlapping domain/provider, so a filter combination
  // that each value individually matches can still match zero routes.
  const routingFixture: ManufacturingModelRouting = {
    tenant_id: "tenant_acme",
    plant_name: "Acme Plant",
    scenario: "Fixture scenario",
    provenance: "reference_scenario",
    as_of: "2026-07-22T12:00:00Z",
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
        notes: [],
      },
      {
        provider_id: "external-general-llm",
        display_name: "External General LLM",
        provider_type: "hosted",
        hosting_boundary: "external",
        status: "action_required",
        egress_mode: "external",
        cost_basis: "usage",
        allowed_policies: ["no-external-egress"],
        notes: [],
      },
    ],
    routes: [
      {
        route_id: "route_quality_fixture",
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
        evidence_refs: [],
        audit_event_id: "audit_quality_fixture",
        observability_events: [],
      },
      {
        route_id: "route_ops_fixture",
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
        required_permissions: [],
        evidence_refs: [],
        audit_event_id: "audit_ops_fixture",
        observability_events: [],
      },
    ],
    budget_notes: [],
    observability_notes: [],
  };

  beforeEach(() => {
    mocks.useAxisQuery.mockReset();
    mocks.useAxisQuery.mockImplementation((path: string) => {
      if (path === "/identity/session") {
        return {
          data: authenticatedIdentity,
          source: "api",
          error: null,
          isLoading: false,
          isRefreshing: false,
          isUnavailable: false,
        };
      }
      if (path.startsWith(`${OPERATIONS_API_PREFIX}/model-routing`)) {
        return {
          data: routingFixture,
          source: "api",
          error: null,
          isLoading: false,
          isRefreshing: false,
          isUnavailable: false,
        };
      }
      return unavailableResult();
    });
  });

  it("renders the empty state instead of an excluded route's details when filters match nothing", async () => {
    const user = userEvent.setup();
    render(<ModelRoutingConsole />);

    // Each value exists individually, but the Quality route never uses the
    // local-vllm provider — the combination matches zero routes.
    await user.selectOptions(screen.getByLabelText("Domain"), "Quality");
    await user.selectOptions(screen.getByLabelText("Provider"), "local-vllm");

    expect(
      screen.getByRole("heading", { name: "No routes match the current filters" }),
    ).toBeInTheDocument();
    // The unfiltered fallback previously rendered the Quality route's detail.
    expect(screen.queryByText("Quality Fixture Agent")).not.toBeInTheDocument();
    expect(screen.queryByText("Operations Fixture Agent")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(
      screen.queryByRole("heading", { name: "No routes match the current filters" }),
    ).not.toBeInTheDocument();
  });

  it("counts blocked routes within the visible filter result and restores the count on reset", async () => {
    const user = userEvent.setup();
    render(<ModelRoutingConsole />);
    expect(screen.getByRole("heading", { name: "2 visible" })).toBeInTheDocument();
    expect(screen.getByText("1 blocked")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Provider"), "local-vllm");
    expect(screen.getByRole("heading", { name: "1 visible" })).toBeInTheDocument();
    expect(screen.getByText("0 blocked")).toBeInTheDocument();
    expect(screen.queryByText("1 blocked")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Decision"), "blocked_by_default");
    expect(screen.getByRole("heading", { name: "No routes match the current filters" })).toBeInTheDocument();
    expect(screen.queryByText("1 blocked")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByRole("heading", { name: "2 visible" })).toBeInTheDocument();
    expect(screen.getByText("1 blocked")).toBeInTheDocument();
  });

  it("opens the selected dependency through the existing route filters and detail selection", async () => {
    const user = userEvent.setup();
    render(<ModelRoutingConsole />);
    await user.selectOptions(screen.getByLabelText("Domain"), "Operations");
    const diagram = screen.getByRole("region", { name: "Provider to model diagram" });
    await user.click(within(diagram).getByRole("button", { name: "Select general-large from External General LLM" }));
    expect(new URLSearchParams(window.location.search).get("domain")).toBe("Operations");
    await user.click(screen.getByRole("button", { name: "Inspect first matching route" }));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("provider")).toBe("external-general-llm");
    expect(params.get("route_id")).toBe("route_quality_fixture");
    expect(params.has("domain")).toBe(false);
    expect(screen.getByRole("heading", { name: "Quality Fixture Agent" })).toBeInTheDocument();
  });

  it("uses the payload provenance as the single source-of-truth badge", () => {
    render(<ModelRoutingConsole />);

    expect(screen.getAllByText("model routing: reference scenario")).toHaveLength(1);
    expect(screen.queryByText("model routing: live")).not.toBeInTheDocument();
    expect(
      screen.getByText("model routing: reference scenario").closest(".status-pill"),
    ).toHaveAttribute("data-source-state", "reference");
  });

  it("renders a valid empty routing payload as onboarding state, not an API error", () => {
    mocks.useAxisQuery.mockImplementation((path: string) => {
      if (path === "/identity/session") {
        return {
          data: authenticatedIdentity,
          source: "api",
          error: null,
          isLoading: false,
          isRefreshing: false,
          isUnavailable: false,
        };
      }
      if (path.startsWith(`${OPERATIONS_API_PREFIX}/model-routing`)) {
        return {
          data: {
            ...routingFixture,
            provenance: "empty",
            provider_options: [],
            routes: [],
          },
          source: "api",
          error: null,
          isLoading: false,
          isRefreshing: false,
          isUnavailable: false,
        };
      }
      return unavailableResult();
    });

    render(<ModelRoutingConsole />);

    expect(screen.getByRole("heading", { name: "No model routes yet" })).toBeInTheDocument();
    expect(screen.getByText("model routing: no records")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Routing API unavailable" }))
      .not.toBeInTheDocument();
  });
});
