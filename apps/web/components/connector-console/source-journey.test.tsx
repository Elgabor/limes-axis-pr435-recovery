import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

import {
  SOURCE_INGESTION_ENDPOINTS,
  buildSourceIngestionReadPath,
} from "@/lib/connectors-console";
import { OPERATIONS_API_PREFIX, buildTenantScopedPath } from "@/lib/tenant-scope";

import { SourceJourneySpine } from "./source-journey";

const TENANT_ID = "tenant_demo_manufacturing";
const CONNECTOR_ID = "external_db_operational_mirror";

const BINDINGS_PATH = buildTenantScopedPath(
  `${OPERATIONS_API_PREFIX}/connectors/external-db/source-bindings`,
  TENANT_ID,
  { connector_id: CONNECTOR_ID },
);
const OVERVIEW_PATH = buildSourceIngestionReadPath({
  endpoint: SOURCE_INGESTION_ENDPOINTS.overview,
  tenantId: TENANT_ID,
  connectorId: CONNECTOR_ID,
});

function binding(overrides: Record<string, unknown> = {}) {
  return {
    binding_id: "binding_journey_001",
    resource_name: "operations.production_orders",
    schema_fingerprint: "a".repeat(64),
    status: "active",
    ingestion_status: "pending_ingestion",
    outcome: "created",
    connection_profile_id: "profile_postgres_discovery_readonly",
    activated_by: "axis-operator",
    activated_at: "2026-08-23T08:00:00Z",
    ...overrides,
  };
}

function summary(overrides: Record<string, unknown> = {}) {
  return {
    status_counts: {},
    total_count: 0,
    dead_lettered_count: 0,
    extract_stage_count: 0,
    last_activity_at: null,
    ...overrides,
  };
}

function mockQueries({
  bindingsSource = "api" as string,
  overviewSource = "api" as string,
  bindings = [] as unknown[],
  overview = summary(),
} = {}) {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path === BINDINGS_PATH) {
      return {
        source: bindingsSource,
        data:
          bindingsSource === "api"
            ? { tenant_id: TENANT_ID, connector_id: CONNECTOR_ID, bindings }
            : null,
        isLoading: bindingsSource === "loading",
        isUnavailable: bindingsSource === "unavailable",
        isTenantNotFound: bindingsSource === "tenant_not_found",
      };
    }
    if (path === OVERVIEW_PATH) {
      return {
        source: overviewSource,
        data:
          overviewSource === "api"
            ? {
                tenant_id: TENANT_ID,
                connector_id: CONNECTOR_ID,
                summary: overview,
                requests: [],
                next_cursor: null,
              }
            : null,
        isLoading: overviewSource === "loading",
        isUnavailable: overviewSource === "unavailable",
        isTenantNotFound: overviewSource === "tenant_not_found",
      };
    }
    throw new Error(`Unexpected query path: ${path}`);
  });
}

describe("SourceJourneySpine", () => {
  beforeEach(() => {
    mocks.useAxisQuery.mockReset();
  });

  it("renders four honest to-do steps with prerequisites when nothing exists", () => {
    mockQueries();
    render(<SourceJourneySpine connectorId={CONNECTOR_ID} tenantId={TENANT_ID} />);
    expect(screen.getByText("Verify & discover")).toBeInTheDocument();
    expect(screen.getByText("Activate tables")).toBeInTheDocument();
    expect(screen.getByText("Request ingestion")).toBeInTheDocument();
    expect(screen.getByText("Validate & review evidence")).toBeInTheDocument();
    const stepOne = document.querySelector('[data-journey-step="verifyDiscover"]')!;
    expect(stepOne.textContent).toContain("Verify the connection and discover the schema");
    expect(stepOne.textContent).toContain("Next:");
    // Nothing may claim progress the API did not report.
    expect(document.body.textContent).not.toContain("Done");
  });

  it("marks verify/discover and activate done from durable bindings", () => {
    mockQueries({
      bindings: [binding()],
      overview: summary({ total_count: 2 }),
    });
    render(<SourceJourneySpine connectorId={CONNECTOR_ID} tenantId={TENANT_ID} />);
    const activate = document.querySelector('[data-journey-step="activate"]')!;
    expect(activate.textContent).toContain("Done");
    expect(activate.textContent).toContain("1 bound table(s) ready for ingestion.");
    const requested = document.querySelector('[data-journey-step="requestIngestion"]')!;
    expect(requested.textContent).toContain("2 governed request(s) raised.");
  });

  it("routes operators to remediation when requests are dead-lettered", () => {
    mockQueries({
      bindings: [binding({ ingestion_status: "ingested" })],
      overview: summary({
        total_count: 3,
        dead_lettered_count: 1,
        status_counts: { failed: 1, completed: 2 },
      }),
    });
    render(<SourceJourneySpine connectorId={CONNECTOR_ID} tenantId={TENANT_ID} />);
    const validate = document.querySelector('[data-journey-step="validate"]')!;
    expect(validate.textContent).toContain("Needs attention");
    expect(validate.textContent).toMatch(/Re-dispatch after remediation/);
    expect(validate.textContent).toMatch(/re-discover, re-activate/);
  });

  it("stays honest when either read model is unavailable", () => {
    mockQueries({ bindingsSource: "unavailable" });
    render(<SourceJourneySpine connectorId={CONNECTOR_ID} tenantId={TENANT_ID} />);
    expect(
      screen.getByText(/journey needs API-backed bindings and request data/),
    ).toBeInTheDocument();
  });
});
