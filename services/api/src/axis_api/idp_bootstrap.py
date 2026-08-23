"""Enterprise Keycloak realm bootstrap boundary.

One typed source of truth for what an Axis-ready Keycloak realm must declare:

- the ``axis_tenant`` user-profile attribute the OIDC verifier requires;
- the canonical Axis realm-role (scope) set used by governed API surfaces;
- the web console client shape: authorization-code flow with PKCE, no implicit
  or password grants, front-channel logout, explicit redirect/post-logout URIs,
  the tenant and audience protocol mappers.

The boundary is operator-facing and idempotent. ``check`` mode only computes
the divergence between the desired state and the live realm; ``apply`` mode
converges it. Every step is classified as ``create``, ``update``,
``already_correct`` or ``conflict``, and diagnostics never contain admin
tokens, client secrets, passwords, cookies, or raw IdP response bodies.

The local Docker Compose demo realm import file is deliberately not part of
this module: production logic declares the canonical platform set, while the
demo realm stays a clearly labeled local artifact (a contract test asserts the
demo realm remains a superset of the canonical roles).
"""

from __future__ import annotations

import contextlib
import json
import time
import typing
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

AXIS_TENANT_ATTRIBUTE = "axis_tenant"

#: The claim name the Axis OIDC verifier reads the tenant binding from
#: (``StaticJwksOidcVerifier.tenant_claim`` default).
AXIS_TENANT_CLAIM = "axis_tenant"

REALM_ROLE_CREATE_PATH = "/admin/realms/{realm}/roles"
REALM_ROLES_LIST_PATH = "/admin/realms/{realm}/roles?max=500"
REALM_GET_PATH = "/admin/realms/{realm}"
CLIENTS_QUERY_PATH = "/admin/realms/{realm}/clients?clientId={client_id}"
USER_PROFILE_PATH = "/admin/realms/{realm}/users/profile"


class RealmRoleSpec(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class AxisIdpClientSpec(BaseModel):
    """Operator-owned console client configuration for one deployment."""

    client_id: str = Field(min_length=1)
    redirect_uris: list[str] = Field(min_length=1)
    web_origins: list[str] = Field(min_length=1)
    post_logout_redirect_uris: list[str] = Field(min_length=1)
    audience: str = Field(min_length=1)


class AxisRealmSpec(BaseModel):
    realm: str = Field(min_length=1)
    client: AxisIdpClientSpec


def canonical_axis_realm_roles() -> tuple[RealmRoleSpec, ...]:
    """The canonical Axis scope-shaped realm roles, from one declaration.

    These are the grants the governed API surfaces actually require. Domain
    demo roles (for example ``briefs:generate``) are intentionally absent:
    they belong to the labeled local demo realm, not to enterprise baselines.
    """
    return (
        RealmRoleSpec(name="audit:read", description="Read Axis audit evidence."),
        RealmRoleSpec(
            name="workflows:read",
            description="Read workflow evidence.",
        ),
        RealmRoleSpec(
            name="notifications:acknowledge",
            description="Acknowledge platform notifications.",
        ),
        RealmRoleSpec(
            name="connectors:manifest:lifecycle",
            description=(
                "Activate and deprecate connector manifests within governed preview boundaries."
            ),
        ),
        RealmRoleSpec(
            name="connectors:manifest:enable_live",
            description=(
                "Enable live connector operation behind the governed live-enablement gate."
            ),
        ),
        RealmRoleSpec(
            name="connectors:source:discover",
            description=(
                "Verify external source connectivity and run bounded schema "
                "discovery for connectors."
            ),
        ),
        RealmRoleSpec(
            name="platform:policy:author",
            description="Author new Axis governance policies.",
        ),
        RealmRoleSpec(
            name="platform:policy:revise",
            description="Revise existing Axis governance policies.",
        ),
        RealmRoleSpec(
            name="platform:policy:read",
            description="Read Axis governance policies.",
        ),
        RealmRoleSpec(
            name="platform:policy:evaluate",
            description="Evaluate requests against Axis governance policies.",
        ),
        RealmRoleSpec(
            name="platform:tenant:operator",
            description="Operate tenants on this Axis deployment.",
        ),
        RealmRoleSpec(
            name="platform:tenant:read",
            description="Read tenant registry records on this Axis deployment.",
        ),
    )


CANONICAL_CLIENT_PROTOCOL = "openid-connect"
CANONICAL_PKCE_METHOD = "S256"

AXIS_TENANT_MAPPER_NAME = "axis_tenant"
AUDIENCE_MAPPER_NAME_TEMPLATE = "{audience}-audience"


def axis_tenant_protocol_mapper() -> dict[str, object]:
    return {
        "name": AXIS_TENANT_MAPPER_NAME,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "consentRequired": False,
        "config": {
            "access.token.claim": "true",
            "claim.name": AXIS_TENANT_CLAIM,
            "id.token.claim": "true",
            "jsonType.label": "String",
            "userinfo.token.claim": "true",
            "user.attribute": AXIS_TENANT_ATTRIBUTE,
        },
    }


def audience_protocol_mapper(audience: str) -> dict[str, object]:
    return {
        "name": AUDIENCE_MAPPER_NAME_TEMPLATE.format(audience=audience),
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "access.token.claim": "true",
            "included.custom.audience": audience,
            "id.token.claim": "false",
        },
    }


