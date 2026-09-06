# Python SDK

`limes-axis-sdk` (module `axis_sdk`) is the typed Python client for the Axis
REST API. It is the integration entry point for enterprise and SME engineers
who script against the governed control-plane surface instead of the console.

The SDK lives in [`packages/sdk-python`](../packages/sdk-python) and follows
the repo naming reserved for future extraction (`limes-axis-sdk`).

The separate `axis_sdk.connector_authoring` namespace provides the
[versioned source-authoring contract](connector-authoring.md) and an offline
reference. It does not add connector REST endpoints or register source adapters.

## Design Boundaries

- The SDK is standalone: it depends only on `httpx` and `pydantic` and never
  imports the API service. `limes-axis-api` is a dev-only dependency used to
  run the SDK test suite against the real FastAPI application in-process.
- The REST client only talks to the configured `base_url`. It performs no other
  network egress and sends no telemetry.
- Response models mirror the committed OpenAPI artifact
  ([`docs/openapi.json`](./openapi.json)) and tolerate additive fields.

## Install

The package is not published yet. Install it from the repository:

```bash
cd packages/sdk-python
uv sync
```

Or add it to another uv project as a path dependency:

```toml
[tool.uv.sources]
limes-axis-sdk = { path = "../limes-axis/packages/sdk-python" }
```

## Quickstart

```python
from axis_sdk import AxisClient

with AxisClient(
    "http://127.0.0.1:8000",
    token="<oidc-bearer-token>",          # or token_provider=lambda: fresh_token()
    tenant_id="tenant_demo_manufacturing",
) as client:
    health = client.system.health()
    inbox = client.approvals.list()
    for approval in inbox.approvals:
        print(approval.approval_id, approval.risk_level, approval.due)
```

The async variant mirrors the same surface:

```python
from axis_sdk import AsyncAxisClient

async with AsyncAxisClient("http://127.0.0.1:8000") as client:
    catalog = await client.actions.catalog()
```

## Authentication and Tenant Context

- `token` sends a static OIDC bearer token on every request.
- `token_provider` is a zero-argument callable invoked per request; use it
  to plug in a token cache or refresh flow.
- Without a token the SDK sends anonymous requests, which the API accepts
  only when `AXIS_OIDC_AUTH_REQUIRED` is disabled (local demos).
- `tenant_id` sets the default tenant context for tenant-scoped endpoints;
  every resource method also accepts an explicit `tenant_id` override.
- Every logical operation carries a generated `X-Request-Id` header that
  is reused across retry attempts, and a `limes-axis-sdk-python/<version>`
  user agent.

## Covered Surface

| Resource | Methods |
| --- | --- |
| `client.system` | `health()`, `ready()`, `deployment_readiness()` |
| `client.approvals` | `list()`, `get(approval_id)`*, `decide(approval_id, decision=..., actor_id=..., actor_scopes=..., note=...)` |
| `client.actions` | `catalog()`, `create_run(action_id, actor_id=..., payload=..., idempotency_key=...)`, `record_outcome(action_run_id, ..., idempotency_key=..., evidence_refs=[...])` |
| `client.workflows` | `console()`, `list_runs(state=..., limit=...)`, `get_run(workflow_id)`* |
| `client.audit` | `explorer()`, `query_events(event_type=..., actor_id=..., scope=..., limit=...)`, `export(export_reason=..., retention_days=..., legal_hold=...)` |
| `client.ontology` | `graph(limit=...)`, `entity(node_id)` |
| `client.agents` | `registry()` |

\* The API does not expose single-approval or single-workflow-run routes;
`get()` and `get_run()` are documented client-side filters over the list
endpoints and raise `LookupError` on a miss.

Not covered yet: the connector surface, audit legal holds and retention
deletion, model routing, notifications, manufacturing operations and
simulation replay outputs, and the browser OIDC session endpoints. Workflow
signaling is not exposed as a public route; approval decisions and action
runs signal the workflow runtime server-side.

## Idempotency

