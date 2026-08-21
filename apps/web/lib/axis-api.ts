import { getApiBaseUrl } from "./api-status";
import { buildAxisAuthInit, type OidcConsoleSession } from "./oidc-session";
import {
  AXIS_CSRF_HEADER_NAME,
  readCsrfTokenFromCookieHeader,
  shouldAttachCsrfHeader,
} from "./session-csrf";

export class AxisApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly body: unknown;
  readonly detail: unknown;
  readonly code: string | null;
  readonly reason: string | null;
  readonly requiredPermission: string | null;
  readonly validationIssues: unknown[];
  readonly requestId: string | null;

  constructor(
    path: string,
    status: number,
    options: {
      body?: unknown;
      requestId?: string | null;
    } = {},
  ) {
    const detail = readErrorDetail(options.body);
    super(errorMessage(detail, status));
    this.name = "AxisApiError";
    this.status = status;
    this.path = path;
    this.body = options.body ?? null;
    this.detail = detail;
    this.code = readStringField(detail, "code");
    this.reason = readStringField(detail, "reason");
    this.requiredPermission = readStringField(detail, "required_permission");
    this.validationIssues = Array.isArray(detail) ? detail : [];
    this.requestId = options.requestId ?? null;
  }
}

export class AxisApiDecodeError extends Error {
  readonly path: string;
  readonly requestId: string | null;
  readonly validationIssues: ReadonlyArray<AxisDecodeIssue>;

  constructor(
    path: string,
    message: string,
    options: ErrorOptions & {
      requestId?: string | null;
      validationIssues?: ReadonlyArray<AxisDecodeIssue>;
    } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "AxisApiDecodeError";
    this.path = path;
    this.requestId = options.requestId ?? null;
    this.validationIssues = options.validationIssues ?? [];
  }
}

/** Safe, display-oriented failure metadata retained by mutation UIs. */
export type AxisOperatorError = {
  code: string | null;
  message: string;
  requestId: string | null;
  status: number | null;
};

/**
 * Reduce a caught value to operator-safe metadata. The raw response body,
 * decoder cause and arbitrary Error messages are deliberately not retained.
 */
export function toAxisOperatorError(
  caught: unknown,
  fallbackMessage: string,
): AxisOperatorError {
  if (caught instanceof AxisApiError) {
    return {
      code: caught.code,
      message: caught.message,
      requestId: caught.requestId,
      status: caught.status,
    };
  }
  if (caught instanceof AxisApiDecodeError) {
    return {
      code: null,
      message: caught.message,
      requestId: caught.requestId,
      status: null,
    };
  }
  return {
    code: null,
    message: fallbackMessage,
    requestId: null,
    status: null,
  };
}

export type AxisDecodeIssue = {
  code: string;
  path: string;
  message: string;
};

export type AxisJsonDecoder<T> = (value: unknown) => T;

export type AxisFetchOptions = {
  session?: OidcConsoleSession | null;
  signal?: AbortSignal;
  method?: string;
  body?: unknown;
  headers?: HeadersInit;
};

export const AXIS_BROWSER_SESSION_SIGNED_OUT_EVENT = "limes-axis:browser-session-signed-out";

const SESSION_REFRESH_PATH = "/identity/session/refresh";

function browserCookieHeader(): string {
  if (typeof document === "undefined") {
    return "";
  }
  return document.cookie ?? "";
}

function buildRequestInit(
  { session, signal, method = "GET", body, headers }: AxisFetchOptions,
): RequestInit {
  const init = buildAxisAuthInit(
    {
      method,
      signal,
      cache: "no-store",
      credentials: "include",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    session ?? null,
  );

  const requestHeaders = new Headers(init.headers);
  if (body !== undefined && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }
  if (
    !requestHeaders.has(AXIS_CSRF_HEADER_NAME)
    && shouldAttachCsrfHeader({
      method,
      hasAuthorizationHeader: requestHeaders.has("Authorization"),
    })
  ) {
    const csrfToken = readCsrfTokenFromCookieHeader(browserCookieHeader());
    if (csrfToken) {
      requestHeaders.set(AXIS_CSRF_HEADER_NAME, csrfToken);
    }
  }
  init.headers = requestHeaders;

  return init;
}

function announceBrowserSessionSignedOut(): void {
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new Event(AXIS_BROWSER_SESSION_SIGNED_OUT_EVENT));
  }
}