def axis_tenant_user_profile_attribute() -> dict[str, object]:
    """The declarative user-profile entry Keycloak 26+ requires so the
    attribute survives on admin-created users instead of being dropped."""
    return {
        "name": AXIS_TENANT_ATTRIBUTE,
        "displayName": "Axis Tenant",
        "multivalued": False,
        "annotations": {},
        "permissions": {"view": ["admin"], "edit": ["admin"]},
    }


# ---------------------------------------------------------------------------
# Structured, secret-safe reporting


class BootstrapStep(BaseModel):
    component: str = Field(min_length=1)
    action: typing.Literal["create", "update", "already_correct", "conflict"]
    detail: str = Field(min_length=1)


class RealmBootstrapReport(BaseModel):
    mode: typing.Literal["check", "apply"]
    realm: str
    status: RealmBootstrapReportStatus
    steps: list[BootstrapStep] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in {"already_correct", "updated", "created"}


RealmBootstrapReportStatus = typing.Literal[
    "already_correct",
    "updated",
    "created",
    "conflict",
    "unreachable",
]


class KeycloakBootstrapUnavailable(RuntimeError):
    """The IdP admin API could not be reached; no configuration conclusion."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class KeycloakBootstrapConflict(RuntimeError):
    """The live realm state cannot be reconciled automatically."""


# ---------------------------------------------------------------------------
# Admin HTTP adapter seam


class KeycloakHttpResponse(BaseModel):
    status: int
    body: object = None


class KeycloakAdminHttp(typing.Protocol):
    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
    ) -> KeycloakHttpResponse:
        """Issue one authenticated admin-API request against the IdP."""
        ...  # pragma: no cover


_TOKEN_REFRESH_SKEW_SECONDS = 30.0


class UrllibKeycloakAdminHttp:
    """Password-grant admin client over urllib with token caching.

    Admin credentials are supplied out of band (environment or secret store),
    cached tokens stay in memory only, and failures are reduced to a reason
    class: response bodies, URLs with query strings, and Authorization
    material never reach exception text or diagnostics.
    """

    def __init__(
        self,
        *,
        base_url: str,
        admin_username: str,
        admin_password: str,
        admin_realm: str = "master",
        admin_client_id: str = "admin-cli",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_username = admin_username
        self.admin_password = admin_password
        self.admin_realm = admin_realm
        self.admin_client_id = admin_client_id
        self.timeout_seconds = timeout_seconds
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
    ) -> KeycloakHttpResponse:
        token = self._valid_token_or_fetch()
        response = self._raw_request(method, path, payload, token)
        if response.status == 401:
            # The cached token expired server-side or was rotated; re-auth once.
            self._access_token = None
            token = self._fetch_access_token()
            response = self._raw_request(method, path, payload, token)
        return response

    def _valid_token_or_fetch(self) -> str:
        if self._access_token is not None and time.time() < self._token_expires_at:
            return self._access_token
        return self._fetch_access_token()

    def _fetch_access_token(self) -> str:
        form = urlencode(
            {
                "grant_type": "password",
                "client_id": self.admin_client_id,
                "username": self.admin_username,
                "password": self.admin_password,
            }
        ).encode("utf-8")
        token_request = Request(
            f"{self.base_url}/realms/{self.admin_realm}/protocol/openid-connect/token",
            data=form,
            method="POST",
        )
        try:
            with urlopen(token_request, timeout=self.timeout_seconds) as raw:
                body = json.loads(raw.read())
        except (OSError, URLError, ValueError) as exc:
            raise KeycloakBootstrapUnavailable("idp_admin_authentication_failed") from exc
        token = body.get("access_token") if isinstance(body, dict) else None
        expires_in = body.get("expires_in") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise KeycloakBootstrapUnavailable("idp_admin_token_missing")
        self._access_token = token
        lifetime = expires_in if isinstance(expires_in, (int, float)) else 60.0
        self._token_expires_at = time.time() + max(
            1.0, float(lifetime) - _TOKEN_REFRESH_SKEW_SECONDS
        )
        return token

    def _raw_request(
        self,
        method: str,
        path: str,
        payload: object | None,
        access_token: str,
    ) -> KeycloakHttpResponse:
        data = None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as raw:
                raw_body = raw.read()
                status = raw.status
        except URLError as exc:
            # HTTPError is a URLError subclass carrying the status code.
            status_code = getattr(exc, "code", None)
            if status_code is None:
                raise KeycloakBootstrapUnavailable("idp_unreachable") from exc
            # Consume the error body but never surface it; it may embed realm
            # details or tokens. Only the stable status class is reported.
            with contextlib.suppress(OSError):
                exc.read()
            return KeycloakHttpResponse(status=status_code, body=None)
        except OSError as exc:
            raise KeycloakBootstrapUnavailable("idp_unreachable") from exc
        parsed: object = None
        if raw_body:
            try:
                parsed = json.loads(raw_body)
            except ValueError:
                parsed = None
        return KeycloakHttpResponse(status=status, body=parsed)


# ---------------------------------------------------------------------------
# Desired-state planning and convergence


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _split_post_logout_attribute(value: object) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    return [part for part in value.split("##") if part]


def _managed_client_updates(
    existing: dict,
    spec: AxisIdpClientSpec,
) -> tuple[list[str], dict[str, object]]:
    """Classify one existing client against the managed field set.

    Returns (conflicts, update_payload). Hard-incompatible shapes (wrong
    protocol, public client, unmanaged redirect targets) fail closed instead
    of being silently flipped.
    """
    conflicts: list[str] = []
    updates: dict[str, object] = {}

    if existing.get("protocol") != CANONICAL_CLIENT_PROTOCOL:
        conflicts.append(
            f"client protocol is {existing.get('protocol')!r}, expected openid-connect"
        )
    if existing.get("publicClient") is True:
        conflicts.append(
            "client is public; Axis requires a confidential client with PKCE, "
            "and flipping this in place would change its authentication semantics"
        )

    current_redirects = set(_string_list(existing.get("redirectUris")))
    spec_redirects = set(spec.redirect_uris)
    extra_redirects = sorted(current_redirects - spec_redirects)
    if extra_redirects:
        conflicts.append(
            "client has redirect URIs outside the declared set: " + ", ".join(extra_redirects)
        )
    elif current_redirects != spec_redirects:
        updates["redirectUris"] = spec.redirect_uris

    current_origins = set(_string_list(existing.get("webOrigins")))
    spec_origins = set(spec.web_origins)
    extra_origins = sorted(current_origins - spec_origins)
    if extra_origins:
        conflicts.append(
            "client has web origins outside the declared set: " + ", ".join(extra_origins)
        )
    elif current_origins != spec_origins:
        updates["webOrigins"] = spec.web_origins

    attributes = existing.get("attributes")
    current_attributes = attributes if isinstance(attributes, dict) else {}
    current_post_logout = set(
        _split_post_logout_attribute(current_attributes.get("post.logout.redirect.uris"))
    )
    spec_post_logout = set(spec.post_logout_redirect_uris)
    extra_post_logout = sorted(current_post_logout - spec_post_logout)
    if extra_post_logout:
        conflicts.append(
            "client has post-logout redirect URIs outside the declared set: "
            + ", ".join(extra_post_logout)
        )

    flow_updates: dict[str, object] = {}
    if existing.get("standardFlowEnabled") is not True:
        flow_updates["standardFlowEnabled"] = True
    if existing.get("implicitFlowEnabled") is not False:
        flow_updates["implicitFlowEnabled"] = False
    if existing.get("directAccessGrantsEnabled") is not False:
        flow_updates["directAccessGrantsEnabled"] = False
    if existing.get("frontchannelLogout") is not True:
        flow_updates["frontchannelLogout"] = True
    if existing.get("enabled") is not True:
        flow_updates["enabled"] = True
    updates.update(flow_updates)

    next_attributes = dict(current_attributes)
    attribute_changed = False
    if extra_post_logout or current_post_logout != spec_post_logout:
        next_attributes["post.logout.redirect.uris"] = "##".join(spec.post_logout_redirect_uris)
        attribute_changed = True
    pkce_method = current_attributes.get("pkce.code.challenge.method")
    if pkce_method != CANONICAL_PKCE_METHOD:
        next_attributes["pkce.code.challenge.method"] = CANONICAL_PKCE_METHOD
        attribute_changed = True
    if attribute_changed:
        updates["attributes"] = next_attributes

    managed_mapper_names = {
        AXIS_TENANT_MAPPER_NAME,
        AUDIENCE_MAPPER_NAME_TEMPLATE.format(audience=spec.audience),
    }
    desired_mappers = [
        axis_tenant_protocol_mapper(),
        audience_protocol_mapper(spec.audience),
    ]
    existing_mappers = existing.get("protocolMappers")
    existing_mappers_by_name: dict[str, dict] = {}
    if isinstance(existing_mappers, list):
        existing_mappers_by_name = {
            mapper.get("name"): mapper
            for mapper in existing_mappers
            if isinstance(mapper, dict) and isinstance(mapper.get("name"), str)
        }

    next_mappers: list[dict[str, object]] = []
    mappers_changed = False
    for desired in desired_mappers:
        current_mapper = existing_mappers_by_name.get(str(desired["name"]))
        if current_mapper is None:
            next_mappers.append(desired)
            mappers_changed = True
            continue
        merged = dict(current_mapper)
        merged_config = dict(current_mapper.get("config") or {})
        desired_config = desired["config"]
        assert isinstance(desired_config, dict)
        config_diverged = any(
            merged_config.get(key) != value for key, value in desired_config.items()
        )
        if config_diverged:
            merged["config"] = {**merged_config, **desired_config}
            mappers_changed = True
        next_mappers.append(merged)

    unmanaged_mappers = sorted(set(existing_mappers_by_name) - managed_mapper_names)
    if unmanaged_mappers:
        conflicts.append(
            "client carries unmanaged protocol mappers requiring operator review: "
            + ", ".join(unmanaged_mappers)
        )

    if mappers_changed:
        preserved = [existing_mappers_by_name[name] for name in sorted(unmanaged_mappers)]
        updates["protocolMappers"] = [*next_mappers, *preserved]

    return conflicts, updates


def build_realm_bootstrap_plan(
    adapter: KeycloakAdminHttp,
    spec: AxisRealmSpec,
) -> list[BootstrapStep]:
    """Compute the divergence between desired and live realm state.

    Read-only against the IdP; every mutation is described, not performed.
    """
    steps: list[BootstrapStep] = []

    realm_response = adapter.request("GET", REALM_GET_PATH.format(realm=spec.realm))
    realm_representation = realm_response.body if isinstance(realm_response.body, dict) else None
    if realm_response.status == 404 or realm_representation is None:
        steps.append(
            BootstrapStep(
                component="realm",
                action="create",
                detail=(
                    f"realm {spec.realm!r} does not exist and will be created with "
                    "hardened defaults"
                ),
            )
        )
    elif realm_response.status != 200:
        raise KeycloakBootstrapUnavailable(f"idp_realm_read_failed_status_{realm_response.status}")
    elif realm_representation.get("enabled") is not True:
        steps.append(
            BootstrapStep(
                component="realm",
                action="update",
                detail="realm exists but is disabled; apply will enable it",
            )
        )
    else:
        steps.append(
            BootstrapStep(
                component="realm",
                action="already_correct",
                detail="realm exists and is enabled",
            )
        )

    clients_response = adapter.request(
        "GET",
        CLIENTS_QUERY_PATH.format(realm=spec.realm, client_id=spec.client.client_id),
    )
    clients = clients_response.body if isinstance(clients_response.body, list) else []
    if clients_response.status != 200:
        raise KeycloakBootstrapUnavailable(
            f"idp_clients_read_failed_status_{clients_response.status}"
        )

    if not clients:
        steps.append(
            BootstrapStep(
                component="client",
                action="create",
                detail=(
                    f"client {spec.client.client_id!r} will be created as a confidential "
                    "authorization-code + PKCE client with the tenant and audience mappers"
                ),
            )
        )
    elif len(clients) > 1:
        steps.append(
            BootstrapStep(
                component="client",
                action="conflict",
                detail=(
                    "multiple clients match the configured client id; resolve the "
                    "duplicate manually before applying"
                ),
            )
        )
    else:
        existing_client = clients[0]
        conflicts, updates = _managed_client_updates(existing_client, spec.client)
        if conflicts:
            for conflict in conflicts:
                steps.append(
                    BootstrapStep(
                        component="client",
                        action="conflict",
                        detail=conflict,
                    )
                )
        elif not updates:
            steps.append(
                BootstrapStep(
                    component="client",
                    action="already_correct",
                    detail="client matches the managed configuration",
                )
            )
        else:
            changed_fields = ", ".join(sorted(updates))
            steps.append(
                BootstrapStep(
                    component="client",
                    action="update",
                    detail=f"client will be converged: {changed_fields}",
                )
            )

    roles_response = adapter.request("GET", REALM_ROLES_LIST_PATH.format(realm=spec.realm))
    if roles_response.status != 200:
        raise KeycloakBootstrapUnavailable(f"idp_roles_read_failed_status_{roles_response.status}")
    role_descriptions: dict[str, str] = {}
    if isinstance(roles_response.body, list):
        for role in roles_response.body:
            if isinstance(role, dict) and isinstance(role.get("name"), str):
                role_descriptions[role["name"]] = str(role.get("description") or "")

    created_roles: list[str] = []
    updated_roles: list[str] = []
    correct_roles: list[str] = []
    for role_spec in canonical_axis_realm_roles():
        if role_spec.name not in role_descriptions:
            created_roles.append(role_spec.name)
        elif role_descriptions[role_spec.name] != role_spec.description:
            updated_roles.append(role_spec.name)
        else:
            correct_roles.append(role_spec.name)
    if created_roles:
        steps.append(
            BootstrapStep(
                component="roles",
                action="create",
                detail=f"canonical roles missing from the realm: {', '.join(created_roles)}",
            )
        )
    if updated_roles:
        steps.append(
            BootstrapStep(
                component="roles",
                action="update",
                detail=f"canonical roles with diverged descriptions: {', '.join(updated_roles)}",
            )
        )
    if correct_roles:
        steps.append(
            BootstrapStep(
                component="roles",
                action="already_correct",
                detail=f"canonical roles already declared: {len(correct_roles)}",
            )
        )

    profile_response = adapter.request("GET", USER_PROFILE_PATH.format(realm=spec.realm))
    if profile_response.status == 404:
        steps.append(
            BootstrapStep(
                component="user_profile",
                action="update",
                detail=(
                    "declarative user profile unavailable; apply will declare the "
                    f"{AXIS_TENANT_ATTRIBUTE!r} attribute"
                ),
            )
        )
    elif profile_response.status != 200:
        raise KeycloakBootstrapUnavailable(
            f"idp_user_profile_read_failed_status_{profile_response.status}"
        )
    else:
        profile = profile_response.body if isinstance(profile_response.body, dict) else {}
        attributes = profile.get("attributes")
        attribute_names = {
            attribute.get("name")
            for attribute in (attributes if isinstance(attributes, list) else [])
            if isinstance(attribute, dict)
        }
        if AXIS_TENANT_ATTRIBUTE in attribute_names:
            steps.append(
                BootstrapStep(
                    component="user_profile",
                    action="already_correct",
                    detail=f"{AXIS_TENANT_ATTRIBUTE!r} is declared in the user profile",
                )
            )
        else:
            steps.append(
                BootstrapStep(
                    component="user_profile",
                    action="update",
                    detail=(
                        f"user profile does not declare {AXIS_TENANT_ATTRIBUTE!r}; "
                        "apply will add it while preserving existing declarations"
                    ),
                )
            )

    return steps


def _report_from_steps(
    mode: typing.Literal["check", "apply"],
    spec: AxisRealmSpec,
    steps: list[BootstrapStep],
) -> RealmBootstrapReport:
    # Operator semantics: "created" means a fresh realm was bootstrapped,
    # "updated" means an existing realm was converged, "already_correct"
    # means nothing needed writing.
    realm_step = next((step for step in steps if step.component == "realm"), None)
    if any(step.action == "conflict" for step in steps):
        status: RealmBootstrapReportStatus = "conflict"
    elif realm_step is not None and realm_step.action == "create":
        status = "created"
    elif any(step.action != "already_correct" for step in steps):
        status = "updated"
    else:
        status = "already_correct"
    return RealmBootstrapReport(mode=mode, realm=spec.realm, status=status, steps=steps)


def check_realm(
    adapter: KeycloakAdminHttp,
    spec: AxisRealmSpec,
) -> RealmBootstrapReport:
    """Dry-run: compute the plan without writing anything."""
    steps = build_realm_bootstrap_plan(adapter, spec)
    return _report_from_steps("check", spec, steps)


def apply_realm(
    adapter: KeycloakAdminHttp,
    spec: AxisRealmSpec,
) -> RealmBootstrapReport:
    """Converge the realm to the desired state; safe to re-run.

    Fails closed before any write when the plan contains conflicts.
    """
    steps = build_realm_bootstrap_plan(adapter, spec)
    if any(step.action == "conflict" for step in steps):
        return _report_from_steps("apply", spec, steps)

    executed = False
    for step in steps:
        if step.action == "create" and step.component == "realm":
            adapter.request(
                "POST",
                "/admin/realms",
                {
                    "realm": spec.realm,
                    "displayName": "Limes Axis",
                    "enabled": True,
                    "registrationAllowed": False,
                    "resetPasswordAllowed": False,
                    "rememberMe": False,
                    "verifyEmail": False,
                },
            )
            executed = True
        elif step.action == "update" and step.component == "realm":
            adapter.request(
                "PUT",
                REALM_GET_PATH.format(realm=spec.realm),
                {"enabled": True},
            )
            executed = True
        elif step.action == "create" and step.component == "client":
            adapter.request(
                "POST",
                REALM_CLIENTS_COLLECTION_PATH.format(realm=spec.realm),
                desired_client_representation(spec.client),
            )
            executed = True
        elif step.action == "update" and step.component == "client":
            clients_response = adapter.request(
                "GET",
                CLIENTS_QUERY_PATH.format(realm=spec.realm, client_id=spec.client.client_id),
            )
            clients = clients_response.body if isinstance(clients_response.body, list) else []
            if not clients or not isinstance(clients[0], dict) or "id" not in clients[0]:
                raise KeycloakBootstrapConflict(
                    "client vanished between planning and apply; re-run check"
                )
            adapter.request(
                "PUT",
                REALM_CLIENT_BY_ID_PATH.format(realm=spec.realm, client_id=str(clients[0]["id"])),
                updates_for_existing_client(clients[0], spec.client),
            )
            executed = True
        elif step.action == "create" and step.component == "roles":
            for role_spec in canonical_axis_realm_roles():
                adapter.request(
                    "POST",
                    REALM_ROLE_CREATE_PATH.format(realm=spec.realm),
                    role_spec.model_dump(),
                )
            executed = True
        elif step.action == "update" and step.component == "roles":
            for role_spec in canonical_axis_realm_roles():
                adapter.request(
                    "PUT",
                    REALM_ROLE_BY_NAME_PATH.format(realm=spec.realm, role_name=role_spec.name),
                    role_spec.model_dump(),
                )
            executed = True
        elif step.action == "update" and step.component == "user_profile":
            _apply_user_profile_attribute(adapter, spec.realm)
            executed = True

    report = _report_from_steps("apply", spec, steps)
    if executed and report.status == "already_correct":
        report = report.model_copy(update={"status": "updated"})
    return report


REALM_CLIENTS_COLLECTION_PATH = "/admin/realms/{realm}/clients"
REALM_CLIENT_BY_ID_PATH = "/admin/realms/{realm}/clients/{client_id}"
REALM_ROLE_BY_NAME_PATH = "/admin/realms/{realm}/roles/{role_name}"


def desired_client_representation(client_spec: AxisIdpClientSpec) -> dict[str, object]:
    """The full desired representation for a fresh console client.

    The client secret is intentionally absent: Keycloak generates one at
    creation, and operators retrieve it through their own secret-management
    path. This module never displays or returns secrets.
    """
    return {
        "clientId": client_spec.client_id,
        "name": "Limes Axis web console",
        "description": (
            "Confidential OIDC client for the Limes Axis web console "
            "(authorization code flow with PKCE)."
        ),
        "enabled": True,
        "protocol": CANONICAL_CLIENT_PROTOCOL,
        "publicClient": False,
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "frontchannelLogout": True,
        "redirectUris": client_spec.redirect_uris,
        "webOrigins": client_spec.web_origins,
        "attributes": {
            "post.logout.redirect.uris": "##".join(client_spec.post_logout_redirect_uris),
            "pkce.code.challenge.method": CANONICAL_PKCE_METHOD,
        },
        "protocolMappers": [
            axis_tenant_protocol_mapper(),
            audience_protocol_mapper(client_spec.audience),
        ],
    }


def updates_for_existing_client(
    existing: dict,
    client_spec: AxisIdpClientSpec,
) -> dict[str, object]:
    """Recompute the convergence payload at apply time from live state."""
    conflicts, updates = _managed_client_updates(existing, client_spec)
    if conflicts:
        raise KeycloakBootstrapConflict("; ".join(conflicts))
    return updates


def _apply_user_profile_attribute(adapter: KeycloakAdminHttp, realm: str) -> None:
    profile_response = adapter.request("GET", USER_PROFILE_PATH.format(realm=realm))
    profile = profile_response.body if isinstance(profile_response.body, dict) else {}
    attributes = profile.get("attributes")
    existing_attributes = [
        attribute for attribute in (attributes if isinstance(attributes, list) else [])
    ]
    already_declared = any(
        isinstance(attribute, dict) and attribute.get("name") == AXIS_TENANT_ATTRIBUTE
        for attribute in existing_attributes
    )
    if not already_declared:
        existing_attributes.append(axis_tenant_user_profile_attribute())
    payload: dict[str, object] = {"attributes": existing_attributes}
    if isinstance(profile.get("groups"), list):
        payload["groups"] = profile["groups"]
    adapter.request("PUT", USER_PROFILE_PATH.format(realm=realm), payload)
