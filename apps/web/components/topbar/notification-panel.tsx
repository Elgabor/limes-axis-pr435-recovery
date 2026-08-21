"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  PopoverHeader,
  popoverClass,
  popoverLinkClass,
  popoverRowClass,
} from "@/components/topbar/panel-chrome";
import { SourcePill } from "@/components/ui/source-pill";
import {
  axisFetchParsedJson,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";
import { notificationTone } from "@/lib/identity-format";
import type {
  IdentitySessionReadModel,
  ManufacturingNotificationAcknowledgementResult,
  ManufacturingNotificationCenter,
  ManufacturingPlatformNotification,
} from "@/lib/platform-overview";
import type { useOidcConsoleSession } from "@/lib/use-oidc-session";
import {
  parseManufacturingNotificationAcknowledgementResult,
} from "@/lib/runtime-contracts/overview";
import { deriveSourceState, type AxisSource } from "@/lib/source-state";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

type AcknowledgementScope = Readonly<{
  key: string | null;
  isActive: () => boolean;
  setActive: (active: boolean) => void;
}>;

type AcknowledgementState = {
  scope: AcknowledgementScope;
  pendingNotificationIds: ReadonlySet<string>;
  optimisticallyAcknowledgedNotificationIds: ReadonlySet<string>;
  acknowledgementError: AxisOperatorError | null;
  lastReconciledCenter: ManufacturingNotificationCenter | null;
};

function acknowledgementScopeKey(
  identitySession: IdentitySessionReadModel | null,
): string | null {
  if (
    !identitySession?.authenticated
    || !identitySession.tenant_id
    || !identitySession.actor_id
  ) {
    return null;
  }

  // JSON encoding keeps tenant and actor ids unambiguous even when either id
  // contains punctuation that is commonly used as a hand-written separator.
  return JSON.stringify([identitySession.tenant_id, identitySession.actor_id]);
}

function createAcknowledgementScope(key: string | null): AcknowledgementScope {
  let active = true;
  return {
    key,
    isActive: () => active,
    setActive: (nextActive) => {
      active = nextActive;
    },
  };
}

function createAcknowledgementState(
  scope: AcknowledgementScope,
  center: ManufacturingNotificationCenter | null,
): AcknowledgementState {
  return {
    scope,
    pendingNotificationIds: new Set(),
    optimisticallyAcknowledgedNotificationIds: new Set(),
    acknowledgementError: null,
    lastReconciledCenter: center,
  };
}

function reconcileAcknowledgementState(
  state: AcknowledgementState,
  center: ManufacturingNotificationCenter | null,
): AcknowledgementState {
  if (state.lastReconciledCenter === center) {
    return state;
  }

  if (center === null || state.optimisticallyAcknowledgedNotificationIds.size === 0) {
    return { ...state, lastReconciledCenter: center };
  }

  const refreshedNotifications = new Map(
    center.notifications.map((item) => [item.notification_id, item]),
  );
  const nextOptimisticIds = new Set(state.optimisticallyAcknowledgedNotificationIds);
  for (const notificationId of state.optimisticallyAcknowledgedNotificationIds) {
    const refreshedNotification = refreshedNotifications.get(notificationId);
    if (!refreshedNotification || refreshedNotification.read_state === "acknowledged") {
      nextOptimisticIds.delete(notificationId);
    }
  }

  return {
    ...state,
    optimisticallyAcknowledgedNotificationIds: nextOptimisticIds,
    lastReconciledCenter: center,
  };
}

export function NotificationPanel({
  center,
  identitySession,
  onAcknowledged,
  session,
  source,
}: {
  center: ManufacturingNotificationCenter | null;
  identitySession: IdentitySessionReadModel | null;
  onAcknowledged: () => void;
  session: ReturnType<typeof useOidcConsoleSession>["session"];
  source: AxisSource;
}) {
  const scopeKey = acknowledgementScopeKey(identitySession);
  // Object identity is intentional: this is a request-generation token as
  // well as a tenant+actor key. A late A -> B -> A completion must not mutate
  // the second A session merely because its principal ids match again.
  const currentScope = useMemo(
    () => createAcknowledgementScope(scopeKey),
    [scopeKey],
  );
  const [acknowledgementState, setAcknowledgementState] = useState<AcknowledgementState>(
    () => createAcknowledgementState(currentScope, center),
  );

  useEffect(() => {
    currentScope.setActive(true);
    return () => currentScope.setActive(false);
  }, [currentScope]);

  const scopedAcknowledgementState = acknowledgementState.scope === currentScope
    ? acknowledgementState
    : createAcknowledgementState(currentScope, center);
  const reconciledAcknowledgementState = reconcileAcknowledgementState(
    scopedAcknowledgementState,
    center,
  );
  if (reconciledAcknowledgementState !== acknowledgementState) {
    // React permits a guarded render-time adjustment when state is derived
    // from changed props. It commits the restarted render, so another
    // principal never receives one painted frame of the previous scope.
    setAcknowledgementState(reconciledAcknowledgementState);
  }

  const pendingNotificationIds = reconciledAcknowledgementState.pendingNotificationIds;
  const optimisticallyAcknowledgedNotificationIds =
    reconciledAcknowledgementState.optimisticallyAcknowledgedNotificationIds;
  const acknowledgementError = reconciledAcknowledgementState.acknowledgementError;

  if (!center) {
    const sourceState = deriveSourceState(source, false);
    return (
      <section className={popoverClass} aria-label="Notifications">
        <PopoverHeader label="Notifications">
          <SourcePill state={sourceState} subject="notifications" />
        </PopoverHeader>
        <p className="m-0 text-sm leading-snug text-muted">
          {sourceState === "loading"
            ? "Loading notification evidence."
            : `Notification data requires ${OPERATIONS_API_PREFIX}/notifications.`}
        </p>
      </section>
    );
  }

  const items = center.notifications.slice(0, 5);
  const canAcknowledge = Boolean(
    identitySession?.authenticated
      && identitySession.actor_id
      && identitySession.tenant_id
      && identitySession.scopes.includes("notifications:acknowledge"),
  );
  const sessionRequiredLabel = identitySession?.authenticated
    ? "Your OIDC session needs notifications:acknowledge."
    : "Sign in with SSO to acknowledge notifications.";

  async function acknowledgeNotification(item: ManufacturingPlatformNotification) {
    if (
      !identitySession?.actor_id
      || !identitySession.tenant_id
      || !canAcknowledge
      || item.read_state === "acknowledged"
      || pendingNotificationIds.has(item.notification_id)
      || optimisticallyAcknowledgedNotificationIds.has(item.notification_id)
    ) {
      return;
    }

    const requestScope = currentScope;
    const requestTenantId = identitySession.tenant_id;
    const requestActorId = identitySession.actor_id;
    const requestActorScopes = [...identitySession.scopes];
    setAcknowledgementState((current) => {
      if (!requestScope.isActive()) {
        return current;
      }
      const activeState = current.scope === requestScope
        ? current
        : createAcknowledgementState(requestScope, center);
      return {
        ...activeState,
        pendingNotificationIds: new Set(activeState.pendingNotificationIds).add(
          item.notification_id,
        ),
        acknowledgementError: null,
      };
    });
    try {
      await axisFetchParsedJson<ManufacturingNotificationAcknowledgementResult>(
        `${OPERATIONS_API_PREFIX}/notifications/${item.notification_id}/acknowledgement`,
        parseManufacturingNotificationAcknowledgementResult,
        {
          method: "POST",
          session,
          body: {
            tenant_id: requestTenantId,
            actor_id: requestActorId,
            actor_scopes: requestActorScopes,
            state: "acknowledged",
            reason: "Acknowledged from the Axis console notification center.",
          },
        },
      );
      if (!requestScope.isActive()) {
        return;
      }
      setAcknowledgementState((current) => current.scope === requestScope
        ? {
            ...current,
            optimisticallyAcknowledgedNotificationIds: new Set(
              current.optimisticallyAcknowledgedNotificationIds,
            ).add(item.notification_id),
          }
        : current);
      onAcknowledged();
    } catch (caught) {
      if (requestScope.isActive()) {
        setAcknowledgementState((current) => current.scope === requestScope
          ? {
              ...current,
              acknowledgementError: toAxisOperatorError(
                caught,
                "Axis could not persist the acknowledgement.",
              ),
            }
          : current);
      }
    } finally {
      if (!requestScope.isActive()) {
        return;
      }
      setAcknowledgementState((current) => {
        if (current.scope !== requestScope) {
          return current;
        }
        const next = new Set(current.pendingNotificationIds);
        next.delete(item.notification_id);
        return { ...current, pendingNotificationIds: next };
      });
    }
  }

  return (
    <section className={popoverClass} aria-label="Notifications">
      <PopoverHeader label="Notifications">
        <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
          <span className="status-pill status-checking">
            {formatNumber(center.unread_count)} unread
          </span>
          <SourcePill
            state={deriveSourceState(source, true, center.provenance)}
            subject="notifications"
          />
        </span>
      </PopoverHeader>
      <div className="grid gap-2">
        {items.length > 0 ? (
          items.map((item) => {
            const acknowledged =
              item.read_state === "acknowledged" ||
              optimisticallyAcknowledgedNotificationIds.has(item.notification_id);
            const pending = pendingNotificationIds.has(item.notification_id);
            return (
              <div
                aria-label={`${item.action_label}: ${item.title}`}
                className={cn(
                  "notification-row",
                  popoverRowClass,
                  acknowledged && "opacity-70",
                )}
                key={item.notification_id}
              >
                <span
                  aria-hidden="true"
                  className={`status-dot ${notificationTone(item.severity)}`}
                />
                <span className="min-w-0 [&_small]:line-clamp-2 [&_strong]:truncate">
                  <strong>{item.title}</strong>
                  <small>
                    {acknowledged
                      ? item.acknowledgement_reason ?? "Acknowledged"
                      : item.detail}
                  </small>
                </span>
                <span className="col-start-2 mt-2 inline-flex items-center gap-1.5">
                  <Link
                    className="grid h-7 w-[54px] place-items-center rounded-lg border border-line text-[11px] leading-none font-bold whitespace-nowrap text-signal dark:border-white/15"
                    href={item.route}
                    title={item.action_label}
                  >
                    Open
                  </Link>
                  <button
                    className="grid h-7 w-[52px] cursor-pointer place-items-center rounded-lg border border-positive/35 bg-positive/8 text-[11px] leading-none font-bold whitespace-nowrap text-positive disabled:cursor-not-allowed disabled:border-line/60 disabled:bg-ink/3 disabled:text-muted dark:disabled:bg-white/5"
                    disabled={!canAcknowledge || acknowledged || pending}
                    onClick={() => void acknowledgeNotification(item)}
                    type="button"
                  >
                    {acknowledged ? "Acked" : pending ? "Saving" : "Ack"}
                  </button>
                </span>
              </div>
            );
          })
        ) : (
          <div className={popoverRowClass}>
            <span aria-hidden="true" className="status-dot signal-ready" />
            <span>
              <strong>No active notifications</strong>
              <small>Axis did not derive pending alerts from persisted platform state.</small>
            </span>
          </div>
        )}
      </div>
      {items.length > 0 && !canAcknowledge ? (
        <p className="m-0 text-[11px] leading-snug text-muted">{sessionRequiredLabel}</p>
      ) : null}
      {acknowledgementError ? (
        <p className="m-0 text-[11px] leading-snug text-warning" role="alert">
          {acknowledgementError.message}
          {acknowledgementError.requestId ? (
            <span className="ml-1 font-mono text-[10px] break-all text-muted">
              Ref {acknowledgementError.requestId}
            </span>
          ) : null}
        </p>
      ) : null}
      <Link className={popoverLinkClass} href="/audit">
        Open audit evidence
      </Link>
    </section>
  );
}
