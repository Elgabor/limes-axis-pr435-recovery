# ADR 0010: MCP is an authenticated adapter to governed domain capabilities

- **Status:** Accepted
- **Date:** 2026-09-06
- **Owners:** @metaforismo
- **Related:** [Issue #367](https://github.com/Limes-Labs/limes-axis/issues/367), [gateway specification](../mcp-gateway.md), [threat model](../mcp-threat-model.md)

## Context

Axis has tenant-bound HTTP routes, typed domain commands, policy/approval checks,
idempotency and worker ports, but no MCP gateway. Wrapping every REST endpoint
would expose demo fallbacks and execution surfaces as if discovery conferred
authority. Some handlers still own gates inline; some action commands can signal
workflows. An agent-facing adapter needs an explicit capability boundary first.
The published MCP 2026-07-28 revision also replaces connection sessions with
per-request metadata and moves durable tasks to a separate extension.

## Decision

The future gateway lives in the control API deployment as a Streamable HTTP
adapter with an explicit catalog. It targets MCP 2026-07-28 and independently
pins the optional Tasks extension when implemented. The
[gateway specification](../mcp-gateway.md) owns protocol, scopes, layer mappings,
pagination, cache, budgets, error and version contracts; the
[threat model](../mcp-threat-model.md) owns defensive acceptance cases.

Each request has a dedicated audience-bound OAuth access token and a registered
active tenant. Explicit OAuth grants intersect Axis permissions and policy.
Discovery and invocation apply the same current authority. No anonymous demo
fallback, token passthrough, arbitrary REST/database tool or cross-tenant catalog
is admitted. Domain owners retain authorization, effect, transaction and evidence
semantics; the worker retains execution and recovery. A proposal-only command
must exist before exposing proposals; MCP input or cancellation cannot decide
an Axis approval or undo a committed effect.

## Consequences

- This slice ships a design and verification contract, not an endpoint, OAuth
  registration, permission grant or runtime flag. Current REST/SDK behavior and
  dependencies remain unchanged.
- Capabilities can be delivered independently, but stay undiscoverable until
  their transport and domain gates pass. There is no inferred feature readiness.
- Reusing existing owners can require a narrow command extraction because an
  HTTP handler's inline gates cannot be skipped by a second transport.
- MCP 2025-11-25 and earlier clients are not initially supported; compatible
  dual-era handling would require a separately reviewed contract and tests.
- Private zero-TTL results favor clear revocation behavior over caching. Shared
  quota/concurrency storage and local IdP/client conformance are enablement costs.
- Product demonstrations use an isolated authenticated deployment with synthetic
  data and normal governance. Fixtures remain useful; the existing anonymous REST
  compatibility paths need a separate migration before removal. A future OSS
  edition follows ADR 0002 and is not defined by demo mode.

## Alternatives Considered

- **Generate tools from OpenAPI:** does not encode proposal/approval boundaries,
  object visibility or safe disclosure and would include unrestricted effects.
- **Separate gateway forwarding API tokens:** adds a credential/trust hop and
  encourages token passthrough or a service identity broader than the caller.
- **New policy/workflow engine in MCP:** duplicates domain authority and recovery.
- **Implement the previous experimental task API:** conflicts with the current
  independently versioned extension and creates an avoidable migration burden.

## Verification

Run the owner suites listed in the specification, `make docs-check` and
`make verify`; record exact results and CI in the PR. Compare base/head runtime
trees and the full OpenAPI JSON for unchanged behavior and operation counts.
MCP transport/client conformance, IdP resource setup, filtered discovery,
proposal-only dispatch, durable tasks and hosted load/security evidence remain
NOT RUN until their implementation slices. Documentation is not deployment proof.

## Supersession

None.
