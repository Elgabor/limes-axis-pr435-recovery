import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuditExportBundle, ManufacturingAuditExplorer } from "@/lib/audit-demo";

const mocks = vi.hoisted(() => ({
  axisFetchParsedJson: vi.fn(),
  useAxisQuery: vi.fn(),
  useConsoleTenantScope: vi.fn(),
  session: {
    accessToken: "fixture-token",
    actorId: "fixture-actor",
    tenantId: "tenant_fixture",
    scopes: ["audit:read"],
  },
}));

vi.mock("@/lib/axis-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/axis-api")>()),
  axisFetchParsedJson: mocks.axisFetchParsedJson,
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({
    refreshNonce: 0,
    triggerRefresh: vi.fn(),
    apiBaseUrl: "http://localhost:8000",
    apiStatus: { state: "ok", label: "Ready", detail: "" },
  }),
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: mocks.session }),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-console-tenant-scope", () => ({
  IDENTITY_SESSION_ENDPOINT: "/identity/session",
  useConsoleTenantScope: mocks.useConsoleTenantScope,
}));

import { AuditExplorer } from "./audit-explorer";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const explorerFixture: ManufacturingAuditExplorer = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Component fixture",
  provenance: "live",
  as_of: "2026-07-09T09:00:00+02:00",
  ledger_status: "ready",
  metrics: [],
  filter_options: {
    tenants: ["tenant_fixture"],
    event_types: ["agent.proposal.created"],
    scopes: ["wf_fixture"],
    actors: ["agent_fixture"],
    categories: ["agent"],
  },
  events: [
    {
      audit_event_id: "audit_evt_fixture",
      occurred_at: "2026-07-09T09:01:00+02:00",
      tenant_id: "tenant_fixture",
      actor_id: "agent_fixture",
      actor_type: "agent",
      event_type: "agent.proposal.created",
      category: "agent",
      domain: "Supply",
      scope: "wf_fixture",
      result: "pending",
      severity: "watch",
      source: "axis-agent-runtime",
      summary: "Agent proposed a governed supply action.",
      permission_scope: "approvals:supply:request",
      data_classification: "internal",
      related_workflow_id: "wf_fixture",
      related_approval_id: null,
      related_agent_id: "agent_fixture",
      evidence_refs: ["risk_fixture"],
      payload_preview: { action_id: "expedite_fixture" },
    },
  ],
  retention_notes: ["Fixture retention note."],
};

const exportBundleFixture: AuditExportBundle = {
  tenant_id: "tenant_fixture",
  scenario: "Component fixture",
  format: "jsonl",
  export_reason: "console-review",
  filters: {
    tenant_id: "tenant_fixture",
    event_type: null,
    actor_id: null,
    scope: null,
    limit: 100,
  },
  retention_policy: {
    policy_id: "retention_fixture",
    retention_days: 365,
    retention_basis: "regulatory",
    disposal_action: "cryptographic_erasure",
    legal_hold: false,
    export_requires_review: true,
    notes: [],
  },
  manifest: {
    export_id: "export_fixture",
    generated_at: "2026-07-09T08:30:00+02:00",
    tenant_id: "tenant_fixture",
    record_count: 42,
    format: "jsonl",
    redaction_policy: "payload_preview_only",
    retention_policy_id: "retention_fixture",
    checksum_sha256: "f00dfeed".repeat(8),
    integrity_chain_tip_sha256: "beefcafe".repeat(8),
    retention_enforced: true,
    retention_window_start: "2025-07-09T08:30:00+02:00",
    excluded_record_count: 3,
  },
  integrity_proof: {
    algorithm: "sha256-hash-chain-v1",
    verification_status: "verified",
    record_count: 42,
    chain_tip_sha256: "beefcafe".repeat(8),
    event_hashes: ["c0ffee00".repeat(8)],
  },
  ledger_signature: {
    algorithm: "unsigned",
    key_id: null,
    signing_mode: "not_configured",
    verification_status: "unsigned",
    signed_payload_sha256: "d00d0000".repeat(8),
    signature: null,
    notes: ["Audit ledger signing key is not configured."],
  },
  events: [],
  retention_notes: [],
};

