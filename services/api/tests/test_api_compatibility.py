from dataclasses import replace
from datetime import datetime
from email.utils import parsedate_to_datetime

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import axis_api.main as main_module
from axis_api.api_compatibility import DEPRECATED_AT, SUNSET_AT, LegacyRouteDeprecationMiddleware
from axis_api.config import Settings
from axis_api.main import create_app
from axis_api.telemetry import configure_api_telemetry


def _points(reader):
    data = reader.get_metrics_data()
    if data is None:
        return []
    return [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "axis.api.deprecated_requests"
        for point in metric.data.data_points
    ]


@pytest.fixture(scope="module")
def observed_app():
    settings = Settings(postgres_dsn="sqlite+pysqlite://", otel_enabled=True)
    reader = InMemoryMetricReader()
    runtime = configure_api_telemetry(
        settings,
        span_exporter=InMemorySpanExporter(),
        metric_reader=reader,
    )
    app = create_app(settings, telemetry=runtime)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client, reader


def _assert_headers(response):
    timestamp = int(response.headers["Deprecation"][1:])
    assert datetime.fromtimestamp(timestamp, DEPRECATED_AT.tzinfo) == DEPRECATED_AT
    assert parsedate_to_datetime(response.headers["Sunset"]) == SUNSET_AT
    assert SUNSET_AT > DEPRECATED_AT
    assert 'rel="deprecation"' in response.headers["Link"]


def test_all_legacy_operations_have_an_equivalent_canonical_contract(openapi_schema):
    def without_schema_titles(value):
        if isinstance(value, dict):
            return {
                key: without_schema_titles(item)
                for key, item in value.items()
                if not (key == "title" and isinstance(item, str))
            }
        if isinstance(value, list):
            return [without_schema_titles(item) for item in value]
        return value

    paths = openapi_schema["paths"]
    legacy = [
        (method, path)
        for path, operations in paths.items()
        if path.startswith("/demo/manufacturing/")
        for method in operations
    ]
    assert len(legacy) == 103
    for method, path in legacy:
        canonical = (
            "/demo/bootstrap"
            if path == "/demo/manufacturing/bootstrap"
            else path.replace("/demo/manufacturing/", "/operations/", 1)
        )
        old, new = paths[path][method], paths[canonical][method]
        assert old["deprecated"] and not new.get("deprecated")
        for field in ("parameters", "requestBody", "responses", "security"):
            # FastAPI embeds the operation path in generated schema titles.
            assert without_schema_titles(old.get(field)) == without_schema_titles(new.get(field))


@pytest.mark.parametrize(
    "method,path,status",
    [
        ("GET", "/demo/manufacturing/overview", 422),
        ("POST", "/demo/manufacturing/bootstrap", 422),
        ("GET", "/demo/manufacturing/agents/private-agent/runs/private-run", 404),
    ],
)
def test_error_responses_are_counted_once_with_headers(observed_app, method, path, status):
    _, client, reader = observed_app
    before = sum(point.value for point in _points(reader))
    response = client.request(method, path, headers={"Origin": "http://localhost:3000"})
    assert response.status_code == status
    _assert_headers(response)
    assert "Deprecation" in response.headers["Access-Control-Expose-Headers"]
    assert response.headers["X-Request-Id"]
    assert sum(point.value for point in _points(reader)) == before + 1


@pytest.mark.parametrize(
    "method,path,status",
    [
        ("GET", "/operations/overview", 422),
        ("POST", "/demo/bootstrap", 422),
        ("GET", "/health", 200),
    ],
)
def test_other_requests_are_not_reported_as_legacy(observed_app, method, path, status):
    _, client, reader = observed_app
    before = sum(point.value for point in _points(reader))
    response = client.request(method, path)
    assert response.status_code == status
    assert "Deprecation" not in response.headers
    assert "Sunset" not in response.headers
    assert sum(point.value for point in _points(reader)) == before


@pytest.mark.parametrize(
    "method,path,status",
    [
        ("GET", "/demo/manufacturing/unknown-private-resource", 404),
        ("DELETE", "/demo/manufacturing/overview", 405),
        ("PRIVATE-METHOD", "/demo/manufacturing/unknown-private-resource", 404),
    ],
)
def test_unmatched_namespace_requests_use_fixed_labels(observed_app, method, path, status):
    _, client, reader = observed_app
    before = sum(point.value for point in _points(reader))
    response = client.request(method, path)
    assert response.status_code == status
    _assert_headers(response)
    points = _points(reader)
    assert sum(point.value for point in points) == before + 1
    assert "private" not in str([point.attributes for point in points]).lower()
    assert any(point.attributes["http.route"] == "unmatched" for point in points)
    if method == "PRIVATE-METHOD":
        assert any(point.attributes["http.request.method"] == "_OTHER" for point in points)


def test_labels_use_templates_and_exclude_request_data(observed_app):
    _, client, reader = observed_app
    for value in ("private-one", "private-two"):
        response = client.get(
            f"/demo/manufacturing/agents/{value}/runs/{value}?secret={value}",
            headers={"Cookie": f"private={value}"},
        )
        assert response.status_code == 404
    points = _points(reader)
    assert all(
        set(point.attributes)
        == {
            "http.route",
            "http.request.method",
            "http.response.status_code",
        }
        for point in points
    )
    assert "private" not in str([point.attributes for point in points])
    assert "secret" not in str([point.attributes for point in points])
    assert any(
        point.attributes["http.route"] == ("/demo/manufacturing/agents/{agent_id}/runs/{run_id}")
        for point in points
    )


