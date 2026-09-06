# ADR 0005: Versioned connector authoring contract in the Python SDK

- **Status:** Accepted
- **Date:** 2026-09-06
- **Owners:** @metaforismo
- **Related:** [Issue #334](https://github.com/Limes-Labs/limes-axis/issues/334), [capability matrix](../connector-capabilities.md)

## Context

The post-PR-318 audit found two wired live sources with distinct runtime ports
and no common versioned authoring surface. Future adapters need reusable typed
requests and checkpoint semantics without duplicating the existing source trust
path or creating another package/deployment dependency.

## Decision

`axis_sdk.connector_authoring` owns protocol 1.0 in the existing Python SDK.
It contains dependency-light typed ports and validation, explicit version and
capability negotiation, and an offline in-memory reference connector. Its
protocol version is independent of REST/package and persisted manifest versions.
The [author guide](../connector-authoring.md) owns the version/deprecation policy,
host mapping and author responsibilities.

The API and worker retain identity, authorization, credentials, egress,
activation, claims, persistence, retries and append-only audit ownership. The
SDK passes identifiers and candidate checkpoints; it does not decide those
gates or create source registrations. Existing adapters are not migrated by this
change. Future adoption must map the contract into an existing governed path
with boundary tests before enabling source I/O.

## Consequences

- Authors can test discovery, bounded reads, checkpoint binding and health
  without installing or importing the API service at runtime.
- No new runtime dependency, loader, endpoint or deployment setting is needed.
- Optional writeback is a typed extension only; there is no enabled executor.
- Protocol removals require the documented notice/migration window. Host
  serializer compatibility must be explicit; models do not silently downgrade.
- The offline reference provides contract evidence, not service conformance,
  sandboxing, production adapter adoption or hosted reliability evidence.

## Alternatives Considered

- **Separate connector package now:** adds release, locking and deployment
  overhead before a production consumer needs independent distribution.
- **Put the contract in the API service:** forces partner authors to depend on
  persistence, drivers and server composition just to validate a connector.
- **Automatically register SDK implementations:** creates an execution path
  outside the current persisted lifecycle and approval boundaries.

## Verification

`make test-sdk` exercises protocol negotiation, bounded reference reads,
tenant/source/protocol checkpoint refusal and metadata-only evidence.
`make verify` checks the existing component and REST contracts. Exact outcomes
belong in the PR. Live sources, writeback, distributed claims, partner
interoperability and production host adoption remain NOT RUN.

## Supersession

None.
