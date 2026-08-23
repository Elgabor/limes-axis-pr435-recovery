import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
  axisFetch: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/axis-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/axis-api")>()),
  axisFetch: mocks.axisFetch,
}));

const consoleMocks = vi.hoisted(() => ({
  triggerRefresh: vi.fn(),
}));
vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ triggerRefresh: consoleMocks.triggerRefresh }),
}));

const toastMocks = vi.hoisted(() => ({
  push: vi.fn(),
}));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => toastMocks,
}));

import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";
import { SOURCE_INGESTION_ENDPOINTS } from "@/lib/connectors-console";

import { ConnectorSourceIngestionSection } from "./source-ingestion-panel";

const TENANT_ID = "tenant_demo_manufacturing";
const CONNECTOR_ID = "external_db_operational_mirror";

const ELIGIBILITY_PATH =
  `${SOURCE_INGESTION_ENDPOINTS.eligibility}`
  + `?tenant_id=${TENANT_ID}&connector_id=${CONNECTOR_ID}`
  + "&actor_scopes=connectors%3Asource%3Aingest%3Aread";
const REQUESTS_PATH =
  `${SOURCE_INGESTION_ENDPOINTS.requests}`
  + `?tenant_id=${TENANT_ID}&connector_id=${CONNECTOR_ID}`
  + "&actor_scopes=connectors%3Asource%3Aingest%3Aread";
const OVERVIEW_PATH =
  `${SOURCE_INGESTION_ENDPOINTS.overview}`
  + `?tenant_id=${TENANT_ID}&connector_id=${CONNECTOR_ID}`
  + "&actor_scopes=connectors%3Asource%3Aingest%3Aread";

const eligibleRow = {
  binding_id: "binding_console_eligible",
  resource_name: "operations.production_orders",
  schema_fingerprint: "a".repeat(64),
  eligible: true,
  blocked_reason: null,
};
const staleRow = {
  binding_id: "binding_console_stale",
  resource_name: "operations.inventory_snapshots",
  schema_fingerprint: "b".repeat(64),
  eligible: false,
  blocked_reason: "stale_fingerprint",
};
const notPendingRow = {
  binding_id: "binding_console_done",
  resource_name: "operations.shipment_lines",
  schema_fingerprint: "c".repeat(64),
  eligible: false,
  blocked_reason: "binding_not_pending_ingestion",
};

function requestView(overrides: Record<string, unknown> = {}) {
  return {
    tenant_id: TENANT_ID,
    connector_id: CONNECTOR_ID,
    request_id: "ingest_console_abc123",
    requested_by: "connector-console-operator",
    reason: "Nightly governed validation.",
    stage: "validate",
    status: "pending",
    attempt_count: 0,
    selections: [
      {
        binding_id: eligibleRow.binding_id,
        resource_name: eligibleRow.resource_name,
        schema_fingerprint: eligibleRow.schema_fingerprint,
      },
    ],
    outcome: "created",
    planned_limits: null,
    extraction: null,
    attempts: [],
    last_error: null,
    completed_at: null,
    dead_lettered_at: null,
    cancelled_at: null,
    created_at: "2026-08-23T08:00:00Z",
    updated_at: "2026-08-23T08:00:00Z",
    ...overrides,
  };
}

function batchesPage(count: number) {
  return {
    tenant_id: TENANT_ID,
    connector_id: CONNECTOR_ID,
    request_id: "ingest_console_abc123",
    total_count: count,
    next_cursor: null,
    batches: Array.from({ length: count }, (_, index) => ({
      batch_key: `ingest_console_abc123:binding_${index}:${index}`,
      binding_id: `binding_${index}`,
      resource_name: `operations.table_${index}`,
      pinned_schema_fingerprint: "a".repeat(64),
      observed_schema_fingerprint: "a".repeat(64),
      ordering_mode: "primary_key" as const,
      has_watermark: true,
      row_count: 12,
      byte_size: 256,
      truncated: index === 0,
      limit_reason: index === 0 ? "row_limit" : null,
      duration_ms: 40,
      digest_sha256: "b".repeat(64),
      storage_uri: `axis-local-object-store://tenants/x/b${index}.json`,
      content_type: "application/json",
      stored_size_bytes: 300,
      classification: "undeclared",
      executed_by: "axis-source-ingestion-outbox",
      created_at: "2026-08-23T08:00:00Z",
    })),
  };
}

