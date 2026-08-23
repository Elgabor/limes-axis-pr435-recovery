"use client";

import { useEffect, useRef, useState } from "react";

import { AxisApiDecodeError, AxisApiError, axisFetchParsedJson } from "@/lib/axis-api";
import { useConsole } from "@/providers/console-provider";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";

export type AxisQuerySource = "loading" | "api" | "tenant_not_found" | "unavailable";

export type AxisQueryFailureDetails = {
  code: string | null;
  reason: string | null;
  /** Permission named by a 403 `missing_required_scope` denial, when sent. */
  requiredPermission: string | null;
  requestId: string | null;
  validationIssues: readonly unknown[];
};

const EMPTY_FAILURE_DETAILS: AxisQueryFailureDetails = {
  code: null,
  reason: null,
  requiredPermission: null,
  requestId: null,
  validationIssues: [],
};

type UseAxisQueryOptions<T> = {
  enabled?: boolean;
  expectedTenantId?: string;
  parse: (value: unknown) => T;
};

/**
 * Fetch a JSON payload from the Axis API with stale-while-revalidate
 * semantics: the initial load starts at `source: "loading"`, but refetches
 * triggered by the global refresh bus keep the previous data on screen and
 * flag `isRefreshing` instead. A failed refresh sets a classified failure
 * source and `error` while keeping the stale data for display. Changing
 * `path` is a different query, so it resets to
 * loading and drops the old data. An actor or tenant change is also a new
 * query identity and can never reuse the previous principal's data.
 */
export function useAxisQuery<T>(path: string, options: UseAxisQueryOptions<T>) {
  const { refreshNonce } = useConsole();
  const oidcSession = useOidcConsoleSession();
  const { session } = oidcSession;
  const [data, setData] = useState<T | null>(null);
  const [source, setSource] = useState<AxisQuerySource>("loading");
  const [error, setError] = useState<string | null>(null);
  /** HTTP status of the last failed request; null for non-HTTP failures. */
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [errorDetails, setErrorDetails] = useState<AxisQueryFailureDetails>(
    EMPTY_FAILURE_DETAILS,
  );
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [stateKey, setStateKey] = useState<string | null>(null);
  const enabled = options.enabled ?? true;
  const expectedTenantId = options.expectedTenantId;
  const parse = options.parse;

  // The data currently held for `lastLoadedKeyRef.current`; used to decide
  // whether a refetch is a background refresh (keep data) or a fresh load.
  const staleDataRef = useRef<T | null>(null);
  const lastLoadedKeyRef = useRef<string | null>(null);
  const sessionIdentity = session ? `${session.tenantId}\u0000${session.actorId}` : "cookie-session";
  const queryKey = `${path}\u0000${sessionIdentity}`;
  // Older test doubles predate the hydration flag. The production hook always
  // supplies it, while treating an omitted value as hydrated keeps those
  // structural mocks backwards compatible.
  const sessionHydrated = oidcSession.hydrated ?? true;
  const queryEnabled = enabled && sessionHydrated;

  useEffect(() => {
    if (!queryEnabled) {
      // Invalidating the loaded key prevents a disabled query from reusing
      // principal-scoped data when it is enabled again.
      lastLoadedKeyRef.current = null;
      staleDataRef.current = null;
      return;
    }

    if (lastLoadedKeyRef.current !== queryKey) {
      lastLoadedKeyRef.current = queryKey;
      staleDataRef.current = null;
    }

    const isRefresh = staleDataRef.current !== null;
    const controller = new AbortController();

    async function load() {
      setStateKey(queryKey);
      if (isRefresh) {
        setIsRefreshing(true);
      } else {
        setData(null);
        setSource("loading");
        setError(null);
        setErrorStatus(null);
        setErrorDetails(EMPTY_FAILURE_DETAILS);
        setIsRefreshing(false);
      }

      try {
        const fetchOptions = { session, signal: controller.signal };
        // Validate tenant ownership inside the response decoder. If this guard
        // fails, axisFetchParsedJson wraps it in AxisApiDecodeError while it
        // still has access to the response correlation header.
        const payload = await axisFetchParsedJson(path, (value) => {
          const parsed = parse(value);
          if (
            expectedTenantId
            && (
              typeof parsed !== "object"
              || parsed === null
              || !("tenant_id" in parsed)
              || parsed.tenant_id !== expectedTenantId
            )
          ) {
            throw new TypeError("Axis API response belongs to a different tenant.");
          }
          return parsed;
        }, fetchOptions);

        if (!controller.signal.aborted) {
          staleDataRef.current = payload;
          setData(payload);
          setSource("api");
          setError(null);
          setErrorStatus(null);
          setErrorDetails(EMPTY_FAILURE_DETAILS);
          setIsRefreshing(false);
        }
      } catch (caught) {
        if (!controller.signal.aborted) {
          if (!isRefresh) {
            setData(null);
          }
          const tenantNotFound =
            caught instanceof AxisApiError
            && caught.status === 404
            && caught.code === "TENANT_NOT_FOUND";
          setSource(tenantNotFound ? "tenant_not_found" : "unavailable");
          setError(caught instanceof Error ? caught.message : "Axis API request failed.");
          setErrorStatus(caught instanceof AxisApiError ? caught.status : null);
          setErrorDetails({
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
          });
          setIsRefreshing(false);
        }
      }
    }

    void load();

    return () => controller.abort();
  }, [
    path,
    session,
    sessionIdentity,
    queryKey,
    refreshNonce,
    queryEnabled,
    parse,
    expectedTenantId,
  ]);

  // Effects run after React commits. Masking by the render-time query key is
  // therefore essential: without it, a tenant/path change can expose the
  // previous query's data for one committed frame.
  const isCurrentQuery = queryEnabled && stateKey === queryKey;

  return {
    data: isCurrentQuery ? data : null,
    source: isCurrentQuery ? source : "loading",
    error: isCurrentQuery ? error : null,
    errorStatus: isCurrentQuery ? errorStatus : null,
    errorCode: isCurrentQuery ? errorDetails.code : null,
    errorReason: isCurrentQuery ? errorDetails.reason : null,
    errorRequiredPermission: isCurrentQuery
      ? errorDetails.requiredPermission
      : null,
    errorRequestId: isCurrentQuery ? errorDetails.requestId : null,
    validationIssues: isCurrentQuery ? errorDetails.validationIssues : [],
    isRefreshing: isCurrentQuery ? isRefreshing : false,
    isLoading: !isCurrentQuery || source === "loading",
    isUnavailable: isCurrentQuery && source === "unavailable",
    isTenantNotFound: isCurrentQuery && source === "tenant_not_found",
  };
}
