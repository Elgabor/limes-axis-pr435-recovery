import type { APIRequestContext } from "@playwright/test";

/*
 * Local Keycloak seams for the SSO denial lane.
 *
 * Everything here runs against the documented local-only demo IdP
 * (`infra/docker/docker-compose.yml`, realm `axis`). Admin credentials come
 * from env with the compose file's documented local defaults — they are the
 * same values already published in that file and are never valid beyond this
 * machine. The lane mints one throwaway persona per run through the Keycloak
 * Admin REST API (least-privilege realm role = exact Axis scope name), drives
 * the real authorization-code + PKCE browser login, and deletes the persona
 * afterwards. Residual Axis-side records (sessions, audit events) persist by
 * design under the persona's unique id.
 */

const KEYCLOAK_BASE_URL =
  process.env.AXIS_E2E_KEYCLOAK_BASE_URL ?? "http://127.0.0.1:8080";
const KEYCLOAK_ADMIN_USERNAME =
  process.env.AXIS_E2E_KEYCLOAK_ADMIN_USER ?? "axis";
const KEYCLOAK_ADMIN_PASSWORD =
  process.env.AXIS_E2E_KEYCLOAK_ADMIN_PASSWORD ?? "axis-axis";
const REALM = "axis";

export type SsoPersona = {
  userId: string;
  username: string;
  /** Only set for personas created in the same call; lookups omit it. */
  password?: string;
};

async function adminAccessToken(request: APIRequestContext): Promise<string> {
  const response = await request.post(
    `${KEYCLOAK_BASE_URL}/realms/master/protocol/openid-connect/token`,
    {
      form: {
        grant_type: "password",
        client_id: "admin-cli",
        username: KEYCLOAK_ADMIN_USERNAME,
        password: KEYCLOAK_ADMIN_PASSWORD,
      },
    },
  );
  if (!response.ok()) {
    throw new Error(
      `Keycloak admin login failed (${response.status()}). Is the local Keycloak stack running?`,
    );
  }
  const body = (await response.json()) as { access_token: string };
  return body.access_token;
}

/**
 * Declare `axis_tenant` in the realm's user profile. Keycloak 26's
 * declarative profile silently drops undeclared attributes from admin-created
 * users, so personas would lose their tenant claim without this. Idempotent.
 */
export async function ensureTenantAttributeInUserProfile(
  request: APIRequestContext,
): Promise<void> {
  const accessToken = await adminAccessToken(request);
  const authHeaders = { authorization: `Bearer ${accessToken}` };
  const response = await request.get(
    `${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/users/profile`,
    { headers: authHeaders },
  );
  if (!response.ok()) {
    throw new Error(`Keycloak user-profile read failed (${response.status()}).`);
  }
  const profile = (await response.json()) as {
    attributes: Array<{ name: string } & Record<string, unknown>>;
    groups?: Array<Record<string, unknown>>;
  };
  if (profile.attributes.some((attribute) => attribute.name === "axis_tenant")) {
    return;
  }
  profile.attributes.push({
    name: "axis_tenant",
    displayName: "Axis Tenant",
    multivalued: false,
    annotations: {},
    permissions: { view: ["admin"], edit: ["admin"] },
  });
  const updated = await request.put(
    `${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/users/profile`,
    {
      headers: authHeaders,
      data: {
        attributes: profile.attributes,
        ...(profile.groups ? { groups: profile.groups } : {}),
      },
    },
  );
  if (!updated.ok()) {
    throw new Error(`Keycloak user-profile update failed (${updated.status()}).`);
  }
}

/**
 * Mint a throwaway operator persona whose only Axis grant is the connector
 * lifecycle scope — deliberately without `connectors:manifest:enable_live`.
 */
export async function createLifecycleOnlyPersona(
  request: APIRequestContext,
  runToken: string,
): Promise<SsoPersona> {
  const accessToken = await adminAccessToken(request);
  const authHeaders = { authorization: `Bearer ${accessToken}` };

  // Idempotent: 201 on first run, 409 once the role exists.
  await request.post(`${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/roles`, {
    headers: authHeaders,
    data: {
      name: "connectors:manifest:lifecycle",
      description: "Axis scope role exercised by the local SSO denial lane.",
    },
  });

  const username = `axis-e2e-lifecycle-${runToken}`;
  const password = `e2e-persona-${runToken}-${Math.random().toString(36).slice(2, 10)}`;
  const created = await request.post(`${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/users`, {
    headers: authHeaders,
    data: {
      username,
      // Email must be present: Keycloak's default user profile forces the
      // Verify-Profile required action on login otherwise.
      email: `${username}@example.invalid`,
      enabled: true,
      emailVerified: true,
      firstName: "E2E",
      lastName: "Connector Operator",
      attributes: { axis_tenant: ["tenant_demo_manufacturing"] },
      credentials: [{ type: "password", value: password, temporary: false }],
    },
  });
  if (!created.ok()) {
    throw new Error(`Keycloak persona creation failed (${created.status()}).`);
  }
  // Role assignment must go through the role-mappings endpoint: Keycloak
  // silently ignores a `realmRoles` array on the user-creation payload, and
  // its mapping endpoint resolves roles by id, not by name-only entries.
  const persona = await lookupPersona(request, username);
  const realmRoles = await (
    await request.get(`${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/roles`, {
      headers: authHeaders,
    })
  ).json() as Array<{ id: string; name: string }>;
  const lifecycleRole = realmRoles.find(
    (role) => role.name === "connectors:manifest:lifecycle",
  );
  if (!lifecycleRole) {
    throw new Error("Realm role connectors:manifest:lifecycle missing after creation.");
  }
  const mapped = await request.post(
    `${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/users/${persona.userId}/role-mappings/realm`,
    {
      headers: authHeaders,
      data: [{ id: lifecycleRole.id, name: lifecycleRole.name }],
    },
  );
  if (!mapped.ok()) {
    throw new Error(`Keycloak role mapping failed (${mapped.status()}).`);
  }
  return { ...persona, password };
}