/** Mirror the real hook surface so panel state helpers resolve truthfully. */
function queryResult(source: string, data: unknown) {
  return {
    source,
    data,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
    isTenantNotFound: source === "tenant_not_found",
  };
}

/** Route the two queries by path so each test controls both sections. */
function mockQueries({
  rows = [eligibleRow, staleRow, notPendingRow],
  requests = [] as unknown[],
  eligibilitySource = "api",
  requestsSource = "api",
  extractionAvailable = false,
  plannedLimits = null as Record<string, number> | null,
  batches = null as ReturnType<typeof batchesPage> | null,
  overviewSummary = {
    status_counts: {} as Record<string, number>,
    total_count: 0,
    dead_lettered_count: 0,
    extract_stage_count: 0,
    last_activity_at: null as string | null,
  },
  overviewSource = "api",
} = {}) {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path.includes("/batches?") || path.endsWith("/batches")) {
      return queryResult(batches ? "api" : "loading", batches);
    }
    if (path === OVERVIEW_PATH) {
      return queryResult(
        overviewSource,
        overviewSource === "api"
          ? {
              tenant_id: TENANT_ID,
              connector_id: CONNECTOR_ID,
              summary: overviewSummary,
              requests: [],
              next_cursor: null,
            }
          : null,
      );
    }
    if (path === ELIGIBILITY_PATH) {
      const data =
        eligibilitySource === "api"
          ? {
              tenant_id: TENANT_ID,
              connector_id: CONNECTOR_ID,
              extraction_available: extractionAvailable,
              planned_limits: plannedLimits,
              rows,
            }
          : null;
      return queryResult(eligibilitySource, data);
    }
    if (path === REQUESTS_PATH) {
      return queryResult(requestsSource, requestsSource === "api" ? requests : null);
    }
    throw new Error(`Unexpected query path: ${path}`);
  });
}

