# Aggregate persistence boundaries

[Issue #356](https://github.com/Limes-Labs/limes-axis/issues/356) calls for one
reviewable extraction slice. The model aggregate is the first implementation;
most other SQL still lives in
[`AxisPersistenceRepository`](../services/api/src/axis_api/persistence.py).
The facade preserves its import path and all existing method signatures.

## Model aggregate ownership

[`repositories/models.py`](../services/api/src/axis_api/repositories/models.py)
owns the four model persistence records, five read operations and four write
operations for `model_endpoints` and `model_invocations`. `ModelReadPort` and
`ModelWritePort` describe these specific operations; `ModelPersistencePort`
combines them for the facade. `ModelRepository` implements their SQL with the
caller-supplied SQLAlchemy session. There is no generic repository base or query
framework.

| Surface | Operations | Owner |
| --- | --- | --- |
| Endpoint reads | Get by tenant/endpoint; list by tenant/status/limit | `ModelRepository` |
| Endpoint writes | Create; update status, audit link and notes | `ModelRepository` |
| Invocation reads | Get by tenant/ID or tenant/idempotency; keyset list | `ModelRepository` |
| Invocation writes | Create requested record; record result | `ModelRepository` |
| Existing imports/calls | Four record exports and nine method delegates | `AxisPersistenceRepository` module/class |
| Missing-record error | One shared exception, re-exported at its original path | [`repositories/errors.py`](../services/api/src/axis_api/repositories/errors.py) |
| Authorization and routing | Permissions, policies, tenant binding and provider selection | [`model_endpoints.py`](../services/api/src/axis_api/model_endpoints.py), [`model_invocations.py`](../services/api/src/axis_api/model_invocations.py) |

The facade constructs one model repository with the same session it receives.
Reads retain tenant filters, endpoint sorting, limits, and newest-first invocation
continuation by `(created_at, id)`. Writes retain the existing flush behavior,
uniqueness constraints, decimal precision, error types and JSON fields. This is
an ownership change without a SQL, schema, migration or public API change.

## Transaction ownership

A repository instance belongs to one caller-supplied session/unit of work.
The aggregate never opens, replaces, commits, rolls back or closes that session.
Its writes flush; the caller controls durability and savepoints.

- Request/session orchestration still owns commit, rollback and close through
  [`session_scope`](../services/api/src/axis_api/db.py) and the API dependency.
- Model, audit and usage writes use that same session. Moving model SQL does not
  introduce a second transaction or separate commit of linked audit evidence.
- Model invocation orchestration retains the commit of the requested record
  before awaiting an external provider. It retains idempotency collision recovery
  through a savepoint and the existing behavior for a pending invocation replay.
- Domain code still decides whether a denial must persist audit before an HTTP
  error. The repository does not decide permissions or invoke providers.
- PostgreSQL constraints remain the source of uniqueness enforcement; the facade
  does not turn them into an in-memory preflight check.

## Measured slice and remaining owners

Measured against `afe53b13da64286141208b26b607ae1c0e379034`:

| Measure | Before | After |
| --- | ---: | ---: |
| `persistence.py` physical lines | 6,357 | 6,201 |
| `AxisPersistenceRepository` AST line span | 5,111 | 5,008 |
| Methods declared in the facade | 237 | 237 |
| Model SQL method bodies in the facade | 9 | 0 |
| Model record definitions in the facade module | 4 | 0 |

Nine compatibility delegates deliberately remain. The new aggregate module has
303 lines including records, ports and SQL. All nine SQL methods and four record
definitions are AST-identical to their previous definitions. Reduction of the
facade's public method count is not a goal of this compatible slice.

The remaining aggregate groups still owned by `persistence.py` are:

| Aggregate group | Transaction boundary to preserve in a later slice |
| --- | --- |
| Audit/legal holds and notification acknowledgements | Append/hold evidence and acknowledgement locking |
| Identity/browser sessions and actors | Admission/refresh claims, revocation and tenant binding |
| Approvals and decision outbox | Decision evidence, durable dispatch intent and claim ownership |
| Actions and workflows | Idempotent execution state, approvals, outcomes and timeline |
| Connector configuration/manifests | Revision/lifecycle uniqueness and transition evidence |
| Source bindings/ingestion/extraction/exports | Activation, claims, checkpoint/batch identity and audit linkage |
| Credentials, egress and live sync | Lease/claim ownership and governed source access evidence |
| Ontology proposals/promotions/policies | Policy revisions, promotion identity and lineage ordering |
| Data assets/resources/contracts/stewardship | Asset-scoped observation and revision locks |
| Tenants, quotas and usage | Tenant bootstrap/lifecycle, metering idempotency and projection |
| Platform policies | Scoped active revision and replacement ordering |
| Agents | Idempotent run state, model/action links and append-only steps |
| Reference/manufacturing/simulation data | Reference identity and scenario idempotency |

Extract one group at a time under
[the code-health parent](https://github.com/Limes-Labs/limes-axis/issues/354),
keeping caller contracts and transaction authority visible. Do not move domain
policy into a base repository or hide provider/workflow awaits inside SQL code.

## Contract verification

[`test_model_persistence_contract.py`](../services/api/tests/test_model_persistence_contract.py)
runs the same eight contracts against both the facade and aggregate (16 cases).
The default API suite uses a temporary SQLite file, allowing independent writer
and observer sessions. It tests tenant scoping, filtering and ordering, decimal
and JSON round trips, timestamp-tie keyset continuation, result rollback,
tenant-scoped idempotency/savepoint recovery, and atomic model/audit visibility,
commit and rollback.

For PostgreSQL, use an isolated test server whose user can create databases:

```sh
export AXIS_MODEL_CONTRACT_POSTGRES_DSN='postgresql+psycopg://axis:axis@localhost:5432/axis'
make test-model-persistence-postgres
```

The target refuses a missing DSN and explicitly selects PostgreSQL. The fixture
rejects other backends, creates a random `axis_model_contract_<uuid>` database,
applies the real Alembic chain, runs the contract suite, and drops only that new
database in cleanup. It overrides Alembic's environment DSN only while migrating
that database. It does not migrate or delete the DSN's original database.

[The live-API CI job](../.github/workflows/ci.yml) runs this target against its
isolated PostgreSQL 16 service before starting the API. Existing endpoint,
invocation, tenant, telemetry and persistence tests remain part of `make verify`;
OpenAPI must remain identical. Exact local and CI results belong in the PR.
Hosted providers, production database load and other external-service integration
lanes require separate evidence.
