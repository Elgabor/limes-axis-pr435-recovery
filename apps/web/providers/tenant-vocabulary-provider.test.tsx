import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TenantVocabularySet } from "@/lib/platform-tenants";

const mocks = vi.hoisted(() => ({
  fetchTenantVocabulary: vi.fn(),
  refreshNonce: 0,
}));

vi.mock("@/lib/platform-tenants", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/platform-tenants")>()),
  fetchTenantVocabulary: mocks.fetchTenantVocabulary,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ refreshNonce: mocks.refreshNonce }),
}));

import {
  resolveVocabularyTenantId,
  TenantVocabularyProvider,
  useTenantVocabulary,
} from "./tenant-vocabulary-provider";

const vocabularySet: TenantVocabularySet = {
  tenant_id: "tenant_fixture",
  vocabulary: {
    site_singular: "Site",
    site_plural: "Sites",
    workspace_label: "Operations",
    domain_labels: {
      Supply: "Pharmacy supply",
      Quality: "",
    },
  },
  configured: true,
  changes: [],
  vocabulary_notes: [],
};

function Consumer() {
  const { labelDomain, source } = useTenantVocabulary();
  return (
    <div>
      <span>{source}</span>
      <span>{labelDomain("Supply")}</span>
      <span>{labelDomain("Quality")}</span>
      <span>{labelDomain("Unknown")}</span>
    </div>
  );
}

function MutatingConsumer() {
  const { labelDomain, replaceVocabulary } = useTenantVocabulary();
  return (
    <div>
      <span>{labelDomain("Supply")}</span>
      <button
        onClick={() => replaceVocabulary({
          ...vocabularySet,
          vocabulary: {
            ...vocabularySet.vocabulary,
            domain_labels: { Supply: "Fresh label" },
          },
        })}
        type="button"
      >
        Replace
      </button>
    </div>
  );
}

beforeEach(() => {
  mocks.fetchTenantVocabulary.mockReset();
  mocks.refreshNonce = 0;
});

describe("TenantVocabularyProvider", () => {
  it("fetches once and shares mapped labels with raw-key fallback", async () => {
    mocks.fetchTenantVocabulary.mockResolvedValue(vocabularySet);

    render(
      <TenantVocabularyProvider enabled tenantId="tenant_fixture">
        <Consumer />
      </TenantVocabularyProvider>,
    );

    expect(await screen.findByText("Pharmacy supply")).toBeInTheDocument();
    expect(screen.getByText("Quality")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByText("api")).toBeInTheDocument();
    expect(mocks.fetchTenantVocabulary).toHaveBeenCalledTimes(1);
  });

  it("rejects a response for a different tenant", async () => {
    mocks.fetchTenantVocabulary.mockResolvedValue({
      ...vocabularySet,
      tenant_id: "tenant_other",
    });

    render(
      <TenantVocabularyProvider enabled tenantId="tenant_fixture">
        <Consumer />
      </TenantVocabularyProvider>,
    );

    await waitFor(() => expect(screen.getByText("unavailable")).toBeInTheDocument());
    expect(screen.queryByText("Pharmacy supply")).not.toBeInTheDocument();
  });

  it("does not let an in-flight refresh overwrite a just-saved replacement", async () => {
    const user = userEvent.setup();
    let resolveRefresh: ((record: TenantVocabularySet) => void) | undefined;
    mocks.fetchTenantVocabulary
      .mockResolvedValueOnce(vocabularySet)
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveRefresh = resolve;
      }));

    const view = render(
      <TenantVocabularyProvider enabled tenantId="tenant_fixture">
        <MutatingConsumer />
      </TenantVocabularyProvider>,
    );
    await screen.findByText("Pharmacy supply");

    mocks.refreshNonce = 1;
    view.rerender(
      <TenantVocabularyProvider enabled tenantId="tenant_fixture">
        <MutatingConsumer />
      </TenantVocabularyProvider>,
    );
    await waitFor(() => expect(mocks.fetchTenantVocabulary).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole("button", { name: "Replace" }));
    expect(screen.getByText("Fresh label")).toBeInTheDocument();

    resolveRefresh?.({
      ...vocabularySet,
      vocabulary: {
        ...vocabularySet.vocabulary,
        domain_labels: { Supply: "Stale label" },
      },
    });
    await waitFor(() => expect(screen.queryByText("Stale label")).not.toBeInTheDocument());
    expect(screen.getByText("Fresh label")).toBeInTheDocument();
  });
});

describe("resolveVocabularyTenantId", () => {
  it("uses the route tenant on detail pages and the console tenant elsewhere", () => {
    expect(resolveVocabularyTenantId("/tenants/tenant%20one", "tenant_console")).toBe(
      "tenant one",
    );
    expect(resolveVocabularyTenantId("/workflows", "tenant_console")).toBe("tenant_console");
    expect(resolveVocabularyTenantId("/tenants", "tenant_console")).toBeNull();
  });
});
