# Configuration ownership and validation

The API's [generated environment reference](configuration-reference.md) lists
all 182 settings, their Python names, defaults and field constraints. Generate
it with `make settings-reference`; `make settings-reference-check` detects drift.
The API test suite checks the committed reference, so CI also enforces freshness.
Generation reads declarations only and redacts credential-bearing defaults.

## Ownership

[`axis_api.config.Settings`](../services/api/src/axis_api/config.py) remains the
single flat environment facade. Capability models in
[`axis_api.settings`](../services/api/src/axis_api/settings) declare fields and
local validators; they do not read environment variables or instantiate clients.

| Capability | Responsibility | Fields |
| --- | --- | --- |
| Identity | OIDC, sessions, authenticated tenant admission and cache | 32 |
| Persistence | Postgres, Redis, TypeDB, ontology runtime and object storage | 23 |
| Models | Model invocation, egress opt-in and agent call budgets | 7 |
| Connectors | Credential leases, source adapters, discovery and ingestion | 44 |
| Policy | Rate limits, deployment policy declarations and replay gates | 15 |
| Observability | Telemetry, metering, audit signing and readiness probes | 17 |
| Runtime | Public URLs, CORS, Temporal/outbox, scheduled jobs, DR and support | 44 |

Add a field to its owning model with an explicit environment alias. Keep
cross-capability startup checks in `validate_runtime_configuration`; keep
capability-local construction validators with their fields. Runtime code keeps
using the existing flat attributes, such as `settings.oidc_auth_required`.
Do not create independent environment loaders for the capability models.

## Production combinations

`create_app` validates the profile before constructing FastAPI or initializing
runtime dependencies. `AXIS_ENV=prod` and `production` are case-insensitive and
ignore surrounding whitespace. Existing requirements remain: OIDC is required,
tenant admission is `registered_only`, rate limiting covers `*` using Redis and
fails closed, and enabled usage metering fails closed.

The following inconsistent production profiles now fail startup with environment
variable names in the error, without printing configured values:

- Rate-limit requests or window length are zero or negative. Both must be positive.
- Source ingestion dispatch is enabled but its retry maximum is below its base delay.
- Source ingestion dispatch and extraction are enabled but the claim timeout is
  less than or equal to the extraction time budget. The timeout must be larger.

Disabled ingestion capabilities do not trigger the corresponding checks.
Development settings retain their previous behavior. The claim check is a
minimum consistency check for one extraction, not a guarantee that an entire
claimed batch finishes before expiry: operators must allow additional time for
batch processing, storage writes and runtime overhead. Claim fencing remains
authoritative. Configure the worker separately; this API validation does not
validate a remote worker's environment or prove deployment readiness.

The existing approval outbox retry-window and Temporal claim-timeout validators
still apply at settings construction in every environment. All field bounds,
defaults, environment names and deployment manifests remain unchanged.

## Compatibility evidence

Before extraction, `config.py` contained 182 field definitions in 863 lines.
After extraction, the 98-line facade owns no field definitions; each of the same
182 fields belongs to exactly one of seven models. No new setting is introduced.
The baseline is commit `0f0ef5f`.

[`test_settings.py`](../services/api/tests/test_settings.py) uses a fixture
captured before extraction to verify every default and serialized alias, all
182 environment names with non-default values, both constructor forms, JSON
lists and constructor/environment/dotenv precedence. Existing runtime tests
exercise authenticated tenancy, rate limiting, audit, egress and deployment
readiness through the unchanged facade. OpenAPI comparison verifies the public
HTTP contract separately.

Run the focused checks with:

```sh
make test-api PYTEST_ARGS='tests/test_settings.py tests/test_approval_outbox_config.py tests/test_runtime_readiness.py tests/test_rate_limit.py tests/test_deployment_readiness.py -q'
make settings-reference-check openapi-check docs-check
```