/**
 * Latches once a browser-session refresh has definitively failed.
 *
 * Without it an expired session loops forever: the 401 arms a refresh, the
 * refresh fails, the signed-out event makes the console re-run every live
 * query, and each of those 401s again — the API rejects without clearing the
 * `axis_csrf` cookie, so nothing ever disarms the refresh. A tab left open
 * overnight would wake up hammering the API and never finish loading.
 *
 * The latch is cleared only when the readable CSRF cookie changes. A public
 * endpoint can answer 200 while the browser session is still dead, so response
 * status alone is not proof that a new cookie session exists. Signing in again
 * (in this tab or another) rotates the CSRF cookie and re-arms refresh without
 * a reload.
 */
let browserSessionSignedOut = false;
let signedOutCsrfToken: string | null = null;

/** Test-only: module state outlives individual cases. */
export function resetBrowserSessionState(): void {
  browserSessionSignedOut = false;
  signedOutCsrfToken = null;
  inflightBrowserSessionRefresh = null;
}

let inflightBrowserSessionRefresh: Promise<boolean> | null = null;

function markBrowserSessionSignedOut(): void {
  browserSessionSignedOut = true;
  signedOutCsrfToken = readCsrfTokenFromCookieHeader(browserCookieHeader());
  announceBrowserSessionSignedOut();
}

function clearSignedOutLatchAfterCookieRotation(): void {
  if (!browserSessionSignedOut) {
    return;
  }
  const currentCsrfToken = readCsrfTokenFromCookieHeader(browserCookieHeader());
  if (currentCsrfToken !== signedOutCsrfToken) {
    browserSessionSignedOut = false;
    signedOutCsrfToken = null;
  }
}

