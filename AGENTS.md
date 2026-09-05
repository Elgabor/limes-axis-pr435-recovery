# Working on Limes Axis

Read [architecture](docs/architecture.md), [development](docs/development.md)
and [CONTRIBUTING](CONTRIBUTING.md) before changing a boundary. This is the
private commercial source of truth; the edition matrix does not authorize export.

## Locate the work

- `services/api/src/axis_api/main.py` composes HTTP routes, identity and tenant
  binding; domain modules own transitions. `persistence.py` owns SQL and
  `models.py`/`migrations/` own persisted contracts.
- `apps/web/lib/axis-api.ts` owns HTTP transport; `use-axis-query.ts` owns query
  cancellation and principal/tenant invalidation. Runtime schemas validate
  responses before components consume them.
- `services/worker` owns Temporal workflows and activities; the API owns the
  signal/outbox contracts. `packages/sdk-python` is a supported client API.
- Start with `git status --short --branch`, HEAD, remotes and worktrees. An
  `origin` remote may be another local checkout; verify the GitHub URL before
  choosing the base. Preserve unrelated and untracked work.

## Verify the change

- `make install` installs the committed locks. Each Python package has its own
  `.venv`; never borrow another checkout's editable environment.
- `make test-api PYTEST_ARGS='tests/test_data_asset_lineage.py -q'` is a targeted
  API example. The same argument works for `test-worker` and `test-sdk`.
- `make test-web WEB_TEST_ARGS='lib/axis-api.test.ts'` selects a web test file.
- `make verify` runs local component/contract gates, including schema tests.
  [Development](docs/development.md) separates browser and live-service gates.
- Keep route/schema tests on the `openapi_schema` fixture when they only inspect
  the default contract. It fetches the actual HTTP contract once and decodes a
  fresh dictionary per test. Configuration and runtime tests own their app.
- Use `make benchmark-lineage` for reproducible local lineage query counts and
  timing. Do not describe SQLite numbers as production PostgreSQL capacity.

## Invariants

Preserve authenticated tenant binding, fail-closed permission/egress gates,
secret redaction, append-only evidence, transaction ownership, advisory locks,
idempotency and outbox recovery. A small wrapper may enforce one of these.
Keep supported REST aliases, SDK surfaces, persisted IDs and historical
migrations. OpenAPI equality does not replace runtime tenant/concurrency tests.

Use fresh local ports and an explicitly isolated database for live tests.
`/health` only proves process liveness; `/ready`, route checks and browser tests
prove different things. Report PASS/FAIL and skipped or NOT RUN boundaries.
