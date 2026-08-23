"use client";

import { useEffect, useSyncExternalStore } from "react";

import { AxisApiDecodeError, AxisApiError, axisFetchParsedJson } from "./axis-api";
import type { OidcConsoleSession } from "./oidc-session";
import type { IdentitySessionReadModel } from "./platform-overview";
import { parseIdentitySessionReadModel } from "./runtime-contracts/overview";
import { useOidcConsoleSession } from "./use-oidc-session";
import { useConsole } from "@/providers/console-provider";
import type {
  AxisQueryFailureDetails,
  AxisQuerySource,
} from "./use-axis-query";

/**
 * The one identity-session endpoint shared by every console surface.
 *
 * Every surface used to run its own `GET /identity/session` query, so a single
 * console page issued the same request once per mounted component. This seam
 * keeps one authoritative request per (refresh nonce × principal) key and
 * shares the resulting snapshot through a module-level store.
 */

export const IDENTITY_SESSION_ENDPOINT = "/identity/session";

const EMPTY_FAILURE_DETAILS: AxisQueryFailureDetails = {
  code: null,
  reason: null,
  requiredPermission: null,
  requestId: null,
  validationIssues: [],
};

type IdentityQuerySnapshot = {
  /**
   * Query key the snapshot belongs to. Consumers mask everything unless this
   * matches their render-time key, so a principal change can never expose the
   * previous actor's session facts for even one committed frame.
   */
  key: string | null;
  data: IdentitySessionReadModel | null;
  source: AxisQuerySource;
  error: string | null;
  errorStatus: number | null;
  errorDetails: AxisQueryFailureDetails;
  isRefreshing: boolean;
};

const INITIAL_SNAPSHOT: IdentityQuerySnapshot = {
  key: null,
  data: null,
  source: "loading",
  error: null,
  errorStatus: null,
  errorDetails: EMPTY_FAILURE_DETAILS,
  isRefreshing: false,
};

let snapshot: IdentityQuerySnapshot = INITIAL_SNAPSHOT;
/** Key whose payload `snapshot.data` currently holds. */
let loadedKey: string | null = null;
/** Key with an in-flight request; deduplicates concurrent consumers. */
let activeKey: string | null = null;
/** Session attached to the latest fetch; reused by background revalidation. */
let lastFetchedSession: OidcConsoleSession | null = null;

const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): IdentityQuerySnapshot {
  return snapshot;
}

function getServerSnapshot(): IdentityQuerySnapshot {
  return INITIAL_SNAPSHOT;
}

function commit(next: Partial<Omit<IdentityQuerySnapshot, "key">>): void {
  snapshot = { ...snapshot, ...next };
  for (const listener of listeners) {
    listener();
  }
}

/**
 * Refreshes reuse the previous payload only when the principal identity is
 * unchanged; a nonce bump alone distinguishes them from fresh loads.
 */
function isRefreshKey(previous: string | null, next: string): boolean {
  if (previous === null || previous === next) {
    return false;
  }
  const identityOf = (key: string) => key.slice(key.indexOf("\u0000") + 1);
  return identityOf(previous) === identityOf(next);
}

function classifyFailure(caught: unknown): {
  source: AxisQuerySource;
  error: string;
  errorStatus: number | null;
  errorDetails: AxisQueryFailureDetails;
} {
  const tenantNotFound =
    caught instanceof AxisApiError
    && caught.status === 404
    && caught.code === "TENANT_NOT_FOUND";
  return {
    source: tenantNotFound ? "tenant_not_found" : "unavailable",
    error: caught instanceof Error ? caught.message : "Axis API request failed.",
    errorStatus: caught instanceof AxisApiError ? caught.status : null,
    errorDetails: {
      code: caught instanceof AxisApiError ? caught.code : null,
      reason: caught instanceof AxisApiError ? caught.reason : null,
      requiredPermission:
        caught instanceof AxisApiError ? caught.requiredPermission : null,
      requestId:
        caught instanceof AxisApiError || caught instanceof AxisApiDecodeError
          ? caught.requestId
          : null,
      validationIssues:
        caught instanceof AxisApiError || caught instanceof AxisApiDecodeError
          ? caught.validationIssues
          : [],
    },
  };
}

