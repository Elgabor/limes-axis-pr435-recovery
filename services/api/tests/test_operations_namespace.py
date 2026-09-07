import re
from collections.abc import Callable, Iterator
from typing import Protocol

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from axis_api.config import Settings
from axis_api.main import create_app

CANONICAL_PREFIX = "/operations"
LEGACY_PREFIX = "/demo/manufacturing"
HTTP_METHODS = {"delete", "get", "patch", "post", "put"}
SOURCE_ALIASES = {
    ("/connectors/sources/verify", "POST"): ("/connectors/external-db/verify-source", "POST"),
    ("/connectors/sources/discover", "POST"): ("/connectors/external-db/discover", "POST"),
}


class RouteView(Protocol):
    path: str
    methods: set[str]
    endpoint: Callable[..., object]


def _effective_routes(app: FastAPI) -> Iterator[RouteView]:
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        effective_route_contexts = getattr(route, "effective_route_contexts", None)
        if effective_route_contexts is not None:
            yield from effective_route_contexts()


def _operation_routes(
    app: FastAPI,
    prefix: str,
) -> dict[tuple[str, str], RouteView]:
    routes: dict[tuple[str, str], RouteView] = {}
    for route in _effective_routes(app):
        if not route.path.startswith(f"{prefix}/"):
            continue
        suffix = route.path.removeprefix(prefix)
        for method in route.methods:
            routes[(suffix, method)] = route
    return routes


def _request_path(route: RouteView) -> str:
    return re.sub(r"{[^}]+}", "alias-probe", route.path)


def test_operations_preserve_legacy_aliases_and_scope_new_source_routes() -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            oidc_auth_required=True,
            workflow_signals_enabled=False,
        )
    )
    canonical_routes = _operation_routes(app, CANONICAL_PREFIX)
    legacy_routes = _operation_routes(app, LEGACY_PREFIX)
    bootstrap_route = legacy_routes.pop(("/bootstrap", "POST"))

    assert canonical_routes
    assert bootstrap_route.endpoint.__name__ == "manufacturing_demo_bootstrap"
    # New source-neutral aliases reuse the governed handlers but do not grow
    # the deprecated manufacturing namespace. Every older alias still exists.
    assert canonical_routes.keys() == legacy_routes.keys() | SOURCE_ALIASES.keys()
    assert not legacy_routes.keys() & SOURCE_ALIASES.keys()

    client = TestClient(app)
    for key, canonical_route in canonical_routes.items():
        legacy_route = legacy_routes[SOURCE_ALIASES.get(key, key)]
        assert canonical_route.endpoint is legacy_route.endpoint

        canonical_response = client.request(
            key[1],
            _request_path(canonical_route),
        )
        legacy_response = client.request(
            key[1],
            _request_path(legacy_route),
        )

        assert canonical_response.status_code == legacy_response.status_code, key
        assert canonical_response.content == legacy_response.content, key


def test_bootstrap_remains_demo_only() -> None:
    client = TestClient(create_app())

    assert client.get("/operations/bootstrap").status_code == 404


def test_openapi_deprecates_only_the_legacy_operations_namespace() -> None:
    schema = create_app().openapi()

    legacy_paths = {
        path: path_item
        for path, path_item in schema["paths"].items()
        if path.startswith(f"{LEGACY_PREFIX}/")
    }
    canonical_paths = {
        path: path_item
        for path, path_item in schema["paths"].items()
        if path.startswith(f"{CANONICAL_PREFIX}/")
    }

    assert legacy_paths
    assert canonical_paths
    assert all(
        operation["deprecated"] is True
        for path_item in legacy_paths.values()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    )
    assert all(
        operation.get("deprecated", False) is False
        for path_item in canonical_paths.values()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    )
