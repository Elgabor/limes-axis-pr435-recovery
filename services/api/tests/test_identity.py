import base64
import hashlib
import json

import pytest
from jose import jwt
from jose.utils import base64url_encode
from pydantic import BaseModel

from axis_api.identity import (
    ActorBindingError,
    OidcAuthenticationError,
    OidcPrincipal,
    RemoteJwksOidcVerifier,
    StaticJwksOidcVerifier,
    bind_request_actor,
)


def _oct_jwks(secret: str, kid: str = "axis-test") -> dict:
    return {
        "keys": [
            {
                "kty": "oct",
                "kid": kid,
                "k": base64url_encode(secret.encode()).decode(),
            }
        ]
    }


def _token(secret: str, claims: dict, kid: str = "axis-test") -> str:
    return jwt.encode(claims, secret, algorithm="HS256", headers={"kid": kid})


def test_static_jwks_oidc_verifier_validates_token_and_extracts_actor_context() -> None:
    secret = "axis-test-secret"
    verifier = StaticJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks=_oct_jwks(secret),
        tenant_claim="axis_tenant",
    )
    token = _token(
        secret,
        {
            "iss": "https://issuer.example/realms/axis",
            "aud": "limes-axis-api",
            "sub": "plant-operations-owner-role",
            "axis_tenant": "tenant_demo_manufacturing",
            "scope": "approvals:supply:decide audit:read",
            "scp": ["workflows:read"],
            "realm_access": {"roles": ["operations-owner"]},
            "resource_access": {
                "limes-axis-api": {"roles": ["approvals:maintenance:decide"]}
            },
            "exp": 4102444800,
        },
    )

    principal = verifier.verify_authorization_header(f"Bearer {token}")

    assert principal.actor_id == "plant-operations-owner-role"
    assert principal.subject_id == "plant-operations-owner-role"
    assert principal.tenant_id == "tenant_demo_manufacturing"
    assert principal.expires_at == 4102444800
    assert principal.scopes == [
        "approvals:maintenance:decide",
        "approvals:supply:decide",
        "audit:read",
        "operations-owner",
        "workflows:read",
    ]


def test_static_jwks_oidc_verifier_rejects_wrong_audience() -> None:
    secret = "axis-test-secret"
    verifier = StaticJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks=_oct_jwks(secret),
        tenant_claim="axis_tenant",
    )
    token = _token(
        secret,
        {
            "iss": "https://issuer.example/realms/axis",
            "aud": "other-api",
            "sub": "plant-operations-owner-role",
            "axis_tenant": "tenant_demo_manufacturing",
            "scope": "approvals:supply:decide",
            "exp": 4102444800,
        },
    )

    try:
        verifier.verify_authorization_header(f"Bearer {token}")
    except OidcAuthenticationError as exc:
        assert exc.reason == "invalid_token"
    else:
        raise AssertionError("expected wrong audience to be rejected")


def test_static_jwks_oidc_verifier_validates_id_token_nonce_and_client_audience() -> None:
    secret = "axis-test-secret"
    verifier = StaticJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks=_oct_jwks(secret),
        tenant_claim="axis_tenant",
    )
    id_token = _token(
        secret,
        {
            "iss": "https://issuer.example/realms/axis",
            "aud": "axis-console",
            "azp": "axis-console",
            "sub": "plant-operations-owner-role",
            "nonce": "login-nonce",
            "exp": 4102444800,
        },
    )

    claims = verifier.verify_id_token(
        id_token,
        client_id="axis-console",
        nonce="login-nonce",
    )

    assert claims["sub"] == "plant-operations-owner-role"
    assert claims["nonce"] == "login-nonce"


