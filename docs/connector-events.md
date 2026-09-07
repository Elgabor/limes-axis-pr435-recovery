# Governed event ingress contract

Issue [#340](https://github.com/Limes-Labs/limes-axis/issues/340) adds an opt-in
**authoring protocol 1.1** contract and an offline webhook reference in
`axis_sdk.connector_authoring`. It defines the shared boundary for webhook,
queue and later industrial telemetry adapters. There is no HTTP listener, broker
client, production registration, receipt store or acknowledgement implementation.
The [capability matrix](connector-capabilities.md) remains runtime truth.

## Envelope and identity

[`EventEnvelope`](../packages/sdk-python/src/axis_sdk/connector_authoring/events.py)
rejects unknown fields and contains:

| Field | Meaning |
| --- | --- |
| `event_id` | Publisher-assigned stable ID, unique across all partitions of one resource generation; retries retain it. |
| `resource_id`, `source_revision`, `schema_fingerprint` | Exact host-approved resource, source generation digest and payload schema digest. |
| `partition` | Host-bound ordering domain, never a tenant selector. |
| `position` | Optional nonnegative integer; policy determines whether it is required. Booleans are rejected. |
| `occurred_at` | Aware event time normalized to UTC; historical events may be replayed. It is not the transport authentication timestamp. |
| `event_type`, `data` | Approved operation name and schema-validated JSON object. Raw data belongs only in the governed payload sink. |

Identifiers are bounded to 200 characters; digests are lowercase SHA-256.
Tenant, actor, connector and credential references come from trusted host
configuration and `OperationContext`, never the body. References alone grant
no permission. The resource generation identifies a host-approved immutable
stream incarnation; restarting a consumer or changing schema must not silently
create a generation or reset its history.

`EventCandidate` freezes a canonical byte snapshot, with masked ordinary
serialization and fresh detached envelope reads. Its content digest covers the
whole normalized envelope, including partition and schema. Canonicalization uses
the typed model, UTC time, sorted object keys, compact UTF-8 JSON and finite
numbers. This is the Axis Python profile, not a universal JSON signing standard.
Signatures authenticate exact wire bytes before this normalization.

The event receipt key hashes `(tenant, connector, resource, source_revision,
event_id)`. It deliberately excludes attempt ID, partition and schema: moving a
known ID to another partition or changing its schema cannot evade conflict
checking. The partition watermark key hashes the same scope with `partition`
instead of `event_id`. Receipts hold canonical content digests; same key and
same digest is a duplicate, while changed content is `duplicate_conflict`.

## Ordering, replay and durable acceptance

`classify_event(candidate, observation, policy)` is a pure decision. Observations
must come from the host ledger under its existing transaction/claim fence; they
are not authorization flags. Missing history or capacity defaults to refusal.

| Policy | Rule for a previously unseen event |
| --- | --- |
| `unordered` | Position and watermark must both be absent. Use stable event IDs for deduplication. |
| `contiguous` | Require exactly `committed_position + 1`, or the configured first position. Gaps retry; unseen earlier positions fail. |
| `monotonic` | Require a position above the watermark (or at/above the configured first position). The host proves no delivered record was skipped. Numeric holes are permitted. |

A matching receipt returns `duplicate` even when capacity is exhausted; the
caller must still pass current identity, resource, credential and rate gates.
No decision writes a receipt or advances a checkpoint. Ordering is per partition,
with no global order or distributed exactly-once claim.

The future host acceptance transaction must:

1. Authenticate/bind the request, validate the signed payload, and pass current
   admission gates. Stage bounded raw bytes in the existing private object sink.
2. Recheck active resource generation, authorization, lease and claim ownership
   at the commit boundary. Lock/fence the partition and enforce a unique scoped
   event receipt across partitions. Read receipt and watermark facts there.
3. Classify, then atomically persist the new receipt/content digest, payload
   reference, existing ingestion outbox intent, metadata audit and watermark.
   Duplicate acceptance must reuse the committed receipt without another intent.
   Stage cleanup must follow existing orphan reconciliation when commit fails.
4. Only after commit, return a success acknowledgement or commit transport
   progress. A lost acknowledgement is safe to retry through the same receipt.
   Downstream workflow success is a separate state from durable ingress.

A crash before commit leaves no accepted event; retry may create it. A crash
between database commit and transport acknowledgement causes redelivery and
receipt lookup. The existing outbox/worker owns downstream retries, claims,
leases and dead-letter transitions. A host must never commit the transport's
progress first or bypass failed prior work with a later watermark.

Retain a complete receipt ledger for every accepting resource generation, bounded
by an operator-approved event/byte quota and acceptance lifetime. At capacity,
backpressure or close that generation; do not delete active deduplication keys
and continue accepting old IDs. Closed generations reject ingress. Retention
cleanup occurs only after closure and the approved replay/retention window;
new generations require reviewed activation and producer coordination. Unknown
or expired replay history returns `history_unavailable`, never a fresh success.
Reprocessing committed business effects requires an explicitly governed new
operation, not clearing receipts or changing event IDs during a retry.

## Webhook reference and admission limits

[`ReferenceWebhookAdapter`](../packages/sdk-python/src/axis_sdk/connector_authoring/webhook_reference.py)
accepts only synthetic `asset.updated` data using the existing `ReferenceAsset`
schema. It does not execute asset/device commands. The descriptor advertises
`event_ingress` at 1.1 only. Default 1.0 hosts reject it before callback selection;
use `EVENT_SUPPORTED_PROTOCOLS` and require the capability explicitly. Existing
1.0 read ports and default negotiation remain supported.

The Axis reference signature is HMAC-SHA256 over `axis-event/1.1`, a SHA-256 of
the canonical trusted binding, decimal transport timestamp, and exact body bytes,
separated by newlines. `signature_input` defines the precise bytes. The binding
includes tenant, actor, connector, resource/schema/generation and partition.
The signature header is `sha256=` plus 64 lowercase hex characters. This is an
Axis-specific profile, not generic provider webhook compatibility. It uses
[Python's HMAC comparison](https://docs.python.org/3.12/library/hmac.html#hmac.compare_digest).

The host resolves the current executed credential lease into an in-memory
`SecretBytes` key (at least 32 bytes); key issuance, entropy, rotation, expiry,
revocation and source-specific signature profiles remain host obligations.
Transport timestamps allow at most 300 seconds of age and 30 seconds of future
skew, configurable downward. A replay outside that window requires a newly
signed transport attempt with unchanged event identity/content. A valid signature
proves publisher possession of a key, not current Axis authorization.

The reference rejects oversized bytes before signature/parsing work (64 KiB
default, maximum profile cap 1 MiB), compression, non-JSON media types, duplicate
JSON keys, invalid schema and resource/partition mismatch. The canonical
candidate also has a 1 MiB cap. A future HTTP edge must impose streamed byte,
header, connection and read-deadline limits **before allocation**, require TLS,
and rate-limit unauthenticated peers before this already-buffered SDK call.

`EventAdmissionPort.admit` is mandatory after signature verification and before
schema parsing. Its production host implementation must enforce persisted tenant
and source event/byte budgets, concurrent work and queue capacity, plus current
identity/scope, lifecycle, binding and lease gates. Rate counters are shared
across requests/workers and use server identity; constructing another adapter
cannot reset them. Fair scheduling and separate per-tenant reservations prevent
one producer from consuming all capacity. Unknown policy/backend state denies
admission. The example's permissive fixture is explicitly offline only.

## Backpressure, dead-letter and schema changes

Fixed `EventErrorCode` values contain no payload, signature or provider messages.
`retryable` is a hint for the host, never an SDK retry loop. A future HTTP mapping
uses 401/403 for authentication/admission refusal, 413 for size, 400/422 for invalid
content, 409 for content conflict/gaps, 429 with bounded Retry-After for rate,
and 503 for unavailable host/history/capacity. Position gaps are retryable even
though other conflicts are permanent; clients inspect the fixed code.

Before durable ingress, failures return refusal without success ACK or progress.
Unauthenticated bodies never enter a dead-letter store. Authenticated invalid or
conflicting payloads may be quarantined only by a separately authorized, bounded
host policy; evidence contains fixed reason, trusted IDs and hashes, with raw
bytes isolated in the private sink. Ordered poison events pause their partition.
Skipping one requires a recorded operator decision and durable terminal outcome;
no adapter silently advances past it. After acceptance, bounded attempts, backoff,
dead-letter and audited manual requeue use existing outbox/worker ownership.
Full queues stop consumption/acceptance instead of silently discarding events.

Schema fingerprint mismatch fails closed, including additive unknown fields.
New schemas need reviewed discovery/activation and an explicit source-generation
migration with retained old schema/receipt interpretation and a cutover plan.
Old-generation events cannot be relabelled as new automatically. Event type
changes, units, device identity or telemetry meaning require semantic review,
not just JSON shape compatibility. No schema registry auto-registration occurs.

## Host mapping and adoption gate

Reuse G0–G7 from the [capability matrix](connector-capabilities.md):

| Existing boundary | Event adoption responsibility |
| --- | --- |
| G0 identity/tenant admission | Bind producer identity and permissions server-side; never derive tenancy from event fields. |
| G1 manifest/run lifecycle | Require active approved source generation and current execution policy. |
| G2 credential leases | Resolve and recheck current executed lease evidence; SDK has no resolver. |
| G3 egress/execution | Govern broker connections, TLS/SASL targets and key/provider I/O through existing policy owners. |
| G4 source activation | Extend resource bindings for event schemas explicitly; current table discovery/ingestion routes do not accept this envelope. |
| G5 ingestion outbox/worker | Own fenced receipts, atomic intent/audit/watermark, transport progress, retry, dead-letter and recovery. |
| G6 source limits | Enforce byte/event/time budgets, fair scheduling and shared admission counters at the actual transport. |
| G7 payload/evidence | Store raw data privately; use `candidate.evidence()` for hash/size/position-presence metadata only. Never audit candidate dumps or structured validation inputs. |

The SDK candidate is untrusted data passed inside a trusted host, not a signed
permission token. Reconstructing it or implementing a port cannot grant access.
Production adoption needs reviewed schema/migrations and runtime wiring in these
owners; this slice neither maps events onto table-only routes nor supplies an
alternative API, credential provider, database, retry scheduler or DLQ service.

## Kafka and MQTT design validation

These mappings are proposed host requirements, checked with offline contract
vectors; they are not tested broker integrations.

**Kafka-compatible consumer groups.** Pin cluster/topic incarnation and partition
to the resource generation. Derive stable event IDs from that incarnation,
partition and offset, or require a publisher ID with equivalent scope. Use the
monotonic policy: compaction can leave numeric offset holes. Disable auto-commit;
commit the next offset only after every delivered record in the processed prefix
has a durable outcome. Rebalance must revoke old ownership and fence late commits.
Kafka transactions do not atomically commit an Axis database. This mapping follows
[Kafka 4.3 design: delivery and compaction](https://kafka.apache.org/43/design/design/).
Tests show a numeric hole is allowed and an unseen rewind is refused. Runtime
evidence must cover crash/rebalance, retained history loss, poison messages,
TLS/SASL/ACLs and queue pressure before a real adapter is enabled.

**MQTT 5.0 / industrial telemetry.** Require application event IDs and an approved
device/topic binding; packet IDs and DUP flags are not business identities. Use
unordered deduplication unless the publisher defines a durable per-device
sequence. QoS 0 cannot support lossless acceptance; QoS 1 permits redelivery;
QoS 2 does not commit Axis business effects. Retained messages are snapshots and
need declared application semantics. Choose a client with explicit durable
handoff before transport success (PUBACK for QoS 1, appropriate ownership state
for QoS 2), bounded in-flight delivery and reconnect/session recovery. These
constraints follow [MQTT 5.0 sections 3.3, 4.3, 4.4 and 4.9](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html).
Tests exercise absent sequence and duplicate IDs; broker persistence, QoS/session
recovery, topic authorization, device clocks and pressure remain NOT RUN.

## Reproduce and evidence limits

```sh
make install
cd packages/sdk-python
uv run python examples/event_ingress.py
uv run pytest tests/test_event_ingress.py tests/test_connector_authoring.py -q
```

The [example](../packages/sdk-python/examples/event_ingress.py) prints only
synthetic decision/evidence metadata and explicitly does not acknowledge work.
[Test vectors](../packages/sdk-python/tests/test_event_ingress.py) cover protocol
opt-in, scope/signature/time failures, payload/schema limits, host refusal/rate,
immutable content, duplicate/conflict, replay history, ordering and unchanged
observations before commit. Full local verification and exact-head CI belong in
the PR. NOT RUN: HTTP/broker wire interoperability, real secrets and admission,
PostgreSQL receipt contention and crash recovery, object-store/Temporal delivery,
production integration, tenant fairness/load and operational certification.
[ADR 0014](adr/0014-governed-event-ingress-contract.md) records ownership.
