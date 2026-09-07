# Governed S3 / MinIO input

`s3_object_storage` reads bounded objects through connector authoring protocol
1.0 and the existing discovery, activation and ingestion outbox. It is opt-in
and separate from CSV/Postgres live sync. The
[host mapping](../services/api/src/axis_api/connector_s3_ingestion.py) owns
authorization, secret resolution, payload storage and checkpoint commit; the
[source reader](../services/api/src/axis_api/connector_s3_source.py) proposes
records and candidate progress without SQL or credential ownership.

## Enable one source scope

Configure the same deployment-owned `AXIS_S3_SOURCE_PROFILES` JSON array in the
API and worker. Each profile binds one tenant, profile ID, HTTPS endpoint,
bucket, nonempty directory prefix, allowed suffixes, credential reference and
private-endpoint reference. For example:

```json
[
  {
    "tenant_id": "tenant_example",
    "profile_id": "approved_documents",
    "endpoint": "https://minio.internal.example",
    "bucket": "approved-input",
    "prefix": "documents/",
    "allowed_suffixes": [".json", ".jsonl", ".csv", ".txt"],
    "credential_secret_ref": "env://AXIS_S3_INPUT_CREDENTIALS",
    "private_endpoint_ref": "private-endpoint://example/minio"
  }
]
```

The referenced environment value is a JSON object containing `access_key`,
`secret_key`, and optionally `session_token`. Inject it through the existing
deployment secret mechanism. It is resolved only from active lease evidence;
credentials never enter the profile, checkpoint, database or API evidence.
Use source credentials restricted to listing the approved prefix and reading
its objects. The adapter never writes to the source bucket.

Enable `AXIS_CONNECTOR_SYNC_EXECUTION_ENABLED` and
`AXIS_S3_SOURCE_INGESTION_ENABLED` for metadata operations. Worker extraction
also needs `AXIS_SOURCE_INGESTION_DISPATCH_ENABLED` and
`AXIS_SOURCE_INGESTION_EXTRACTION_ENABLED`. Register and activate the existing
manifest lifecycle with `live_query` and `external_egress` allowed, an active
credential handle/lease and an active approved-private-endpoint policy pinned
to this profile's endpoint hash. The endpoint hash is SHA-256 of lowercase
`hostname:effective_port`. The transport pins that origin and refuses redirects.
HTTP is allowed only for explicit `allow_insecure_local` loopback fixtures.

1. Call `POST /operations/connectors/sources/verify`, then
   `POST /operations/connectors/sources/discover` with `schema_name: "s3"`.
   They retain the existing `connectors:source:discover` scope and authenticated
   tenant binding. The older external-db aliases still work.
2. Discovery reports one `s3.objects_<profile_sha256>` collection with the
   fixed object-envelope schema, without reading file contents.
3. Activate that exact resource and observed fingerprint through the existing
   source activation route and `connectors:source:activate` scope.
4. Submit a governed ingestion request with `stage: "extract"` and the active
   binding, using `connectors:source:ingest`. The worker commits one bounded
   batch per binding. A new request ID continues from committed progress;
   replaying the same ID returns its original result.

Changing any profile field changes its source revision and resource identity,
requiring rediscovery and explicit activation. The revision identifies source
configuration, not an immutable bucket snapshot or a CDC position.

## Incremental and failure contract

Each successful listing covers the entire approved prefix before absence can
be considered. The default enumeration limit is 1,000 objects, configurable up
to 10,000; every listed entry counts, including excluded file types. Exceeding
that limit fails the request without progress. An empty or partial listing is
never interpreted as proof of deletion after a transport error.
Keys containing dot path segments, backslashes or control characters are
rejected before GET to keep prefix scope independent of URL normalization.

Object identity and absence are scoped to the activated binding. Objects are
keyed by SHA-256 of their key. Unchanged ETag and size skip GET;
changed validators trigger a conditional `If-Match` GET, exact length checks
and SHA-256 hashing of the downloaded bytes. An identical content hash avoids
a duplicate upsert even if the ETag changed. This relies on the S3 provider's
ETag validator contract; it does not recover overwritten historical versions.

Raw keys and base64 content appear only in payload envelopes. SQL checkpoint
state contains bounded key hashes, ETag hashes, content hashes and sizes.
Metadata views carry counts, digests and checkpoint revision, with no raw
cursor. An `observed_absent` payload references the old object hash after a
complete listing; it does not delete an Axis asset or claim transactional
source deletion. Concurrent bucket changes can be observed on a later request.
Its raw-key and content fields are explicitly null, matching the discovered
nullable field contract.

The per-object limit defaults to 256 KiB and cannot exceed 1 MiB. Existing
ingestion limits further bound emitted records, encoded bytes and elapsed
work. Row/byte exhaustion produces `more`; the next request resumes from the
committed inventory. Source calls have bounded connect/read timeouts, reduced
to the remaining operation/credential budget. Budget checks occur between
stream chunks; an in-flight socket read may take its already assigned timeout.
Expired authorization prevents further reads and checkpoint commit.

The worker prepares SQL evidence, releases the connection, then reads and
stores the payload. A final SQL transaction fences the unexpired request
claim, locks and rechecks current binding/manifest/lease/handle/policy rows,
compares the binding checkpoint revision, and commits checkpoint, batch
metadata, audit and terminal request state together. Batch identities hash a
framed tuple of tenant, connector, request, binding and revision so long IDs
and delimiter characters cannot exceed the SQL key bound or alias other tuples. A competing checkpoint,
lost claim, revoked grant, partial object, storage error or audit failure never
advances that attempt's checkpoint. Operational failures use the existing
retry/backoff/dead-letter and governed requeue paths.

Payload storage precedes the SQL commit. Content-addressed keys make identical
retries address the same object; failed attempts may leave unreferenced objects
or additional versions under a WORM store. Source I/O and payload storage are
at-least-once, while committed checkpoint advancement is fenced. There is no
distributed transaction or exactly-once source observation claim.

## Verification

The unit/host suite covers incremental changes and absence, listing and byte
caps, partial reads, metadata-only evidence, current authorization, request
replay, claim loss, checkpoint conflict, storage/audit failures and connection
release during payload I/O:

```sh
make test-api PYTEST_ARGS='tests/test_connector_s3_source.py tests/test_connector_s3_ingestion.py tests/test_connector_postgres_discovery.py -q'
```

The opt-in MinIO tests require a disposable local MinIO on `127.0.0.1:19335`
with fixture user `axis335fixture` and password `axis335fixturepassword`.
They create and remove only uniquely named fixture buckets. Run:

```sh
cd services/api
AXIS_RUN_S3_MINIO=1 uv run pytest tests/integration/test_s3_source_minio.py -q
```

The PostgreSQL concurrency test uses a freshly created/migrated random database
and drops only that database. Set `AXIS_MODEL_CONTRACT_POSTGRES_DSN` to an
isolated PostgreSQL server with CREATEDB, then run:

```sh
AXIS_RUN_S3_POSTGRES=1 AXIS_MODEL_CONTRACT_BACKEND=postgresql uv run pytest tests/integration/test_s3_checkpoint_postgres.py -q
```

The live API CI job runs both integration files with a pinned loopback MinIO
container, a disposable PostgreSQL database and unconditional fixture cleanup.

Local MinIO, SQLite host transactions and PostgreSQL migration/CAS evidence are
separate from production certification. AWS S3, non-env credential providers,
deployment OIDC/network controls, WORM sink operation, source permission
propagation, document parsing, CDC and hosted scale remain **NOT RUN** or
unimplemented. Existing governed export and reconciliation adapter limits
still apply to stored payloads.
