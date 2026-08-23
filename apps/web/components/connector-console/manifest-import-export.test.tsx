import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";

import {
  csvConnectorFixture,
  manifestDetailFixture,
} from "./connector-fixtures";
import { ManifestExportPanel } from "./manifest-export-panel";
import {
  MANIFESTS_ENDPOINT,
  MANIFEST_VALIDATION_ENDPOINT,
  ManifestImportPanel,
  buildManifestDetailPath,
} from "./manifest-import-panel";

const mocks = vi.hoisted(() => ({
  axisFetch: vi.fn(),
  onApplied: vi.fn(),
}));

vi.mock("@/lib/axis-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/axis-api")>();
  return {
    ...actual,
    axisFetch: mocks.axisFetch,
    axisFetchParsedJson: async function axisFetchParsedJson<T>(
      path: string,
      decoder: (value: unknown) => T,
      options: import("@/lib/axis-api").AxisFetchOptions = {},
    ): Promise<T> {
      const response: Response = await mocks.axisFetch(path, options);
      const body = await response.json();
      const requestId = actual.axisResponseRequestId(response);
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

const tenantId = "tenant_demo_manufacturing";
const identitySession: IdentitySessionReadModel = {
  authenticated: true,
  actor_id: "plant-operations-owner-role",
  api_auth_required: true,
  audience: "axis-console",
  capabilities: [],
  enterprise_sso_ready: true,
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
  tenant_id: tenantId,
};

function documentFor(connectorId: string) {
  return {
    manifest: { ...csvConnectorFixture.manifest, connector_id: connectorId },
    runtime_policy: csvConnectorFixture.runtime_policy,
    preview_sample: csvConnectorFixture.preview_sample,
    notes: [],
  };
}

function response(
  payload: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function validationResponse(
  results: Array<{
    connector_id: string | null;
    outcome: "would_register" | "would_replace" | "invalid";
    errors?: Array<{ field_path: string; message: string; reason: string }>;
  }>,
) {
  return {
    tenant_id: tenantId,
    summary: {
      would_register: results.filter((result) => result.outcome === "would_register").length,
      would_replace: results.filter((result) => (
        result.outcome === "would_replace"
      )).length,
      invalid: results.filter((result) => result.outcome === "invalid").length,
    },
    results: results.map((result) => ({ ...result, errors: result.errors ?? [] })),
  };
}

function manifestDetail(connectorId: string, revisionNumber = 3) {
  const currentRevision = {
    ...manifestDetailFixture.current_revision,
    connector_id: connectorId,
    revision_number: revisionNumber,
    manifest: {
      ...manifestDetailFixture.current_revision.manifest,
      connector_id: connectorId,
    },
  };
  return {
    tenant_id: tenantId,
    connector_id: connectorId,
    current_revision: currentRevision,
    revisions: [currentRevision],
    transitions: [],
  };
}

function renderImport(extra?: React.ReactNode) {
  return render(
    <ToastProvider>
      {extra}
      <ManifestImportPanel
        identitySession={identitySession}
        onApplied={mocks.onApplied}
        tenantId={tenantId}
      />
    </ToastProvider>,
  );
}

function setJson(value: unknown) {
  fireEvent.change(screen.getByLabelText("Registration document JSON", { selector: "textarea:not([readonly])" }), {
    target: { value: typeof value === "string" ? value : JSON.stringify(value) },
  });
}

beforeEach(() => {
  mocks.axisFetch.mockReset();
  mocks.onApplied.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ManifestImportPanel", () => {
  it("does not claim that every registration document requires a preview sample", () => {
    renderImport();

    expect(screen.queryByText(/Every document must include preview_sample/)).not.toBeInTheDocument();
  });

  it("renders each outcome and field-level errors for a mixed batch", async () => {
    const user = userEvent.setup();
    const documents = [documentFor("new-connector"), documentFor("existing-connector"), {}];
    mocks.axisFetch
      .mockResolvedValueOnce(response(validationResponse([
        { connector_id: "new-connector", outcome: "would_register" },
        { connector_id: "existing-connector", outcome: "would_replace" },
        {
          connector_id: null,
          outcome: "invalid",
          errors: [{
            field_path: "preview_sample.file_name",
            message: "Field required",
            reason: "invalid_preview_sample_payload",
          }],
        },
      ])))
      .mockResolvedValueOnce(response(manifestDetail("existing-connector", 4)));
    renderImport();

    setJson(documents);
    await user.click(screen.getByRole("button", { name: "Check" }));

    const table = await screen.findByRole("table", { name: "Import connector manifests" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Would register")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Would replace")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Replaces revision 4")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Invalid")).toBeInTheDocument();
    expect(within(rows[2]).getByText("preview_sample.file_name")).toBeInTheDocument();
    expect(within(rows[2]).getByText(/Field required/)).toBeInTheDocument();
    expect(screen.getAllByText("1", { selector: "p.text-xl" })).toHaveLength(3);
  });

  it("keeps Apply disabled while any checked document is invalid", async () => {
    const user = userEvent.setup();
    mocks.axisFetch.mockResolvedValueOnce(response(validationResponse([
      { connector_id: "valid", outcome: "would_register" },
      {
        connector_id: "invalid",
        outcome: "invalid",
        errors: [{ field_path: "preview_sample", message: "Field required", reason: "missing" }],
      },
    ])));
    renderImport();

    setJson([documentFor("valid"), documentFor("invalid")]);
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(await screen.findByText("1 of 2 will be rejected as invalid. Apply stays disabled until every document is valid.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review apply" })).toBeDisabled();
  });

  it("makes a would-replace row applyable and routes it to PUT with revision guards", async () => {
    const user = userEvent.setup();
    mocks.axisFetch
      .mockResolvedValueOnce(response(validationResponse([
        { connector_id: "existing", outcome: "would_replace" },
      ])))
      .mockResolvedValueOnce(response(manifestDetail("existing", 7)))
      .mockResolvedValueOnce(response({ revision_number: 8 }, 200));
    renderImport();

    const document = documentFor("existing");
    setJson(document);
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(await screen.findByText("Replaces revision 7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review apply" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Review apply" }));
    await user.click(screen.getByRole("button", { name: "Apply manifests" }));

    expect(await screen.findAllByText("1 of 1 manifests were applied.")).toHaveLength(2);
    expect(mocks.axisFetch).toHaveBeenNthCalledWith(
      2,
      buildManifestDetailPath("existing", tenantId),
      expect.objectContaining({ session: null }),
    );
    expect(mocks.axisFetch).toHaveBeenNthCalledWith(
      3,
      `${MANIFESTS_ENDPOINT}/existing`,
      expect.objectContaining({
        method: "PUT",
        body: expect.objectContaining({
          ...document,
          expected_revision_number: 7,
          idempotency_key: expect.stringMatching(/^connector-manifest-replace:.+:1$/),
        }),
      }),
    );
  });

  it("reports an expected-revision 409 as a concurrent-change conflict", async () => {
    const user = userEvent.setup();
    mocks.axisFetch
      .mockResolvedValueOnce(response(validationResponse([
        { connector_id: "existing", outcome: "would_replace" },
      ])))
      .mockResolvedValueOnce(response(manifestDetail("existing", 7)))
      .mockResolvedValueOnce(response({
        detail: {
          reason: "expected_revision_mismatch",
          current_revision_number: 8,
        },
      }, 409));
    renderImport();

    setJson(documentFor("existing"));
    await user.click(screen.getByRole("button", { name: "Check" }));
    await user.click(await screen.findByRole("button", { name: "Review apply" }));
    await user.click(screen.getByRole("button", { name: "Apply manifests" }));

    expect(await screen.findByText("Concurrent change")).toBeInTheDocument();
    expect(screen.getAllByText(
      "Apply stopped because someone else changed existing. Check the batch again before replacing it.",
    )).toHaveLength(2);
    expect(mocks.onApplied).not.toHaveBeenCalled();
  });

  it("stops after a partial apply failure and identifies landed, failed, and untouched documents", async () => {
    const user = userEvent.setup();
    const documents = [documentFor("landed"), documentFor("failed"), documentFor("untouched")];
    mocks.axisFetch
      .mockResolvedValueOnce(response(validationResponse(documents.map((document) => ({
        connector_id: document.manifest.connector_id,
        outcome: "would_register" as const,
      })))))
      .mockResolvedValueOnce(response({ manifest_id: "created" }, 201))
      .mockResolvedValueOnce(response(
        { detail: { reason: "write_failed", debug: "secret-apply-trace" } },
        500,
        { "x-request-id": "req-manifest-apply-500" },
      ));
    renderImport();

    setJson(documents);
    await user.click(screen.getByRole("button", { name: "Check" }));
    await user.click(await screen.findByRole("button", { name: "Review apply" }));
    await user.click(screen.getByRole("button", { name: "Apply manifests" }));

    expect(await screen.findAllByText("1 of 3 manifests were applied. The remaining documents were not applied.")).toHaveLength(2);
    const rows = within(screen.getByRole("table", { name: "Import connector manifests" }))
      .getAllByRole("row")
      .slice(1);
    expect(within(rows[0]).getByText("Applied")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Failed")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Not applied")).toBeInTheDocument();
    expect(mocks.axisFetch.mock.calls.filter(([path]) => path === MANIFESTS_ENDPOINT)).toHaveLength(2);
    expect(mocks.onApplied).toHaveBeenCalledTimes(1);
    expect(screen.getByText("req-manifest-apply-500")).toBeInTheDocument();
    expect(screen.queryByText(/secret-apply-trace|write_failed/)).not.toBeInTheDocument();
  });

  it("ignores validation that completes after the registration JSON changes", async () => {
    const user = userEvent.setup();
    let resolveValidation: (value: Response) => void = () => {};
    let validationSettled = false;
    mocks.axisFetch.mockImplementationOnce(async () => {
      const result = await new Promise<Response>((resolve) => { resolveValidation = resolve; });
      validationSettled = true;
      return result;
    });
    renderImport();

    setJson(documentFor("first-document"));
    await user.click(screen.getByRole("button", { name: "Check" }));
    setJson(documentFor("replacement-document"));
    resolveValidation(response(validationResponse([
      { connector_id: "first-document", outcome: "would_register" },
    ])));

    await waitFor(() => expect(validationSettled).toBe(true));
    expect(screen.queryByRole("table", { name: "Import connector manifests" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review apply" })).toBeDisabled();
    expect(screen.getByLabelText("Registration document JSON", {
      selector: "textarea:not([readonly])",
    })).toHaveValue(JSON.stringify(documentFor("replacement-document")));
  });

  it("rejects more than 50 documents before making a request", async () => {
    const user = userEvent.setup();
    renderImport();

    setJson(Array.from({ length: 51 }, (_, index) => documentFor(`connector-${index}`)));
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(screen.getByRole("alert")).toHaveTextContent("51 documents were provided. Check at most 50 at a time.");
    expect(mocks.axisFetch).not.toHaveBeenCalled();
  });

  it("shows malformed JSON locally without making a request", async () => {
    const user = userEvent.setup();
    renderImport();

    setJson("{not-json");
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(screen.getByRole("alert")).toHaveTextContent("This is not valid JSON");
    expect(mocks.axisFetch).not.toHaveBeenCalled();
  });

  it("rejects an empty array locally without making a request", async () => {
    const user = userEvent.setup();
    renderImport();

    setJson([]);
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Provide one JSON object or a non-empty array of JSON objects.",
    );
    expect(mocks.axisFetch).not.toHaveBeenCalled();
  });

  it("applies a valid batch sequentially and refreshes once after every document lands", async () => {
    const user = userEvent.setup();
    const documents = [documentFor("first"), documentFor("second")];
    mocks.axisFetch
      .mockResolvedValueOnce(response(validationResponse(documents.map((document) => ({
        connector_id: document.manifest.connector_id,
        outcome: "would_register" as const,
      })))))
      .mockResolvedValueOnce(response({ manifest_id: "first" }, 201))
      .mockResolvedValueOnce(response({ manifest_id: "second" }, 201));
    renderImport();

    setJson(documents);
    await user.click(screen.getByRole("button", { name: "Check" }));
    await user.click(await screen.findByRole("button", { name: "Review apply" }));
    await user.click(screen.getByRole("button", { name: "Apply manifests" }));

    expect(await screen.findAllByText("2 of 2 manifests were applied.")).toHaveLength(2);
    expect(mocks.axisFetch.mock.calls.map(([path]) => path)).toEqual([
      MANIFEST_VALIDATION_ENDPOINT,
      MANIFESTS_ENDPOINT,
      MANIFESTS_ENDPOINT,
    ]);
    expect(mocks.onApplied).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Review apply" })).toBeDisabled();
  });

  it("loads a JSON file into the same checked import flow", async () => {
    const user = userEvent.setup();
    const document = documentFor("uploaded");
    mocks.axisFetch.mockResolvedValueOnce(response(validationResponse([
      { connector_id: "uploaded", outcome: "would_register" },
    ])));
    renderImport();

    await user.upload(
      screen.getByLabelText("Upload JSON file"),
      new File([JSON.stringify(document)], "connector.json", { type: "application/json" }),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Check" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(await screen.findByText("uploaded")).toBeInTheDocument();
    expect(mocks.axisFetch).toHaveBeenCalledWith(
      MANIFEST_VALIDATION_ENDPOINT,
      expect.objectContaining({ body: expect.objectContaining({ manifests: [document] }) }),
    );
  });

  it("clears typed JSON while a selected file is still loading", async () => {
    const user = userEvent.setup();
    renderImport();
    setJson(documentFor("typed-document"));
    expect(screen.getByRole("button", { name: "Check" })).toBeEnabled();

    vi.stubGlobal("FileReader", class DeferredFileReader {
      result: string | ArrayBuffer | null = null;
      onload: ((event: ProgressEvent<FileReader>) => void) | null = null;
      onerror: ((event: ProgressEvent<FileReader>) => void) | null = null;

      readAsText() {}
    });
    await user.upload(
      screen.getByLabelText("Upload JSON file"),
      new File([JSON.stringify(documentFor("uploaded"))], "connector.json", {
        type: "application/json",
      }),
    );

    expect(screen.getByLabelText("Registration document JSON", {
      selector: "textarea:not([readonly])",
    })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Check" })).toBeDisabled();
  });
});

describe("manifest export round trip", () => {
  it("feeds the exact formatted export into import and reports it as replaceable", async () => {
    const user = userEvent.setup();
    mocks.axisFetch
      .mockResolvedValueOnce(response(validationResponse([
        {
          connector_id: csvConnectorFixture.manifest.connector_id,
          outcome: "would_replace",
        },
      ])))
      .mockResolvedValueOnce(response(manifestDetail(
        csvConnectorFixture.manifest.connector_id,
        2,
      )));
    renderImport(<ManifestExportPanel connector={csvConnectorFixture} />);

    await user.click(screen.getByRole("button", { name: "Export manifest" }));
    const exportedJson = (screen.getByLabelText("Registration document JSON", {
      selector: "textarea[readonly]",
    }) as HTMLTextAreaElement).value;
    setJson(exportedJson);
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(await screen.findByText("Would replace", {
      selector: ".status-pill",
    })).toBeInTheDocument();
    expect(mocks.axisFetch).toHaveBeenCalledWith(
      MANIFEST_VALIDATION_ENDPOINT,
      expect.objectContaining({
        body: expect.objectContaining({ manifests: [JSON.parse(exportedJson)] }),
      }),
    );
    expect(JSON.parse(exportedJson).preview_sample).toEqual(csvConnectorFixture.preview_sample);
  });

  it("copies and downloads the formatted registration document", async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => "blob:manifest");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(
      <ToastProvider>
        <ManifestExportPanel connector={csvConnectorFixture} />
      </ToastProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Export manifest" }));
    const json = (screen.getByLabelText("Registration document JSON") as HTMLTextAreaElement).value;
    await user.click(screen.getByRole("button", { name: "Copy JSON" }));
    expect(await navigator.clipboard.readText()).toBe(json);
    await user.click(screen.getByRole("button", { name: "Download JSON" }));

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:manifest");
    click.mockRestore();
  });
});