/**
 * Mint a persona bound to a different Axis tenant, with no connector grants at
 * all — used to prove cross-tenant isolation under a verified session.
 */
export async function createForeignTenantPersona(
  request: APIRequestContext,
  runToken: string,
): Promise<SsoPersona> {
  const accessToken = await adminAccessToken(request);
  const username = `axis-e2e-foreign-${runToken}`;
  const password = `e2e-persona-${runToken}-${Math.random().toString(36).slice(2, 10)}`;
  const created = await request.post(`${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/users`, {
    headers: { authorization: `Bearer ${accessToken}` },
    data: {
      username,
      email: `${username}@example.invalid`,
      enabled: true,
      emailVerified: true,
      firstName: "E2E",
      lastName: "Foreign Tenant",
      attributes: { axis_tenant: [`tenant_e2e_sso_other_${runToken}`] },
      credentials: [{ type: "password", value: password, temporary: false }],
    },
  });
  if (!created.ok()) {
    throw new Error(`Foreign-tenant persona creation failed (${created.status()}).`);
  }
  const persona = await lookupPersona(request, username);
  return { ...persona, password };
}

async function lookupPersona(
  request: APIRequestContext,
  username: string,
): Promise<SsoPersona> {
  const accessToken = await adminAccessToken(request);
  const users = await (
    await request.get(`${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/users`, {
      headers: { authorization: `Bearer ${accessToken}` },
      params: { username, exact: "true" },
    })
  ).json();
  const matches = users as Array<{ id: string }>;
  if (matches.length !== 1) {
    throw new Error(`Keycloak persona lookup for ${username} was ambiguous.`);
  }
  return { userId: matches[0].id, username };
}

/** Delete the throwaway persona; the realm role stays (it is definitionally local). */
export async function deletePersona(
  request: APIRequestContext,
  persona: SsoPersona,
): Promise<void> {
  const accessToken = await adminAccessToken(request);
  await request.delete(
    `${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/users/${persona.userId}`,
    { headers: { authorization: `Bearer ${accessToken}` } },
  );
}

/**
 * Mint a throwaway console-operator persona with explicit realm roles.
 *
 * Realm roles become the verified principal's Axis scopes (the API reads them
 * from `realm_access.roles`), so the caller names exactly the scopes the lane
 * needs — least privilege by construction.
 */
export async function createPersonaWithRealmRoles(
  request: APIRequestContext,
  input: {
    runToken: string;
    usernamePrefix: string;
    roles: string[];
    lastName: string;
    tenantId?: string;
  },
): Promise<SsoPersona> {
  await ensureTenantAttributeInUserProfile(request);
  const accessToken = await adminAccessToken(request);
  const authHeaders = { authorization: `Bearer ${accessToken}` };
  const username = `axis-e2e-${input.usernamePrefix}-${input.runToken}`;
  const password = `e2e-persona-${input.runToken}-${Math.random().toString(36).slice(2, 10)}`;

  for (const role of input.roles) {
    // Idempotent: 201 on first run, 409 once the role exists.
    await request.post(`${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/roles`, {
      headers: authHeaders,
      data: { name: role, description: "Axis scope role exercised by a local e2e lane." },
    });
  }

  const created = await request.post(`${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/users`, {
    headers: authHeaders,
    data: {
      username,
      email: `${username}@example.invalid`,
      enabled: true,
      emailVerified: true,
      firstName: "E2E",
      lastName: input.lastName,
      attributes: { axis_tenant: [input.tenantId ?? "tenant_demo_manufacturing"] },
      credentials: [{ type: "password", value: password, temporary: false }],
    },
  });
  if (!created.ok()) {
    throw new Error(`Keycloak persona creation failed (${created.status()}).`);
  }

  const persona = await lookupPersona(request, username);
  const realmRoles = (await (
    await request.get(`${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/roles`, { headers: authHeaders })
  ).json()) as Array<{ id: string; name: string }>;
  const mappings = input.roles
    .map((role) => {
      const match = realmRoles.find((candidate) => candidate.name === role);
      if (!match) {
        throw new Error(`Realm role ${role} missing after creation.`);
      }
      return { id: match.id, name: match.name };
    });
  const mapped = await request.post(
    `${KEYCLOAK_BASE_URL}/admin/realms/${REALM}/users/${persona.userId}/role-mappings/realm`,
    { headers: authHeaders, data: mappings },
  );
  if (!mapped.ok()) {
    throw new Error(`Keycloak role mapping failed (${mapped.status()}).`);
  }
  return { ...persona, password };
}