def _at_hash(access_token: str) -> str:
    digest = hashlib.sha256(access_token.encode()).digest()
    return (
        base64.urlsafe_b64encode(digest[: len(digest) // 2])
        .rstrip(b"=")
        .decode()
    )


def test_static_jwks_oidc_verifier_validates_at_hash_against_access_token() -> None:
    """Identity providers (Keycloak included) embed an `at_hash` binding in ID
    tokens; decoding one requires the access token from the same response, and
    a mismatched access token must be rejected."""
    secret = "axis-test-secret"
    verifier = StaticJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks=_oct_jwks(secret),
        tenant_claim="axis_tenant",
    )
    access_token = "access-token-from-the-same-token-response"
    id_claims = {
        "iss": "https://issuer.example/realms/axis",
        "aud": "axis-console",
        "azp": "axis-console",
        "sub": "plant-operations-owner-role",
        "nonce": "login-nonce",
        "exp": 4102444800,
        "at_hash": _at_hash(access_token),
    }
    id_token = _token(secret, id_claims)

    # Without the access token the at_hash claim cannot be checked and the
    # decode must fail closed.
    try:
        verifier.verify_id_token(id_token, client_id="axis-console", nonce="login-nonce")
    except OidcAuthenticationError as exc:
        assert exc.reason == "invalid_id_token"
    else:
        raise AssertionError("expected missing access token to be rejected")

    # The matching access token validates the binding.
    claims = verifier.verify_id_token(
        id_token,
        client_id="axis-console",
        nonce="login-nonce",
        access_token=access_token,
    )
    assert claims["sub"] == "plant-operations-owner-role"

    # A foreign access token fails the comparison.
    try:
        verifier.verify_id_token(
            id_token,
            client_id="axis-console",
            nonce="login-nonce",
            access_token="different-access-token",
        )
    except OidcAuthenticationError as exc:
        assert exc.reason == "invalid_id_token"
    else:
        raise AssertionError("expected at_hash mismatch to be rejected")


def test_static_jwks_oidc_verifier_rejects_id_token_authorized_party_mismatch() -> None:
    secret = "axis-test-secret"
    verifier = StaticJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks=_oct_jwks(secret),
        tenant_claim="axis_tenant",
    )
    id_token = _token(
        secret,
        {
            "iss": "https://issuer.example/realms/axis",
            "aud": ["axis-console", "unexpected-client"],
            "azp": "unexpected-client",
            "sub": "plant-operations-owner-role",
            "nonce": "login-nonce",
            "exp": 4102444800,
        },
    )

    try:
        verifier.verify_id_token(
            id_token,
            client_id="axis-console",
            nonce="login-nonce",
        )
    except OidcAuthenticationError as exc:
        assert exc.reason == "invalid_id_token_authorized_party"
    else:
        raise AssertionError("expected wrong authorized party to be rejected")


def test_static_jwks_oidc_verifier_rejects_single_audience_id_token_with_wrong_azp() -> None:
    secret = "axis-test-secret"
    verifier = StaticJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks=_oct_jwks(secret),
        tenant_claim="axis_tenant",
    )
    id_token = _token(
        secret,
        {
            "iss": "https://issuer.example/realms/axis",
            "aud": "axis-console",
            "azp": "unexpected-client",
            "sub": "plant-operations-owner-role",
            "nonce": "login-nonce",
            "exp": 4102444800,
        },
    )

    try:
        verifier.verify_id_token(
            id_token,
            client_id="axis-console",
            nonce="login-nonce",
        )
    except OidcAuthenticationError as exc:
        assert exc.reason == "invalid_id_token_authorized_party"
    else:
        raise AssertionError("expected wrong authorized party to be rejected")


def test_static_jwks_oidc_verifier_rejects_id_token_without_expiry() -> None:
    secret = "axis-test-secret"
    verifier = StaticJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks=_oct_jwks(secret),
        tenant_claim="axis_tenant",
    )
    id_token = _token(
        secret,
        {
            "iss": "https://issuer.example/realms/axis",
            "aud": "axis-console",
            "azp": "axis-console",
            "sub": "plant-operations-owner-role",
            "nonce": "login-nonce",
        },
    )

    try:
        verifier.verify_id_token(
            id_token,
            client_id="axis-console",
            nonce="login-nonce",
        )
    except OidcAuthenticationError as exc:
        assert exc.reason == "missing_id_token_expiry"
    else:
        raise AssertionError("expected missing expiry to be rejected")


def test_remote_jwks_oidc_verifier_fetches_and_caches_jwks(monkeypatch) -> None:
    secret = "axis-test-secret"
    jwks = _oct_jwks(secret)
    fetches: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"keys":[{"kty":"oct","kid":"axis-test","k":"YXhpcy10ZXN0LXNlY3JldA"}]}'

    def fake_urlopen(url: str, timeout: int):
        fetches.append(f"{url}:{timeout}")
        return FakeResponse()

    monkeypatch.setattr("axis_api.identity.urlopen", fake_urlopen)
    verifier = RemoteJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks_url="https://issuer.example/realms/axis/protocol/openid-connect/certs",
        cache_seconds=300,
        tenant_claim="axis_tenant",
    )
    token = _token(
        secret,
        {
            "iss": "https://issuer.example/realms/axis",
            "aud": "limes-axis-api",
            "sub": "agent_supply_risk",
            "axis_tenant": "tenant_demo_manufacturing",
            "scope": "supply:read",
            "exp": 4102444800,
        },
    )

    assert verifier.verify_authorization_header(f"Bearer {token}").actor_id == "agent_supply_risk"
    assert verifier.verify_authorization_header(f"Bearer {token}").actor_id == "agent_supply_risk"
    assert fetches == [
        "https://issuer.example/realms/axis/protocol/openid-connect/certs:2"
    ]
    assert verifier.jwks == jwks


