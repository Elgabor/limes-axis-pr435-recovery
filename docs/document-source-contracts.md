# Document source observations

[#863](https://github.com/Limes-Labs/limes-axis/issues/863) implements the shared
contract slice of [#338](https://github.com/Limes-Labs/limes-axis/issues/338).
[`document_source_contracts.py`](../services/api/src/axis_api/document_source_contracts.py)
contains immutable, bounded observations and a pure transition classifier. It
performs no I/O, authorization, source registration, persistence or transport
negotiation. Neither Microsoft 365 nor Google Drive becomes an executable source.

## Identity, revisions and payloads

`DocumentIdentity` includes host-bound tenant/connector scope and normalized
provider/account/container/item IDs. Their canonical digest is a stable scoped key.
The container is a provider drive/library, not the current parent folder. A rename
or move within that container preserves identity; a cross-container move requires
explicit reconciliation. Two connections to the same provider item remain separate
security scopes; this contract does not silently deduplicate them.

`DocumentSnapshot` distinguishes files and folders, source and content revisions,
parent-item reference, media type, ACL observation and handling-policy references.
Parent IDs are scoped to the same account/container, not global IDs. Source version
strings are opaque and never compared lexically or treated as a total event order.
Files may initially be metadata-only; a payload reference, when present, contains an
existing artifact UUID, SHA-256 and size, never bytes, credentials or a bearer URL.
Folders have no file content. Original artifact retention and legal holds stay in
the existing object-storage/records owners.

## Permission evidence is not read authority

An ACL observation records its source revision, aware capture/expiry timestamps,
completeness and bounded grants. Timestamps are normalized to UTC. Grants preserve
source-account principal identity, user/group/domain/link kind, an optional trust
layer mapping reference and optional inheritance origin. Missing mappings remain
unresolved; no mapping by email/display name or implicit organization-wide grant
is allowed. Cross-account principal observations require explicit provider-side
normalization and cannot be inserted as another account's grant.

`ready_for_authorization(now)` means **necessary evidence is present**, not that a
particular user is allowed. Empty, incomplete, unavailable, expired or future ACL
observations return false. Unresolved principals also return false. Domain/link
access is preserved as evidence but unsupported for baseline read eligibility,
even if a mapping reference is supplied. User/group mappings still require current
trust-layer resolution, membership, marking, purpose and object/field checks on
every actual read. A connector service account's broad source access is irrelevant
to an Axis end user's entitlement. Ineligible content must not enter a readable
search projection; even eligible content remains subject to current authorization.

A source change feed alone does not establish ACL freshness. Adapters must define
an independent refresh strategy and invalidate stale derived visibility. Handling
references travel with downstream artifacts; they are not themselves new grants.

## Events, replay and deletion

`DocumentChange` version `1.0` is a domain contract, not a new SDK protocol version.
An `observed` event carries a full normalized snapshot and a content/metadata/
permissions change reason. A `removed` event carries only an explicit tombstone:
source deletion, access loss and removal from the approved scope are distinct.
Missing items in incomplete/truncated enumeration cannot be expressed as deletion
evidence. A `restored` event needs a new snapshot and explicit revalidation reference.
References convey no authority and must be checked by the host before acceptance.

`classify_document_change(previous, incoming)` checks scope, exact replay and the
`supersedes_digest` optimistic precondition. A changed duplicate is a conflict; a
stale event cannot replace newer permission evidence. A tombstone cannot be replaced
by an ordinary observation even with its current digest: restoration is explicit.
The classifier returns `new` or `duplicate`; it does **not** write state or implement
a new ledger, queue, checkpoint store or concurrency mechanism.

The host must bind the predecessor before source work, retain the provider's actual
ordering/revision evidence, and compare-and-swap it under the existing claim fence
when committing. A conflict requires reconciliation or fresh source/ACL observation;
never rewrite an old event's predecessor to the latest digest and retry blindly.
Incomplete or unordered feeds cannot establish freshness from arrival time or ETags.
Older duplicate-history handling remains with the existing delivery ledger; this
classifier only validates the proposed transition from the current observation.
An explicit resync must not discard a tombstone and treat stale content as a fresh
initial item. Removal blocks ordinary retrieval, not retention of original evidence.

## Existing owners and verification

Reuse host tenant binding and source activation, the existing ingestion outbox and
claim fencing, current permission/identity mapping, canonical object storage and
metadata-only audit. Parsing/OCR stays with #493/#494; query-time enforcement stays
with #343; directory lifecycle stays with #330/#727. This contract requires neither
a new SDK event-ingress transport nor a separate authorization service.

Use `parse_document_change()` at untrusted boundaries; it maps validation failures
to a fixed safe code. Do not log or expose raw Pydantic `.errors()` or chained input
exceptions. Only `change.evidence()` belongs in ordinary audit, after host scope is
bound. Full snapshots contain sensitive metadata even though bytes are not included.

From a complete locked checkout:

```sh
make test-api PYTEST_ARGS='tests/test_document_source_contracts.py -q'
make docs-check
```

Tests cover both provider namespaces, inherited/direct grants, ACL validity,
revision changes, moves, duplicate/conflicting/stale events, explicit restoration,
immutable observations and metadata-only evidence. They need no cloud or database.
Provider discovery/sync and real permission propagation remain #864 through #868.
No live adapter, runtime trust boundary or component ownership is changed here.
