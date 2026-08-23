import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  axisFetch: vi.fn(),
}));

vi.mock("@/lib/axis-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/axis-api")>();
  return { ...actual, axisFetch: mocks.axisFetch };
});

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { ToastProvider } from "@/components/ui/toast";
import type { ConnectorManifestRecord, ConnectorRegistryItem } from "@/lib/connectors-demo";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

import { csvConnectorFixture } from "./connector-fixtures";
import { ConnectorLifecyclePanel } from "./lifecycle-panel";

const TENANT_ID = "tenant_demo_manufacturing";
const LIFECYCLE_PATH = `${OPERATIONS_API_PREFIX}/connectors/manifests/file_csv_manufacturing_assets/lifecycle?tenant_id=${TENANT_ID}`;

function manifestRecord(status: string) {
  return {
    tenant_id: TENANT_ID,
    manifest_id: "manifest-1",
    connector_id: "file_csv_manufacturing_assets",
    revision_number: 3,
    display_name: "Manufacturing assets CSV",
    connector_type: "file_csv",
    source_type: "csv_upload",
    version: "1.0.0",
    status,
    runtime_boundary: "self_hosted",
    registered_by: "operator",
    manifest: csvConnectorFixture.manifest,
    runtime_policy: csvConnectorFixture.runtime_policy,
    preview_sample: null,
    audit_event_id: "audit-lifecycle-1",
    audit_event_type: "connector.manifest.lifecycle_transitioned",
    revises_revision_number: 2,
    replaced_by_revision_number: null,
    revision_idempotency_key: null,
    idempotent_replay: false,
    unchanged: false,
    notes: [],
    created_at: "2026-08-22T07:00:00Z",
  };
}

function okResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json", "x-request-id": "req-lifecycle-1" },
  });
}

function renderPanel(
  connector: ConnectorRegistryItem,
  identitySession: Parameters<
    typeof ConnectorLifecyclePanel
  >[0]["identitySession"] = null,
  revisions?: Parameters<typeof ConnectorLifecyclePanel>[0]["revisions"],
  transitions?: Parameters<typeof ConnectorLifecyclePanel>[0]["transitions"],
) {
  const onTransitioned = vi.fn();
  render(
    <ToastProvider>
      <ConnectorLifecyclePanel
        connector={connector}
        identitySession={identitySession}
        onTransitioned={onTransitioned}
        revisions={revisions}
        transitions={transitions}
        tenantId={TENANT_ID}
      />
    </ToastProvider>,
  );
  return { onTransitioned };
}

function connectorWithStatus(status: string | null): ConnectorRegistryItem {
  return {
    ...csvConnectorFixture,
    registry_origin: "persisted_manifest",
    persisted_manifest:
      status === null
        ? null
        : {
            ...csvConnectorFixture.persisted_manifest!,
            status,
          },
  };
}

function revision(overrides: Partial<ConnectorManifestRecord>) {
  return { ...manifestRecord("registered_preview_only"), ...overrides };
}

