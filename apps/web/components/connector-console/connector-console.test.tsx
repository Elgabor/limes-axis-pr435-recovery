import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  connectorEndpointFixtures,
  connectorRegistryFixture,
  manifestDetailFixture,
  manifestRegistryFixture,
} from "./connector-fixtures";

const mocks = vi.hoisted(() => ({
  axisFetch: vi.fn(),
  useAxisQuery: vi.fn(),
  useConsoleTenantScope: vi.fn(),
  triggerRefresh: vi.fn(),
}));

vi.mock("@/lib/axis-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/axis-api")>();
  return {
    ...actual,
    axisFetch: mocks.axisFetch,
    axisFetchParsedJson: async <T,>(
      path: string,
      decoder: (value: unknown) => T,
      options: import("@/lib/axis-api").AxisFetchOptions = {},
    ): Promise<T> => {
      const response = await mocks.axisFetch(path, options) as Response;
      const requestId = actual.axisResponseRequestId(response);
      const body = await response.json();
      if (!response.ok) {
        throw new actual.AxisApiError(path, response.status, { body, requestId });
      }
      return actual.decodeAxisJson(path, body, decoder, requestId);
    },
  };
});

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-console-tenant-scope", () => ({
  IDENTITY_SESSION_ENDPOINT: "/identity/session",
  useConsoleTenantScope: mocks.useConsoleTenantScope,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({
    refreshNonce: 0,
    triggerRefresh: mocks.triggerRefresh,
    apiBaseUrl: "http://localhost:8000",
    apiStatus: { state: "ok", label: "Ready", detail: "" },
  }),
}));

import { ToastProvider } from "@/components/ui/toast";
import { ConnectorConsole } from "./index";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

type Source = "loading" | "api" | "unavailable";

function queryResult(data: unknown, source: Source) {
  return {
    data,
    source,
    error: source === "unavailable" ? "Axis API request failed." : null,
    isRefreshing: false,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
  };
}

/** Serve fixtures for every endpoint, with optional per-path overrides. */
function mockQueries(overrides: Record<string, { data: unknown; source: Source }> = {}) {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    const basePath = path.split("?")[0];
    const override = overrides[path] ?? overrides[basePath];
    if (override) {
      return queryResult(override.data, override.source);
    }
    const fixture = connectorEndpointFixtures[path]
      ?? connectorEndpointFixtures[basePath]
      ?? connectorEndpointFixtures[`${basePath}?tenant_id=tenant_demo_manufacturing`];
    if (fixture) {
      return queryResult(fixture, "api");
    }
    return queryResult(null, "loading");
  });
}

function renderConsole() {
  return render(
    <ToastProvider>
      <ConnectorConsole />
    </ToastProvider>,
  );
}

beforeEach(() => {
  mocks.axisFetch.mockReset();
  mocks.useAxisQuery.mockReset();
  mocks.useConsoleTenantScope.mockReset();
  mocks.triggerRefresh.mockReset();
  mocks.useConsoleTenantScope.mockReturnValue({
    identity: queryResult({
      authenticated: false,
      actor_id: null,
      api_auth_required: false,
      tenant_id: null,
    }, "api"),
    tenantScope: { mode: "demo", tenantId: "tenant_demo_manufacturing" },
    tenantId: "tenant_demo_manufacturing",
    tenantQueriesEnabled: true,
  });
  window.history.replaceState(null, "", "/connectors");
});

