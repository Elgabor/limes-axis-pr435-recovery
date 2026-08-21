from __future__ import annotations

import re
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-Id"
REQUEST_ID_STATE_KEY = "request_id"
_REQUEST_ID_HEADER_BYTES = REQUEST_ID_HEADER.casefold().encode("ascii")
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


def normalize_request_id(candidate: str | None) -> str:
    normalized = candidate.strip() if candidate is not None else ""
    if _REQUEST_ID_PATTERN.fullmatch(normalized):
        return normalized
    return new_request_id()


def _request_id_from_scope(scope: Scope) -> str:
    values = [
        value.decode("latin-1")
        for name, value in scope.get("headers", [])
        if name.lower() == _REQUEST_ID_HEADER_BYTES
    ]
    return normalize_request_id(values[0] if len(values) == 1 else None)


class RequestCorrelationMiddleware:
    """Attach one validated correlation id to the request state and response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from_scope(scope)
        scope.setdefault("state", {})[REQUEST_ID_STATE_KEY] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)
