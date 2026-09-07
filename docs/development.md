# Development and verification

Start with the [architecture map](architecture.md). Use Python 3.12 and Node 24
for CI parity, with pnpm 10.28.0 and uv. The declared Python support is
3.12–3.13; Node must be at least 22. `make install` uses frozen/locked dependency
installation and fails if manifests disagree with their locks.

## Fast feedback

Run from the repository root:

```sh
make install
make test-api PYTEST_ARGS='tests/test_data_asset_lineage.py -q'
make test-api PYTEST_ARGS='-k openapi -q'
make test-worker PYTEST_ARGS='tests/test_approval_workflow.py -q'
make test-sdk PYTEST_ARGS='tests/test_config.py -q'
make test-web WEB_TEST_ARGS='lib/axis-api.test.ts'
make lint typecheck
make openapi-check docs-check
make settings-reference-check
```

Python arguments are relative to the selected package. Use selectors on a
component target, not `make test`, which forwards them to every Python suite.
For a failure, add `-x -vv --tb=short`; add `--durations=15` to identify slow
tests. API warnings are errors. TypeScript checks unused locals and parameters.
The [unused-surface audit](code-health-unused-surface.md) records consumer evidence
and compatibility decisions; the [API policy](api-compatibility.md) defines the
telemetry and notice required before removing legacy routes.

API settings are organized by [capability](configuration.md) behind the stable
flat environment facade. After changing a field, run `make settings-reference`
and commit the generated reference; API tests reject stale documentation.

After moving or changing an HTTP handler, run `make route-inventory` and commit
the generated [ownership map](api-route-inventory.md). API tests reject a stale
inventory; `make route-inventory-check` runs that check directly. Follow the
[domain extraction boundaries](api-route-extraction.md) and run
`make openapi-check` for public contract parity.

`make test` includes API, worker, SDK, web and JSON schemas. `make verify`
also runs lint, typecheck, web build, OpenAPI parity, documentation, demo,
security, deployment, Helm render and container-package contracts. These are
local CI component gates; they do not build/scan container images, execute
cluster rehearsals or start external services. Helm is required for render checks.

For the web CI build and its API-unavailable browser lane:

```sh
make verify NEXT_PUBLIC_AXIS_API_BASE_URL=http://127.0.0.1:65534
pnpm --filter @limes-axis/web exec playwright install chromium
make test-e2e-smoke AXIS_E2E_PORT=13100
```

The smoke suite runs Chromium at desktop, mobile and tablet sizes. To rebuild
and run it directly: `pnpm --filter @limes-axis/web test:e2e`. A build embeds the
API URL; changing the environment only when starting Next does not retarget it.

The model persistence contract runs through both the existing facade and the
aggregate implementation in the default API suite. For its real PostgreSQL lane,
set `AXIS_MODEL_CONTRACT_POSTGRES_DSN` to an isolated test server with `CREATEDB`
and run `make test-model-persistence-postgres`. It creates/migrates a temporary
database and cleans up only that database. The live-API CI job runs this lane;
see [aggregate verification](persistence-aggregates.md).

The [OSS candidate contract](oss-export.md) documents the offline file allowlist,
manifest checks and separate release review. Its synthetic repository tests run
in the API suite; no publication or production export is part of `make verify`.

The [layer ownership contract](layered-architecture.md) is checked by
`make architecture-check`, also included in `make docs-check` and CI. Update
`docs/architecture-layers.json` when service/issue ownership or public ports change,
then run `python3 scripts/check_architecture_layers.py --write` to regenerate
its Markdown. The checker never refreshes the legacy import budget;
new vertical dependencies need redesign, and removed edges need budget removal.

## Runtime and worktrees

Create a worktree from the intended Git revision and run `make install` there.
Node modules, Python editable environments, `.next`, `.axis` and browser results
belong to that checkout. OpenAPI checks use unique temporary files and remove
them on exit, so checks from separate worktrees cannot overwrite each other.

Copy `.env.example` to `.env` only if no local file exists. The `demo-api`,
`demo-db-upgrade` and `worker` Make targets load the root `.env` through
the installed python-dotenv CLI (which preserves JSON arrays);
Use an absolute path for `AXIS_ENV_FILE` to select another file (including paths
with spaces); the commands run inside their Python package. A missing file fails before startup.
Shell environment takes precedence. Unit
verification does not load that root file. Direct package commands still follow
Pydantic's package-local `.env` convention.

