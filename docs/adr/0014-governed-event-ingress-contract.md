# ADR 0014: Governed event ingress in the authoring SDK

- **Status:** Accepted
- **Date:** 2026-09-07
- **Owners:** @metaforismo
- **Related:** [Issue #340](https://github.com/Limes-Labs/limes-axis/issues/340), [event contract](../connector-events.md)

## Context

The authoring SDK has read/checkpoint ports but no event envelope or replay
semantics. Webhooks, Kafka and industrial telemetry need one host acceptance
boundary without introducing another identity, credential or retry authority.
An SDK validator cannot by itself acknowledge durable ingestion.

## Decision

Add the explicit `event_ingress` capability at opt-in protocol 1.1 with immutable
candidate bytes, scoped event/content identity, host ledger observations and
pure ordering/duplicate decisions. Keep 1.0 as the default read protocol.
A synthetic signed webhook reference requires a host admission callback and
validates pinned resource/schema/partition before producing a candidate.

The existing API and worker retain all production authority. Adoption must extend
their resource bindings and fenced ingestion transaction: receipt, payload
reference, outbox intent, audit and watermark commit before transport success.
Retain complete deduplication history for an accepting bounded source generation;
unknown history refuses replay. Existing execution owners handle downstream
retry/dead-letter, with no silent ordered-event skip. Kafka/MQTT mappings are
validated as design vectors before their adapters are built.

## Consequences

- Authors can exercise authentication, limits, replay and ordering offline with
  no broker dependency or production route changes.
- Legacy hosts refuse the new capability until explicitly adopting 1.1.
- Stable resource-wide event IDs detect conflicting replays across attempts,
  partitions and schemas; timestamp authentication and event age stay separate.
- A production host still needs durable ledger migrations, fencing, resource
  activation, distributed budgets and transport-specific acknowledgement tests.
- The reference signature profile is Axis-specific and covers synthetic asset
  updates only. It is not a provider or industrial-control adapter.

## Alternatives Considered

- **Build separate acceptance pipelines per transport:** duplicates transaction,
  authorization and retry ownership and makes replay behavior inconsistent.
- **Acknowledge when SDK validation succeeds:** loses accepted work on crashes
  before durable commit and cannot prevent concurrent duplicates.
- **Assume transport exactly-once covers database effects:** cannot coordinate
  an independent Axis transaction or manual business replay.
- **Include event ingress in default 1.0 negotiation:** claims unsupported
  serializers/semantics for existing read hosts.

## Verification

SDK tests cover scoped signatures, clock/size/schema refusal, required host
admission, rate persistence, immutable canonical candidates, duplicate/conflict,
unknown history, gaps/rewinds and per-partition design vectors. The offline example
is executable and tested. Full local checks and exact-head CI are recorded in
the PR. Live webhook/broker behavior, distributed durability and production
adoption remain NOT RUN; no runtime capability is marked enabled.

## Supersession

None. This extends ADR 0005 without retiring protocol 1.0.