describe("ConnectorSourceIngestionSection", () => {
  beforeEach(() => {
    mocks.useAxisQuery.mockReset();
    mocks.axisFetch.mockReset();
    consoleMocks.triggerRefresh.mockReset();
    toastMocks.push.mockReset();
  });

  it("queries tenant-scoped read paths carrying the ingestion read scope", () => {
    mockQueries();
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      ELIGIBILITY_PATH,
      expect.objectContaining({ parse: expect.any(Function), expectedTenantId: TENANT_ID }),
    );
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      REQUESTS_PATH,
      expect.objectContaining({ parse: expect.any(Function), expectedTenantId: TENANT_ID }),
    );
  });

  it("renders honest eligibility states: eligible plus precise blocked reasons", () => {
    mockQueries();
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const table = screen.getByRole("table", { name: "Ingestion eligibility" });
    expect(table).toHaveTextContent("operations.production_orders");
    expect(table).toHaveTextContent("Eligible");
    expect(table).toHaveTextContent("Stale fingerprint");
    expect(table).toHaveTextContent("Not awaiting ingestion");
  });

  it("states validation-only up front and never implies row reads or syncs", () => {
    mockQueries({ requests: [requestView()] });
    const { container } = render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    expect(screen.getByText(/Validation stage only\./)).toBeInTheDocument();
    expect(screen.getByText(/No source is dialed and no rows are read/)).toBeInTheDocument();
    expect(container.textContent ?? "").not.toMatch(/\bsync(ed|ing)\b|extract(ion|ed) rows/i);
  });

  it("submits selected eligible bindings with a required reason, then refreshes", async () => {
    const user = userEvent.setup();
    mockQueries();
    mocks.axisFetch.mockResolvedValue(
      new Response(JSON.stringify(requestView()), { status: 200 }),
    );
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );

    const submit = screen.getByRole("button", { name: "Request ingestion" });
    expect(submit).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /operations\.production_orders/ }));
    expect(submit).toBeDisabled(); // reason still missing

    await user.type(screen.getByLabelText("Governance reason"), "Nightly governed validation.");
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => {
      expect(consoleMocks.triggerRefresh).toHaveBeenCalledTimes(1);
    });
    expect(mocks.axisFetch).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/connectors/external-db/source-ingestion-requests`,
      expect.objectContaining({ method: "POST" }),
    );
    // axisFetch receives the typed payload object and owns serialization.
    const body = vi.mocked(mocks.axisFetch).mock.calls[0][1].body as {
      selections: { binding_id: string }[];
      reason: string;
    };
    expect(body.selections).toEqual([{ binding_id: "binding_console_eligible" }]);
    expect(body.reason).toBe("Nightly governed validation.");
    // The client pins no fingerprint; only the API does.
    expect(JSON.stringify(body)).not.toContain("fingerprint");
    expect(toastMocks.push).toHaveBeenCalled();
  });

  it("reports a deterministic replay honestly instead of pretending novelty", async () => {
    const user = userEvent.setup();
    mockQueries({ requests: [requestView()] });
    mocks.axisFetch.mockResolvedValue(
      new Response(JSON.stringify(requestView({ outcome: "replayed" })), { status: 200 }),
    );
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    await user.click(screen.getByRole("checkbox", { name: /operations\.production_orders/ }));
    await user.type(screen.getByLabelText("Governance reason"), "Nightly governed validation.");
    await user.click(screen.getByRole("button", { name: "Request ingestion" }));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        /already exists; the existing request was returned unchanged/,
      );
    });
    expect(toastMocks.push).toHaveBeenCalledWith(
      expect.objectContaining({ tone: "neutral" }),
    );
  });

  it("maps scope denial, conflict, and validation failures to honest copy", async () => {
    const user = userEvent.setup();
    for (const [status, detail, expected] of [
      [
        403,
        { code: "PERMISSION_DENIED", reason: "missing_scope:connectors:source:ingest" },
        /lacks the connectors:source:ingest scope/,
      ],
      [
        409,
        { code: "CONFLICT", reason: "request_id_conflict" },
        /already names a different ingestion request/,
      ],
      [
        422,
        { code: "VALIDATION_FAILED", reason: "stale_fingerprint" },
        /rejected the request/,
      ],
    ] as const) {
      mockQueries();
      mocks.axisFetch.mockResolvedValue(
        new Response(JSON.stringify({ detail }), { status }),
      );
      const { unmount } = render(
        <ConnectorSourceIngestionSection
          connectorId={CONNECTOR_ID}
          identitySession={null}
          tenantId={TENANT_ID}
        />,
      );
      await user.click(screen.getByRole("checkbox", { name: /operations\.production_orders/ }));
      await user.type(screen.getByLabelText("Governance reason"), "Nightly governed validation.");
      await user.click(screen.getByRole("button", { name: "Request ingestion" }));
      await waitFor(() => {
        expect(screen.getByText(expected)).toBeInTheDocument();
      });
      unmount();
    }
  });

  it("renders every durable request state without inventing transitions", () => {
    mockQueries({
      requests: [
        requestView({ request_id: "req_pending" }),
        requestView({ request_id: "req_dispatching", status: "dispatching", attempt_count: 1 }),
        requestView({ request_id: "req_completed", status: "completed", attempt_count: 1 }),
        requestView({ request_id: "req_cancelled", status: "cancelled" }),
        requestView({
          request_id: "req_dead",
          status: "failed",
          attempt_count: 3,
          dead_lettered_at: "2026-08-23T09:00:00Z",
          last_error: "stale_fingerprint",
          selections: [
            {
              binding_id: staleRow.binding_id,
              resource_name: staleRow.resource_name,
              schema_fingerprint: staleRow.schema_fingerprint,
            },
          ],
        }),
      ],
    });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const table = screen.getByRole("table", { name: "Governed ingestion requests" });
    expect(table).toHaveTextContent("Pending dispatch");
    expect(table).toHaveTextContent("Working");
    expect(table).toHaveTextContent("Completed");
    expect(table).toHaveTextContent("Failed");
    expect(table).toHaveTextContent("Cancelled");
    expect(table).toHaveTextContent("Dead-lettered");

    // Details stay in the DOM (progressively disclosed, keyboard-native);
    // their content is asserted directly without needing to open them.
    const deadDetail = document.querySelector('[data-request-detail="req_dead"]');
    expect(deadDetail).not.toBeNull();
    expect(deadDetail).toHaveTextContent("operations.inventory_snapshots");
    expect(deadDetail).toHaveTextContent("stale_fingerprint");
  });

  it("keeps unavailable API states explicit instead of showing invented rows", () => {
    mockQueries({ eligibilitySource: "unavailable", requestsSource: "unavailable" });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // Both sections (eligibility and requests) fail closed with the same
    // honest copy; neither invents rows.
    expect(screen.getAllByText(/Ingestion requests unavailable:/).length).toBe(2);
    expect(screen.getAllByText(/Nothing shown here is invented/).length).toBe(2);
  });

  it("hides the form behind the SSO gate while keeping eligibility visible", () => {
    mockQueries();
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={{
          api_auth_required: true,
          authenticated: false,
        } as never}
        tenantId={TENANT_ID}
      />,
    );
    expect(screen.queryByRole("button", { name: "Request ingestion" })).not.toBeInTheDocument();
    expect(screen.getByText(/Sign in to raise governed ingestion requests/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Ingestion eligibility" })).toBeInTheDocument();
  });

  it("offers the extraction stage and shows planned limits only when the API enables them", async () => {
    const user = userEvent.setup();
    mockQueries({
      extractionAvailable: true,
      plannedLimits: { max_rows: 10000, max_bytes: 5000000 },
      requests: [requestView()],
    });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    expect(screen.getByText(/Extraction is enabled here/)).toBeInTheDocument();
    expect(screen.getByText(/max_rows≤10000/)).toBeInTheDocument();

    const stageSelect = screen.getByLabelText(/Validate only/);
    await user.selectOptions(stageSelect, "extract");
    await user.click(screen.getByRole("checkbox", { name: /operations\.production_orders/ }));
    await user.type(screen.getByLabelText("Governance reason"), "Bounded extract probe.");
    await user.click(screen.getByRole("button", { name: "Request ingestion" }));

    await waitFor(() => {
      const body = vi.mocked(mocks.axisFetch).mock.calls[0][1].body as { stage: string };
      expect(body.stage).toBe("extract");
    });
  });

  it("hides the stage selector entirely when extraction is off", () => {
    mockQueries();
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    expect(screen.queryByLabelText(/Validate only/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Extraction is enabled here/)).not.toBeInTheDocument();
  });

  it("cancels a still-pending request from its disclosure and refreshes", async () => {
    const user = userEvent.setup();
    mockQueries({ requests: [requestView()] });
    mocks.axisFetch.mockResolvedValue(
      new Response(JSON.stringify(requestView({ status: "cancelled" })), { status: 200 }),
    );
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    // Cancel lives inside the keyboard-native disclosure, only for pending.
    const details = document.querySelector("[data-request-detail]");
    expect(details).not.toBeNull();
    details!.setAttribute("open", "");
    const cancel = screen.getByRole("button", { name: "Cancel request" });
    await user.click(cancel);
    await waitFor(() => {
      expect(consoleMocks.triggerRefresh).toHaveBeenCalled();
    });
    expect(mocks.axisFetch).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/connectors/external-db/source-ingestion-requests/ingest_console_abc123/cancel`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("renders the honest preflight checklist for default-off deployments", () => {
    mockQueries();
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const checklist = screen.getByRole("region", { name: "Extraction readiness" });
    expect(checklist).toHaveTextContent(/Validation only — extraction is default-off here/);
  });

  it("loads batch evidence only when a request disclosure is opened", async () => {
    mockQueries({
      requests: [requestView()],
      extractionAvailable: true,
      plannedLimits: { max_rows: 10000 },
      batches: batchesPage(2),
    });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    // Closed by default: no evidence table yet.
    expect(screen.queryByRole("table", { name: /Extraction batch evidence/ })).not.toBeInTheDocument();

    const details = document.querySelector("[data-request-detail]")!.parentElement!;
    details.setAttribute("open", "");
    details.dispatchEvent(new Event("toggle", { bubbles: false }));

    await waitFor(() => {
      expect(
        screen.getByRole("table", { name: /Extraction batch evidence/ }),
      ).toBeInTheDocument();
    });
    const table = screen.getByRole("table", { name: /Extraction batch evidence/ });
    // Watermark presence without value; digest abbreviated.
    expect(table).toHaveTextContent("Watermark present");
    expect(table).toHaveTextContent("b".repeat(12));
    expect(table).toHaveTextContent("row_limit");
    expect(table.textContent).not.toContain("a".repeat(64));
  });

  it("runs dry-run reconciliation from the disclosure and reports counts", async () => {
    const user = userEvent.setup();
    mockQueries({
      requests: [requestView()],
      extractionAvailable: true,
      batches: batchesPage(1),
    });
    mocks.axisFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          tenant_id: TENANT_ID,
          request_id: "ingest_console_abc123",
          dry_run: true,
          clean_matches: 1,
          digest_mismatches: 0,
          missing_objects: 0,
          orphaned_objects: 0,
          findings: [],
        }),
        { status: 200 },
      ),
    );
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const details = document.querySelector("[data-request-detail]")!.parentElement!;
    details.setAttribute("open", "");
    details.dispatchEvent(new Event("toggle", { bubbles: false }));

    const button = await screen.findByRole("button", { name: "Check storage" });
    await user.click(button);

    await waitFor(() => {
      const statuses = screen.getAllByRole("status").map((el) => el.textContent ?? "").join(" ");
      expect(statuses).toMatch(/Clean matches 1/);
    });
    expect(mocks.axisFetch).toHaveBeenCalledWith(
      expect.stringContaining("/batches/reconciliation"),
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("offers re-dispatch only for dead-lettered requests with a required reason", async () => {
    const user = userEvent.setup();
    mockQueries({
      requests: [
        requestView({ request_id: "req_dead", status: "failed", attempt_count: 3,
                      dead_lettered_at: "2026-08-23T09:00:00Z" }),
        requestView({ request_id: "req_plain_failed", status: "failed", attempt_count: 1,
                      dead_lettered_at: null }),
        requestView({ request_id: "req_done", status: "completed", attempt_count: 1 }),
      ],
    });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    // Only OPENED dead-lettered disclosures expose the action.
    const openDisclosure = (requestId: string) => {
      const el = Array.from(
        document.querySelectorAll("[data-request-detail]"),
      ).find((node) => node.getAttribute("data-request-detail") === requestId);
      el!.parentElement!.setAttribute("open", "");
      el!.parentElement!.dispatchEvent(new Event("toggle"));
    };

    const doneDetails = Array.from(
      document.querySelectorAll("[data-request-detail]"),
    ).find((el) => el.getAttribute("data-request-detail") === "req_done")!;
    doneDetails.parentElement!.setAttribute("open", "");
    doneDetails.parentElement!.dispatchEvent(new Event("toggle"));
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /Re-dispatch after remediation/ }),
      ).not.toBeInTheDocument();
    });
    // Ordinary failed (non-dead-lettered) also offers nothing.
    const plainDetails = Array.from(
      document.querySelectorAll("[data-request-detail]"),
    ).find((el) => el.getAttribute("data-request-detail") === "req_plain_failed")!;
    plainDetails.parentElement!.setAttribute("open", "");
    plainDetails.parentElement!.dispatchEvent(new Event("toggle"));
    expect(
      screen.queryByRole("button", { name: /Re-dispatch after remediation/ }),
    ).not.toBeInTheDocument();

    openDisclosure("req_dead");
    const button = await screen.findByRole("button", { name: /Re-dispatch after remediation/ });
    expect(button).toBeDisabled(); // reason required
    await user.type(screen.getByLabelText(/Remediation reason/), "Fresh discovery done.");
    expect(button).toBeEnabled();

    // Keyboard submit path.
    screen.getByLabelText(/Remediation reason/).focus();
    await user.keyboard("{Enter}");

    await waitFor(() => {
      const call = mocks.axisFetch.mock.calls.find(([path]) =>
        String(path).endsWith("/requeue"),
      );
      expect(call).toBeDefined();
      const body = call![1].body as { reason: string; idempotency_key: string };
      expect(body.reason).toBe("Fresh discovery done.");
      expect(body.idempotency_key).toMatch(/^requeue_/);
    });
  });

  it("keeps one stable idempotency key across retries of the same re-dispatch ask", async () => {
    const user = userEvent.setup();
    mockQueries({
      requests: [requestView({ status: "failed", attempt_count: 2,
                               dead_lettered_at: "2026-08-23T09:00:00Z" })],
    });
    mocks.axisFetch
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: {} }), { status: 409 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(requestView({ status: "pending" })), { status: 200 }),
      );
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const details = document.querySelector("[data-request-detail]")!.parentElement!;
    details.setAttribute("open", "");
    details.dispatchEvent(new Event("toggle"));
    await user.type(await screen.findByLabelText(/Remediation reason/), "Remediated.");

    await user.click(screen.getByRole("button", { name: /Re-dispatch after remediation/ }));
    await waitFor(() => {
      expect(mocks.axisFetch).toHaveBeenCalledTimes(1);
    });
    const firstKey = (
      mocks.axisFetch.mock.calls[0][1].body as { idempotency_key: string }
    ).idempotency_key;

    // Retry of the SAME ask: identical key, no regeneration.
    await user.click(screen.getByRole("button", { name: /Re-dispatch after remediation/ }));
    await waitFor(() => {
      expect(mocks.axisFetch).toHaveBeenCalledTimes(2);
    });
    const secondKey = (
      mocks.axisFetch.mock.calls[1][1].body as { idempotency_key: string }
    ).idempotency_key;
    expect(secondKey).toBe(firstKey);
    expect(firstKey).toMatch(/^requeue_/);
  });

  it("surfaces conflict copy when re-dispatch is refused", async () => {
    const user = userEvent.setup();
    mockQueries({
      requests: [requestView({ status: "failed", attempt_count: 2,
                               dead_lettered_at: "2026-08-23T09:00:00Z" })],
    });
    mocks.axisFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "CONFLICT",
            message: "refused",
            reason: "requeue_conflict",
          },
        }),
        { status: 409 },
      ),
    );
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const details = document.querySelector("[data-request-detail]")!.parentElement!;
    details.setAttribute("open", "");
    details.dispatchEvent(new Event("toggle"));
    await user.type(await screen.findByLabelText(/Remediation reason/), "Remediated.");
    await user.click(await screen.findByRole("button", { name: /Re-dispatch after remediation/ }));
    await waitFor(() => {
      // The shared operator error surface names the refusal class.
      expect(document.body.textContent).toMatch(/dead-lettered requests can be re-dispatched|refused/i);
    });
  });

  it("wraps tables in horizontally scrollable regions for narrow screens", () => {
    mockQueries({ requests: [requestView()] });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    for (const table of screen.getAllByRole("table")) {
      expect(table.parentElement).toHaveClass("overflow-x-auto");
    }
  });

  it("overview strip stays quiet and educational when nothing needs attention", () => {
    mockQueries();
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const strip = screen.getByTestId("source-ingestion-overview");
    expect(strip).toHaveTextContent(/All clear/);
  });

  it("surfaces dead-lettered work as needing a decision, with totals", () => {
    mockQueries({
      overviewSummary: {
        status_counts: { failed: 1, completed: 2 },
        total_count: 3,
        dead_lettered_count: 1,
        extract_stage_count: 1,
        last_activity_at: "2026-08-23T08:30:00Z",
      },
    });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const strip = screen.getByTestId("source-ingestion-overview");
    expect(strip).toHaveTextContent("1 dead-lettered request(s) need a decision");
    expect(strip).toHaveTextContent("3 request(s) overall · 1 extraction");
  });

  it("renders the per-attempt timeline inside an opened request disclosure", async () => {
    mockQueries({
      requests: [
        requestView({
          status: "failed",
          dead_lettered_at: "2026-08-23T09:00:00Z",
          attempt_count: 2,
          last_error: "stale_fingerprint",
          attempts: [
            {
              attempt_number: 1,
              outcome: "retried",
              error_code: "RuntimeError",
              finished_at: "2026-08-23T08:05:00Z",
              selections: [
                {
                  binding_id: eligibleRow.binding_id,
                  resource_name: eligibleRow.resource_name,
                  outcome: "validated",
                  reason: null,
                },
              ],
            },
            {
              attempt_number: 2,
              outcome: "dead_lettered",
              error_code: "stale_fingerprint",
              finished_at: "2026-08-23T09:00:00Z",
              selections: [
                {
                  binding_id: eligibleRow.binding_id,
                  resource_name: eligibleRow.resource_name,
                  outcome: "failed",
                  reason: "stale_fingerprint",
                },
              ],
            },
          ],
        }),
      ],
    });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const details = document.querySelector("[data-request-detail]")!.parentElement!;
    details.setAttribute("open", "");
    details.dispatchEvent(new Event("toggle"));
    const timeline = await screen.findByRole("region", {
      name: /Dispatch attempt timeline/,
    });
    expect(timeline).toHaveTextContent("#1 Retried after an operational failure");
    expect(timeline).toHaveTextContent("#2 Dead-lettered");
    expect(timeline).toHaveTextContent("stale_fingerprint");
    // The timeline never invents row-level facts.
    expect(timeline.textContent ?? "").not.toMatch(/row-[0-9]/);
  });

  it("announces truncation honestly when older attempts exist", async () => {
    const entry = (finishedAt: string) => ({
      attempt_number: 1,
      outcome: "dead_lettered" as const,
      error_code: "RuntimeError",
      finished_at: finishedAt,
      selections: [
        {
          binding_id: eligibleRow.binding_id,
          resource_name: eligibleRow.resource_name,
          outcome: "failed" as const,
          reason: "RuntimeError",
        },
      ],
    });
    mockQueries({
      requests: [
        requestView({
          status: "failed",
          dead_lettered_at: "2026-08-23T09:00:00Z",
          attempt_count: 55,
          last_error: "RuntimeError",
          attempts_truncated: true,
          attempts: [entry("2026-08-23T08:59:00Z"), entry("2026-08-23T09:00:00Z")],
        }),
      ],
    });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const details = document.querySelector("[data-request-detail]")!.parentElement!;
    details.setAttribute("open", "");
    details.dispatchEvent(new Event("toggle"));
    expect(
      await screen.findByTestId(/attempts-truncated-/),
    ).toHaveTextContent(/latest 50 recorded dispatch attempts/);
  });

  it("renders no truncation notice for fully-visible histories", async () => {
    mockQueries({
      requests: [
        requestView({
          status: "completed",
          completed_at: "2026-08-23T08:10:00Z",
          attempts_truncated: false,
          attempts: [
            {
              attempt_number: 1,
              outcome: "completed" as const,
              error_code: null,
              finished_at: "2026-08-23T08:10:00Z",
              selections: [
                {
                  binding_id: eligibleRow.binding_id,
                  resource_name: eligibleRow.resource_name,
                  outcome: "validated" as const,
                  reason: null,
                },
              ],
            },
          ],
        }),
      ],
    });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const details = document.querySelector("[data-request-detail]")!.parentElement!;
    details.setAttribute("open", "");
    details.dispatchEvent(new Event("toggle"));
    await screen.findByRole("region", { name: /Dispatch attempt timeline/ });
    expect(screen.queryByTestId(/attempts-truncated-/)).not.toBeInTheDocument();
  });

  it("renders duplicate attempt pairs from re-dispatch cycles without collision", async () => {
    const deadSelection = {
      binding_id: eligibleRow.binding_id,
      resource_name: eligibleRow.resource_name,
      outcome: "failed" as const,
      reason: "RuntimeError",
    };
    mockQueries({
      requests: [
        requestView({
          status: "failed",
          dead_lettered_at: "2026-08-23T09:00:00Z",
          attempt_count: 2,
          last_error: "RuntimeError",
          attempts: [
            {
              attempt_number: 1,
              outcome: "dead_lettered" as const,
              error_code: "RuntimeError",
              finished_at: "2026-08-23T08:30:00Z",
              selections: [deadSelection],
            },
            {
              // Same number + outcome as the first cycle: keys must not collide.
              attempt_number: 1,
              outcome: "dead_lettered" as const,
              error_code: "RuntimeError",
              finished_at: "2026-08-23T09:00:00Z",
              selections: [deadSelection],
            },
          ],
        }),
      ],
    });
    render(
      <ConnectorSourceIngestionSection
        connectorId={CONNECTOR_ID}
        identitySession={null}
        tenantId={TENANT_ID}
      />,
    );
    const details = document.querySelector("[data-request-detail]")!.parentElement!;
    details.setAttribute("open", "");
    details.dispatchEvent(new Event("toggle"));
    const timeline = await screen.findByRole("region", {
      name: /Dispatch attempt timeline/,
    });
    const entries = timeline.querySelectorAll("ol > li");
    expect(entries.length).toBe(2);
    expect(timeline.textContent).toMatch(/#1 Dead-lettered.*#1 Dead-lettered/s);
  });
});
