import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConnectorRunRecord } from "@/lib/connectors-demo";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import type { ConnectorRegistries } from "@/lib/use-connector-registries";

import {
  connectorEndpointFixtures,
  csvConnectorFixture,
  dbConnectorFixture,
  runRegistryFixture,
} from "./connector-fixtures";

const mocks = vi.hoisted(() => ({
  axisFetch: vi.fn(),
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

vi.mock("@/lib/ids", () => ({
  safeRandomUuid: () => "TOKEN-1234",
}));

import { ConnectorRuns } from "./runs";
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

function buildRegistries(
  overrides: Partial<Record<keyof ConnectorRegistries, { data: unknown; source: Source }>> = {},
): ConnectorRegistries {
  const paths: Partial<Record<keyof ConnectorRegistries, string>> = {
    registry: `${OPERATIONS_API_PREFIX}/connectors`,
    credentialHandles: `${OPERATIONS_API_PREFIX}/connectors/credential-handles`,
    credentialLeases: `${OPERATIONS_API_PREFIX}/connectors/credential-leases`,
    egressPolicies: `${OPERATIONS_API_PREFIX}/connectors/egress-policies`,
    runs: `${OPERATIONS_API_PREFIX}/connectors/runs`,
    evidenceInvariants:
      `${OPERATIONS_API_PREFIX}/connectors/evidence-invariants?tenant_id=tenant_demo_manufacturing`,
    evidenceSnapshots:
      `${OPERATIONS_API_PREFIX}/connectors/evidence-invariants/snapshots?tenant_id=tenant_demo_manufacturing`,
  };

  return Object.fromEntries(
    Object.entries(paths).map(([key, path]) => {
      const override = overrides[key as keyof ConnectorRegistries];
      return [
        key,
        override
          ? queryResult(override.data, override.source)
          : queryResult(connectorEndpointFixtures[path], "api"),
      ];
    }),
  ) as unknown as ConnectorRegistries;
}

let currentIdentity: IdentitySessionReadModel | null = null;

function mockIdentity(
  identity: { authenticated: boolean; actor_id: string | null; api_auth_required?: boolean } | null,
) {
  currentIdentity = identity
    ? {
        ...identity,
        api_auth_required: identity.api_auth_required ?? false,
        audience: "axis-console",
        capabilities: [],
        enterprise_sso_ready: false,
        expires_at: null,
        issuer: "test",
        jwks_source: "test",
        limitations: [],
        mode: "test",
        notes: [],
        unauthenticated_reason: null,
        readiness_status: "ready",
        scopes: [],
        session_boundary: "test",
        tenant_id: "tenant_demo_manufacturing",
      }
    : null;
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function runRecord(overrides: Partial<ConnectorRunRecord>): ConnectorRunRecord {
  return { ...runRegistryFixture.runs[0], ...overrides };
}

function renderRuns(
  registries: ConnectorRegistries = buildRegistries(),
  tenantId = "tenant_demo_manufacturing",
) {
  return render(
    <ConnectorRuns
      connector={csvConnectorFixture}
      identitySession={currentIdentity}
      registries={registries}
      tenantId={tenantId}
    />,
  );
}

beforeEach(() => {
  mocks.axisFetch.mockReset();
  mocks.triggerRefresh.mockReset();
  mockIdentity({ authenticated: true, actor_id: "plant-operations-owner-role" });
});

describe("ConnectorRuns list states", () => {
  it("lists recorded runs with audit links", () => {
    renderRuns();

    const table = screen.getByRole("table", { name: "Governed runs" });
    expect(within(table).getByText("run_seeded_1")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Open audit" })).toHaveAttribute(
      "href",
      expect.stringContaining("audit-run-1"),
    );
  });

  it("shows an explicit empty state when no runs exist for the connector", () => {
    renderRuns(
      buildRegistries({
        runs: { data: { ...runRegistryFixture, runs: [] }, source: "api" },
      }),
    );

    expect(
      screen.getByText("No runs are recorded for this connector yet."),
    ).toBeInTheDocument();
  });

  it("shows an ErrorPanel when the runs registry is unavailable", () => {
    renderRuns(buildRegistries({ runs: { data: null, source: "unavailable" } }));

    expect(
      screen.getByRole("heading", { name: "Connector run records could not be loaded." }),
    ).toBeInTheDocument();
  });

  it("keeps validated stale runs visible when a refresh fails", () => {
    renderRuns(
      buildRegistries({
        runs: { data: runRegistryFixture, source: "unavailable" },
      }),
    );

    expect(screen.getByRole("table", { name: "Governed runs" })).toBeInTheDocument();
    expect(
      screen.getByText("Live refresh failed. Showing the last validated run data."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Connector run records could not be loaded." }),
    ).not.toBeInTheDocument();
  });
});

describe("ConnectorRuns validate action", () => {
  it("re-runs the CSV preview with the recorded sample and reports the result inline", async () => {
    const user = userEvent.setup();
    mocks.axisFetch.mockResolvedValueOnce(
      jsonResponse({
        tenant_id: "tenant_acme",
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
    );
    renderRuns(buildRegistries(), "tenant_acme");

    await user.click(screen.getByRole("button", { name: "Validate" }));

    expect(await screen.findByText("Validation passed")).toBeInTheDocument();
    expect(screen.getByText(/2 rows checked \/ 2 accepted \/ 0 rejected/)).toBeInTheDocument();

    const [path, options] = mocks.axisFetch.mock.calls[0];
    expect(path).toBe(`${OPERATIONS_API_PREFIX}/connectors/file-csv/preview`);
    expect(options.body).toEqual({
      tenant_id: "tenant_acme",
      connector_id: "file_csv_manufacturing_assets",
      file_name: "assets.csv",
      csv_content: "asset_id,asset_name\nast-1,CNC Mill\nast-2,Press",
    });
  });

  it("surfaces validation issues when the preview is blocked", async () => {
    const user = userEvent.setup();
    mocks.axisFetch.mockResolvedValueOnce(
      jsonResponse({
        tenant_id: "tenant_demo_manufacturing",
        connector_id: "file_csv_manufacturing_assets",
        file_name: "assets.csv",
        preview_status: "blocked",
        sync_mode: "preview_only",
        record_count: 2,
        accepted_record_count: 0,
        rejected_record_count: 2,
        validation_issues: ["Missing required column: asset_id"],
        proposed_entities: [],
        audit_event_preview: {
          event_type: "connector.preview.generated",
          scope: "file_csv_manufacturing_assets",
          actor_id: "connector-preview-service",
          result: "blocked",
          evidence_refs: [],
          payload_preview: {},
        },
        preview_notes: [],
      }),
    );
    renderRuns();

    await user.click(screen.getByRole("button", { name: "Validate" }));

    expect(await screen.findByText("Validation found issues")).toBeInTheDocument();
    expect(screen.getByText("Missing required column: asset_id")).toBeInTheDocument();
  });

  it("drops a validate response that arrives after the selected connector changed", async () => {
    const user = userEvent.setup();
    let resolveFetch: (value: Response) => void = () => {};
    mocks.axisFetch.mockImplementationOnce(
      () => new Promise<Response>((resolve) => { resolveFetch = resolve; }),
    );
    const registries = buildRegistries();
    const { rerender } = renderRuns(registries, "tenant_demo_manufacturing");

    await user.click(screen.getByRole("button", { name: "Validate" }));

    // The operator selects a different connector while connector A's
    // preview request is still in flight. Without a tenant/id check on
    // commit, A's response used to land in whatever connector is current.
    rerender(
      <ConnectorRuns
        connector={dbConnectorFixture}
        identitySession={currentIdentity}
        registries={registries}
        tenantId="tenant_demo_manufacturing"
      />,
    );

    resolveFetch(
      jsonResponse({
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
    );

    await waitFor(() => expect(mocks.axisFetch).toHaveResolvedTimes(1));

    expect(screen.queryByText("Validation passed")).not.toBeInTheDocument();
    // The stale response must not wedge the button disabled either.
    expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled();
  });
});

describe("ConnectorRuns preview-sync stepper", () => {
  it("runs create -> dispatch -> execute with idempotent payloads and links audit evidence", async () => {
    const user = userEvent.setup();
    mocks.axisFetch
      .mockResolvedValueOnce(
        jsonResponse(
          runRecord({
            run_id: "run_console_token1234",
            status: "sync_schedule_deferred",
            audit_event_id: "audit-create",
          }),
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          runRecord({
            run_id: "run_console_token1234",
            status: "sync_dispatch_deferred",
            dispatch_result: {
              adapter: "deferred-sync-dispatch",
              status: "sync_dispatch_deferred",
              dispatch_ref: "dispatch://deferred",
              external_sync_started: false,
              idempotency_key: "idem_dispatch_console_token1234",
              result_summary: {},
              notes: [],
            },
            audit_event_id: "audit-dispatch",
          }),
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          runRecord({
            run_id: "run_console_token1234",
            status: "sync_execution_deferred",
            sync_execution_result: {
              adapter: "deferred-sync-execution",
              status: "sync_execution_deferred",
              sync_ref: "sync://deferred",
              external_sync_started: false,
              idempotency_key: "idem_exec_console_token1234",
              result_summary: {},
              notes: [],
            },
            audit_event_id: "audit-execute",
          }),
        ),
      );
    renderRuns();

    await user.click(screen.getByRole("button", { name: "Run sync (preview)" }));

    await waitFor(() => expect(screen.getAllByText("Completed")).toHaveLength(3));

    const [createPath, createOptions] = mocks.axisFetch.mock.calls[0];
    expect(createPath).toBe(`${OPERATIONS_API_PREFIX}/connectors/runs`);
    expect(createOptions.body).toMatchObject({
      tenant_id: "tenant_demo_manufacturing",
      connector_id: "file_csv_manufacturing_assets",
      run_id: "run_console_token1234",
      execution_mode: "scheduled_sync_plan",
      requested_by: "plant-operations-owner-role",
      credential_handle_ids: ["handle_csv_readonly"],
      credential_lease_id: "lease_csv_active",
      schedule_timezone: "UTC",
    });

    const [dispatchPath, dispatchOptions] = mocks.axisFetch.mock.calls[1];
    expect(dispatchPath).toBe(
      `${OPERATIONS_API_PREFIX}/connectors/runs/run_console_token1234/dispatch`,
    );
    expect(dispatchOptions.body).toMatchObject({
      dispatch_id: "dispatch_console_token1234",
      actor_scopes: ["connectors:sync:dispatch"],
      credential_lease_id: "lease_csv_active",
      idempotency_key: "idem_dispatch_console_token1234",
    });

    const [executePath, executeOptions] = mocks.axisFetch.mock.calls[2];
    expect(executePath).toBe(
      `${OPERATIONS_API_PREFIX}/connectors/runs/run_console_token1234/execute-sync`,
    );
    expect(executeOptions.body).toMatchObject({
      execution_id: "exec_console_token1234",
      actor_scopes: ["connectors:sync:execute"],
      idempotency_key: "idem_exec_console_token1234",
    });

    const auditLinks = screen.getAllByRole("link", { name: "Open audit" });
    expect(
      auditLinks.some((link) => link.getAttribute("href")?.includes("audit-execute")),
    ).toBe(true);
    expect(mocks.triggerRefresh).toHaveBeenCalled();
  });

  it("shows a stage-scoped error and stops when dispatch fails", async () => {
    const user = userEvent.setup();
    mocks.axisFetch
      .mockResolvedValueOnce(
        jsonResponse(runRecord({ status: "sync_schedule_deferred" }), 201),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: {
              message: "The actor cannot dispatch scheduled connector sync.",
              required_permission: "connectors:sync:dispatch",
            },
          },
          403,
        ),
      );
    renderRuns();

    await user.click(screen.getByRole("button", { name: "Run sync (preview)" }));

    expect(
      await screen.findByRole("heading", { name: "Dispatch sync failed" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("The actor cannot dispatch scheduled connector sync."),
    ).toBeInTheDocument();
    // The execute stage never fires after a dispatch failure.
    expect(mocks.axisFetch).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Waiting")).toBeInTheDocument();
  });

  it("disables the sync action with the SSO message when unauthenticated", () => {
    mockIdentity({ authenticated: false, actor_id: null, api_auth_required: true });
    renderRuns();

    expect(screen.getByRole("button", { name: "Run sync (preview)" })).toBeDisabled();
    expect(
      screen.getByText("Sign in with SSO to run governed syncs."),
    ).toBeInTheDocument();
  });

  it("disables the sync action when no active credential lease exists", () => {
    renderRuns(
      buildRegistries({
        credentialLeases: {
          data: {
            ...connectorEndpointFixtures[
              `${OPERATIONS_API_PREFIX}/connectors/credential-leases`
            ] as object,
            leases: [],
          },
          source: "api",
        },
      }),
    );

    expect(screen.getByRole("button", { name: "Run sync (preview)" })).toBeDisabled();
    expect(screen.getByText(/needs an active credential lease/)).toBeInTheDocument();
  });
});
