import json
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

from jose import JWTError, jwt
from pydantic import BaseModel, Field


class OidcAuthenticationError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ActorBindingError(PermissionError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


PUBLIC_DEMO_ACTOR_ID = "public-demo-steward"


def resolve_declared_actor(
    request_actor: str | None,
    principal_actor_id: str | None,
) -> str:
    """Attribute a declared write to the verified principal when one exists.

    Unauthenticated demo traffic may name an actor in the body; a verified
    OIDC principal always overrides it so the body cannot spoof attribution.
    """
    if principal_actor_id is not None:
        return principal_actor_id
    if request_actor is not None:
        return request_actor
    return PUBLIC_DEMO_ACTOR_ID


class OidcPrincipal(BaseModel):
    actor_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)
    expires_at: int | None = Field(default=None, ge=0)
    subject_id: str | None = Field(default=None, min_length=1)
    session_source: str = Field(default="bearer_token", min_length=1)


def _authorization_token(authorization: str | None) -> str:
    if not authorization:
        raise OidcAuthenticationError("missing_authorization")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise OidcAuthenticationError("invalid_authorization_header")

    return token


def _claim_scopes(claims: dict, audience: str) -> list[str]:
    scopes: set[str] = set()
    scope = claims.get("scope")
    if isinstance(scope, str):
        scopes.update(scope.split())

    scp = claims.get("scp")
    if isinstance(scp, str):
        scopes.update(scp.split())
    elif isinstance(scp, list):
        scopes.update(str(item) for item in scp if item)

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        roles = realm_access.get("roles", [])
        if isinstance(roles, list):
            scopes.update(str(role) for role in roles if role)

    resource_access = claims.get("resource_access")
    if isinstance(resource_access, dict):
        client_access = resource_access.get(audience, {})
        if isinstance(client_access, dict):
            roles = client_access.get("roles", [])
            if isinstance(roles, list):
                scopes.update(str(role) for role in roles if role)

    return sorted(scopes)


class StaticJwksOidcVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: list[str],
        jwks: dict,
        actor_claim: str = "sub",
        tenant_claim: str = "axis_tenant",
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.algorithms = algorithms
        self.jwks = jwks
        self.actor_claim = actor_claim
        self.tenant_claim = tenant_claim

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        token = _authorization_token(authorization)
        try:
            claims = jwt.decode(
                token,
                self._key_for_token(token),
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
            )
        except JWTError as exc:
            raise OidcAuthenticationError("invalid_token") from exc

        actor_id = claims.get(self.actor_claim)
        tenant_id = claims.get(self.tenant_claim)
        if not isinstance(actor_id, str) or not actor_id:
            raise OidcAuthenticationError("missing_actor_claim")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise OidcAuthenticationError("missing_tenant_claim")

        return OidcPrincipal(
            actor_id=actor_id,
            tenant_id=tenant_id,
            scopes=_claim_scopes(claims, self.audience),
            expires_at=claims.get("exp") if isinstance(claims.get("exp"), int) else None,
            subject_id=claims.get("sub") if isinstance(claims.get("sub"), str) else None,
        )

    def verify_id_token(
        self,
        token: str,
        *,
        client_id: str,
        nonce: str,
    ) -> dict:
        try:
            claims = jwt.decode(
                token,
                self._key_for_token(token),
                algorithms=self.algorithms,
                audience=client_id,
                issuer=self.issuer,
            )
        except JWTError as exc:
            raise OidcAuthenticationError("invalid_id_token") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise OidcAuthenticationError("missing_id_token_subject")

        if claims.get("nonce") != nonce:
            raise OidcAuthenticationError("id_token_nonce_mismatch")

        expires_at = claims.get("exp")
        if not isinstance(expires_at, int):
            raise OidcAuthenticationError("missing_id_token_expiry")

        authorized_party = claims.get("azp")
        if authorized_party is not None and authorized_party != client_id:
            raise OidcAuthenticationError("invalid_id_token_authorized_party")

        audiences = claims.get("aud")
        if isinstance(audiences, list) and len(audiences) > 1:
            authorized_party = claims.get("azp")
            if authorized_party != client_id:
                raise OidcAuthenticationError("invalid_id_token_authorized_party")

        return claims

    def _key_for_token(self, token: str) -> dict:
        keys = self.jwks.get("keys", [])
        if not isinstance(keys, list) or not keys:
            raise OidcAuthenticationError("jwks_empty")

        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if kid:
            for key in keys:
                if isinstance(key, dict) and key.get("kid") == kid:
                    return key
            raise OidcAuthenticationError("jwks_key_not_found")

        if len(keys) == 1 and isinstance(keys[0], dict):
            return keys[0]

        raise OidcAuthenticationError("jwks_key_not_found")


