import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  axisFetch: vi.fn(),
  triggerRefresh: vi.fn(),
}));

vi.mock("@/lib/axis-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/axis-api")>();
  return { ...actual, axisFetch: mocks.axisFetch };
});

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({
    apiBaseUrl: "http://localhost:8000",
    apiStatus: { state: "online", label: "Online", detail: "API reachable" },
    refreshNonce: 0,
    triggerRefresh: mocks.triggerRefresh,
  }),
}));

import { ToastProvider } from "@/components/ui/toast";
import type { ConnectorRegistryItem } from "@/lib/connectors-demo";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

import { dbConnectorFixture } from "./connector-fixtures";
import { ConnectorSourceDiscoveryPanel } from "./source-discovery-panel";

const TENANT_ID = "tenant_demo_manufacturing";
const VERIFY_PATH = `${OPERATIONS_API_PREFIX}/connectors/external-db/verify-source?tenant_id=${TENANT_ID}`;
const DISCOVER_PATH = `${OPERATIONS_API_PREFIX}/connectors/external-db/discover?tenant_id=${TENANT_ID}`;
const ACTIVATION_PATH = `${OPERATIONS_API_PREFIX}/connectors/external-db/source-bindings?tenant_id=${TENANT_ID}`;

function okResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json", "x-request-id": "req-discovery-1" },
  });
}

function deniedResponse(reason: string): Response {
  return new Response(
    JSON.stringify({
      detail: {
        code: "permission_denied",
        message: "denied",
        reason,
        required_permission: reason.replace("missing_scope:", ""),
      },
    }),
    {
      status: 403,
      headers: { "content-type": "application/json", "x-request-id": "req-denied" },
    },
  );
}

const verificationOutcome = {
  verification_id: "verify_console_1",
  result: {
    adapter: "axis-postgres-source-discovery",
    status: "source_verified",
    block_reason: "",
    database_name: "axis",
    evidence_summary: {},
    notes: [],
  },
  correlation_ref: `source-verify://${TENANT_ID}/external_db_operational_mirror/v1`,
};

const discoveryOutcome = {
  discovery_id: "discovery_console_1",
  result: {
    adapter: "axis-postgres-source-discovery",
    status: "discovery_completed",
    block_reason: "",
    discovered_schema: "operations",
    tables: [
      {
        schema_name: "operations",
        table_name: "production_orders",
        column_names: ["order_id", "asset_id"],
        column_fingerprint: "a".repeat(64),
        schema_fingerprint_version: "postgres_schema_v2",
        columns_truncated: false,
      },
    ],
    tables_truncated: false,
    evidence_summary: {},
    notes: [],
  },
  observations: [
    {
      table_name: "production_orders",
      observation: {
        resource_name: "operations.production_orders",
        schema_fingerprint: "a".repeat(64),
        previous_fingerprint: null,
        drift_state: "added",
        last_source_kind: "postgres_discovery",
        first_seen_at: "2026-08-23T07:00:00Z",
        last_seen_at: "2026-08-23T07:00:00Z",
        observation_count: 1,
        observed_by: "operator",
      },
    },
  ],
  correlation_ref: `source-discovery://${TENANT_ID}/external_db_operational_mirror/d1`,
};

const registriesFixture = {
  credentialLeases: {
    data: {
      leases: [
        {
          lease_id: "lease_external_db_readonly_001",
          connector_id: "external_db_operational_mirror",
          handle_id: "cred_external_db_readonly",
          status: "active",
          expires_at: "2099-01-01T00:00:00Z",
        },
      ],
    },
  },
  egressPolicies: {
    data: {
      policies: [
        {
          policy_id: "egress_policy_private_endpoint_ops",
          connector_id: "external_db_operational_mirror",
          connection_profile_id: "profile_postgres_discovery_readonly",
          status: "active",
          policy_mode: "approved_private_endpoint",
        },
      ],
    },
  },
} as never;

function renderPanel(connector: ConnectorRegistryItem = dbConnectorFixture) {
  return render(
    <ToastProvider>
      <ConnectorSourceDiscoveryPanel
        connector={connector}
        identitySession={null}
        registries={registriesFixture}
        tenantId={TENANT_ID}
      />
    </ToastProvider>,
  );
}

