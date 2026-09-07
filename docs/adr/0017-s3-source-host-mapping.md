# ADR 0017: S3 source reads in the governed ingestion host

- **Status:** Accepted
- **Date:** 2026-09-07
- **Owners:** Limes Labs maintainers
- **Related:** [Issue #335](https://github.com/Limes-Labs/limes-axis/issues/335),
  [PR #419](https://github.com/Limes-Labs/limes-axis/pull/419)
- **Review:** Implementation self-review covers scope/lease/egress gates, read
  budgets, retry and checkpoint ownership, atomic metadata commit, bounded
  batch identities and retained route contracts.

## Context

Axis can write S3-compatible output, but that port does not enumerate an input
bucket or provide source checkpoints. Connector authoring protocol 1.0 defines
bounded discovery/read ports while existing API and worker owners govern
authorization, claims, storage and evidence.

## Decision

The API package depends explicitly on the repository's Python SDK and maps a
new `s3_object_storage` reader into existing source discovery, activation and
ingestion owners. Deployment profiles scope tenant, origin, bucket, prefix,
file types and limits. Only lease-scoped environment references supply source
credentials. The source reader owns no SQL or checkpoint commit.

Migration `0066_s3_source_checkpoint` adds a bounded JSON inventory and revision
counter to existing source bindings. The dispatcher prepares under SQL,
releases the connection for source/storage I/O, then commits checkpoint CAS,
batch metadata, audit and fenced completion in one transaction after locking
and revalidating current grants. Content-addressed payloads precede SQL and
may remain unreferenced after failure. No second outbox or scheduler is added.

## Consequences

- S3 input uses the same tenant/scopes, binding, claim and retry contracts.
- API and worker container contexts must include the SDK package before locked
  dependency installation. Default flags keep source I/O disabled.
- The checkpoint inventories a bounded mutable prefix; it is neither a source
  snapshot nor CDC. Absence events are observations, not graph deletions.
- Profile changes require a new discovery/activation. Existing bindings and
  CSV/Postgres ports remain compatible; source-neutral HTTP aliases are added.
- SQL owns commit arbitration but cannot make source I/O or WORM versions
  exactly-once. Existing raw-payload access controls remain necessary.

## Alternatives Considered

- **Treat export storage as an input connector:** it lacks governed listing,
  source identity, conditional reads and incremental state.
- **New ingestion service/checkpoint table:** duplicates claim, retry and audit
  ownership already present in source ingestion and bindings.
- **Hold SQL while reading files:** makes network latency occupy database
  connections and prevents a clear fenced commit boundary.
- **Provider notifications/CDC:** requires separate delivery, version history
  and replay semantics beyond bounded pull ingestion.

## Verification

[Source and host tests](../s3-source-ingestion.md#verification) cover bounded
reads, failure/replay, lease/claim loss and SQL connection release. The actual
MinIO contract crosses the 1,000-object listing page; an isolated migrated
PostgreSQL contract races two checkpoint updates and permits one winner.
The live API CI job runs both MinIO and PostgreSQL contracts on each change.
Production AWS, WORM, identity/network deployment and scale are NOT RUN.

## Supersession

None.