function mockAuditApi() {
  mocks.axisFetchParsedJson.mockImplementation((path: string) => {
    if (path.startsWith(`${OPERATIONS_API_PREFIX}/audit/export`)) {
      return Promise.resolve(exportBundleFixture);
    }
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

function queryResult(data: unknown, source: "loading" | "api" | "unavailable") {
  return {
    data,
    source,
    error: source === "unavailable" ? "Axis API request failed." : null,
    isRefreshing: false,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
  };
}

describe("AuditExplorer integrity and export", () => {
  beforeEach(() => {
    mocks.axisFetchParsedJson.mockReset();
    mocks.useAxisQuery.mockReset();
    mocks.useConsoleTenantScope.mockReset();
    mocks.useConsoleTenantScope.mockReturnValue({
      identity: queryResult({ authenticated: true, tenant_id: "tenant_fixture" }, "api"),
      tenantId: "tenant_fixture",
      tenantQueriesEnabled: true,
    });
    mocks.useAxisQuery.mockReturnValue(queryResult(explorerFixture, "api"));
    mockAuditApi();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders plain-first integrity summary lines from the export bundle", async () => {
    render(<AuditExplorer />);

    expect(await screen.findByText("Ledger verified — hash chain intact")).toBeInTheDocument();
    expect(screen.getByText("Retention enforced")).toBeInTheDocument();
    expect(screen.getByText("Signature: not configured")).toBeInTheDocument();

    // Raw hashes stay out of the primary copy; they live behind Inspect.
    expect(screen.queryByText(new RegExp("f00dfeed"))).not.toBeInTheDocument();
    expect(screen.queryByText(new RegExp("beefcafe"))).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect" })).toBeInTheDocument();
  });

  it("downloads the fetched export bundle as a dated JSON file", async () => {
    const user = userEvent.setup();
    const objectUrls: Blob[] = [];
    const createObjectURL = vi.fn((blob: Blob) => {
      objectUrls.push(blob);
      return "blob:axis-export";
    });
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });

    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloads.push(this.download);
    });

    render(<AuditExplorer />);
    await user.click(
      await screen.findByRole("button", { name: /Download export bundle/ }),
    );

    await waitFor(() => {
      expect(downloads).toEqual(["axis-audit-export-tenant_fixture-2026-07-09.json"]);
    });
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:axis-export");
    const serialized = await objectUrls[0].text();
    expect(JSON.parse(serialized)).toEqual(exportBundleFixture);
  });

  it("keeps the ?event_id= deep link selecting the requested event", async () => {
    const originalLocation = window.location.href;
    window.history.replaceState(null, "", "/audit?event_id=audit_evt_fixture");

    render(<AuditExplorer />);

    const selected = await screen.findByRole("button", { pressed: true });
    expect(selected).toHaveTextContent("agent.proposal.created");

    window.history.replaceState(null, "", originalLocation);
  });

  it("attaches the active bearer session to audit reads and exports", async () => {
    render(<AuditExplorer />);

    await screen.findByText("Ledger verified — hash chain intact");
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);
    expect(mocks.axisFetchParsedJson.mock.calls[0]?.[2]).toMatchObject({
      session: mocks.session,
    });
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/audit/events?tenant_id=tenant_fixture&limit=100`,
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_fixture" }),
    );
  });

  it("renders the empty state instead of an excluded record's details when filters match nothing", async () => {
    // Two events whose tenant/event/scope combinations do not overlap, so a
    // tenant+event filter pair that each individually matches a real event
    // can still match zero events in combination.
    const twoEventExplorer: ManufacturingAuditExplorer = {
      ...explorerFixture,
      filter_options: {
        tenants: ["tenant_a", "tenant_b"],
        event_types: ["agent.proposal.created", "policy.egress.blocked"],
        scopes: ["wf_a", "wf_b"],
        actors: ["agent_a", "model-router"],
        categories: ["agent", "policy"],
      },
      events: [
        {
          ...explorerFixture.events[0],
          audit_event_id: "audit_evt_a",
          tenant_id: "tenant_a",
          event_type: "agent.proposal.created",
          scope: "wf_a",
        },
        {
          ...explorerFixture.events[0],
          audit_event_id: "audit_evt_b",
          tenant_id: "tenant_b",
          event_type: "policy.egress.blocked",
          scope: "wf_b",
          actor_id: "model-router",
        },
      ],
    };
    mocks.useAxisQuery.mockReturnValue(queryResult(twoEventExplorer, "api"));

    const user = userEvent.setup();
    render(<AuditExplorer />);

    // Each value exists individually, but tenant_a never co-occurs with
    // policy.egress.blocked — the combination matches zero events.
    await user.selectOptions(screen.getByLabelText("Tenant"), "tenant_a");
    await user.selectOptions(screen.getByLabelText("Event"), "policy.egress.blocked");
    expect(window.location.search).toContain("tenant=tenant_a");
    expect(window.location.search).toContain("event_type=policy.egress.blocked");

    expect(
      screen.getByRole("heading", { name: "No matching audit evidence" }),
    ).toBeInTheDocument();
    // The unfiltered fallback previously rendered audit_evt_a's raw id here.
    expect(screen.queryByText("audit_evt_a")).not.toBeInTheDocument();
    expect(screen.queryByText("audit_evt_b")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(
      screen.queryByRole("heading", { name: "No matching audit evidence" }),
    ).not.toBeInTheDocument();
  });
});