describe("ConnectorSourceDiscoveryPanel", () => {
  beforeEach(() => {
    mocks.axisFetch.mockReset();
  });

  it("marks prerequisites ready when an active lease and policy exist", () => {
    renderPanel();

    const list = screen.getByRole("list", { name: /What you need/i });
    expect(list).toHaveTextContent("An active credential lease for this connector");
    expect(screen.getAllByText("Ready")).toHaveLength(2);
    // Lease and egress IDs are prefilled from the real tenant records.
    expect(
      screen.getByLabelText("Credential lease ID") as HTMLInputElement,
    ).toHaveValue("lease_external_db_readonly_001");
    expect(
      screen.getByLabelText("Egress policy ID") as HTMLInputElement,
    ).toHaveValue("egress_policy_private_endpoint_ops");
  });

  it("prefills references when registries resolve after first paint", () => {
    // The E2E race this regression locks in: one registry (leases) resolves
    // before mount, the other (policies) after; both inputs must end up
    // filled because prefill stays derived until the operator overrides.
    const empty = {
      credentialLeases: { data: undefined },
      egressPolicies: { data: undefined },
    } as never;
    const { rerender } = render(
      <ToastProvider>
        <ConnectorSourceDiscoveryPanel
          connector={dbConnectorFixture}
          identitySession={null}
          registries={empty}
          tenantId={TENANT_ID}
        />
      </ToastProvider>,
    );
    expect(screen.getByLabelText("Credential lease ID")).toHaveValue("");

    rerender(
      <ToastProvider>
        <ConnectorSourceDiscoveryPanel
          connector={dbConnectorFixture}
          identitySession={null}
          registries={registriesFixture}
          tenantId={TENANT_ID}
        />
      </ToastProvider>,
    );
    expect(
      screen.getByLabelText("Credential lease ID") as HTMLInputElement,
    ).toHaveValue("lease_external_db_readonly_001");
    expect(
      screen.getByLabelText("Egress policy ID") as HTMLInputElement,
    ).toHaveValue("egress_policy_private_endpoint_ops");
  });

  it("keeps an explicit operator override over the registry prefill", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.clear(screen.getByLabelText("Credential lease ID"));
    await user.type(screen.getByLabelText("Credential lease ID"), "lease_manual_ref");

    expect(
      screen.getByLabelText("Credential lease ID") as HTMLInputElement,
    ).toHaveValue("lease_manual_ref");
  });

  it("verifies the source through the tenant-scoped API path", async () => {
    const user = userEvent.setup();
    renderPanel();

    mocks.axisFetch.mockResolvedValue(okResponse(verificationOutcome));
    await user.click(screen.getByRole("button", { name: "Verify connection" }));

    await waitFor(() =>
      expect(screen.getByText(/Connected read-only to database/)).toBeInTheDocument(),
    );
    expect(mocks.axisFetch).toHaveBeenCalledTimes(1);
    const [path, options] = mocks.axisFetch.mock.calls[0];
    expect(path).toBe(VERIFY_PATH);
    expect(options.body.actor_scopes).toEqual(["connectors:source:discover"]);
    expect(options.body.credential_lease_id).toBe("lease_external_db_readonly_001");
    expect(options.body).not.toHaveProperty("credential_lease_result");
  });

  it("renders discovered tables with catalog drift states", async () => {
    const user = userEvent.setup();
    renderPanel();

    mocks.axisFetch.mockResolvedValue(okResponse(discoveryOutcome));
    await user.click(screen.getByRole("button", { name: "Discover tables" }));

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    const table = screen.getByRole("table");
    expect(table).toHaveTextContent("operations.production_orders");
    expect(table).toHaveTextContent("order_id, asset_id");
    expect(table).toHaveTextContent("New");
    expect(mocks.axisFetch.mock.calls[0][0]).toBe(DISCOVER_PATH);
    expect(mocks.axisFetch.mock.calls[0][1].body.schema_name).toBe("operations");
  });

  it("maps runtime blocks to their operator copy without a request failure", async () => {
    const user = userEvent.setup();
    renderPanel();

    const blocked = structuredClone(discoveryOutcome);
    blocked.result.status = "discovery_blocked_source_unreachable";
    blocked.result.block_reason = "source_unreachable";
    blocked.result.tables = [];
    blocked.observations = [];
    mocks.axisFetch.mockResolvedValue(okResponse(blocked));

    await user.click(screen.getByRole("button", { name: "Discover tables" }));

    await waitFor(() =>
      expect(
        screen.getByText(/The source did not answer within its timeout/),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("names the missing grant on a scope denial", async () => {
    const user = userEvent.setup();
    renderPanel();

    mocks.axisFetch.mockResolvedValue(deniedResponse("missing_scope:connectors:source:discover"));
    await user.click(screen.getByRole("button", { name: "Verify connection" }));

    await waitFor(() =>
      expect(
        screen.getAllByText(/connectors:source:discover/).length,
      ).toBeGreaterThan(0),
    );
  });

  async function discoverTables() {
    const user = userEvent.setup();
    renderPanel();
    const twoTableOutcome = structuredClone(discoveryOutcome);
    twoTableOutcome.result.tables.push({
      schema_name: "operations",
      table_name: "quality_checks",
      column_names: ["check_id"],
      column_fingerprint: "b".repeat(64),
      schema_fingerprint_version: "postgres_schema_v2",
      columns_truncated: false,
    });
    twoTableOutcome.observations.push({
      table_name: "quality_checks",
      observation: {
        resource_name: "operations.quality_checks",
        schema_fingerprint: "b".repeat(64),
        previous_fingerprint: null,
        drift_state: "added",
        last_source_kind: "postgres_discovery",
        first_seen_at: "2026-08-23T07:00:00Z",
        last_seen_at: "2026-08-23T07:00:00Z",
        observation_count: 1,
        observed_by: "operator",
      },
    });
    mocks.axisFetch.mockResolvedValue(okResponse(twoTableOutcome));
    await user.click(screen.getByRole("button", { name: "Discover tables" }));
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    return user;
  }

  it("reveals the activation panel only after a table is selected", async () => {
    const user = await discoverTables();

    expect(screen.queryByRole("region", { name: /Activate selected tables/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Activate: operations.production_orders" }));
    expect(screen.getByText("1 table selected")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Activate: operations.quality_checks" }));
    expect(screen.getByText("2 tables selected")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Activate: operations.quality_checks" }));
    expect(screen.getByText("1 table selected")).toBeInTheDocument();
  });

  it("requires a governance reason before activation can run", async () => {
    const user = await discoverTables();
    await user.click(screen.getByRole("checkbox", { name: "Activate: operations.production_orders" }));

    const activateButton = screen.getByRole("button", { name: "Activate 1 table" });
    expect(activateButton).toBeDisabled();

    await user.type(screen.getByLabelText("Activation reason"), "Bind for governed ingestion");
    expect(activateButton).toBeEnabled();
  });

  it("activates selected tables through the tenant-scoped API path and clears selection", async () => {
    const user = await discoverTables();
    await user.click(screen.getByRole("checkbox", { name: "Activate: operations.production_orders" }));
    await user.type(
      screen.getByLabelText("Activation reason"),
      "Bind for governed ingestion",
    );

    await user.type(
      screen.getByLabelText(/Existing binding to replace/),
      "binding_reviewed_predecessor",
    );
    const activationOutcome = {
      tenant_id: TENANT_ID,
      connector_id: "external_db_operational_mirror",
      activation_id: "activation_console_1",
      bindings: [
        {
          binding_id: "binding_console_1",
          resource_name: "operations.production_orders",
          schema_fingerprint: "a".repeat(64),
          status: "active",
          ingestion_status: "pending_ingestion",
          outcome: "activated",
          connection_profile_id: "profile_postgres_discovery_readonly",
          activated_by: "connector-console-operator",
          activated_at: "2026-08-23T08:00:00Z",
        },
      ],
      correlation_ref: `source-activation://${TENANT_ID}/external_db_operational_mirror/a1`,
    };
    mocks.axisFetch.mockResolvedValueOnce(okResponse(activationOutcome));

    await user.click(screen.getByRole("button", { name: "Activate 1 table" }));

    await waitFor(() =>
      expect(screen.getByText("Activated 1 binding")).toBeInTheDocument(),
    );
    const [path, options] = mocks.axisFetch.mock.calls.at(-1)!;
    expect(path).toBe(ACTIVATION_PATH);
    expect(options.body.actor_scopes).toEqual(["connectors:source:activate"]);
    expect(options.body.activation_reason).toBe("Bind for governed ingestion");
    expect(options.body.credential_lease_id).toBe("lease_external_db_readonly_001");
    expect(options.body.egress_policy_id).toBe("egress_policy_private_endpoint_ops");
    expect(options.body.selections).toEqual([
      {
        binding_id: expect.stringMatching(/^binding_console_[0-9a-f]+$/),
        resource_name: "operations.production_orders",
        expected_schema_fingerprint: "a".repeat(64),
        expected_schema_fingerprint_version: "postgres_schema_v2",
        supersedes_binding_id: "binding_reviewed_predecessor",
      },
    ]);
    // Success resets the journey and refreshes persisted views.
    expect(mocks.triggerRefresh).toHaveBeenCalled();
    expect(
      screen.queryByRole("checkbox", { name: "Activate: operations.production_orders" }),
    ).not.toBeInTheDocument();
    // The journey never claims row data moved: no sync language anywhere.
    expect(document.body.textContent ?? "").not.toMatch(/\bsynced\b|synchron/i);
  });

  it("maps an activation scope denial to the grant that is missing", async () => {
    const user = await discoverTables();
    await user.click(screen.getByRole("checkbox", { name: "Activate: operations.production_orders" }));
    await user.type(screen.getByLabelText("Activation reason"), "Bind");

    mocks.axisFetch.mockResolvedValueOnce(
      deniedResponse("missing_scope:connectors:source:activate"),
    );
    await user.click(screen.getByRole("button", { name: "Activate 1 table" }));

    await waitFor(() =>
      expect(
        screen.getAllByText(/missing the source activation scope/).length,
      ).toBeGreaterThan(0),
    );
    expect(screen.queryByText(/Activated 1 binding/)).not.toBeInTheDocument();
  });

  it("maps a binding conflict to honest recovery copy", async () => {
    const user = await discoverTables();
    await user.click(screen.getByRole("checkbox", { name: "Activate: operations.production_orders" }));
    await user.type(screen.getByLabelText("Activation reason"), "Bind");

    mocks.axisFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: {
            code: "conflict",
            message: "conflict",
            reason: "binding_already_active",
          },
        }),
        { status: 409, headers: { "content-type": "application/json", "x-request-id": "req-conflict" } },
      ),
    );
    await user.click(screen.getByRole("button", { name: "Activate 1 table" }));

    await waitFor(() =>
      expect(
        screen.getAllByText(/already has an active binding/).length,
      ).toBeGreaterThan(0),
    );
    expect(screen.queryByText(/Activated 1 binding/)).not.toBeInTheDocument();
  });

  it("toggles a table selection from the keyboard alone", async () => {
    const user = await discoverTables();

    const checkbox = screen.getByRole("checkbox", {
      name: "Activate: operations.production_orders",
    });
    checkbox.focus();
    expect(checkbox).toHaveFocus();

    await user.keyboard(" ");
    expect(screen.getByText("1 table selected")).toBeInTheDocument();

    await user.keyboard(" ");
    expect(screen.queryByText(/table selected/)).not.toBeInTheDocument();
  });

  it("maps a stale-fingerprint rejection to honest operator copy", async () => {
    const user = await discoverTables();
    await user.click(screen.getByRole("checkbox", { name: "Activate: operations.production_orders" }));
    await user.type(screen.getByLabelText("Activation reason"), "Bind");

    mocks.axisFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: {
            code: "validation_failed",
            message: "stale",
            reason: "schema_fingerprint_stale",
            selection_index: 0,
          },
        }),
        { status: 422, headers: { "content-type": "application/json", "x-request-id": "req-stale" } },
      ),
    );
    await user.click(screen.getByRole("button", { name: "Activate 1 table" }));

    await waitFor(() =>
      expect(
        screen.getAllByText(/changed since it was discovered|schema changed since discovery/i)
          .length,
      ).toBeGreaterThan(0),
    );
    expect(screen.queryByText(/Activated 1 binding/)).not.toBeInTheDocument();
  });
});
