import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  IdentitySessionReadModel,
  ManufacturingNotificationCenter,
} from "@/lib/platform-overview";
import { DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/sessions",
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({
    apiBaseUrl: "http://localhost:8000",
    apiStatus: { state: "online", label: "Online", detail: "API reachable" },
    refreshNonce: 0,
    triggerRefresh: vi.fn(),
  }),
}));

// Neither needs coverage here: ThemeToggle needs a ThemeProvider and
// ConsoleCommandMenu needs a router context, both unrelated to the
// notification badge this test is about.
vi.mock("@/components/theme-toggle", () => ({
  ThemeToggle: () => null,
}));

vi.mock("@/components/console-command-menu", () => ({
  ConsoleCommandMenu: () => null,
}));

import { ConsoleTopbar } from "./console-topbar";

const identitySession: IdentitySessionReadModel = {
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
};

function queryResult(data: unknown, source: "loading" | "api" | "unavailable" = "api") {
  return {
    data,
    source,
    error: source === "unavailable" ? "Axis API request failed." : null,
    isRefreshing: false,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
  };
}

function mockNotifications(unreadCount: number) {
  const center: ManufacturingNotificationCenter = {
    tenant_id: DEMO_TENANT_ID,
    plant_name: "Fixture Plant",
    scenario: "Fixture scenario",
    provenance: "live",
    as_of: "2026-07-24T09:00:00Z",
    unread_count: unreadCount,
    action_required_count: 0,
    watch_count: unreadCount,
    notifications: [],
    generation_boundary: "boundary-1",
    notes: [],
  };

  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path === "/identity/session") {
      return queryResult(identitySession);
    }
    if (path === `${OPERATIONS_API_PREFIX}/notifications?tenant_id=${DEMO_TENANT_ID}`) {
      return queryResult(center);
    }
    return queryResult(null, "loading");
  });
}

beforeEach(() => {
  mocks.useAxisQuery.mockReset();
});

describe("ConsoleTopbar notification badge", () => {
  it("marks the compact Settings shortcut current on descendant routes", () => {
    mockNotifications(0);
    render(<ConsoleTopbar />);

    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("caps a double-digit unread count at 9+, matching the sidebar convention", () => {
    mockNotifications(25);
    render(<ConsoleTopbar />);

    expect(screen.getByLabelText("Open notifications")).toHaveTextContent("9+");
  });

  it("shows the exact count under 10", () => {
    mockNotifications(4);
    render(<ConsoleTopbar />);

    expect(screen.getByLabelText("Open notifications")).toHaveTextContent("4");
  });

  it.each([
    ["identity is unavailable", null, "unavailable" as const],
    [
      "an authenticated identity has no tenant",
      { ...identitySession, authenticated: true, mode: "oidc" as const },
      "api" as const,
    ],
  ])("does not leave notifications loading forever when %s", async (_, identity, source) => {
    const user = userEvent.setup();
    mocks.useAxisQuery.mockImplementation((path: string) => {
      if (path === "/identity/session") {
        return queryResult(identity, source);
      }
      return queryResult(null, "loading");
    });

    render(<ConsoleTopbar />);
    await user.click(screen.getByLabelText("Open notifications"));

    expect(screen.getByText("notifications: unavailable")).toBeInTheDocument();
    expect(screen.queryByText("notifications: loading")).not.toBeInTheDocument();
  });
});
