import json

import pytest


@pytest.fixture(scope="session")
def _openapi_json() -> str:
    from fastapi.testclient import TestClient

    from axis_api.main import create_app

    # Only the default contract is shared. Runtime/configuration tests still
    # construct their own applications and never receive this client.
    client = TestClient(create_app())
    try:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        return response.text
    finally:
        client.close()


@pytest.fixture
def openapi_schema(_openapi_json: str) -> dict:
    # Decode per test to preserve the isolation of the former HTTP responses.
    return json.loads(_openapi_json)