class RemoteJwksOidcVerifier(StaticJwksOidcVerifier):
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: list[str],
        jwks_url: str,
        cache_seconds: int,
        actor_claim: str = "sub",
        tenant_claim: str = "axis_tenant",
    ) -> None:
        super().__init__(
            issuer=issuer,
            audience=audience,
            algorithms=algorithms,
            jwks={"keys": []},
            actor_claim=actor_claim,
            tenant_claim=tenant_claim,
        )
        self.jwks_url = jwks_url
        self.cache_seconds = cache_seconds
        self._cache_expires_at = 0.0
        self._refresh_lock = threading.Lock()
        self._last_forced_refresh_at = 0.0
        self._forced_refresh_cooldown_seconds = min(5.0, max(1.0, cache_seconds / 10))

    def _key_for_token(self, token: str) -> dict:
        if time.time() < self._cache_expires_at:
            try:
                return super()._key_for_token(token)
            except OidcAuthenticationError as exc:
                if exc.reason != "jwks_key_not_found":
                    raise

        # Known keys on a valid cache stay lock-free. Only cache refreshes and
        # unknown-key misses are serialized, avoiding a global bearer-auth
        # bottleneck while still bounding IdP requests under hostile traffic.
        with self._refresh_lock:
            now = time.time()
            cache_was_valid = now < self._cache_expires_at
            if not cache_was_valid:
                self.jwks = self._fetch_jwks()
                self._cache_expires_at = now + self.cache_seconds
            try:
                return super()._key_for_token(token)
            except OidcAuthenticationError as exc:
                if exc.reason != "jwks_key_not_found" or not cache_was_valid:
                    raise
                if (
                    now - self._last_forced_refresh_at
                    < self._forced_refresh_cooldown_seconds
                ):
                    raise
                # Support normal IdP key rotation without allowing random-kid
                # traffic to force one blocking network fetch per request.
                self._last_forced_refresh_at = now
                self.jwks = self._fetch_jwks()
                self._cache_expires_at = now + self.cache_seconds
                return super()._key_for_token(token)

    def _fetch_jwks(self) -> dict:
        try:
            with urlopen(self.jwks_url, timeout=2) as response:
                return json.loads(response.read())
        except (OSError, URLError, ValueError) as exc:
            raise OidcAuthenticationError("jwks_fetch_failed") from exc


def bind_request_actor(
    request_model: BaseModel,
    principal: OidcPrincipal | None,
    *,
    expected_tenant_id: str,
) -> BaseModel:
    if principal is None:
        return request_model

    if principal.tenant_id != expected_tenant_id:
        raise ActorBindingError(
            reason="tenant_mismatch",
            message="The authenticated OIDC tenant cannot access this tenant scope.",
        )

    request_actor = getattr(request_model, "actor_id", None)
    if request_actor and request_actor != principal.actor_id:
        raise ActorBindingError(
            reason="actor_mismatch",
            message="The request actor does not match the authenticated OIDC actor.",
        )

    return request_model.model_copy(
        update={
            "actor_id": principal.actor_id,
            "actor_scopes": principal.scopes,
        }
    )
