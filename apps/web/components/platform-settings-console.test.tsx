import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import type {
  AxisReadyReport,
  DeploymentReadinessReport,
  OidcReadinessReport,
  SupportDiagnosticsReport,
} from "@/lib/platform-settings";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

// The console renders its own ConsolePage (dynamic source label); stub the
// scaffold so the test focuses on the settings panels rather than the topbar.
vi.mock("@/components/console-page", () => ({
  ConsolePage: ({
    title,
    sourceLabel,
    children,
  }: {
    title?: string;
    sourceLabel?: string;
    children: React.ReactNode;
  }) => (
    <div>
      <h1>{title}</h1>
      {sourceLabel ? <p>{sourceLabel}</p> : null}
      {children}
    </div>
  ),
}));

import { PlatformSettingsConsole } from "./platform-settings-console";

type Source = "loading" | "api" | "unavailable";

function queryResult(data: unknown, source: Source) {
  return {
    data,
    source,
    error: source === "unavailable" ? "Axis API request failed." : null,
    errorStatus: null,
    isRefreshing: false,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
    errorRequestId: source === "unavailable" ? "req-settings-refresh" : null,
  };
}

const readyFixture: AxisReadyReport = {
  status: "ready",
  service: "axis-api",
  dependencies: {
    postgres: { required: true, status: "ready", latency_ms: 3.2 },
    temporal: { required: true, status: "unavailable", latency_ms: 1000 },
    typedb: { required: false, status: "disabled", latency_ms: 0 },
  },
  identity: {
    oidc_auth_required: false,
    enterprise_sso_ready: false,
    readiness_status: "action_required",
  },
  external_model_egress_enabled: false,
};

const oidcFixture: OidcReadinessReport = {
  status: "action_required",
  enterprise_sso_ready: false,
  auth_required: false,
  issuer: "http://keycloak.local/realms/axis",
  audience: "limes-axis-api",
  jwks_source: "derived_from_issuer",
  jwks_url_configured: false,
  jwks_cache_seconds: 300,
  algorithms: ["RS256"],
  token_binding: {
    actor_claim: "sub",
    tenant_claim: "axis_tenant",
    scope_sources: ["scope"],
  },
  checks: [
    {
      check_id: "https_issuer",
      status: "action_required",
      detail: "OIDC issuer is not HTTPS; use a TLS issuer for enterprise SSO.",
    },
    {
      check_id: "actor_claim",
      status: "ready",
      detail: "Actor claim binding is configured.",
    },
  ],
};

const identityFixture: IdentitySessionReadModel = {
  authenticated: false,
  mode: "public_evaluation",
  actor_id: null,
  tenant_id: null,
  scopes: [],
  expires_at: null,
  api_auth_required: false,
  enterprise_sso_ready: false,
  readiness_status: "action_required",
  issuer: "http://keycloak.local/realms/axis",
  audience: "limes-axis-api",
  jwks_source: "derived_from_issuer",
  session_boundary: "public",
  capabilities: [],
  limitations: [],
  notes: [],
};

const deploymentFixture: DeploymentReadinessReport = {
  status: "action_required",
  environment: "development",
  profile: "local_demo",
  production_ready: false,
  demo_safe: true,
  capabilities: {
    object_store_adapter: "filesystem",
    object_store_worm_retention_enabled: false,
    object_store_retention_mode: "none",
    object_store_retention_days: 0,
  },
  production_blockers: ["api_rate_limiting"],
  checks: [
    {
      check_id: "api_rate_limiting",
      status: "action_required",
      production_required: true,
      detail: "API rate limiting is not enabled; configure request throttling before production.",
    },
    {
      check_id: "external_model_egress_disabled",
      status: "ready",
      production_required: true,
      detail: "External model egress is disabled by default.",
    },
  ],
  notes: [],
};

const supportFixture: SupportDiagnosticsReport = {
  status: "action_required",
  service: "axis-api",
  environment: "development",
  safe_to_share: true,
  demo_support_ready: true,
  production_support_ready: false,
  support_blockers: ["production_support_model"],
  diagnostics: {
    deployment: {
      profile: "local_demo",
      demo_safe: true,
      production_ready: false,
      production_blockers: ["api_rate_limiting"],
    },
    identity: {
      readiness_status: "action_required",
      enterprise_sso_ready: false,
      oidc_auth_required: false,
      jwks_source: "derived_from_issuer",
      jwks_url_configured: false,
    },
    external_model_egress_enabled: false,
    live_connector_execution_enabled: false,
    audit_ledger_signing_configured: false,
    object_store_adapter: "filesystem",
    object_store_worm_retention_enabled: false,
    object_store_retention_mode: "none",
    object_store_retention_days: 0,
  },
  checks: [
    {
      check_id: "production_support_model",
      status: "action_required",
      detail: "Production support model, escalation paths and SLOs remain Enterprise work.",
    },
  ],
  support_artifacts: [],
  redaction_policy: ["no_bearer_tokens"],
  notes: [],
};