describe("ConnectorLifecyclePanel", () => {
  beforeEach(() => {
    mocks.axisFetch.mockReset();
  });

  it("offers activation for a registered preview-only manifest and refreshes on success", async () => {
    const user = userEvent.setup();
    const { onTransitioned } = renderPanel(connectorWithStatus("registered_preview_only"));

    expect(screen.getByText(/Registered for previews only/)).toBeInTheDocument();

    mocks.axisFetch.mockResolvedValue(okResponse(manifestRecord("active_preview")));
    await user.click(screen.getByRole("button", { name: "Activate for previews" }));

    await waitFor(() => expect(onTransitioned).toHaveBeenCalledTimes(1));
    expect(mocks.axisFetch).toHaveBeenCalledTimes(1);
    const [path, options] = mocks.axisFetch.mock.calls[0];
    expect(path).toBe(LIFECYCLE_PATH);
    expect(options.body.target_status).toBe("active_preview");
    expect(options.body.transition_reason).toBeTruthy();
    expect(options.body.required_scope).toBe("connectors:manifest:lifecycle");
  });

  it("keeps an activated connector's live enablement behind its requirement list", async () => {
    const user = userEvent.setup();
    renderPanel(connectorWithStatus("active_preview"));

    // The CSV fixture blocks live_query, so the submit stays gated.
    await user.click(screen.getByRole("button", { name: /Enable live sync/ }));
    const requirements = screen.getByRole("list", {
      name: "Live-enablement requirements",
    });
    expect(requirements).toHaveTextContent("Missing");
    expect(requirements).toHaveTextContent(
      "Runtime policy allows live query and external egress",
    );

    const submit = screen.getByRole("button", { name: "Enable live operation" });
    expect(submit).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Activate for previews" })).not
      .toBeInTheDocument();
  });

  it("requires a two-step confirm before deprecating", async () => {
    const user = userEvent.setup();
    const { onTransitioned } = renderPanel(connectorWithStatus("active_live"));

    await user.click(screen.getByRole("button", { name: "Deprecate connector" }));
    expect(mocks.axisFetch).not.toHaveBeenCalled();

    mocks.axisFetch.mockResolvedValue(okResponse(manifestRecord("deprecated")));
    await user.click(screen.getByRole("button", { name: "Confirm deprecation" }));

    await waitFor(() => expect(onTransitioned).toHaveBeenCalledTimes(1));
    expect(mocks.axisFetch.mock.calls[0][1].body.target_status).toBe("deprecated");
  });

  it("names the missing evidence categories instead of submitting an incomplete request", async () => {
    const user = userEvent.setup();
    const liveReady = connectorWithStatus("active_preview");
    liveReady.manifest = {
      ...liveReady.manifest,
      sync_modes: ["live_sync"],
    };
    liveReady.runtime_policy = {
      ...liveReady.runtime_policy,
      allowed_operations: ["preview", "live_query", "external_egress"],
      blocked_operations: [],
      egress_policy: "egress_eu_west_readonly",
    };
    renderPanel(liveReady);

    await user.click(screen.getByRole("button", { name: /Enable live sync/ }));
    const submit = screen.getByRole("button", { name: "Enable live operation" });
    expect(submit).toBeDisabled();

    await user.type(
      screen.getByLabelText("Evidence references"),
      "approval:connector-live-enable",
    );
    expect(submit).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Still missing policy, credential evidence for live enablement.",
    );

    await user.type(
      screen.getByLabelText("Evidence references"),
      "\npolicy:egress-review\ncredential:vault://prod/db-readonly",
    );
    expect(submit).toBeEnabled();
  });

  it("maps a scope denial to operator copy while keeping the request reference", async () => {
    const user = userEvent.setup();
    const { onTransitioned } = renderPanel(connectorWithStatus("registered_preview_only"));

    mocks.axisFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "PERMISSION_DENIED",
            message: "denied",
            reason: "missing_manifest_lifecycle_scope",
          },
        }),
        { status: 403, headers: { "x-request-id": "req-403-lifecycle" } },
      ),
    );
    await user.click(screen.getByRole("button", { name: "Activate for previews" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your session is missing the connector lifecycle scope (connectors:manifest:lifecycle) for this tenant. A tenant admin can grant it.",
    );
    expect(screen.getByText("req-403-lifecycle")).toBeInTheDocument();
    expect(onTransitioned).not.toHaveBeenCalled();
  });

  it("distinguishes a missing enable-live scope from the base lifecycle scope", async () => {
    const user = userEvent.setup();
    const liveReady = connectorWithStatus("active_preview");
    liveReady.manifest = {
      ...liveReady.manifest,
      sync_modes: ["live_sync"],
    };
    liveReady.runtime_policy = {
      ...liveReady.runtime_policy,
      allowed_operations: ["preview", "live_query", "external_egress"],
      blocked_operations: [],
      egress_policy: "egress_eu_west_readonly",
    };
    renderPanel(liveReady);

    mocks.axisFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "PERMISSION_DENIED",
            message: "denied",
            reason: "missing_manifest_live_scope",
          },
        }),
        { status: 403, headers: { "x-request-id": "req-403-live" } },
      ),
    );
    await user.click(screen.getByRole("button", { name: /Enable live sync/ }));
    await user.type(
      screen.getByLabelText("Evidence references"),
      "approval:connector-live-enable\npolicy:egress-review\ncredential:vault://prod/db-readonly",
    );
    await user.click(screen.getByRole("button", { name: "Enable live operation" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enabling live operation additionally requires the enable-live scope (connectors:manifest:enable_live)",
    );
  });

  it("falls back to status-class copy for an unrecognized denial reason", async () => {
    const user = userEvent.setup();
    const { onTransitioned } = renderPanel(connectorWithStatus("registered_preview_only"));

    mocks.axisFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "PERMISSION_DENIED",
            message: "denied",
            reason: "some_future_denial_class",
          },
        }),
        { status: 403, headers: {} },
      ),
    );
    await user.click(screen.getByRole("button", { name: "Activate for previews" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your session does not carry the connector lifecycle scope for this tenant.",
    );
    // No fabricated request reference when the API sent none.
    expect(screen.queryByText(/Request reference/)).not.toBeInTheDocument();
    expect(onTransitioned).not.toHaveBeenCalled();
  });

  it("replaces actions with the SSO gate when the deployment enforces sign-in", () => {
    renderPanel(
      connectorWithStatus("registered_preview_only"),
      {
        authenticated: false,
        actor_id: null,
        tenant_id: TENANT_ID,
        scopes: [],
        mode: "sso",
        api_auth_required: true,
        expires_at: null,
        enterprise_sso_ready: true,
        readiness_status: "ready",
        issuer: "https://issuer.example",
        audience: "limes-axis-api",
        jwks_source: "remote",
        session_boundary: "cookie",
        capabilities: [],
        limitations: [],
        notes: [],
        unauthenticated_reason: null,
      } as NonNullable<Parameters<typeof ConnectorLifecyclePanel>[0]["identitySession"]>,
    );

    expect(screen.getByText("Sign in with SSO to change connector activation.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activate for previews" })).not
      .toBeInTheDocument();
  });

  it("renders the persisted revision trail newest-first without narrating transitions", () => {
    renderPanel(connectorWithStatus("active_preview"), null, [
      // Envelope order: newest revision first, current included.
      revision({
        revision_number: 3,
        status: "active_preview",
        audit_event_type: "connector.manifest.lifecycle_transitioned",
        created_at: "2026-08-22T07:00:00Z",
        replaced_by_revision_number: null,
      }),
      revision({
        revision_number: 2,
        status: "registered_preview_only",
        audit_event_type: "connector.manifest.registered",
        created_at: "2026-08-21T07:00:00Z",
        replaced_by_revision_number: 3,
      }),
    ]);

    const history = screen.getByRole("list", { name: "Revision history" });
    const rows = within(history).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("r3");
    expect(rows[0]).toHaveTextContent("Active Preview");
    // Activation changes are the transition ledger's job, not revision copy.
    expect(rows[0]).not.toHaveTextContent("Transitioned");
    expect(rows[1]).toHaveTextContent("r2");
    expect(rows[1]).toHaveTextContent("Registration recorded");
  });

  it("renders the governed transition ledger with actor and reason", () => {
    renderPanel(
      connectorWithStatus("active_preview"),
      null,
      [revision({ revision_number: 1 })],
      [
        {
          from_status: "registered_preview_only",
          target_status: "active_preview",
          transitioned_by: "platform-connector-owner-role",
          transition_reason: "Ready for governed preview configuration.",
          evidence_refs: ["approval:connector-manifest-preview-activation"],
          audit_event_id: "audit-transition-1",
          audit_event_type: "connector.manifest.lifecycle_transitioned",
          transitioned_at: "2026-08-22T07:05:00Z",
        },
      ],
    );

    const trail = screen.getByRole("list", { name: "Transition history" });
    expect(within(trail).getAllByRole("listitem")).toHaveLength(1);
    expect(trail).toHaveTextContent("Active Preview");
    expect(trail).toHaveTextContent("Activated for previews");
    expect(trail).toHaveTextContent("platform-connector-owner-role");
    expect(trail).toHaveTextContent(
      "Registered Preview Only → Active Preview: Ready for governed preview configuration.",
    );
  });

  it("labels an unrecognized transition audit event without inventing a claim", () => {
    renderPanel(
      connectorWithStatus("active_preview"),
      null,
      [revision({ revision_number: 1 })],
      [
        {
          from_status: "registered_preview_only",
          target_status: "active_preview",
          transitioned_by: "operator",
          transition_reason: "reason",
          evidence_refs: [],
          audit_event_id: "audit-transition-x",
          audit_event_type: "connector.manifest.some_future_event",
          transitioned_at: "2026-08-22T07:05:00Z",
        },
      ],
    );

    expect(screen.getByRole("list", { name: "Transition history" })).toHaveTextContent(
      "Transition recorded",
    );
  });

  it("omits both trails entirely when no revisions or transitions exist", () => {
    renderPanel(connectorWithStatus("active_preview"));

    expect(screen.queryByRole("list", { name: "Revision history" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Transition history" })).not.toBeInTheDocument();
  });
});
