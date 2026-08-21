import {
  AxisApiError,
  axisFetch,
  axisResponseRequestId,
  type AxisFetchOptions,
} from "./axis-api";

export const IDENTITY_SESSION_ADMIN_SCOPE = "identity:sessions:admin";

export type IdentityBrowserSessionRecord = {
  session_ref: string;
  actor_id: string;
  status: string;
  current: boolean;
  created_at: string;
  expires_at: string;
  absolute_expires_at: string | null;
  last_seen_at: string | null;
  refresh_count: number;
  revoked_at: string | null;
  revocation_reason: string | null;
};

export type IdentityBrowserSessionList = {
  tenant_id: string;
  actor_id: string;
  tenant_wide: boolean;
  sessions: IdentityBrowserSessionRecord[];
  notes: string[];
};

export function identitySessionsPath(tenantWide: boolean): string {
  return tenantWide ? "/identity/sessions?tenant_wide=true" : "/identity/sessions";
}

export function canListTenantSessions(scopes: string[]): boolean {
  return scopes.includes(IDENTITY_SESSION_ADMIN_SCOPE);
}

export async function revokeIdentitySession(
  sessionRef: string,
  options: AxisFetchOptions = {},
): Promise<void> {
  const path = `/identity/sessions/${encodeURIComponent(sessionRef)}/revoke`;
  // method is set after the spread so a caller-supplied method can never
  // override the required POST for revocation.
  const response = await axisFetch(path, { ...options, method: "POST" });

  if (!response.ok) {
    throw new AxisApiError(path, response.status, {
      requestId: axisResponseRequestId(response),
    });
  }
}

export function sessionStatusLabel(status: string): string {
  if (!status) {
    return "Unknown";
  }
  const compact = status.replaceAll("_", " ");
  return compact.charAt(0).toUpperCase() + compact.slice(1);
}

export function sessionStatusClass(status: string): string {
  if (status === "active") {
    return "signal-ready";
  }
  if (status === "refreshing" || status === "rotated") {
    return "signal-watch";
  }
  return "signal-action-required";
}

export function isRevocableSessionStatus(status: string): boolean {
  return status === "active" || status === "refreshing";
}

export function formatSessionInstant(value: string | null | undefined): string {
  if (!value) {
    return "Not recorded";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Not recorded";
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}