const fixtures: [string, unknown][] = [
  ["/ready", readyFixture],
  ["/identity/oidc/readiness", oidcFixture],
  ["/identity/session", identityFixture],
  ["/deployment/readiness", deploymentFixture],
  ["/support/diagnostics", supportFixture],
];

function mockQueriesByPath(
  overrides: Record<string, Source> = {},
  retainedPaths: readonly string[] = [],
) {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    const match = fixtures.find(([prefix]) => path === prefix);
    if (!match) {
      throw new Error(`Unexpected settings query path: ${path}`);
    }
    const source = overrides[path] ?? "api";
    const retainData = source === "api" || retainedPaths.includes(path);
    return queryResult(retainData ? match[1] : null, source);
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/settings");
  mocks.useAxisQuery.mockReset();
});

describe("PlatformSettingsConsole", () => {
  it("renders the System status heading and the four tabs", () => {
    mockQueriesByPath();
    render(<PlatformSettingsConsole />);

    expect(screen.getByRole("heading", { name: "System status" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Readiness" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Identity" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Deployment" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Support" })).toBeInTheDocument();
    // Readiness content renders by default.
    expect(screen.getByText("Axis API boundary")).toBeInTheDocument();
  });

  it("keeps healthy panels rendered when one endpoint fails", async () => {
    mockQueriesByPath({ "/support/diagnostics": "unavailable" });
    const user = userEvent.setup();
    render(<PlatformSettingsConsole />);

    // The old 5-way OR collapse blanked the whole page; now only the failing
    // panel degrades, inside its own tab.
    expect(screen.getByText("Axis API boundary")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Settings API unavailable" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Support" }));
    expect(
      screen.getByRole("heading", { name: "Support diagnostics API unavailable" }),
    ).toBeInTheDocument();
    expect(window.location.search).toBe("?tab=support");
  });

  it("keeps validated panel data visible but never labels a failed refresh live", async () => {
    mockQueriesByPath(
      { "/support/diagnostics": "unavailable" },
      ["/support/diagnostics"],
    );
    const user = userEvent.setup();
    render(<PlatformSettingsConsole />);

    expect(screen.getByText("Stale system status")).toBeInTheDocument();
    expect(screen.queryByText("Live system status")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Support" }));
    expect(
      screen.getByText(
        /Live refresh failed\. Showing the last validated system status.+Request req-settings-refresh\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Safe to share")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Support diagnostics API unavailable" }),
    ).not.toBeInTheDocument();
  });

  it("restores a linked settings tab from the URL", () => {
    window.history.replaceState(null, "", "/settings?tab=identity");
    mockQueriesByPath();

    render(<PlatformSettingsConsole />);

    expect(screen.getByRole("tab", { name: "Identity" })).toHaveAttribute(
      "data-state",
      "active",
    );
    expect(screen.getByText("Browser session")).toBeInTheDocument();
  });

  it("pushes discrete tab changes into browser history", async () => {
    const pushState = vi.spyOn(window.history, "pushState");
    mockQueriesByPath();
    render(<PlatformSettingsConsole />);

    await userEvent.click(screen.getByRole("tab", { name: "Identity" }));

    expect(pushState).toHaveBeenCalledWith(
      window.history.state,
      "",
      "/settings?tab=identity",
    );
    pushState.mockRestore();
  });

  it("renders a loading skeleton for a pending panel instead of an error", () => {
    mockQueriesByPath({ "/ready": "loading" });
    render(<PlatformSettingsConsole />);

    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("heading", { name: "Readiness API unavailable" }),
    ).not.toBeInTheDocument();
  });

  it("shows plain-English guidance next to every action-required check", async () => {
    mockQueriesByPath();
    const user = userEvent.setup();
    render(<PlatformSettingsConsole />);

    // Deployment readiness gate on the default readiness tab.
    expect(
      screen.getByText("Enable API rate limiting before exposing the platform to production traffic."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Identity" }));
    expect(
      screen.getByText("Use an HTTPS issuer URL from your enterprise IdP before production."),
    ).toBeInTheDocument();
    // Ready checks carry no guidance line; the raw API detail stays as
    // secondary text.
    expect(
      screen.getByText("Actor claim binding is configured."),
    ).toBeInTheDocument();
  });

  it("links to the sessions console from the identity tab", async () => {
    mockQueriesByPath();
    const user = userEvent.setup();
    render(<PlatformSettingsConsole />);

    await user.click(screen.getByRole("tab", { name: "Identity" }));
    expect(screen.getByRole("link", { name: "Manage browser sessions" })).toHaveAttribute(
      "href",
      "/settings/sessions",
    );
  });
});