Use an unused API/web port pair and set the corresponding public URLs and exact
CORS origins in that worktree's environment. For example, with a dedicated
Postgres database selected by `AXIS_POSTGRES_DSN`:

```sh
make demo-db-upgrade
make demo-api AXIS_API_PORT=18000
# Another terminal, same worktree:
make demo-web AXIS_API_PORT=18000 AXIS_WEB_PORT=13000
```

For that example, set `AXIS_API_BASE_URL=http://127.0.0.1:18000`,
`AXIS_PUBLIC_BASE_URL=http://127.0.0.1:13000` and include
`http://127.0.0.1:13000` plus the chosen browser port in `AXIS_CORS_ORIGINS`.
SSO additionally requires matching IdP callbacks; the existing `demo-api-sso`
shortcut intentionally retains the documented 8000/3000 Keycloak profile.

The default Compose stack binds fixed host ports and is **not** isolated merely
by placing it in another worktree. `COMPOSE_PROJECT_NAME` separates container
and volume names, but does not solve host-port collisions. Use dedicated
databases and an explicit Compose port override when running multiple stacks.
Port 8001 is already TypeDB's HTTP port in the default stack: choose another
`AXIS_SOURCE_API_PORT` for a source-connector API lane. Do not stop someone
else's stack, migrate a shared database or delete volumes to free a port.

Postgres migrations use JSONB and cannot be rehearsed on SQLite. API unit tests
use fresh in-memory databases; this does not prove PostgreSQL locking or recovery.

## Runtime debugging and end-to-end gates

Keep API output in its terminal, or redirect it to `.axis/api.log` after
`mkdir -p .axis`. `/health` verifies process liveness; `/ready` checks configured
dependencies. Use `/openapi.json` for the actual route contract. API errors and
the console's operator error view retain `X-Request-Id` for correlation; never
copy credentials, raw source rows or provider payloads into logs.

```sh
make demo-check-live AXIS_API_PORT=18000 AXIS_WEB_PORT=13000
make test-integration
AXIS_E2E_API_BASE_URL=http://127.0.0.1:18000 AXIS_E2E_PORT=13100 \
  pnpm --filter @limes-axis/web test:e2e:live
```

Integration tests require the configured Postgres/TypeDB/Temporal/object-store
services and explicit `AXIS_RUN_INTEGRATION=1` (set by the Make target). The live
browser command builds for the chosen API, runs read-only lanes, then serializes
state-mutating tests in Chromium, as CI does. Bootstrap and source-ingestion
lanes also require the fixtures and gated runtime described in
[demo readiness](demo-readiness.md) and [connectors](platform-connectors.md).
`make test-e2e-connectors-source AXIS_SOURCE_API_PORT=18001` targets an already
configured dedicated source API; it does not start one or grant egress.

Playwright refuses to reuse another server and retains traces/screenshots for
failures even when local retries are disabled. Inspect `apps/web/test-results/`:

```sh
pnpm --filter @limes-axis/web exec playwright show-trace test-results/<case>/trace.zip
```

Stop owned foreground processes with Ctrl-C. Run `make dev-stack-down` only for
the stack/project you started; it retains volumes. Live tests use namespaced
records and can leave append-only evidence, so use a disposable database.

## Performance measurement

The [workload and baseline contract](performance-baseline.md) defines SME and
enterprise fixture shapes, bounded load/soak runs, SQL/resource measurements,
Python stack profiles and a comparison policy. Run `make benchmark-performance`
with `BENCHMARK_ARGS='run --profile sme-single-node --output /tmp/axis-baseline'`;
use three trials for regression comparisons. Local ASGI/SQLite results remain
separate from deployment capacity and browser rendering.

```sh
make benchmark-lineage
make benchmark-lineage BENCHMARK_ARGS='--proposals 1 --repeat 25'
make benchmark-lineage BENCHMARK_ARGS='--proposals 200 --promotions 55 --repeat 25'
```

This creates an ephemeral SQLite database, seeds deterministic timestamps and
metadata-only records, warms up three reads, then reports statement counts and
median/min/max latency. Each sample opens a fresh ORM session. Imports, seeding
and warmup are outside timing. Run without concurrent suites/builds; use query
counts as the stable regression signal, not a wall-clock assertion in CI.

The [connector workspace measurement](connector-workspace.md#measured-evidence-and-reproduction)
uses an isolated API fixture and a real browser to capture the initial request
waterfall and response bytes. Its HTTP measurements are separate from database
capacity and readiness checks.