def test_path_converter_keeps_one_template_for_nested_resource_ids(observed_app):
    _, client, reader = observed_app
    response = client.get("/demo/manufacturing/ontology/entities/private/segment/value")
    assert response.status_code == 422
    _assert_headers(response)
    points = _points(reader)
    assert any(
        point.attributes["http.route"] == ("/demo/manufacturing/ontology/entities/{node_id}")
        for point in points
    )
    assert "private" not in str([point.attributes for point in points])


@pytest.mark.asyncio
@pytest.mark.parametrize("root_path", ["", "/proxy"])
async def test_stream_failure_does_not_double_count_or_replace_existing_links(
    observed_app, root_path
):
    app, _, reader = observed_app
    before = sum(point.value for point in _points(reader))
    messages = []

    async def inner(scope, receive, send):
        scope["route"] = APIRoute("/demo/manufacturing/stream", lambda: None, methods=["GET"])
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"link", b'</next>; rel="next"')],
            }
        )
        await send({"type": "http.response.body", "body": b"part", "more_body": True})
        raise RuntimeError("stream interrupted")

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    middleware = LegacyRouteDeprecationMiddleware(inner, telemetry=app.state.telemetry)
    with pytest.raises(RuntimeError, match="stream interrupted"):
        await middleware(
            {
                "type": "http",
                "method": "GET",
                "root_path": root_path,
                "path": root_path + "/demo/manufacturing/stream",
            },
            receive,
            send,
        )
    headers = dict(messages[0]["headers"])
    assert headers[b"link"].startswith(b'</next>; rel="next", ')
    assert b"deprecation" in headers
    assert messages[1]["body"] == b"part"
    assert sum(point.value for point in _points(reader)) == before + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
async def test_non_http_scopes_pass_through_unchanged(observed_app, scope_type):
    app, _, reader = observed_app
    before = sum(point.value for point in _points(reader))
    scope = {"type": scope_type, "path": "/demo/manufacturing/anything"}
    calls = []

    async def inner(actual_scope, receive, send):
        assert actual_scope is scope
        calls.append(scope_type)

    middleware = LegacyRouteDeprecationMiddleware(inner, telemetry=app.state.telemetry)
    await middleware(scope, None, None)
    assert calls == [scope_type]
    assert scope == {"type": scope_type, "path": "/demo/manufacturing/anything"}
    assert sum(point.value for point in _points(reader)) == before


def test_unhandled_failure_retains_cors_correlation_and_deprecation(observed_app, monkeypatch):
    _, client, reader = observed_app

    def fail(*args, **kwargs):
        raise RuntimeError("private provider failure")

    monkeypatch.setattr(main_module, "get_persisted_manufacturing_overview", fail)
    before = sum(point.value for point in _points(reader))
    response = client.get(
        "/demo/manufacturing/overview?tenant_id=tenant_test",
        headers={"Origin": "http://localhost:3000", "X-Request-Id": "req_compat_failure"},
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    _assert_headers(response)
    assert response.headers["X-Request-Id"] == "req_compat_failure"
    assert "Sunset" in response.headers["Access-Control-Expose-Headers"]
    assert sum(point.value for point in _points(reader)) == before + 1
    assert any(point.attributes["http.response.status_code"] == 500 for point in _points(reader))


@pytest.mark.parametrize(
    "overrides,method,path,expected",
    [
        ({"oidc_auth_required": True}, "GET", "/demo/manufacturing/overview", 401),
        (
            {
                "api_rate_limit_enabled": True,
                "api_rate_limit_requests": 1,
                "api_rate_limit_paths": ["/demo/manufacturing/overview"],
            },
            "GET",
            "/demo/manufacturing/overview",
            429,
        ),
        ({}, "POST", "/demo/manufacturing/bootstrap", 403),
        ({}, "POST", "/demo/bootstrap", 403),
        ({"oidc_auth_required": True}, "POST", "/demo/bootstrap", 401),
    ],
)
def test_denials_are_preserved_and_measured(overrides, method, path, expected):
    settings = Settings(postgres_dsn="sqlite+pysqlite://", otel_enabled=True, **overrides)
    reader = InMemoryMetricReader()
    runtime = configure_api_telemetry(
        settings,
        span_exporter=InMemorySpanExporter(),
        metric_reader=reader,
    )
    with TestClient(create_app(settings, telemetry=runtime)) as client:
        if expected == 429:
            client.get(path)
        response = client.request(
            method,
            path,
            json={
                "tenant_id": "tenant_test",
                "requested_by": "actor",
                "actor_scopes": [],
            },
        )
        assert response.status_code == expected
        legacy = path.startswith("/demo/manufacturing/")
        if legacy:
            _assert_headers(response)
        else:
            assert "Deprecation" not in response.headers
        assert (
            sum(
                point.value
                for point in _points(reader)
                if point.attributes["http.response.status_code"] == expected
            )
            == int(legacy)
        )


@pytest.mark.parametrize("metrics_enabled", [False, True])
def test_disabled_or_broken_metrics_cannot_break_legacy_responses(metrics_enabled):
    settings = Settings(postgres_dsn="sqlite+pysqlite://", otel_enabled=metrics_enabled)
    runtime = configure_api_telemetry(
        settings,
        span_exporter=InMemorySpanExporter(),
        metric_reader=InMemoryMetricReader(),
    )

    class BrokenCounter:
        def add(self, *args, **kwargs):
            raise RuntimeError("collector failure")

    runtime = replace(runtime, deprecated_request_counter=BrokenCounter())
    with TestClient(create_app(settings, telemetry=runtime)) as client:
        response = client.get("/demo/manufacturing/overview")
        assert response.status_code == 422
        _assert_headers(response)
