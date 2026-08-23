import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IdentityBrowserSessionList, IdentityBrowserSessionRecord } from "@/lib/identity-sessions";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
  revokeIdentitySession: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-identity-session", () => ({
  useIdentitySession: () => mocks.useAxisQuery("/identity/session"),
}));

vi.mock("@/lib/identity-sessions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/identity-sessions")>()),
  revokeIdentitySession: mocks.revokeIdentitySession,
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

// The console renders its own ConsolePage (topbar, theme toggle, command
// menu); stub the scaffold so the test focuses on the session list rather
// than needing every provider that chain pulls in.
vi.mock("@/components/console-page", () => ({
  ConsolePage: ({
    children,
    controls,
  }: {
    children: React.ReactNode;
    controls?: React.ReactNode;
  }) => (
    <div>
      {controls}
      {children}
    </div>
  ),
}));

import { SessionSecurityConsole } from "./session-security-console";

const identitySession: IdentitySessionReadModel = {
  authenticated: true,
  mode: "secure_oidc_cookie",
  actor_id: "operator_acme",
  tenant_id: "tenant_acme",
  scopes: [],
  expires_at: null,
  api_auth_required: true,
  enterprise_sso_ready: true,
  readiness_status: "ready",
  issuer: "",
  audience: "",
  jwks_source: "disabled",
  session_boundary: "secure_oidc_cookie",
  capabilities: [],
  limitations: [],
  notes: [],
  unauthenticated_reason: null,
};

function sessionRecord(
  overrides: Partial<IdentityBrowserSessionRecord> & { session_ref: string },
): IdentityBrowserSessionRecord {
  return {
    actor_id: "operator_acme",
    status: "active",
    current: false,
    created_at: "2026-07-24T09:00:00Z",
    expires_at: "2026-07-25T09:00:00Z",
    absolute_expires_at: null,
    last_seen_at: "2026-07-24T09:00:00Z",
    refresh_count: 3,
    revoked_at: null,
    revocation_reason: null,
    ...overrides,
  };
}

const sessionList: IdentityBrowserSessionList = {
  tenant_id: "tenant_acme",
  actor_id: "operator_acme",
  tenant_wide: false,
  sessions: [
    sessionRecord({ session_ref: "sess_slow" }),
    sessionRecord({ session_ref: "sess_fast" }),
  ],
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

function mockQueries() {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path === "/identity/session") {
      return queryResult(identitySession);
    }
    if (path === "/identity/sessions") {
      return queryResult(sessionList);
    }
    return queryResult(null, "loading");
  });
}

/** A deferred promise so the test can control exactly when a revoke resolves. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  mocks.useAxisQuery.mockReset();
  mocks.revokeIdentitySession.mockReset();
  mockQueries();
});

describe("SessionSecurityConsole revoke", () => {
  it("does not clear the pending flag for a still in-flight revoke when a later one completes first", async () => {
    const user = userEvent.setup();
    const slow = deferred<void>();
    const fast = deferred<void>();
    mocks.revokeIdentitySession.mockReturnValueOnce(slow.promise);
    mocks.revokeIdentitySession.mockReturnValueOnce(fast.promise);

    render(<SessionSecurityConsole />);

    const slowRow = await screen.findByLabelText("Browser session sess_slow");
    const fastRow = screen.getByLabelText("Browser session sess_fast");
    const slowButton = within(slowRow).getByRole("button", { name: /Revoke/ });
    const fastButton = within(fastRow).getByRole("button", { name: /Revoke/ });

    await user.click(slowButton);
    expect(slowButton).toHaveTextContent("Revoking");
    expect(slowButton).toBeDisabled();

    await user.click(fastButton);
    expect(fastButton).toHaveTextContent("Revoking");
    expect(fastButton).toBeDisabled();

    // The fast revoke completes first; it must not clear the pending flag
    // for the still in-flight slow revoke and re-enable its button.
    fast.resolve();
    await waitFor(() => expect(fastButton).not.toBeDisabled());
    expect(slowButton).toHaveTextContent("Revoking");
    expect(slowButton).toBeDisabled();

    slow.resolve();
    await waitFor(() => expect(slowButton).not.toBeDisabled());
  });

  it("announces a revoke failure with role=alert", async () => {
    const user = userEvent.setup();
    mocks.revokeIdentitySession.mockRejectedValueOnce(new Error("boom"));

    render(<SessionSecurityConsole />);

    const slowRow = await screen.findByLabelText("Browser session sess_slow");
    await user.click(within(slowRow).getByRole("button", { name: /Revoke/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Axis could not revoke the session.",
    );
  });
});
