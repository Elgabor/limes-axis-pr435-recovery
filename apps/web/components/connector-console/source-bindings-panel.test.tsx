import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

import { ConnectorSourceBindingsSection } from "./source-bindings-panel";

const TENANT_ID = "tenant_demo_manufacturing";
const CONNECTOR_ID = "external_db_operational_mirror";
const BINDINGS_PATH =
  `${OPERATIONS_API_PREFIX}/connectors/external-db/source-bindings`
  + `?tenant_id=${TENANT_ID}&connector_id=${CONNECTOR_ID}`;

const persistedBinding = {
  binding_id: "binding_console_1",
  resource_name: "operations.production_orders",
  schema_fingerprint: "a".repeat(64),
  status: "active",
  ingestion_status: "pending_ingestion",
  outcome: "activated",
  connection_profile_id: "profile_postgres_discovery_readonly",
  activated_by: "connector-console-operator",
  activated_at: "2026-08-23T08:00:00Z",
};

function apiQuery(bindings: unknown[]) {
  return {
    source: "api",
    data: {
      tenant_id: TENANT_ID,
      connector_id: CONNECTOR_ID,
      bindings,
    },
  };
}

describe("ConnectorSourceBindingsSection", () => {
  beforeEach(() => {
    mocks.useAxisQuery.mockReset();
  });

  it("queries the tenant-scoped persisted bindings path", () => {
    mocks.useAxisQuery.mockReturnValue(apiQuery([persistedBinding]));

    render(<ConnectorSourceBindingsSection connectorId={CONNECTOR_ID} tenantId={TENANT_ID} />);

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      BINDINGS_PATH,
      expect.objectContaining({ parse: expect.any(Function) }),
    );
  });

  it("renders persisted bindings as Active plus Pending ingestion", () => {
    mocks.useAxisQuery.mockReturnValue(apiQuery([persistedBinding]));

    const { container } = render(
      <ConnectorSourceBindingsSection connectorId={CONNECTOR_ID} tenantId={TENANT_ID} />,
    );

    const table = screen.getByRole("table", { name: "Active source bindings" });
    expect(table).toHaveTextContent("operations.production_orders");
    expect(table).toHaveTextContent("a".repeat(12));
    // Durable truth stays honest: active for governance, pending for data.
    expect(table).toHaveTextContent("Active");
    expect(table).toHaveTextContent("Pending ingestion");
    expect(container.textContent ?? "").not.toMatch(/\bsynced\b|synchron/i);
  });

  it("renders the honest empty state before anything is bound", () => {
    mocks.useAxisQuery.mockReturnValue(apiQuery([]));

    render(<ConnectorSourceBindingsSection connectorId={CONNECTOR_ID} tenantId={TENANT_ID} />);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.getByText(/No discovered table is bound for ingestion yet/),
    ).toBeInTheDocument();
  });

  it("renders an explicit failure state instead of invented rows", () => {
    mocks.useAxisQuery.mockReturnValue({ source: "unavailable" });

    render(<ConnectorSourceBindingsSection connectorId={CONNECTOR_ID} tenantId={TENANT_ID} />);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.getByText(/^Bindings unavailable:/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Nothing shown here is invented/),
    ).toBeInTheDocument();
  });

  it("renders a loading placeholder while the API answers", () => {
    mocks.useAxisQuery.mockReturnValue({ source: "loading" });

    render(<ConnectorSourceBindingsSection connectorId={CONNECTOR_ID} tenantId={TENANT_ID} />);

    expect(screen.getByRole("region", { name: "Active source bindings" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
