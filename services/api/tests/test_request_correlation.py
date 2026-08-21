import re

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from axis_api.config import Settings
from axis_api.main import create_app
from axis_api.request_correlation import REQUEST_ID_HEADER

_GENERATED_REQUEST_ID_PATTERN = re.compile(r"req_[0-9a-f]{32}")


def request_id_test_client() -> TestClient:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))

    @app.get("/_test/request-id")
    def request_id_from_state(request: Request) -> dict[str, str]:
        return {"request_id": request.state.request_id}

    @app.get("/_test/handled-server-error")
    def handled_server_error() -> None:
        raise HTTPException(status_code=500, detail="synthetic failure")

    @app.get("/_test/unhandled-server-error")
    def unhandled_server_error() -> None:
        raise RuntimeError("synthetic unhandled failure")

    return TestClient(app)


def test_request_correlation_generates_and_exposes_request_id() -> None:
    response = request_id_test_client().get("/_test/request-id")

    assert response.status_code == 200
    request_id = response.headers[REQUEST_ID_HEADER]
    assert _GENERATED_REQUEST_ID_PATTERN.fullmatch(request_id)
    assert response.json() == {"request_id": request_id}


def test_request_correlation_echoes_valid_client_request_id() -> None:
    response = request_id_test_client().get(
        "/_test/request-id",
        headers={REQUEST_ID_HEADER: "client:job_123.attempt-2"},
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "client:job_123.attempt-2"
    assert response.json() == {"request_id": "client:job_123.attempt-2"}


@pytest.mark.parametrize(
    "invalid_request_id",
    [
        "contains spaces",
        "req_" + "a" * 125,
        "unsafe/value",
    ],
)
def test_request_correlation_replaces_invalid_client_request_id(
    invalid_request_id: str,
) -> None:
    response = request_id_test_client().get(
        "/_test/request-id",
        headers={REQUEST_ID_HEADER: invalid_request_id},
    )

    request_id = response.headers[REQUEST_ID_HEADER]
    assert request_id != invalid_request_id
    assert _GENERATED_REQUEST_ID_PATTERN.fullmatch(request_id)
    assert response.json() == {"request_id": request_id}


def test_request_correlation_replaces_ambiguous_duplicate_headers() -> None:
    response = request_id_test_client().get(
        "/_test/request-id",
        headers=[
            (REQUEST_ID_HEADER, "req_first"),
            (REQUEST_ID_HEADER, "req_second"),
        ],
    )

    request_id = response.headers[REQUEST_ID_HEADER]
    assert request_id not in {"req_first", "req_second"}
    assert _GENERATED_REQUEST_ID_PATTERN.fullmatch(request_id)
    assert response.json() == {"request_id": request_id}


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/missing", 404),
        ("/operations/connectors", 422),
        ("/_test/handled-server-error", 500),
    ],
)
def test_request_correlation_echoes_request_id_on_error_responses(
    path: str,
    expected_status: int,
) -> None:
    response = request_id_test_client().get(
        path,
        headers={REQUEST_ID_HEADER: "req_support_case_123"},
    )

    assert response.status_code == expected_status
    assert response.headers[REQUEST_ID_HEADER] == "req_support_case_123"


def test_request_correlation_survives_unhandled_server_errors() -> None:
    client = request_id_test_client()
    response = TestClient(client.app, raise_server_exceptions=False).get(
        "/_test/unhandled-server-error",
        headers={
            "Origin": "http://localhost:3000",
            REQUEST_ID_HEADER: "req_unhandled_123",
        },
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert response.headers[REQUEST_ID_HEADER] == "req_unhandled_123"
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert REQUEST_ID_HEADER.casefold() in response.headers[
        "access-control-expose-headers"
    ].casefold()


def test_request_id_is_allowed_and_exposed_for_browser_cors() -> None:
    client = request_id_test_client()
    preflight = client.options(
        "/ready",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": REQUEST_ID_HEADER,
        },
    )
    response = client.get(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            REQUEST_ID_HEADER: "req_browser_123",
        },
    )

    assert preflight.status_code == 200
    assert REQUEST_ID_HEADER.casefold() in preflight.headers[
        "access-control-allow-headers"
    ].casefold()
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "req_browser_123"
    assert REQUEST_ID_HEADER.casefold() in response.headers[
        "access-control-expose-headers"
    ].casefold()
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
