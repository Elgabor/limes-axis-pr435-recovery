# limes-axis-sdk

Typed Python SDK for the Limes Axis REST API (module `axis_sdk`).

- Sync (`AxisClient`) and async (`AsyncAxisClient`) clients over httpx.
- Pydantic response models mirroring the committed OpenAPI artifact.
- Typed exceptions for the standard Axis error envelope.
- Conservative, idempotent-only retries with exponential backoff and jitter.
- No egress beyond the configured `base_url`; no telemetry.
- Versioned source authoring contracts in `axis_sdk.connector_authoring`, with
  an offline reference and no automatic source registration.

See [`docs/sdk-python.md`](../../docs/sdk-python.md) for the full guide and
[`examples/sdk-python-quickstart`](../../examples/sdk-python-quickstart) for a
runnable example.

See [`docs/connector-authoring.md`](../../docs/connector-authoring.md) for source
ports, host responsibilities, checkpoint handling and protocol compatibility.

## Development

```bash
uv sync
uv run ruff check .
uv run pytest
```

The test suite runs the SDK end-to-end against the real FastAPI application
from `services/api` in-process via `httpx.ASGITransport`; `limes-axis-api` is
a dev-only dependency.
