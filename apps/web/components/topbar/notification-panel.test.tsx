import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  IdentitySessionReadModel,
  ManufacturingNotificationCenter,
  ManufacturingPlatformNotification,
} from "@/lib/platform-overview";
import { AxisApiError } from "@/lib/axis-api";

const mocks = vi.hoisted(() => ({
  axisFetchParsedJson: vi.fn(),
}));

vi.mock("@/lib/axis-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/axis-api")>();
  return {
    ...actual,
    axisFetchParsedJson: mocks.axisFetchParsedJson,
  };
});

import { NotificationPanel } from "./notification-panel";

const identitySession: IdentitySessionReadModel = {
  authenticated: true,
  mode: "oidc",
  actor_id: "operator_acme",
  tenant_id: "tenant_acme",
  scopes: ["notifications:acknowledge"],
  expires_at: null,
  api_auth_required: true,
  enterprise_sso_ready: true,
  readiness_status: "ready",
  issuer: "",
  audience: "",
  jwks_source: "disabled",
  session_boundary: "secure_oidc_cookie",
  capabilities: [],
  limitations: [],
  notes: [],
  unauthenticated_reason: null,
};

function notification(
  overrides: Partial<ManufacturingPlatformNotification> & { notification_id: string },
): ManufacturingPlatformNotification {
  return {
    category: "risk",
    severity: "watch",
    title: overrides.notification_id,
    detail: "Fixture notification detail.",
    source: "fixture",
    route: "/overview",
    occurred_at: "2026-07-24T09:00:00Z",
    owner_role: null,
    related_workflow_id: null,
    related_approval_id: null,
    evidence_refs: [],
    action_label: "Open",
    read_state: "unread",
    acknowledged_by: null,
    acknowledged_at: null,
    acknowledgement_reason: null,
    ...overrides,
  };
}

const center: ManufacturingNotificationCenter = {
  tenant_id: "tenant_acme",
  plant_name: "Fixture Plant",
  scenario: "Fixture scenario",
  provenance: "live",
  as_of: "2026-07-24T09:00:00Z",
  unread_count: 2,
  action_required_count: 0,
  watch_count: 2,
  notifications: [
    notification({ notification_id: "notif_slow" }),
    notification({ notification_id: "notif_fast" }),
  ],
  generation_boundary: "boundary-1",
  notes: [],
};

const switchedIdentitySession: IdentitySessionReadModel = {
  ...identitySession,
  actor_id: "operator_globex",
  tenant_id: "tenant_globex",
};

const switchedCenter: ManufacturingNotificationCenter = {
  ...center,
  tenant_id: "tenant_globex",
};