async function performBrowserSessionRefresh(): Promise<boolean> {
  const headers = new Headers();
  const csrfToken = readCsrfTokenFromCookieHeader(browserCookieHeader());
  if (csrfToken) {
    headers.set(AXIS_CSRF_HEADER_NAME, csrfToken);
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}${SESSION_REFRESH_PATH}`, {
      cache: "no-store",
      credentials: "include",
      headers,
      method: "POST",
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Rotate the API-owned browser session once, deduplicating concurrent callers.
 *
 * Multiple 401s from parallel requests share one in-flight POST
 * /identity/session/refresh instead of storming the atomic rotation claim.
 */
export function refreshBrowserSession(): Promise<boolean> {
  if (!inflightBrowserSessionRefresh) {
    inflightBrowserSessionRefresh = performBrowserSessionRefresh().finally(() => {
      inflightBrowserSessionRefresh = null;
    });
  }
  return inflightBrowserSessionRefresh;
}

function shouldAttemptSessionRefresh(
  response: Response,
  init: RequestInit,
  path: string,
): boolean {
  if (response.status !== 401 || path === SESSION_REFRESH_PATH) {
    return false;
  }
  // A session already known to be dead must not re-arm the refresh cycle.
  if (browserSessionSignedOut) {
    return false;
  }
  // Bearer-mode requests own their token lifecycle; the cookie refresh
  // endpoint cannot mint bearer credentials for them.
  if (new Headers(init.headers).has("Authorization")) {
    return false;
  }
  // Without the readable CSRF cookie there is no browser session to refresh,
  // so anonymous 401s never trigger refresh attempts.
  return readCsrfTokenFromCookieHeader(browserCookieHeader()) !== null;
}

export async function axisFetch(
  path: string,
  options: AxisFetchOptions = {},
): Promise<Response> {
  const init = buildRequestInit(options);
  const response = await fetch(`${getApiBaseUrl()}${path}`, init);

  // A public or bearer-mode 200 does not prove that a failed browser session is
  // alive. The API rotates the readable CSRF token with the cookie session, so
  // that boundary safely detects a fresh sign-in without re-arming on unrelated
  // responses.
  clearSignedOutLatchAfterCookieRotation();

  if (!shouldAttemptSessionRefresh(response, init, path)) {
    return response;
  }

  const refreshed = await refreshBrowserSession();
  if (!refreshed) {
    markBrowserSessionSignedOut();
    return response;
  }

  // Retry exactly once. The init is rebuilt so the retried request picks up
  // the rotated CSRF cookie issued by the refresh response.
  const retryInit = buildRequestInit(options);
  const retryResponse = await fetch(`${getApiBaseUrl()}${path}`, retryInit);

  // If the retry is still a cookie-mode 401 (session died between refresh and
  // retry, or the resource still rejects the actor) do not refresh again;
  // converge to the signed-out state so the console re-runs its live queries
  // against /identity/session, matching the refresh-failure path above.
  if (shouldAttemptSessionRefresh(retryResponse, retryInit, path)) {
    markBrowserSessionSignedOut();
  }
  return retryResponse;
}

export async function axisFetchParsedJson<T>(
  path: string,
  decoder: AxisJsonDecoder<T>,
  options: AxisFetchOptions = {},
): Promise<T> {
  const response = await axisFetch(path, options);
  const body = await readResponseBody(response);
  const requestId = axisResponseRequestId(response);

  if (!response.ok) {
    throw new AxisApiError(path, response.status, { body, requestId });
  }

  return decodeAxisJson(path, body, decoder, requestId);
}

/**
 * Read the operator-facing correlation reference from an Axis response.
 *
 * `x-request-id` is the API contract; `x-correlation-id` remains a compatibility
 * fallback for older deployments and upstream gateways. Keeping this in the
 * fetch layer prevents one-off response handlers from silently dropping the
 * reference or changing the precedence.
 */
export function axisResponseRequestId(response: Response): string | null {
  return response.headers.get("x-request-id") ?? response.headers.get("x-correlation-id");
}

/** Validate a JSON body already read from an Axis response. */
export function decodeAxisJson<T>(
  path: string,
  body: unknown,
  decoder: AxisJsonDecoder<T>,
  requestId: string | null = null,
): T {
  if (body === null || typeof body === "string") {
    throw new AxisApiDecodeError(path, "Axis API returned an invalid JSON response.", {
      requestId,
    });
  }
  try {
    return decoder(body);
  } catch (error) {
    throw new AxisApiDecodeError(
      path,
      "Axis API response did not match the expected contract.",
      { cause: error, requestId, validationIssues: readDecodeIssues(error) },
    );
  }
}

function readDecodeIssues(error: unknown): AxisDecodeIssue[] {
  if (!error || typeof error !== "object" || !("issues" in error)) {
    return [];
  }
  const issues = (error as { issues?: unknown }).issues;
  if (!Array.isArray(issues)) {
    return [];
  }
  return issues.slice(0, 20).flatMap((issue): AxisDecodeIssue[] => {
    if (!issue || typeof issue !== "object") {
      return [];
    }
    const record = issue as Record<string, unknown>;
    const pathParts = Array.isArray(record.path) ? record.path : [];
    return [{
      code: typeof record.code === "string" ? record.code : "invalid_value",
      path: pathParts.map(String).join("."),
      message: typeof record.message === "string" ? record.message : "Invalid value",
    }];
  });
}

async function readResponseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text.trim()) {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function readErrorDetail(body: unknown): unknown {
  return isRecord(body) && "detail" in body ? body.detail : body;
}

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  const message = readStringField(detail, "message");
  return message ?? `Axis API request failed with ${status}`;
}

function readStringField(value: unknown, key: string): string | null {
  if (!isRecord(value)) {
    return null;
  }
  const field = value[key];
  return typeof field === "string" && field.trim() ? field : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