describe("ConnectorConsole states", () => {
  it("scopes every connector registry read to the verified tenant", () => {
    mocks.useConsoleTenantScope.mockReturnValue({
      identity: queryResult({
        authenticated: true,
        actor_id: "acme-owner",
        api_auth_required: true,
        tenant_id: "tenant_acme",
      }, "api"),
      tenantScope: { mode: "authenticated", tenantId: "tenant_acme" },
      tenantId: "tenant_acme",
      tenantQueriesEnabled: true,
    });
    mockQueries();
    renderConsole();

    const connectorCalls = mocks.useAxisQuery.mock.calls.filter(
      ([path]) => typeof path === "string" && path.startsWith(`${OPERATIONS_API_PREFIX}/connectors`),
    );
    expect(new Set(connectorCalls.map(([path]) => path)).size).toBe(9);
    connectorCalls.forEach(([path, options]) => {
      expect(path).toContain("tenant_id=tenant_acme");
      expect(options).toMatchObject({ expectedTenantId: "tenant_acme" });
      expect(options.enabled).toBe(
        path.includes("/evidence-invariants/snapshots") ? false : true,
      );
    });
  });

  it("fails closed when the identity API cannot verify a tenant", () => {
    mocks.useConsoleTenantScope.mockReturnValue({
      identity: queryResult(null, "unavailable"),
      tenantScope: { mode: "unresolved", tenantId: null },
      tenantId: null,
      tenantQueriesEnabled: false,
    });
    mockQueries();
    renderConsole();

    expect(screen.getByRole("heading", { name: "Tenant identity unavailable" })).toBeInTheDocument();
    expect(
      mocks.useAxisQuery.mock.calls.every(([, options]) => options.enabled === false),
    ).toBe(true);
  });

  it("renders loading skeletons without error copy while the registry loads", () => {
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors`]: { data: null, source: "loading" },
    });
    renderConsole();

    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("renders the ErrorPanel when the registry API is unreachable", () => {
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors`]: { data: null, source: "unavailable" },
    });
    renderConsole();

    expect(
      screen.getByRole("heading", { name: "Connector API unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Local fallback connector records are disabled\./),
    ).toBeInTheDocument();
  });

  it("renders the EmptyPanel with a wizard CTA when the registry has zero connectors", async () => {
    const user = userEvent.setup();
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors`]: {
        data: { ...connectorRegistryFixture, connectors: [] },
        source: "api",
      },
    });
    renderConsole();

    expect(screen.getByRole("heading", { name: "No connectors yet" })).toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add your first connector" }));
    expect(screen.getByRole("dialog", { name: "Add connector" })).toBeInTheDocument();
  });

  it("uses connector registry provenance instead of treating every API payload as live", () => {
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors`]: {
        data: { ...connectorRegistryFixture, provenance: "reference_scenario" },
        source: "api",
      },
    });

    renderConsole();

    expect(screen.getByText("connector registry: reference scenario")).toBeInTheDocument();
    expect(screen.queryByText("connector registry: live")).not.toBeInTheDocument();
  });
});