/** A deferred promise so the test can control exactly when a fetch resolves. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  mocks.axisFetchParsedJson.mockReset();
});

describe("NotificationPanel acknowledgement", () => {
  it("keeps successful acknowledgements disabled while refreshed props are pending", async () => {
    const user = userEvent.setup();
    const slow = deferred<unknown>();
    const fast = deferred<unknown>();
    const onAcknowledged = vi.fn();
    mocks.axisFetchParsedJson.mockReturnValueOnce(slow.promise);
    mocks.axisFetchParsedJson.mockReturnValueOnce(fast.promise);

    render(
      <NotificationPanel
        center={center}
        identitySession={identitySession}
        onAcknowledged={onAcknowledged}
        session={null}
        source="api"
      />,
    );

    const slowRow = screen.getByLabelText(/notif_slow/);
    const fastRow = screen.getByLabelText(/notif_fast/);
    const slowButton = within(slowRow).getByRole("button");
    const fastButton = within(fastRow).getByRole("button");

    await user.click(slowButton);
    expect(slowButton).toHaveTextContent("Saving");
    expect(slowButton).toBeDisabled();

    await user.click(fastButton);
    expect(fastButton).toHaveTextContent("Saving");
    expect(fastButton).toBeDisabled();

    // The fast request completes first. Acknowledging it must not clear the
    // pending flag for the still in-flight slow request and re-enable its
    // button for a double submit.
    fast.resolve({});
    await waitFor(() => expect(fastButton).toHaveTextContent("Acked"));
    expect(fastButton).toBeDisabled();
    expect(slowButton).toHaveTextContent("Saving");
    expect(slowButton).toBeDisabled();
    expect(onAcknowledged).toHaveBeenCalledTimes(1);

    await user.click(fastButton);
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(2);

    slow.resolve({});
    await waitFor(() => expect(slowButton).toHaveTextContent("Acked"));
    expect(slowButton).toBeDisabled();
    expect(onAcknowledged).toHaveBeenCalledTimes(2);
  });

  it("reconciles an optimistic acknowledgement after refreshed props confirm it", async () => {
    const user = userEvent.setup();
    mocks.axisFetchParsedJson.mockResolvedValueOnce({});

    const { rerender } = render(
      <NotificationPanel
        center={center}
        identitySession={identitySession}
        onAcknowledged={vi.fn()}
        session={null}
        source="api"
      />,
    );

    const slowRow = screen.getByLabelText(/notif_slow/);
    const slowButton = within(slowRow).getByRole("button");
    await user.click(slowButton);
    await waitFor(() => expect(slowButton).toHaveTextContent("Acked"));

    const confirmedCenter: ManufacturingNotificationCenter = {
      ...center,
      unread_count: 1,
      notifications: center.notifications.map((item) =>
        item.notification_id === "notif_slow"
          ? {
              ...item,
              read_state: "acknowledged",
              acknowledged_by: "operator_acme",
              acknowledged_at: "2026-07-24T09:01:00Z",
              acknowledgement_reason: "Persisted acknowledgement.",
            }
          : item,
      ),
    };
    rerender(
      <NotificationPanel
        center={confirmedCenter}
        identitySession={identitySession}
        onAcknowledged={vi.fn()}
        session={null}
        source="api"
      />,
    );

    expect(within(slowRow).getByText("Persisted acknowledgement.")).toBeVisible();
    expect(slowButton).toHaveTextContent("Acked");

    const subsequentUnreadCenter: ManufacturingNotificationCenter = {
      ...center,
      notifications: center.notifications.map((item) => ({ ...item })),
    };
    rerender(
      <NotificationPanel
        center={subsequentUnreadCenter}
        identitySession={identitySession}
        onAcknowledged={vi.fn()}
        session={null}
        source="api"
      />,
    );

    await waitFor(() => expect(slowButton).toHaveTextContent("Ack"));
    expect(slowButton).toBeEnabled();
    expect(within(slowRow).getByText("Fixture notification detail.")).toBeVisible();
  });

  it.each([
    {
      boundary: "tenant",
      nextCenter: { ...center, tenant_id: "tenant_globex" },
      nextIdentitySession: { ...identitySession, tenant_id: "tenant_globex" },
    },
    {
      boundary: "actor",
      nextCenter: center,
      nextIdentitySession: { ...identitySession, actor_id: "operator_globex" },
    },
  ])(
    "does not carry optimistic state across an in-place $boundary switch",
    async ({ nextCenter, nextIdentitySession }) => {
      const user = userEvent.setup();
      const onAcknowledged = vi.fn();
      mocks.axisFetchParsedJson.mockResolvedValue({});

      const { rerender } = render(
        <NotificationPanel
          center={center}
          identitySession={identitySession}
          onAcknowledged={onAcknowledged}
          session={null}
          source="api"
        />,
      );

      const initialButton = within(screen.getByLabelText(/notif_slow/)).getByRole("button");
      await user.click(initialButton);
      await waitFor(() => expect(initialButton).toHaveTextContent("Acked"));

      rerender(
        <NotificationPanel
          center={nextCenter}
          identitySession={nextIdentitySession}
          onAcknowledged={onAcknowledged}
          session={null}
          source="api"
        />,
      );

      const switchedButton = within(screen.getByLabelText(/notif_slow/)).getByRole("button");
      expect(switchedButton).toHaveTextContent("Ack");
      expect(switchedButton).toBeEnabled();

      await user.click(switchedButton);
      await waitFor(() => expect(switchedButton).toHaveTextContent("Acked"));

      expect(onAcknowledged).toHaveBeenCalledTimes(2);
      expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(2);
      expect(mocks.axisFetchParsedJson.mock.calls[1]?.[2]).toMatchObject({
        body: {
          actor_id: nextIdentitySession.actor_id,
          tenant_id: nextIdentitySession.tenant_id,
        },
      });
    },
  );

  it("ignores an old successful request after the tenant and actor switch", async () => {
    const user = userEvent.setup();
    const oldRequest = deferred<unknown>();
    const onAcknowledged = vi.fn();
    mocks.axisFetchParsedJson
      .mockReturnValueOnce(oldRequest.promise)
      .mockResolvedValueOnce({});

    const { rerender } = render(
      <NotificationPanel
        center={center}
        identitySession={identitySession}
        onAcknowledged={onAcknowledged}
        session={null}
        source="api"
      />,
    );

    const initialButton = within(screen.getByLabelText(/notif_slow/)).getByRole("button");
    await user.click(initialButton);
    expect(initialButton).toHaveTextContent("Saving");

    rerender(
      <NotificationPanel
        center={switchedCenter}
        identitySession={switchedIdentitySession}
        onAcknowledged={onAcknowledged}
        session={null}
        source="api"
      />,
    );

    const switchedButton = within(screen.getByLabelText(/notif_slow/)).getByRole("button");
    expect(switchedButton).toHaveTextContent("Ack");
    expect(switchedButton).toBeEnabled();

    await act(async () => {
      oldRequest.resolve({});
      await oldRequest.promise;
    });

    expect(switchedButton).toHaveTextContent("Ack");
    expect(switchedButton).toBeEnabled();
    expect(onAcknowledged).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.click(switchedButton);
    await waitFor(() => expect(switchedButton).toHaveTextContent("Acked"));
    expect(onAcknowledged).toHaveBeenCalledTimes(1);
  });

  it("ignores an old failed request after the tenant and actor switch", async () => {
    const user = userEvent.setup();
    const oldRequest = deferred<unknown>();
    const onAcknowledged = vi.fn();
    mocks.axisFetchParsedJson
      .mockReturnValueOnce(oldRequest.promise)
      .mockResolvedValueOnce({});

    const { rerender } = render(
      <NotificationPanel
        center={center}
        identitySession={identitySession}
        onAcknowledged={onAcknowledged}
        session={null}
        source="api"
      />,
    );

    await user.click(within(screen.getByLabelText(/notif_slow/)).getByRole("button"));

    rerender(
      <NotificationPanel
        center={switchedCenter}
        identitySession={switchedIdentitySession}
        onAcknowledged={onAcknowledged}
        session={null}
        source="api"
      />,
    );

    const switchedButton = within(screen.getByLabelText(/notif_slow/)).getByRole("button");
    await act(async () => {
      oldRequest.reject(new AxisApiError(
        "/operations/notifications/notif_slow/acknowledgement",
        503,
        {
          body: { detail: { message: "Old principal request failed." } },
          requestId: "req_old_principal_503",
        },
      ));
      await oldRequest.promise.catch(() => undefined);
    });

    expect(switchedButton).toHaveTextContent("Ack");
    expect(switchedButton).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/req_old_principal_503/)).not.toBeInTheDocument();
    expect(onAcknowledged).not.toHaveBeenCalled();

    await user.click(switchedButton);
    await waitFor(() => expect(switchedButton).toHaveTextContent("Acked"));
    expect(onAcknowledged).toHaveBeenCalledTimes(1);
  });

  it("announces a failed acknowledgement and permits a retry", async () => {
    const user = userEvent.setup();
    const onAcknowledged = vi.fn();
    mocks.axisFetchParsedJson
      .mockRejectedValueOnce(new AxisApiError(
        "/operations/notifications/notif_slow/acknowledgement",
        503,
        {
          body: {
            detail: {
              message: "Axis could not persist the acknowledgement.",
              debug_context: "secret=must-not-render",
            },
          },
          requestId: "req_notification_ack_503",
        },
      ))
      .mockResolvedValueOnce({});

    render(
      <NotificationPanel
        center={center}
        identitySession={identitySession}
        onAcknowledged={onAcknowledged}
        session={null}
        source="api"
      />,
    );

    const slowRow = screen.getByLabelText(/notif_slow/);
    const slowButton = within(slowRow).getByRole("button");
    await user.click(slowButton);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Axis could not persist the acknowledgement.",
    );
    expect(alert).toHaveTextContent("Ref req_notification_ack_503");
    expect(alert).not.toHaveTextContent("secret=must-not-render");
    expect(slowButton).toHaveTextContent("Ack");
    expect(slowButton).toBeEnabled();
    expect(onAcknowledged).not.toHaveBeenCalled();

    await user.click(slowButton);

    await waitFor(() => expect(slowButton).toHaveTextContent("Acked"));
    expect(slowButton).toBeDisabled();
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(2);
    expect(onAcknowledged).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("separates unread count from payload provenance", () => {
    render(
      <NotificationPanel
        center={center}
        identitySession={identitySession}
        onAcknowledged={vi.fn()}
        session={null}
        source="api"
      />,
    );

    expect(screen.getByText("2 unread")).toBeInTheDocument();
    expect(screen.getByText("notifications: live")).toBeInTheDocument();
    expect(screen.queryByText("2 live")).not.toBeInTheDocument();
  });
});
