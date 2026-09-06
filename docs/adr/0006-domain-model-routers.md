# ADR 0006: Domain-owned model HTTP routers

- **Status:** Accepted
- **Date:** 2026-09-06
- **Owners:** @metaforismo
- **Related:** [Issue #355](https://github.com/Limes-Labs/limes-axis/issues/355), [route extraction](../api-route-extraction.md)

## Context

`create_app` contains most HTTP handlers and is difficult to review as a
composition root. Moving every domain at once would enlarge the regression
surface across unrelated authorization and transaction boundaries.

## Decision

Move the complete model HTTP domain into `axis_api.routes.models` as the first
reviewable slice. The builder returns platform and operations routers;
composition mounts both at the previous positions and retains the operations
alias registration. A frozen typed bundle passes the existing repository,
principal, runtime, tenant/actor binding, authorization and policy-error helpers.
Settings and telemetry remain application-local construction inputs.

A generated inventory records every OpenAPI operation, domain label and source
owner. API tests keep it current. The extraction guide records measured size
changes, shared owners, parity evidence and the remaining domains.

## Consequences

- Model handlers have one domain owner without importing the composition root.
- Existing dependency function identity and overrides remain valid.
- Paths, schemas, authorization, tenant binding, audit and transaction behavior
  remain unchanged; there are no new runtime dependencies or settings.
- Shared security helpers remain in `main` until a separate boundary change is
  justified. Most domains still need extraction in subsequent reviewable slices.

## Alternatives Considered

- **Move every route now:** spreads one review across many independent domains.
- **Import `main` from routers:** introduces circular coupling and hidden owners.
- **Create a new dependency registry:** adds framework work without a contract need.

## Verification

Before/after OpenAPI exports must match byte-for-byte, and the committed schema
must pass `make openapi-check`. Existing endpoint, invocation, tenant and telemetry
tests cover the move. A regression test proves application settings isolation,
canonical dependency overrides, provider-call count and denial audit persistence.
`make verify` and CI outcomes are recorded in the PR; hosted provider or deployment
validation is separate from local component evidence.

## Supersession

None.
