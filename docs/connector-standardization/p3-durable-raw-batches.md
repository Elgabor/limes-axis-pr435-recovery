# P3: durable raw extraction batches and fenced replay

Base: P2 commit `93def157a5b34e16f758908ce4031aeeb3130cf9`.
Authorized with P3–P5 and an independent local commit per phase.

## Consumer decision and scope

Qualify the existing `raw_envelope` ingestion consumer. A batch is one bounded
resource selection, not one driver page. Resume skips durably recorded selections
within the same request generation; it does not resume an incomplete source read
at a watermark. The legacy proposal loop keeps its explicitly unverified offset
and transaction semantics. No incremental, CDC, cross-table snapshot consistency
or exactly-once source delivery is introduced.

## Contract and transaction decisions

1. The existing claim transaction commits before work starts. Each selection
   prepares immutable, metadata-only read context under current access checks in
   a short Axis transaction. Source I/O and object-store writes run after that
   transaction closes; the adapter receives no live database session then.
2. Raw object keys include their payload digest. Different content cannot overwrite
   a previously acquired payload. Local writes become atomic and fsync-backed;
   successful object metadata must match the payload digest and byte length.
3. Each batch is recorded with audit in its own short transaction, fenced by the
   current unexpired request claim. A lost/expired claimant records neither batch
   metadata nor audit. Finalization also checks lease expiry and token ownership.
4. A versioned checkpoint identity binds tenant, connector, request generation,
   binding and schema selection. Generation changes only on explicit requeue,
   not on operational retry. Committed batches are reused only after context and
   stored-content verification; they are not read from the source again.
5. A crash before batch commit leaves an uncommitted object detectable by existing
   reconciliation. A crash after commit resumes from the committed metadata.
   Unknown legacy checkpoint versions fail closed; a new authorized snapshot
   request is required instead of reinterpreting old state.

No new database columns are needed: existing request requeue identity, batch keys
and provenance carry the internal checkpoint version. Existing raw data and legacy
IDs are never migrated or rewritten. Storage and record verification are internal;
raw payloads and driver diagnostics remain outside API/audit evidence.

## Acceptance

A8: a second PostgreSQL session observes each committed batch before the next read;
process interruption before/after commit resumes without skipped durable output.
A9: duplicate delivery does not duplicate metadata/audit/counts; incompatible
state/content is refused; source changes cannot overwrite a committed payload.
A12: claim loss/expiry fences both batch and final writes. A13: no graph/source
mutation; raw payloads remain in object storage with metadata/provenance only.

Use synthetic source drivers first, then the dedicated PostgreSQL 16 container
authorized by Lorenzo (`limes-connectors-p1-p5-01a07d85`, localhost-only port).
No shared services, production credentials or remote providers are involved.
Live schema fingerprint revalidation and binding replacement are P4.

## Verification (2026-09-07)

- 10 offline durability tests; 101 combined extraction/ingestion/boundary tests
  before the final additional repeated-requeue generation regression (also passed).
- 8 PostgreSQL 16 tests passed against an isolated loopback database: separate
  process exit immediately before/after batch commit, independent-connection
  visibility, corrupted storage replay, claim token/expiry fencing and no Axis
  transaction during source I/O. Synthetic source payloads are used in these
  transaction tests; live PostgreSQL source characterization follows in P5.
- The focused PostgreSQL fixture creates only tables used by this consumer.
  Full Base.metadata.create_all encountered a pre-existing 64-character unrelated
  checkpoint constraint name; this is not a full migration-chain certification.
- Ruff, docs-check and independent Standards/Spec reviews passed after correcting
  lock re-entry, directory-chain fsync and repeated-requeue generation identity.
- A bounded source selection uses one read-only REPEATABLE READ transaction;
  different selections or explicit generations may observe different snapshots.
- Successful local fsync is tested. Hardware power-loss and remote S3 service
  durability are not simulated; S3 verification uses streamed checksums through
  the existing client contract. Raw retention policy is unchanged.
