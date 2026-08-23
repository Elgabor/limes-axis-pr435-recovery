"""Tests for the enterprise Keycloak realm bootstrap boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axis_api.idp_bootstrap import (
    AXIS_TENANT_ATTRIBUTE,
    AxisIdpClientSpec,
    AxisRealmSpec,
    KeycloakBootstrapUnavailable,
    UrllibKeycloakAdminHttp,
    apply_realm,
    audience_protocol_mapper,
    axis_tenant_protocol_mapper,
    canonical_axis_realm_roles,
    check_realm,
    desired_client_representation,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def make_spec() -> AxisRealmSpec:
    return AxisRealmSpec(
        realm="enterprise",
        client=AxisIdpClientSpec(
            client_id="limes-axis-web",
            redirect_uris=["https://axis.example.com/api/identity/oidc/callback"],
            web_origins=["https://axis.example.com"],
            post_logout_redirect_uris=["https://axis.example.com/"],
            audience="limes-axis-api",
        ),
    )


class FakeKeycloakAdminHttp:
    """Deterministic in-memory Keycloak admin API double."""

    def __init__(self) -> None:
        self.realm: dict | None = None
        self.clients: dict[str, dict] = {}
        self.roles: dict[str, str] = {}
        self.profile_attributes: list[dict] = []
        self.groups: list[dict] = []
        self.requests: list[tuple[str, str]] = []
        self.unavailable = False

    def request(self, method: str, path: str, payload: object | None = None):
        self.requests.append((method, path.split("?")[0]))
        if self.unavailable:
            raise KeycloakBootstrapUnavailable("idp_unreachable")

        if path == "/admin/realms" and method == "POST":
            assert isinstance(payload, dict)
            self.realm = {"realm": payload["realm"], **payload}
            return _response(201)

        if path.startswith("/admin/realms/"):
            # /admin/realms/{realm}/rest...
            rest = path.split("/")[3:]
            if len(rest) == 1:
                if method == "GET":
                    if self.realm is None or self.realm["realm"] != rest[0]:
                        return _response(404)
                    return _response(200, self.realm)
                if method == "PUT":
                    if self.realm is None:
                        return _response(404)
                    self.realm.update(payload or {})
                    return _response(204)
            elif rest[1] == "clients":
                if len(rest) == 2 and method == "POST":
                    assert isinstance(payload, dict)
                    self.clients[payload["clientId"]] = {
                        "id": f"internal-{payload['clientId']}",
                        **payload,
                    }
                    return _response(201)
                if len(rest) == 3 and method == "PUT":
                    for client in self.clients.values():
                        if client["id"] == rest[2]:
                            client.update(payload or {})
                            return _response(204)
                    return _response(404)
            elif rest[1] == "roles":
                if len(rest) == 2 and method == "POST":
                    assert isinstance(payload, dict)
                    self.roles[payload["name"]] = str(payload.get("description") or "")
                    return _response(201)
                if len(rest) == 3 and method == "PUT":
                    if rest[2] not in self.roles:
                        return _response(404)
                    assert isinstance(payload, dict)
                    self.roles[rest[2]] = str(payload.get("description") or "")
                    return _response(204)
            elif rest[1:] == ["users", "profile"]:
                if method == "GET":
                    return _response(
                        200,
                        {
                            "attributes": self.profile_attributes,
                            "groups": self.groups,
                        },
                    )
                if method == "PUT":
                    assert isinstance(payload, dict)
                    self.profile_attributes = payload["attributes"]
                    self.groups = payload.get("groups", [])
                    return _response(204)

        if "/roles?" in path and method == "GET":
            return _response(
                200,
                [
                    {"name": name, "description": description}
                    for name, description in self.roles.items()
                ],
            )
        if "/clients?" in path and method == "GET":
            client_id = path.split("clientId=")[-1]
            matched = [
                client for client in self.clients.values() if client.get("clientId") == client_id
            ]
            return _response(200, matched)
        raise AssertionError(f"fake adapter has no route for {method} {path}")

    def mutations(self) -> list[str]:
        return [f"{method} {path}" for method, path in self.requests if method != "GET"]


def _response(status: int, body: object = None):
    from axis_api.idp_bootstrap import KeycloakHttpResponse

    return KeycloakHttpResponse(status=status, body=body)


def seed_correct_realm(fake: FakeKeycloakAdminHttp, spec: AxisRealmSpec) -> None:
    fake.realm = {"realm": spec.realm, "enabled": True}
    representation = json.loads(json.dumps(desired_client_representation(spec.client)))
    fake.clients[spec.client.client_id] = {
        "id": f"internal-{spec.client.client_id}",
        **representation,
    }
    fake.roles = {role.name: role.description for role in canonical_axis_realm_roles()}
    fake.profile_attributes = [
        {
            "name": "preferred_locale",
            "displayName": "Locale",
            "multivalued": False,
            "annotations": {},
            "permissions": {"view": ["admin"], "edit": ["admin"]},
        },
        {
            "name": AXIS_TENANT_ATTRIBUTE,
            "displayName": "Axis Tenant",
            "multivalued": False,
            "annotations": {},
            "permissions": {"view": ["admin"], "edit": ["admin"]},
        },
    ]


class TestCheckMode:
    def test_fresh_realm_plan_declares_everything_as_create(self) -> None:
        fake = FakeKeycloakAdminHttp()
        spec = make_spec()

        report = check_realm(fake, spec)

        assert report.ok
        actions = {(step.component, step.action) for step in report.steps}
        assert ("realm", "create") in actions
        assert ("client", "create") in actions
        assert ("roles", "create") in actions
        assert ("user_profile", "update") in actions
        assert fake.mutations() == []

    def test_converged_realm_reports_already_correct_without_mutations(self) -> None:
        fake = FakeKeycloakAdminHttp()
        spec = make_spec()
        seed_correct_realm(fake, spec)

        report = check_realm(fake, spec)

        assert report.status == "already_correct"
        assert all(step.action == "already_correct" for step in report.steps)
        assert fake.mutations() == []


class TestApplyMode:
    def test_apply_on_fresh_realm_then_rerun_is_already_correct(self) -> None:
        fake = FakeKeycloakAdminHttp()
        spec = make_spec()

        first = apply_realm(fake, spec)
        assert first.status == "created"

        second = apply_realm(fake, spec)
        assert second.status == "already_correct"
        assert all(step.action == "already_correct" for step in second.steps)

        client = fake.clients[spec.client.client_id]
        assert client["publicClient"] is False
        assert client["directAccessGrantsEnabled"] is False
        assert "secret" not in json.dumps(client)
        assert any(
            attribute["name"] == AXIS_TENANT_ATTRIBUTE for attribute in fake.profile_attributes
        )

    def test_apply_converges_drifted_realm(self) -> None:
        fake = FakeKeycloakAdminHttp()
        spec = make_spec()
        seed_correct_realm(fake, spec)
        del fake.roles["platform:policy:author"]
        fake.roles["audit:read"] = "Stale legacy description"
        fake.clients[spec.client.client_id]["redirectUris"] = []
        del fake.clients[spec.client.client_id]["attributes"]["pkce.code.challenge.method"]

        report = apply_realm(fake, spec)

        assert report.status == "updated"
        assert fake.roles["platform:policy:author"] == next(
            role.description
            for role in canonical_axis_realm_roles()
            if role.name == "platform:policy:author"
        )
        assert fake.roles["audit:read"] == next(
            role.description for role in canonical_axis_realm_roles() if role.name == "audit:read"
        )
        assert fake.clients[spec.client.client_id]["redirectUris"] == list(
            spec.client.redirect_uris
        )
        assert (
            fake.clients[spec.client.client_id]["attributes"]["pkce.code.challenge.method"]
            == "S256"
        )

    def test_apply_preserves_unmanaged_user_profile_attributes_and_groups(self) -> None:
        fake = FakeKeycloakAdminHttp()
        spec = make_spec()
        seed_correct_realm(fake, spec)
        fake.profile_attributes = [
            attribute
            for attribute in fake.profile_attributes
            if attribute["name"] != AXIS_TENANT_ATTRIBUTE
        ]
        fake.groups = [{"name": "axis-operators"}]

        apply_realm(fake, spec)

        names = [attribute["name"] for attribute in fake.profile_attributes]
        assert AXIS_TENANT_ATTRIBUTE in names
        assert "preferred_locale" in names
        assert fake.groups == [{"name": "axis-operators"}]


class TestFailClosedConflicts:
    @pytest.mark.parametrize(
        ("mutation", "expected_fragment"),
        [
            pytest.param(
                lambda fake, spec: fake.clients[spec.client.client_id].update(
                    {"publicClient": True}
                ),
                "public",
                id="public-client",
            ),
            pytest.param(
                lambda fake, spec: fake.clients[spec.client.client_id].update({"protocol": "saml"}),
                "protocol",
                id="wrong-protocol",
            ),
            pytest.param(
                lambda fake, spec: fake.clients[spec.client.client_id]["redirectUris"].append(
                    "https://legacy.example.com/callback"
                ),
                "redirect URIs",
                id="extra-redirect-uri",
            ),
            pytest.param(
                lambda fake, spec: fake.clients[spec.client.client_id]["protocolMappers"].append(
                    {
                        "name": "legacy-mapper",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-hardcoded-claim-mapper",
                        "consentRequired": False,
                        "config": {},
                    }
                ),
                "unmanaged protocol mappers",
                id="unmanaged-mapper",
            ),
        ],
    )
    def test_conflicting_client_state_fails_closed_without_writes(
        self,
        mutation,
        expected_fragment: str,
    ) -> None:
        fake = FakeKeycloakAdminHttp()
        spec = make_spec()
        seed_correct_realm(fake, spec)
        mutation(fake, spec)
        mutations_before = fake.mutations()

        report = apply_realm(fake, spec)

        assert report.status == "conflict"
        assert not report.ok
        conflict_details = [step.detail for step in report.steps if step.action == "conflict"]
        assert any(expected_fragment in detail for detail in conflict_details)
        assert fake.mutations() == mutations_before

    def test_duplicate_clients_fail_closed(self) -> None:
        fake = FakeKeycloakAdminHttp()
        spec = make_spec()
        seed_correct_realm(fake, spec)
        fake.clients["duplicate-entry"] = {
            **desired_client_representation(spec.client),
            "id": "internal-duplicate",
        }

        report = apply_realm(fake, spec)

        assert report.status == "conflict"
        assert any(
            "multiple clients" in step.detail for step in report.steps if step.action == "conflict"
        )


class TestUnreachableIdp:
    def test_unreachable_is_classified_not_crashed(self) -> None:
        fake = FakeKeycloakAdminHttp()
        fake.unavailable = True

        with pytest.raises(KeycloakBootstrapUnavailable) as excinfo:
            check_realm(fake, make_spec())

        assert excinfo.value.reason == "idp_unreachable"

    def test_admin_http_error_responses_do_not_echo_bodies_or_tokens(self) -> None:
        adapter = UrllibKeycloakAdminHttp(
            base_url="http://127.0.0.1:1",
            admin_username="operator",
            admin_password="hunter2-not-in-diagnostics",
        )
        with pytest.raises(KeycloakBootstrapUnavailable):
            adapter._fetch_access_token()


class TestSecretHygiene:
    def test_report_json_never_contains_credentials_or_secrets(self) -> None:
        fake = FakeKeycloakAdminHttp()
        spec = make_spec()
        seed_correct_realm(fake, spec)
        fake.clients[spec.client.client_id]["secret"] = "super-secret-client-value"

        serialized = apply_realm(fake, spec).model_dump_json()

        assert "super-secret-client-value" not in serialized
        assert "hunter2" not in serialized


class TestSingleSourceOfTruthContract:
    def test_local_demo_realm_declares_the_canonical_role_set(self) -> None:
        realm_import = json.loads((REPO_ROOT / "infra/docker/keycloak/axis-realm.json").read_text())
        demo_role_names = {role["name"] for role in realm_import["roles"]["realm"]}
        canonical_names = {role.name for role in canonical_axis_realm_roles()}

        missing = canonical_names - demo_role_names
        assert not missing, f"demo realm is missing canonical roles: {sorted(missing)}"

    def test_demo_realm_mappers_match_the_module_declarations(self) -> None:
        realm_import = json.loads((REPO_ROOT / "infra/docker/keycloak/axis-realm.json").read_text())
        client = realm_import["clients"][0]
        mappers = {mapper["name"]: mapper for mapper in client["protocolMappers"]}

        tenant_mapper = mappers[AXIS_TENANT_ATTRIBUTE]
        assert tenant_mapper["config"]["user.attribute"] == AXIS_TENANT_ATTRIBUTE
        assert tenant_mapper["config"]["claim.name"] == AXIS_TENANT_ATTRIBUTE

        audience_mapper = mappers["limes-axis-api-audience"]
        expected = audience_protocol_mapper("limes-axis-api")
        assert audience_mapper["config"] == expected["config"]

    def test_tenant_mapper_matches_api_verifier_default_claim(self) -> None:
        from axis_api.identity import StaticJwksOidcVerifier

        verifier = StaticJwksOidcVerifier(
            issuer="https://idp.example.test/realms/axis",
            audience="limes-axis-api",
            algorithms=["RS256"],
            jwks={"keys": []},
        )
        assert verifier.tenant_claim == AXIS_TENANT_ATTRIBUTE


class TestMapperDeclarations:
    def test_tenant_mapper_shape(self) -> None:
        mapper = axis_tenant_protocol_mapper()

        assert mapper["name"] == AXIS_TENANT_ATTRIBUTE
        assert mapper["config"]["user.attribute"] == AXIS_TENANT_ATTRIBUTE
        assert mapper["config"]["access.token.claim"] == "true"

    def test_audience_mapper_uses_configured_audience(self) -> None:
        mapper = audience_protocol_mapper("custom-api")

        assert mapper["name"] == "custom-api-audience"
        assert mapper["config"]["included.custom.audience"] == "custom-api"
