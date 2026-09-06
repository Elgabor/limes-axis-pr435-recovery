"""Observe registered legacy routes without changing their execution or authorization."""

from collections.abc import MutableMapping
from contextlib import suppress
from datetime import UTC, datetime
from email.utils import format_datetime

from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.routing import get_route_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from axis_api.telemetry import TelemetryRuntime

LEGACY_PREFIX = "/demo/manufacturing"
DEPRECATED_AT = datetime(2026, 9, 6, tzinfo=UTC)
SUNSET_AT = datetime(2027, 1, 1, tzinfo=UTC)
POLICY_URL = "https://github.com/Limes-Labs/limes-axis/blob/main/docs/api-compatibility.md"
DEPRECATION_EXPOSE_HEADERS = ["Deprecation", "Sunset", "Link"]
_LEGACY_ROUTE_KEY = "axis.legacy_route"
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}


def add_legacy_deprecation_headers(headers: MutableMapping[str, str], scope: Scope) -> None:
    """Also used by the outer 500 handler, which bypasses user middleware."""

    if _LEGACY_ROUTE_KEY not in scope:
        return
    headers["Deprecation"] = f"@{int(DEPRECATED_AT.timestamp())}"
    headers["Sunset"] = format_datetime(SUNSET_AT, usegmt=True)
    policy_link = f'<{POLICY_URL}>; rel="deprecation"; type="text/html"'
    existing_link = headers.get("Link")
    headers["Link"] = f"{existing_link}, {policy_link}" if existing_link else policy_link


class LegacyRouteDeprecationMiddleware:
    """Observe the deprecated namespace, including failures and early denials.

    Use the router's template after dispatch, or a fixed unmatched bucket.
    Never inspect credentials, bodies or query strings; never remove a route.
    """

    def __init__(self, app: ASGIApp, *, telemetry: TelemetryRuntime) -> None:
        self.app = app
        self.telemetry = telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not get_route_path(scope).startswith(LEGACY_PREFIX + "/"):
            await self.app(scope, receive, send)
            return
        scope[_LEGACY_ROUTE_KEY] = True
        started = False

        def record(status: int) -> None:
            if self.telemetry.metrics_enabled:
                route = scope.get("route")
                template = "unmatched"
                if isinstance(route, APIRoute) and scope["method"] in route.methods:
                    # Lazy included routers keep the unprefixed original route.
                    template = route.path_format
                    if not template.startswith(LEGACY_PREFIX + "/"):
                        template = LEGACY_PREFIX + template
                method = scope["method"] if scope["method"] in _HTTP_METHODS else "_OTHER"
                # Observability failure must not change a governed operation's result.
                with suppress(Exception):
                    self.telemetry.deprecated_request_counter.add(
                        1,
                        {
                            "http.route": template,
                            "http.request.method": method,
                            "http.response.status_code": status,
                        },
                    )

        async def send_with_deprecation(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                add_legacy_deprecation_headers(MutableHeaders(scope=message), scope)
                record(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_deprecation)
        except Exception:
            if not started:
                record(500)
            raise