async function ensureFetch(
  stateKey: string,
  session: OidcConsoleSession | null,
  options: { force?: boolean } = {},
): Promise<void> {
  const forced = options.force === true;
  if (forced) {
    // One background revalidation at a time; never stack heartbeats behind a
    // slow response or race an in-flight principal switch.
    if (activeKey !== null) {
      return;
    }
  } else if (activeKey === stateKey || loadedKey === stateKey) {
    return;
  }
  const refresh = forced
    ? Boolean(snapshot.data)
    : isRefreshKey(loadedKey, stateKey);
  activeKey = stateKey;
  if (refresh) {
    // Same principal, new refresh nonce: keep the previous payload visible and
    // flag the revalidation instead of flashing back to loading.
    snapshot = { ...snapshot, key: stateKey, isRefreshing: true };
    for (const listener of listeners) {
      listener();
    }
  } else {
    // A different principal (or first load) invalidates any prior snapshot
    // synchronously so no consumer ever renders the previous session's facts.
    loadedKey = null;
    snapshot = { ...INITIAL_SNAPSHOT, key: stateKey };
    for (const listener of listeners) {
      listener();
    }
  }
  lastFetchedSession = session;

  try {
    const payload = await axisFetchParsedJson(
      IDENTITY_SESSION_ENDPOINT,
      parseIdentitySessionReadModel,
      { session },
    );
    if (activeKey !== stateKey) {
      return; // Superseded by another principal or refresh; drop silently.
    }
    loadedKey = stateKey;
    activeKey = null;
    commit({
      data: payload,
      source: "api",
      error: null,
      errorStatus: null,
      errorDetails: EMPTY_FAILURE_DETAILS,
      isRefreshing: false,
    });
  } catch (caught) {
    if (activeKey !== stateKey) {
      return;
    }
    activeKey = null;
    const failure = classifyFailure(caught);
    if (!refresh) {
      loadedKey = null;
    }
    commit({ ...failure, isRefreshing: false });
  }
}

/** Test-only: module store state outlives individual cases. */
export function resetIdentitySessionStore(): void {
  snapshot = INITIAL_SNAPSHOT;
  loadedKey = null;
  activeKey = null;
  lastFetchedSession = null;
}

const HEARTBEAT_REVALIDATION_THROTTLE_MS = 15_000;

/**
 * Bounded background convergence for enforced-SSO deployments.
 *
 * While the API has verified an authenticated session, a timer plus window
 * focus re-run `/identity/session` so an idle-timeout, revocation, or expiry
 * flips the shell to its sign-in gate promptly instead of at the next
 * unrelated user action. Auth-optional/demo deployments are never polled.
 * Returns a stop function.
 */
export function startIdentitySessionHeartbeat(
  intervalMs: number = 60_000,
): () => void {
  let lastTickAt = 0;

  function tick(): void {
    const now = Date.now();
    if (now - lastTickAt < HEARTBEAT_REVALIDATION_THROTTLE_MS) {
      return;
    }
    lastTickAt = now;
    if (loadedKey === null || activeKey !== null) {
      return;
    }
    const data = snapshot.data;
    if (!data?.authenticated || !data.api_auth_required) {
      // No verified session to lose: nothing to converge (and no polling of
      // demo deployments behind the gate or in auth-optional mode).
      return;
    }
    void ensureFetch(loadedKey, lastFetchedSession, { force: true });
  }

  const intervalId = window.setInterval(tick, intervalMs);
  const onRefocus = (): void => {
    if (document.visibilityState === "visible") {
      tick();
    }
  };
  window.addEventListener("focus", onRefocus);
  document.addEventListener("visibilitychange", onRefocus);
  return () => {
    window.clearInterval(intervalId);
    window.removeEventListener("focus", onRefocus);
    document.removeEventListener("visibilitychange", onRefocus);
  };
}

export type IdentitySessionQuery = {
  data: IdentitySessionReadModel | null;
  source: AxisQuerySource;
  error: string | null;
  errorStatus: number | null;
  errorCode: string | null;
  errorReason: string | null;
  errorRequiredPermission: string | null;
  errorRequestId: string | null;
  validationIssues: readonly unknown[];
  isRefreshing: boolean;
  isLoading: boolean;
  isUnavailable: boolean;
  isTenantNotFound: boolean;
};

/**
 * Shared, API-verified identity session state for the whole console.
 *
 * Semantics mirror `useAxisQuery` (stale-while-revalidate on the global
 * refresh bus, classified failures keep stale data on screen) while all
 * surfaces observe one request and one snapshot.
 */
export function useIdentitySession(): IdentitySessionQuery {
  const { refreshNonce } = useConsole();
  const oidcSession = useOidcConsoleSession();
  const { session } = oidcSession;
  const hydrated = oidcSession.hydrated;
  const sessionIdentity = session
    ? `${session.tenantId}\u0000${session.actorId}`
    : "cookie-session";
  const stateKey = hydrated ? `${refreshNonce}\u0000${sessionIdentity}` : null;

  useEffect(() => {
    if (stateKey === null) {
      return;
    }
    void ensureFetch(stateKey, session);
  }, [stateKey, session]);

  const observed = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const current = stateKey !== null && observed.key === stateKey;

  return {
    data: current ? observed.data : null,
    source: current ? observed.source : "loading",
    error: current ? observed.error : null,
    errorStatus: current ? observed.errorStatus : null,
    errorCode: current ? observed.errorDetails.code : null,
    errorReason: current ? observed.errorDetails.reason : null,
    errorRequiredPermission: current
      ? observed.errorDetails.requiredPermission
      : null,
    errorRequestId: current ? observed.errorDetails.requestId : null,
    validationIssues: current ? observed.errorDetails.validationIssues : [],
    isRefreshing: current ? observed.isRefreshing : false,
    isLoading: !current || observed.source === "loading",
    isUnavailable: current && observed.source === "unavailable",
    isTenantNotFound: current && observed.source === "tenant_not_found",
  };
}
