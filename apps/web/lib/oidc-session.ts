export const AXIS_OIDC_SESSION_STORAGE_KEY = "limes-axis.oidc-session.v1";

export type OidcConsoleSession = {
  accessToken: string;
  actorId: string;
  tenantId: string;
  scopes: string[];
  expiresAt?: number;
};

type JwtClaims = {
  sub?: unknown;
  axis_tenant?: unknown;
  scope?: unknown;
  scp?: unknown;
  realm_access?: unknown;
  resource_access?: unknown;
  exp?: unknown;
};

export function normalizeOidcReturnTo(value: string | null | undefined): string {
  const candidate = value?.trim();
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) {
    return "/";
  }
  return candidate;
}

/** The browser path to return to after an SSO round-trip. */
export function currentReturnPath(): string {
  if (typeof window === "undefined") {
    return "/";
  }

  return `${window.location.pathname}${window.location.search}`;
}

export function buildOidcAuthorizeUrl(apiBaseUrl: string, returnTo: string | null | undefined): string {
  const authorizeUrl = new URL("/identity/oidc/authorize", apiBaseUrl.endsWith("/") ? apiBaseUrl : `${apiBaseUrl}/`);
  authorizeUrl.searchParams.set("return_to", normalizeOidcReturnTo(returnTo));
  return authorizeUrl.toString();
}

export function buildOidcLogoutUrl(apiBaseUrl: string, returnTo: string | null | undefined): string {
  const logoutUrl = new URL("/identity/oidc/logout", apiBaseUrl.endsWith("/") ? apiBaseUrl : `${apiBaseUrl}/`);
  logoutUrl.searchParams.set("return_to", normalizeOidcReturnTo(returnTo));
  return logoutUrl.toString();
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");

  if (typeof atob === "function") {
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }

  return Buffer.from(padded, "base64").toString("utf8");
}

function decodeJwtClaims(accessToken: string): JwtClaims {
  const [, payload] = accessToken.split(".");
  if (!payload) {
    throw new Error("OIDC access token is not a JWT.");
  }

  return JSON.parse(decodeBase64Url(payload)) as JwtClaims;
}

function collectScopes(claims: JwtClaims, audience: string): string[] {
  const scopes = new Set<string>();
  if (typeof claims.scope === "string") {
    claims.scope.split(/\s+/).forEach((scope) => {
      if (scope) {
        scopes.add(scope);
      }
    });
  }

  if (typeof claims.scp === "string") {
    claims.scp.split(/\s+/).forEach((scope) => {
      if (scope) {
        scopes.add(scope);
      }
    });
  } else if (Array.isArray(claims.scp)) {
    claims.scp.forEach((scope) => {
      if (typeof scope === "string" && scope) {
        scopes.add(scope);
      }
    });
  }

  if (isRecord(claims.realm_access) && Array.isArray(claims.realm_access.roles)) {
    claims.realm_access.roles.forEach((role) => {
      if (typeof role === "string" && role) {
        scopes.add(role);
      }
    });
  }

  if (isRecord(claims.resource_access)) {
    const clientAccess = claims.resource_access[audience];
    if (isRecord(clientAccess) && Array.isArray(clientAccess.roles)) {
      clientAccess.roles.forEach((role) => {
        if (typeof role === "string" && role) {
          scopes.add(role);
        }
      });
    }
  }

  return Array.from(scopes).sort();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function createOidcSessionFromAccessToken(
  accessToken: string,
  audience = "limes-axis-api",
): OidcConsoleSession {
  const claims = decodeJwtClaims(accessToken);
  if (typeof claims.sub !== "string" || claims.sub.length === 0) {
    throw new Error("OIDC access token is missing sub.");
  }
  if (typeof claims.axis_tenant !== "string" || claims.axis_tenant.length === 0) {
    throw new Error("OIDC access token is missing axis_tenant.");
  }

  return {
    accessToken,
    actorId: claims.sub,
    tenantId: claims.axis_tenant,
    scopes: collectScopes(claims, audience),
    expiresAt: typeof claims.exp === "number" ? claims.exp : undefined,
  };
}

export function readStoredOidcSession(storage: Storage): OidcConsoleSession | null {
  const rawSession = storage.getItem(AXIS_OIDC_SESSION_STORAGE_KEY);
  if (!rawSession) {
    return null;
  }

  try {
    const parsed = JSON.parse(rawSession) as OidcConsoleSession;
    if (!parsed.accessToken || !parsed.actorId || !parsed.tenantId) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function writeStoredOidcSession(storage: Storage, session: OidcConsoleSession): void {
  storage.setItem(AXIS_OIDC_SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredOidcSession(storage: Storage): void {
  storage.removeItem(AXIS_OIDC_SESSION_STORAGE_KEY);
}

export function buildAxisAuthInit(
  init: RequestInit = {},
  session: OidcConsoleSession | null = null,
): RequestInit {
  if (!session?.accessToken) {
    return init;
  }

  const headers = new Headers(init.headers);
  if (!headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${session.accessToken}`);
  }

  return {
    ...init,
    headers,
  };
}