describe("ConnectorConsole metrics", () => {
  it("renders exactly the five user-relevant metrics from the registries", () => {
    mockQueries();
    renderConsole();

    const metrics = screen.getAllByRole("listitem");
    expect(metrics).toHaveLength(5);

    const labels = metrics.map(
      (metric) => within(metric).getAllByText(/.+/)[0].textContent,
    );
    expect(labels).toEqual([
      "Connectors",
      "Runs",
      "Pending proposals",
      "Egress policies",
      "Evidence issues",
    ]);
    expect(within(metrics[0]).getByText("2")).toBeInTheDocument();
    expect(within(metrics[1]).getByText("1")).toBeInTheDocument();
  });

  it("shows a placeholder value for a metric whose registry is unavailable", () => {
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors/egress-policies`]: { data: null, source: "unavailable" },
    });
    renderConsole();

    const metrics = screen.getAllByRole("listitem");
    expect(within(metrics[3]).getByText("—")).toBeInTheDocument();
  });
});

describe("ConnectorConsole list and detail", () => {
  beforeEach(() => {
    mockQueries();
  });

  it("lists connectors and shows the selected connector's detail tabs", () => {
    renderConsole();

    expect(
      screen.getByRole("button", { name: /Manufacturing assets CSV/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Manufacturing assets CSV" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Data & Schema" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Runs" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Governance & Evidence" })).toBeInTheDocument();
  });

  it("switches the detail panel when another connector is selected", async () => {
    const user = userEvent.setup();
    renderConsole();

    await user.click(screen.getByRole("button", { name: /Operational mirror DB/ }));
    expect(window.location.search).toContain("connector_id=external_db_operational_mirror");
    expect(
      screen.getByRole("heading", { name: "Operational mirror DB" }),
    ).toBeInTheDocument();
  });

  it("renders the exact snapshot requested by a deep link", () => {
    window.history.replaceState(
      null,
      "",
      "/connectors?snapshot_id=snapshot_fixture&connector_id=file_csv_manufacturing_assets",
    );
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors/evidence-invariants/snapshots`]: {
        source: "api",
        data: {
          tenant_id: "tenant_demo_manufacturing",
          plant_name: "Ravenna Works",
          scenario: "Plant Operations Cockpit",
          history_status: "ready",
          metrics: [],
          snapshots: [{
            tenant_id: "tenant_demo_manufacturing",
            snapshot_id: "snapshot_fixture",
            status: "persisted",
            connector_id: "file_csv_manufacturing_assets",
            requested_by: "fixture-operator",
            idempotency_key: "snapshot-fixture-key",
            reason: "Regression fixture",
            invariant_count: 1,
            invariant_counts: { credential_lease: 1 },
            subject_ids: ["lease_csv_active"],
            report_digest_sha256: "a".repeat(64),
            report_hash_algorithm: "sha256",
            permission_decision: { allowed: true, reason: "required_scope_present" },
            audit_event_id: null,
            audit_event_type: "connector.evidence_invariants.snapshot_persisted",
            idempotent_replay: false,
            notes: [],
          }],
          history_notes: [],
        },
      },
    });
    renderConsole();

    expect(
      screen.getByRole("heading", { name: "Requested evidence snapshot" }),
    ).toBeInTheDocument();
    expect(screen.getByText("snapshot_fixture")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Manufacturing assets CSV" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Governance & Evidence" })).toHaveAttribute(
      "data-state",
      "active",
    );
  });

  it("does not fall back to the first connector for an unknown snapshot", () => {
    window.history.replaceState(null, "", "/connectors?snapshot_id=snapshot_unknown");
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors/evidence-invariants/snapshots`]: {
        source: "api",
        data: {
          tenant_id: "tenant_demo_manufacturing",
          plant_name: "Ravenna Works",
          scenario: "Plant Operations Cockpit",
          history_status: "watch",
          metrics: [],
          snapshots: [],
          history_notes: [],
        },
      },
    });
    renderConsole();

    expect(
      screen.getByRole("heading", { name: "Requested snapshot is not available" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Manufacturing assets CSV" }),
    ).not.toBeInTheDocument();
  });

  it("shows the registered manifest state on the overview tab", () => {
    renderConsole();

    expect(screen.getByText("Registered manifest")).toBeInTheDocument();
    expect(screen.getAllByText("Active Preview").length).toBeGreaterThan(0);
    expect(screen.getByText("Current revision")).toBeInTheDocument();
    expect(screen.getByText("2", { selector: "dd" })).toBeInTheDocument();
    const history = screen.getByRole("table", { name: "Revision history" });
    expect(within(history).getByText("0.9.0")).toBeInTheDocument();
    expect(within(history).getByText("1.0.0")).toBeInTheDocument();
  });

  it("renders the schema mapping and sample rows on the Data & Schema tab", async () => {
    const user = userEvent.setup();
    renderConsole();

    await user.click(screen.getByRole("tab", { name: "Data & Schema" }));
    expect(window.location.search).toContain("tab=schema");

    const mapping = screen.getByRole("table", { name: "Field mapping" });
    expect(within(mapping).getByText("asset_id")).toBeInTheDocument();
    expect(within(mapping).getAllByText("manufacturing_asset").length).toBeGreaterThan(0);

    const sample = screen.getByRole("table", { name: "Sample rows" });
    expect(within(sample).getByText("CNC Mill")).toBeInTheDocument();
  });

  it("renders never-sampled state in the connector list and detail", async () => {
    const user = userEvent.setup();
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors`]: {
        data: {
          ...connectorRegistryFixture,
          connectors: connectorRegistryFixture.connectors.map((connector, index) => (
            index === 0 ? { ...connector, preview_sample: null } : connector
          )),
        },
        source: "api",
      },
      [`${OPERATIONS_API_PREFIX}/connectors/manifests/file_csv_manufacturing_assets`]: {
        data: {
          ...manifestDetailFixture,
          current_revision: {
            ...manifestDetailFixture.current_revision,
            preview_sample: null,
          },
        },
        source: "api",
      },
    });
    renderConsole();

    expect(screen.getByText("Never sampled")).toBeInTheDocument();
    expect(screen.queryByText("0 sample rows")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Data & Schema" }));

    expect(screen.getByText("This connector has never been sampled.")).toBeInTheDocument();
    expect(screen.queryByText("No sample rows are recorded for this connector.")).not.toBeInTheDocument();
  });

  it("labels a recorded preview sample distinctly from sync evidence", () => {
    renderConsole();

    const connector = screen.getByRole("button", { name: /Manufacturing assets CSV/ });
    expect(within(connector).getByText("2 sample rows")).toBeInTheDocument();
    expect(within(connector).getByText("Preview sample")).toBeInTheDocument();
    expect(within(connector).queryByText(/Successful sync/)).not.toBeInTheDocument();
  });

  it("renders successful sync evidence ahead of an existing preview sample", () => {
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors`]: {
        data: {
          ...connectorRegistryFixture,
          connectors: connectorRegistryFixture.connectors.map((connector, index) => (
            index === 0
              ? {
                  ...connector,
                  last_successful_sync: {
                    run_id: "run_assets_20260724",
                    completed_at: "2026-07-24T10:30:00Z",
                    records_read: 37,
                  },
                }
              : connector
          )),
        },
        source: "api",
      },
    });
    renderConsole();

    const connector = screen.getByRole("button", { name: /Manufacturing assets CSV/ });
    expect(within(connector).getByText("37 records observed")).toBeInTheDocument();
    expect(
      within(connector).getByText(
        /Successful sync · .+ · run run_assets_20260724/,
      ),
    ).toBeInTheDocument();
    expect(within(connector).queryByText("2 sample rows")).not.toBeInTheDocument();
    expect(within(connector).queryByText("Preview sample")).not.toBeInTheDocument();
  });

  it("renders governance records with plain sections instead of metric tiles", async () => {
    const user = userEvent.setup();
    renderConsole();

    await user.click(screen.getByRole("tab", { name: "Governance & Evidence" }));

    expect(screen.getByText("Credential handles")).toBeInTheDocument();
    expect(screen.getByText("CSV read-only handle")).toBeInTheDocument();
    expect(screen.getByText("Credential leases")).toBeInTheDocument();
    // "Egress policies" appears both as a metric label and a governance section.
    expect(screen.getAllByText("Egress policies")).toHaveLength(2);
    // The db-scoped egress policy does not belong to the selected CSV connector.
    expect(
      screen.getByText("No egress policies are recorded for this connector."),
    ).toBeInTheDocument();
    expect(screen.getByText("Evidence invariants")).toBeInTheDocument();
    expect(
      screen.getByText(/Credential lease lease_csv_active has no linked audit event\./),
    ).toBeInTheDocument();
  });

  it("shows the evidence invariants error state when that registry is unavailable", async () => {
    const user = userEvent.setup();
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors/evidence-invariants`]: { data: null, source: "unavailable" },
    });
    renderConsole();

    await user.click(screen.getByRole("tab", { name: "Governance & Evidence" }));

    // `invariantReport?.invariants.length === 0` used to be `undefined === 0`
    // (false) when the fetch failed, so this error never rendered and the
    // section silently looked empty/clear instead.
    expect(
      screen.getByRole("heading", {
        name: "Evidence invariant findings could not be loaded.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("All evidence invariants hold — every governed record has audit evidence."),
    ).not.toBeInTheDocument();
  });

  it("lists recorded runs for the selected connector on the Runs tab", async () => {
    const user = userEvent.setup();
    renderConsole();

    await user.click(screen.getByRole("tab", { name: "Runs" }));

    const runsTable = screen.getByRole("table", { name: "Governed runs" });
    expect(within(runsTable).getByText("run_seeded_1")).toBeInTheDocument();
    expect(within(runsTable).getByText("Sync Schedule Deferred")).toBeInTheDocument();
  });

  it("opens the wizard from the header action", async () => {
    const user = userEvent.setup();
    renderConsole();

    await user.click(screen.getByRole("button", { name: "Add connector" }));
    expect(screen.getByRole("dialog", { name: "Add connector" })).toBeInTheDocument();
  });

  it("does not persist a validate result panel across a connector switch", async () => {
    const user = userEvent.setup();
    mocks.axisFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          tenant_id: "tenant_demo_manufacturing",
          connector_id: "file_csv_manufacturing_assets",
          file_name: "assets.csv",
          preview_status: "ready",
          sync_mode: "preview_only",
          record_count: 2,
          accepted_record_count: 2,
          rejected_record_count: 0,
          validation_issues: [],
          proposed_entities: [],
          audit_event_preview: {
            event_type: "connector.preview.generated",
            scope: "file_csv_manufacturing_assets",
            actor_id: "connector-preview-service",
            result: "ready",
            evidence_refs: [],
            payload_preview: {},
          },
          preview_notes: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    renderConsole();

    // Validate the CSV connector (Manufacturing assets CSV, selected by
    // default) and confirm the result panel commits.
    await user.click(screen.getByRole("tab", { name: "Runs" }));
    await user.click(screen.getByRole("button", { name: "Validate" }));
    expect(await screen.findByText("Validation passed")).toBeInTheDocument();

    // Switching to the other connector must remount the whole detail pane
    // (ConnectorDetail's `key`), clearing ConnectorRuns' validate state —
    // without the key, this used to keep showing connector A's result.
    await user.click(screen.getByRole("button", { name: /Operational mirror DB/ }));
    await user.click(screen.getByRole("tab", { name: "Runs" }));

    expect(screen.queryByText("Validation passed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validate" })).toBeInTheDocument();
  });
});

