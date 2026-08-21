import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TenantVocabularySet } from "@/lib/platform-tenants";
import { TenantVocabularyProvider } from "@/providers/tenant-vocabulary-provider";

const mocks = vi.hoisted(() => ({
  fetchTenantVocabulary: vi.fn(),
  updateTenantVocabulary: vi.fn(),
  refreshNonce: 0,
}));

vi.mock("@/lib/platform-tenants", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/platform-tenants")>()),
  fetchTenantVocabulary: mocks.fetchTenantVocabulary,
  updateTenantVocabulary: mocks.updateTenantVocabulary,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ refreshNonce: mocks.refreshNonce }),
}));

import { TenantVocabularyEditor } from "./tenant-vocabulary-editor";

const defaultVocabulary: TenantVocabularySet = {
  tenant_id: "tenant_x",
  vocabulary: {
    site_singular: "Site",
    site_plural: "Sites",
    workspace_label: "Operations",
    domain_labels: {},
  },
  configured: false,
  changes: [],
  vocabulary_notes: [],
};

function renderEditor() {
  return render(
    <TenantVocabularyProvider enabled tenantId="tenant_x">
      <TenantVocabularyEditor tenantId="tenant_x" />
    </TenantVocabularyProvider>,
  );
}

beforeEach(() => {
  mocks.fetchTenantVocabulary.mockReset();
  mocks.updateTenantVocabulary.mockReset();
  mocks.refreshNonce = 0;
});