`actions.create_run` accepts the same `idempotency_key` the API enforces.
Replaying the same key with the same payload returns the persisted run with
`idempotent_replay=True`; replaying it with a different payload raises
`PolicyViolationError`. `actions.record_outcome` requires an idempotency
key and at least one evidence reference, matching the API contract.

## Error Handling

HTTP errors raise a typed hierarchy rooted at `AxisError`:

- `AxisConnectionError` — the API could not be reached.
- `MalformedResponseError` — a success response could not be decoded as
  JSON or did not match the expected response model.
- `AxisAPIError` — base for HTTP errors; carries `status_code`, `code`,
  `message`, `request_id` and the raw `detail` payload.
  - `AuthRequiredError` (`AUTH_REQUIRED`, 401)
  - `PermissionDeniedError` (`PERMISSION_DENIED`, 403)
  - `TenantScopeRequiredError` (`TENANT_SCOPE_REQUIRED`)
  - `NotFoundError` (`NOT_FOUND`, 404) and `WorkflowNotFoundError`
    (`WORKFLOW_NOT_FOUND`)
  - `ConflictError` (`CONFLICT`, 409)
  - `ValidationFailedError` (`VALIDATION_FAILED`, 422)
  - `ActionRequiresApprovalError` (`ACTION_REQUIRES_APPROVAL`)
  - `PolicyViolationError` (`POLICY_VIOLATION`)
  - `ConnectorUnavailableError` (`CONNECTOR_UNAVAILABLE`)
  - `ModelProviderBlockedError` (`MODEL_PROVIDER_BLOCKED`)
  - `ReplayNotAvailableError` (`REPLAY_NOT_AVAILABLE`)
  - `RateLimitedError` (`RATE_LIMITED`, 429; exposes `retry_after_seconds`)
  - `ServerError` (unmapped 5xx)

`request_id` is the id the SDK sent with the failing request, unless the
API error envelope reports its own `request_id`, which takes precedence.

```python
from axis_sdk import AxisClient, PermissionDeniedError

with AxisClient("http://127.0.0.1:8000", token=token) as client:
    try:
        client.approvals.decide(
            "appr_expedite_supplier_batch",
            decision="approve",
            actor_id="plant-operations-owner-role",
        )
    except PermissionDeniedError as error:
        print(error.code, error.message, error.request_id)
```

## Retries

Retries are conservative and idempotent-only:

- Only GET requests and idempotency-keyed POSTs are retried.
- Retried failures: transport errors and `502`/`503`/`504` responses.
- A `Retry-After` header on a retryable response (integer seconds or an
  HTTP-date) is honoured: the SDK waits at least that long, capped by
  `backoff_max_seconds`.
- 4xx responses are never retried.
- Backoff is exponential with full jitter (0.25s initial, 4s cap, 2 retries
  by default).

Tune or disable via `RetryConfig`:

```python
from axis_sdk import AxisClient, RetryConfig

client = AxisClient(
    "http://127.0.0.1:8000",
    retry=RetryConfig(max_retries=4, backoff_initial_seconds=0.5),
)
no_retries = AxisClient("http://127.0.0.1:8000", retry=RetryConfig(enabled=False))
```

## Versioning and Compatibility

The SDK version starts at `0.1.0`. While the SDK lives in this monorepo it
tracks the API of the same repository revision: the checked-out SDK is
guaranteed to match the OpenAPI artifact committed alongside it, and the CI
test suite runs the SDK against that exact FastAPI application. There is no
cross-revision compatibility promise before the first published release;
response models tolerate additive server fields but not removals or type
changes.

## Development

```bash
cd packages/sdk-python
uv sync
uv run ruff check .
uv run pytest
```

The tests use `httpx.ASGITransport` to run the SDK against the real API
application in-process with an in-memory SQLite persistence layer seeded
from the Alembic bootstrap payloads — no HTTP mocking. Repo-level gates:
`make lint` and `make test` (or `make test-sdk`).

A runnable example lives in
[`examples/sdk-python-quickstart`](../examples/sdk-python-quickstart).