describe("ConnectorConsole persisted registry entries", () => {
  const wizardManifest = {
    ...manifestRegistryFixture.manifests[0],
    manifest_id: "manifest-wizard",
    connector_id: "file_csv_press_shop_assets",
    display_name: "Press shop assets",
    status: "registered_preview_only",
    manifest: {
      ...manifestRegistryFixture.manifests[0].manifest,
      connector_id: "file_csv_press_shop_assets",
      display_name: "Press shop assets",
    },
  };
  const wizardConnector = {
    ...connectorRegistryFixture.connectors[0],
    manifest: wizardManifest.manifest,
    runtime_policy: wizardManifest.runtime_policy,
    preview_sample: wizardManifest.preview_sample,
    last_successful_sync: null,
    connector_status: "watch" as const,
    registry_origin: "persisted_manifest" as const,
    persisted_manifest: {
      manifest_id: wizardManifest.manifest_id,
      revision_number: wizardManifest.revision_number,
      status: wizardManifest.status,
      registered_by: wizardManifest.registered_by,
      registered_at: wizardManifest.created_at,
      notes: wizardManifest.notes,
    },
  };

  function mockWithWizardManifest() {
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors`]: {
        data: {
          ...connectorRegistryFixture,
          connectors: [...connectorRegistryFixture.connectors, wizardConnector],
        },
        source: "api",
      },
      [`${OPERATIONS_API_PREFIX}/connectors/manifests/${wizardManifest.connector_id}`]: {
        data: {
          tenant_id: wizardManifest.tenant_id,
          connector_id: wizardManifest.connector_id,
          current_revision: wizardManifest,
          revisions: [wizardManifest],
        },
        source: "api",
      },
    });
  }

  it("shows a wizard-registered manifest in the list with its lifecycle state", () => {
    mockWithWizardManifest();
    renderConsole();

    const item = screen.getByRole("button", { name: /Press shop assets/ });
    expect(within(item).getByText("Registered Preview Only")).toBeInTheDocument();
  });

  it("counts reference plus persisted-unique connectors in the Connectors metric", () => {
    mockWithWizardManifest();
    renderConsole();

    const metrics = screen.getAllByRole("listitem");
    expect(within(metrics[0]).getByText("3")).toBeInTheDocument();
  });

  it("keeps persisted provenance and selected detail beyond the old 100-manifest boundary", () => {
    const persistedConnectors = Array.from({ length: 101 }, (_, index) => {
      const connectorId = `file_csv_scale_${index.toString().padStart(3, "0")}`;
      return {
        ...wizardConnector,
        manifest: {
          ...wizardConnector.manifest,
          connector_id: connectorId,
          display_name: `Scale fixture ${index.toString().padStart(3, "0")}`,
        },
        persisted_manifest: {
          ...wizardConnector.persisted_manifest,
          manifest_id: `manifest-scale-${index}`,
        },
      };
    });
    const oldestConnector = persistedConnectors[0];
    const oldestManifest = {
      ...wizardManifest,
      manifest_id: oldestConnector.persisted_manifest.manifest_id,
      connector_id: oldestConnector.manifest.connector_id,
      display_name: oldestConnector.manifest.display_name,
      manifest: oldestConnector.manifest,
    };
    window.history.replaceState(
      null,
      "",
      `/connectors?connector_id=${oldestConnector.manifest.connector_id}`,
    );
    const oldestDetailPath =
      `${OPERATIONS_API_PREFIX}/connectors/manifests/${oldestConnector.manifest.connector_id}`;
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors`]: {
        data: {
          ...connectorRegistryFixture,
          connectors: [...connectorRegistryFixture.connectors, ...persistedConnectors],
        },
        source: "api",
      },
      [oldestDetailPath]: {
        data: {
          tenant_id: oldestManifest.tenant_id,
          connector_id: oldestManifest.connector_id,
          current_revision: oldestManifest,
          revisions: [oldestManifest],
        },
        source: "api",
      },
    });

    renderConsole();

    const selectedItem = screen.getByRole("button", { name: /Scale fixture 000/ });
    expect(within(selectedItem).getByText("Registered Preview Only")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Scale fixture 000" })).toBeInTheDocument();
    expect(screen.getByText("Current revision")).toBeInTheDocument();
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      expect.stringContaining(oldestDetailPath),
      expect.objectContaining({ enabled: true }),
    );
  });

  it("uses the complete connector registry without requesting the capped manifest list", () => {
    mockQueries();
    renderConsole();

    const metrics = screen.getAllByRole("listitem");
    expect(within(metrics[0]).getByText("2")).toBeInTheDocument();
    expect(screen.queryByText("Registered")).not.toBeInTheDocument();
    expect(mocks.useAxisQuery.mock.calls.some(([path]) => (
      typeof path === "string"
      && path.split("?")[0] === `${OPERATIONS_API_PREFIX}/connectors/manifests`
    ))).toBe(false);
  });

  it("renders schema and runs for a persisted-only entry while gating sync by lifecycle", async () => {
    const user = userEvent.setup();
    mockWithWizardManifest();
    renderConsole();

    await user.click(screen.getByRole("button", { name: /Press shop assets/ }));
    expect(screen.getByRole("heading", { name: "Press shop assets" })).toBeInTheDocument();
    // Overview renders the persisted summary before the selected detail fetch.
    expect(screen.getAllByText("Registered Preview Only").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("tab", { name: "Runs" }));
    expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Run sync (preview)" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Preview sync needs a registered manifest in the active preview state before it can run.",
    );
    expect(screen.queryByText("Sync activation pending")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Data & Schema" }));
    const mapping = screen.getByRole("table", { name: "Field mapping" });
    expect(within(mapping).getByText("asset_id")).toBeInTheDocument();
    expect(screen.queryByText("Sync activation pending")).not.toBeInTheDocument();
  });

  it("uses current detail for persisted controls, schema and export when the registry is stale", async () => {
    const user = userEvent.setup();
    const authoritativeManifest = {
      ...wizardManifest.manifest,
      display_name: "Press shop assets current",
      version: "2.0.0",
      schema_fields: [
        {
          ...wizardManifest.manifest.schema_fields[0],
          source_column: "current_press_asset_id",
        },
      ],
    };
    const authoritativeRevision = {
      ...wizardManifest,
      revision_number: wizardManifest.revision_number + 1,
      display_name: authoritativeManifest.display_name,
      version: authoritativeManifest.version,
      status: "active_preview",
      manifest: authoritativeManifest,
      runtime_policy: {
        ...wizardManifest.runtime_policy,
        row_limit: 250,
      },
      revises_revision_number: wizardManifest.revision_number,
      revision_idempotency_key: "wizard-authoritative-revision",
      notes: ["authoritative detail"],
    };
    mockQueries({
      [`${OPERATIONS_API_PREFIX}/connectors`]: {
        data: {
          ...connectorRegistryFixture,
          connectors: [...connectorRegistryFixture.connectors, wizardConnector],
        },
        source: "api",
      },
      [`${OPERATIONS_API_PREFIX}/connectors/manifests/${wizardManifest.connector_id}`]: {
        data: {
          tenant_id: authoritativeRevision.tenant_id,
          connector_id: authoritativeRevision.connector_id,
          current_revision: authoritativeRevision,
          revisions: [wizardManifest, authoritativeRevision],
        },
        source: "api",
      },
    });
    renderConsole();

    await user.click(screen.getByRole("button", { name: /Press shop assets/ }));
    expect(
      screen.getByRole("heading", { name: "Press shop assets current" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Runs" }));
    expect(screen.getByRole("button", { name: "Run sync (preview)" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Preview sync needs an active credential lease for this connector before it can run.",
    );
    expect(screen.queryByText(/registered manifest in the active preview state/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Data & Schema" }));
    expect(
      within(screen.getByRole("table", { name: "Field mapping" })).getByText(
        "current_press_asset_id",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Export manifest" }));
    const exportDocuments = screen
      .getAllByLabelText("Registration document JSON")
      .filter((element) => element.hasAttribute("readonly"));
    expect(exportDocuments).toHaveLength(1);
    const parsedExport = JSON.parse((exportDocuments[0] as HTMLTextAreaElement).value);
    expect(parsedExport.manifest).toMatchObject({
      display_name: "Press shop assets current",
      version: "2.0.0",
      schema_fields: [expect.objectContaining({ source_column: "current_press_asset_id" })],
    });
    expect(parsedExport.runtime_policy.row_limit).toBe(250);
    expect(parsedExport.notes).toEqual(["authoritative detail"]);
  });
});