def test_remote_jwks_oidc_verifier_refreshes_once_for_rotated_kid(monkeypatch) -> None:
    old_secret = "axis-old-secret"
    new_secret = "axis-new-secret"
    payloads = [_oct_jwks(old_secret, "old-key"), _oct_jwks(new_secret, "new-key")]
    fetches = 0

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode()

    def fake_urlopen(_url: str, timeout: int):
        nonlocal fetches
        assert timeout == 2
        payload = payloads[min(fetches, len(payloads) - 1)]
        fetches += 1
        return FakeResponse(payload)

    monkeypatch.setattr("axis_api.identity.urlopen", fake_urlopen)
    verifier = RemoteJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks_url="https://issuer.example/jwks",
        cache_seconds=300,
        tenant_claim="axis_tenant",
    )
    claims = {
        "iss": "https://issuer.example/realms/axis",
        "aud": "limes-axis-api",
        "sub": "operator",
        "axis_tenant": "tenant_demo_manufacturing",
        "exp": 4102444800,
    }

    verifier.verify_authorization_header(
        f"Bearer {_token(old_secret, claims, kid='old-key')}"
    )
    principal = verifier.verify_authorization_header(
        f"Bearer {_token(new_secret, claims, kid='new-key')}"
    )

    assert principal.actor_id == "operator"
    assert fetches == 2
    assert verifier.jwks == payloads[1]


def test_remote_jwks_unknown_kids_share_refresh_cooldown(monkeypatch) -> None:
    secret = "axis-known-secret"
    fetches = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(_oct_jwks(secret, "known-key")).encode()

    def fake_urlopen(_url: str, timeout: int):
        nonlocal fetches
        assert timeout == 2
        fetches += 1
        return FakeResponse()

    monkeypatch.setattr("axis_api.identity.urlopen", fake_urlopen)
    verifier = RemoteJwksOidcVerifier(
        issuer="https://issuer.example/realms/axis",
        audience="limes-axis-api",
        algorithms=["HS256"],
        jwks_url="https://issuer.example/jwks",
        cache_seconds=300,
        tenant_claim="axis_tenant",
    )
    claims = {
        "iss": "https://issuer.example/realms/axis",
        "aud": "limes-axis-api",
        "sub": "operator",
        "axis_tenant": "tenant_demo_manufacturing",
        "exp": 4102444800,
    }

    for kid in ("unknown-one", "unknown-two", "unknown-three"):
        with pytest.raises(OidcAuthenticationError, match="jwks_key_not_found"):
            verifier.verify_authorization_header(
                f"Bearer {_token('attacker-secret', claims, kid=kid)}"
            )

    # Initial cache fill plus one rotation refresh; other random kids are
    # rejected during the shared cooldown without another outbound fetch.
    assert fetches == 2


class _BindingRequest(BaseModel):
    tenant_id: str
    requested_by: str = ""
    actor_scopes: list[str] = []


def _principal(tenant: str = "tenant_demo_manufacturing", actor: str = "operator") -> OidcPrincipal:
    return OidcPrincipal(actor_id=actor, tenant_id=tenant, scopes=["connectors:sync:execute"])


def test_bind_request_actor_without_principal_keeps_body_values() -> None:
    request = _BindingRequest(tenant_id="tenant_demo_manufacturing", requested_by="body-actor")

    bound = bind_request_actor(request, None, actor_field="requested_by")

    assert bound is request


def test_bind_request_actor_fills_empty_actor_and_stamps_scopes() -> None:
    request = _BindingRequest(tenant_id="tenant_demo_manufacturing")

    bound = bind_request_actor(
        request,
        _principal(),
        actor_field="requested_by",
        expected_tenant_id="tenant_demo_manufacturing",
    )

    assert bound.requested_by == "operator"
    assert bound.actor_scopes == ["connectors:sync:execute"]


def test_bind_request_actor_rejects_cross_tenant_principal_fail_closed() -> None:
    request = _BindingRequest(tenant_id="tenant_demo_manufacturing")

    with pytest.raises(ActorBindingError) as excinfo:
        bind_request_actor(
            request,
            _principal(tenant="tenant_other"),
            actor_field="requested_by",
        )

    assert excinfo.value.reason == "tenant_mismatch"


def test_bind_request_actor_rejects_body_actor_impersonation() -> None:
    request = _BindingRequest(tenant_id="tenant_demo_manufacturing", requested_by="someone-else")

    with pytest.raises(ActorBindingError) as excinfo:
        bind_request_actor(request, _principal(), actor_field="requested_by")

    assert excinfo.value.reason == "actor_mismatch"


def test_bind_request_actor_reads_tenant_from_body_when_not_pinned() -> None:
    request = _BindingRequest(tenant_id="tenant_other")

    bound = bind_request_actor(
        request,
        _principal(tenant="tenant_other"),
        actor_field="requested_by",
    )

    assert bound.requested_by == "operator"


def test_bind_request_actor_tolerates_models_without_scope_field() -> None:
    class _NoScopes(BaseModel):
        tenant_id: str
        transitioned_by: str = ""

    bound = bind_request_actor(
        _NoScopes(tenant_id="tenant_demo_manufacturing"),
        _principal(),
        actor_field="transitioned_by",
    )

    assert bound.transitioned_by == "operator"