describe("TenantVocabularyEditor", () => {
  it("shows defaults and saves editable domain rows with the configure scope", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantVocabulary.mockResolvedValue(defaultVocabulary);
    mocks.updateTenantVocabulary.mockResolvedValue({
      kind: "updated",
      record: {
        ...defaultVocabulary,
        configured: true,
        vocabulary: {
          ...defaultVocabulary.vocabulary,
          domain_labels: { supply: "Pharmacy supply" },
        },
      },
    });

    renderEditor();

    expect(await screen.findByText("Using defaults")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add domain label" }));
    await user.type(screen.getByLabelText("Domain key"), "supply");
    await user.type(screen.getByLabelText("Display label"), "Pharmacy supply");
    await user.click(screen.getByRole("button", { name: "Review vocabulary update" }));
    expect(screen.getByText(/Confirm this tenant vocabulary update/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm vocabulary update" }));

    await waitFor(() => expect(mocks.updateTenantVocabulary).toHaveBeenCalledTimes(1));
    expect(mocks.updateTenantVocabulary).toHaveBeenCalledWith(
      "tenant_x",
      expect.objectContaining({
        actor_scopes: ["platform:tenant:operator", "platform:tenant:configure"],
        vocabulary: expect.objectContaining({
          domain_labels: { supply: "Pharmacy supply" },
        }),
      }),
      { session: null },
    );
    expect(await screen.findByText("Tenant configured")).toBeInTheDocument();
    expect(screen.getByText("Vocabulary update applied.")).toBeInTheDocument();
  });

  it("surfaces scope-denied responses with the required permission", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantVocabulary.mockResolvedValue(defaultVocabulary);
    mocks.updateTenantVocabulary.mockResolvedValue({
      kind: "forbidden",
      message: "Configure permission denied.",
      requiredPermission: "platform:tenant:configure",
      requestId: "req-tenant-vocabulary-403",
    });

    renderEditor();

    await screen.findByDisplayValue("Site");
    await user.click(screen.getByRole("button", { name: "Review vocabulary update" }));
    await user.click(screen.getByRole("button", { name: "Confirm vocabulary update" }));

    expect(
      await screen.findByText(
        /Configure permission denied\. Required permission: platform:tenant:configure\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("req-tenant-vocabulary-403")).toBeInTheDocument();
  });

  it("does not overwrite an unsaved edit during a background refresh", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantVocabulary.mockResolvedValueOnce(defaultVocabulary);
    const view = renderEditor();

    const singular = await screen.findByDisplayValue("Site");
    await user.clear(singular);
    await user.type(singular, "Facility");

    mocks.fetchTenantVocabulary.mockResolvedValueOnce({
      ...defaultVocabulary,
      vocabulary: { ...defaultVocabulary.vocabulary, site_singular: "Store" },
    });
    mocks.refreshNonce = 1;
    view.rerender(
      <TenantVocabularyProvider enabled tenantId="tenant_x">
        <TenantVocabularyEditor tenantId="tenant_x" />
      </TenantVocabularyProvider>,
    );

    await waitFor(() => expect(mocks.fetchTenantVocabulary).toHaveBeenCalledTimes(2));
    expect(singular).toHaveValue("Facility");
  });

  it("keeps a pending confirmation intact during a background refresh", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantVocabulary.mockResolvedValueOnce(defaultVocabulary);
    const view = renderEditor();

    const singular = await screen.findByDisplayValue("Site");
    await user.clear(singular);
    await user.type(singular, "Facility");
    await user.click(screen.getByRole("button", { name: "Review vocabulary update" }));

    mocks.fetchTenantVocabulary.mockResolvedValueOnce({
      ...defaultVocabulary,
      vocabulary: { ...defaultVocabulary.vocabulary, site_singular: "Store" },
    });
    mocks.refreshNonce = 1;
    view.rerender(
      <TenantVocabularyProvider enabled tenantId="tenant_x">
        <TenantVocabularyEditor tenantId="tenant_x" />
      </TenantVocabularyProvider>,
    );

    await waitFor(() => expect(mocks.fetchTenantVocabulary).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/Confirm this tenant vocabulary update/)).toBeInTheDocument();
    expect(singular).toHaveValue("Facility");
    expect(mocks.updateTenantVocabulary).not.toHaveBeenCalled();
  });

  it("applies a background refresh when the form is pristine", async () => {
    mocks.fetchTenantVocabulary.mockResolvedValueOnce(defaultVocabulary);
    const view = renderEditor();
    await screen.findByDisplayValue("Site");

    mocks.fetchTenantVocabulary.mockResolvedValueOnce({
      ...defaultVocabulary,
      vocabulary: { ...defaultVocabulary.vocabulary, site_singular: "Store" },
    });
    mocks.refreshNonce = 1;
    view.rerender(
      <TenantVocabularyProvider enabled tenantId="tenant_x">
        <TenantVocabularyEditor tenantId="tenant_x" />
      </TenantVocabularyProvider>,
    );

    expect(await screen.findByDisplayValue("Store")).toBeInTheDocument();
  });

  it("removes an existing domain row from the full replacement payload", async () => {
    const user = userEvent.setup();
    const configuredVocabulary = {
      ...defaultVocabulary,
      configured: true,
      vocabulary: {
        ...defaultVocabulary.vocabulary,
        domain_labels: { supply: "Pharmacy supply" },
      },
    };
    mocks.fetchTenantVocabulary.mockResolvedValue(configuredVocabulary);
    mocks.updateTenantVocabulary.mockResolvedValue({
      kind: "updated",
      record: {
        ...configuredVocabulary,
        vocabulary: {
          ...configuredVocabulary.vocabulary,
          domain_labels: {},
        },
      },
    });

    renderEditor();

    await screen.findByDisplayValue("Pharmacy supply");
    await user.click(screen.getByRole("button", { name: "Remove domain label: supply" }));
    await user.click(screen.getByRole("button", { name: "Review vocabulary update" }));
    await user.click(screen.getByRole("button", { name: "Confirm vocabulary update" }));

    await waitFor(() => expect(mocks.updateTenantVocabulary).toHaveBeenCalledTimes(1));
    expect(mocks.updateTenantVocabulary.mock.calls[0]?.[1]).toMatchObject({
      vocabulary: { domain_labels: {} },
    });
  });

  it("binds controls to the limits reported by the API contract", async () => {
    mocks.fetchTenantVocabulary.mockResolvedValue({
      ...defaultVocabulary,
      vocabulary: {
        ...defaultVocabulary.vocabulary,
        domain_labels: Object.fromEntries(
          Array.from({ length: 50 }, (_, index) => [`domain_${index}`, `Label ${index}`]),
        ),
      },
    });

    renderEditor();

    const singular = await screen.findByDisplayValue("Site");
    expect(singular).toHaveAttribute("maxlength", "100");
    expect(screen.getByRole("button", { name: "Add domain label" })).toBeDisabled();
  });

  it("shows API validation messages without replacing them with a generic error", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantVocabulary.mockResolvedValue(defaultVocabulary);
    mocks.updateTenantVocabulary.mockResolvedValue({
      kind: "invalid",
      message: "Domain labels must use registered operational keys.",
      fieldErrors: { domainLabels: "Unknown domain key: rogue." },
      requestId: "req-tenant-vocabulary-422",
    });

    renderEditor();

    await screen.findByDisplayValue("Site");
    await user.click(screen.getByRole("button", { name: "Review vocabulary update" }));
    await user.click(screen.getByRole("button", { name: "Confirm vocabulary update" }));

    expect(
      await screen.findByText(/Domain labels must use registered operational keys\./),
    ).toBeInTheDocument();
    expect(screen.getByText("Unknown domain key: rogue.")).toBeInTheDocument();
    expect(screen.getByText("req-tenant-vocabulary-422")).toBeInTheDocument();
  });

  it("keeps local vocabulary validation reference-free and does not call the API", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantVocabulary.mockResolvedValue(defaultVocabulary);

    renderEditor();

    await screen.findByDisplayValue("Site");
    await user.click(screen.getByRole("button", { name: "Add domain label" }));
    await user.click(screen.getByRole("button", { name: "Review vocabulary update" }));

    expect(
      screen.getAllByRole("alert").find((alert) =>
        alert.textContent?.includes(
          "Vocabulary update failed: Fix the highlighted fields; nothing was sent.",
        ),
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Request reference:/)).not.toBeInTheDocument();
    expect(mocks.updateTenantVocabulary).not.toHaveBeenCalled();
  });
});
