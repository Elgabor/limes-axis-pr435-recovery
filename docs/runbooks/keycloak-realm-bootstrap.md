# Runbook: Keycloak Realm Bootstrap

Playbook for declaring or verifying an Axis-ready Keycloak realm using
`services/api/scripts/bootstrap_keycloak_realm.py`, the typed boundary in
`services/api/src/axis_api/idp_bootstrap.py` and its contract tests in
`services/api/tests/test_idp_bootstrap.py`. See also the OIDC session section
of [`docs/deployment.md`](../deployment.md).

This runbook covers enterprise/self-managed realms. The Docker Compose demo
realm (`infra/docker/keycloak/axis-realm.json`) is a clearly labeled local
artifact: it is imported automatically for the guided local demo and is **not**
an input to production logic. A contract test keeps it a superset of the
canonical role set declared by the bootstrap module.

## What The Tool Declares

One source of truth — `idp_bootstrap.py` — declares:

- the `axis_tenant` declarative user-profile attribute (the tenant claim the
  Axis API verifier reads; Keycloak 26+ drops undeclared attributes from
  admin-created users without it);
- the canonical Axis realm roles: `audit:read`, `workflows:read`,
  `notifications:acknowledge`, `connectors:manifest:lifecycle`,
  `connectors:manifest:enable_live`, `platform:policy:{author,revise,read,evaluate}`,
  `platform:tenant:{operator,read}`;
- the web console client: confidential client, authorization-code flow with
  PKCE (S256), no implicit flow, no direct access grants, front-channel
  logout, your redirect/web-origin/post-logout URIs, and two protocol mappers
  (`axis_tenant` user-attribute mapper plus the API audience mapper).

The tool never creates, reads, prints, or rotates client secrets: on create,
Keycloak generates one server-side; retrieve it through your own secret
management path and configure `AXIS_OIDC_CLIENT_SECRET` on the API.

## Safety Properties

- **Check mode is read-only.** It computes the divergence plan and exits.
- **Apply mode is idempotent.** Re-runs converge; converged realms report
  every component as `already_correct`.
- **Conflicts fail closed before any write**: public clients, non-OIDC
  protocols, duplicate clients with the same id, redirect URIs / web origins /
  post-logout URIs outside the declared set, and unmanaged protocol mappers
  are reported as conflicts and nothing is modified.
- **No secrets in diagnostics.** Output is structured JSON describing
  components and actions only; admin credentials are accepted from the
  environment only, never from argv.

## Procedure

### 0. Prepare credentials

Use a dedicated admin account with realm-admin rights for the target realm
(least privilege: prefer a client/service account bound to one realm over the
master-realm superuser when your Keycloak configuration allows it).

```bash
export AXIS_IDP_ADMIN_USERNAME='axis-bootstrap'
export AXIS_IDP_ADMIN_PASSWORD='...'   # from your secret store; never argv
```

### 1. Dry-run against an existing realm

```bash
cd services/api
uv run python scripts/bootstrap_keycloak_realm.py \
  --base-url https://keycloak.internal.example \
  --realm axis \
  --client-id limes-axis-web \
  --redirect-uri https://axis.example.com/identity/oidc/callback \
  --web-origin https://axis.example.com \
  --post-logout-uri https://axis.example.com/ \
  --mode check
```

Read each step's `action`: `already_correct`, `create`, `update`, or
`conflict`. Exit codes: `0` converged/no-op, `1` IdP unreachable,
`2` conflicts present.

### 2. Apply

Re-run with `--mode apply`. Steps execute in order (realm → client → roles →
user profile). Conflicts abort the whole apply before the first write.

### 3. Fresh realm

The same command works against a nonexistent realm name: check reports
`realm: create`, and apply provisions the realm with hardened defaults
(self-registration off, no reset-by-password, no remember-me) plus everything
above.

### 4. Verify

```bash
# 1) The tool itself, re-run in check mode:
uv run python scripts/bootstrap_keycloak_realm.py ... --mode check
# expected: status "already_correct", exit 0

# 2) The deployment-level readiness check:
make demo-keycloak-check   # local values; see docs/demo-readiness.md
# or the equivalent OIDC discovery check against your issuer

# 3) Sign in through the console once and confirm
#    GET /identity/session reports authenticated=true, the expected tenant,
#    and the scopes granted to your operator persona.
```

### 5. Rollback / manual remediation boundary

The tool converges forward only; there is no automatic rollback of applied
changes. Realm deletion is never performed. To undo:

- disable the console client (or remove it if it was created by the tool);
- disable individual canonical roles that should not exist;
- re-enable any flag the tool hardened, deliberately, in the Keycloak admin
  console.

Conflict remediation (extra redirect URIs, unmanaged mappers, duplicate
client ids) is always manual by design: review the conflicting state in the
Keycloak admin console, align it with the declared spec (or extend the spec
explicitly), then re-run check → apply.

## Redirect / Post-Logout URIs

- Pass exactly the URIs the deployment serves. Every extra URI is treated as
  a conflict because redirect URIs are an OAuth attack surface.
- `--redirect-uri` must match the API callback route
  (`AXIS_OIDC_REDIRECT_URI`, default path `/identity/oidc/callback`).
- `--post-logout-uri` must match `AXIS_OIDC_POST_LOGOUT_REDIRECT_URI`; the
  console sends `id_token_hint` + `post_logout_redirect_uri` at sign-out.
- Web origins back the browser console origin (`NEXT_PUBLIC_AXIS_API_BASE_URL`
  host when the console calls the API cross-origin).

## HTTPS / Reverse-Proxy Caveats

- Behind TLS-terminating proxies, expose Keycloak with the proxy's external
  scheme/host so issuer URLs and redirects stay consistent (Keycloak 26:
  `KC_PROXY_HEADERS=xforwarded` plus correct frontend hostname settings).
- The issuer configured on the Axis API (`AXIS_OIDC_ISSUER`) must equal what
  Keycloak embeds in tokens; mismatched proxy schemes fail token validation
  closed.
- Do not serve admin endpoints publicly; run the bootstrap script from an
  operations host that can reach the admin API.

## Least-Privilege Role Assignment

Assign only the roles a persona needs; every grant becomes an effective API
scope. Reference personas:

- read-only auditor: `audit:read`;
- connector steward: `connectors:manifest:lifecycle` (+ `connectors:manifest:enable_live`
  only behind the governed live-enablement decision);
- policy author: `platform:policy:author`, `platform:policy:read`,
  `platform:policy:evaluate`.

Every user that signs into the console needs the `axis_tenant` attribute set
to their single tenant identifier.
