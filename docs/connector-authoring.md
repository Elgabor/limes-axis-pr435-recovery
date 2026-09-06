# Connector authoring protocol v1

`axis_sdk.connector_authoring` defines the source-side Python contract in the
existing [`limes-axis-sdk` package](../packages/sdk-python). Protocol **1.0** is
independent of the REST client's package version and the persisted connector
manifest schema. The package is installed from this repository; it is not a
published partner distribution.

The [capability matrix](connector-capabilities.md) remains the inventory of
enabled code paths. Importing this SDK, constructing a context or implementing
a port does not register an adapter, activate a manifest or grant source access.
The API's two live adapters retain their current ports. Adoption by an existing
or new production adapter requires an explicit, reviewed host mapping into the
existing discovery/live-sync/ingestion path; there is no dynamic plugin loader.

## Typed surface

The [contracts](../packages/sdk-python/src/axis_sdk/connector_authoring/contracts.py)
use Pydantic models with unknown fields rejected and structural Python protocols.
`SourceConnector` combines the four read-only ports below. A source can advertise
a smaller capability set when only individual ports are implemented. The host
checks the required capability before selecting a callback.

| Interface | Input and output | Responsibility |
| --- | --- | --- |
| `SourcePort` | `descriptor: SourceDescriptor` | Static connector ID, inclusive protocol range and explicit capabilities. No I/O or credential access. |
| `DiscoveryPort` | `DiscoveryRequest` → `DiscoveryResult` | Bounded metadata-only resources and fields, schema fingerprints, source revisions and explicit truncation. The host checks `validate_for(request)`. |
| `ReadPort` | `ReadRequest` → `ReadBatch` | Bounded JSON records, completion state and a candidate checkpoint. Records belong in the host's payload sink, never in API/audit evidence. |
| `Checkpoint` | Context binding, resource selection and an opaque cursor | Typed handoff from reader to host. Only the host commits it after durable batch success. It is not a new checkpoint store or claim service. |
| `HealthPort` | `OperationContext` → `HealthResult` | Current `ready`, `degraded`, `unavailable` or `unknown` observation with fixed reason codes. It neither authorizes a read nor certifies an operational SLO. |
| `WritebackPort` (optional) | `WritebackRequest` → `WritebackResult` | Explicit approval reference, idempotency key, bounded operations and applied count. No shipped connector implements or enables this port. |

`OperationContext` carries host-bound tenant, connector, actor and operation IDs,
the negotiated protocol and optional credential-lease/egress-policy references.
It never carries tokens, passwords, DSNs or a caller-supplied `authorized` flag.
The references are evidence identifiers, not credentials or authorization results.

`ResourceSelection` pins resource ID, schema fingerprint and source revision.
The revision is a SHA-256 digest of the adapter's documented source version or
snapshot identity. Authors must state what that identity actually guarantees.
The reference hashes its immutable dataset; hashing a schema or table name alone
does not give a mutable database snapshot or CDC semantics.

## Run the minimal reference

From the repository root:

```sh
make install
cd packages/sdk-python
uv run python examples/connector_authoring.py
uv run pytest tests/test_connector_authoring.py -q
```

The [executable example](../packages/sdk-python/examples/connector_authoring.py)
negotiates 1.0, discovers one synthetic asset resource and reads its three records
in two pages. It prints only count/byte/completion evidence. The
[reference connector](../packages/sdk-python/src/axis_sdk/connector_authoring/reference.py)
uses no network, filesystem, credential resolver, persistence or registration.
Its context IDs are offline fixture labels, not an example of production login.

For a new adapter, implement the relevant ports, declare the exact protocol
range and capabilities, then exercise the same typed requests and validators.
Implement source-specific pagination and cursor decoding inside the adapter;
keep claims, retries, persistence, approvals and audit in their current owners.

## Negotiation and deprecation

1. Read the static descriptor before any credential resolution or source I/O.
2. Call `negotiate_protocol(descriptor, required=frozenset({"read"}))`. The host's
   default implemented set is exactly 1.0. A host may supply another set only
   when it implements those serializers and method semantics.
3. Select the highest explicitly supported minor inside the descriptor's range,
   in the same major. No overlap or missing capability raises a fixed error;
   do not fall back to a similarly named adapter or an older unnegotiated mode.
4. Put the selected version in every operation context and checkpoint. Produce
   the selected version's payload shape. Strict model parsing is not automatic
   down-conversion of a future payload.

Breaking method, field, cursor or security semantics require a new **major**.
Additive opt-in capabilities or optional fields require a new **minor**, an
explicit supported-version entry and tests for each retained payload shape.
Package-only fixes that preserve the protocol do not change its version.

A deprecated protocol remains supported for at least **90 calendar days after
the dated notice** and through at least one subsequent SDK release. The
changelog must name the affected version, replacement, migration procedure and
earliest removal date. Removal is explicit: delete it from the host's supported
set after that window and reject incompatible calls before I/O. A security fix
may retire a version earlier only with a documented security decision; it must
still fail closed. No protocol version is currently deprecated.

## Reads, checkpoints and evidence

- `ReadLimits` bounds records, canonical UTF-8 JSON array bytes and elapsed
  source work. The host takes the stricter of its existing profile limits and
  these limits. Real adapters also set driver/network timeouts to the remaining
  budget; a Python type does not preempt a blocked driver or sandbox a plugin.
- `more` requires an advancing, context-bound checkpoint. `complete` means the
  selected source view is exhausted. `truncated` means a bounded partial result
  without a resumability claim and cannot include a checkpoint. Never label a
  capped page complete merely because a requested limit was reached.
- Call `ReadBatch.validate_for(request)` before accepting any adapter output.
  It rejects overproduction, wrong checkpoint bindings and a non-advancing
  `more` result. The adapter rejects invalid source cursors and stale selections
  before reading. The reference tests empty, exact-fit, row/byte/time-limited
  pages, cross-tenant reuse and changed snapshots.
- A checkpoint binds tenant, connector, protocol, resource, schema and source
  revision. It may survive a new operation ID so the existing governed resume
  flow can reuse committed progress. The host must recheck permissions, current
  lease/policy evidence and claim ownership on every operation.
- `Checkpoint.cursor` is a `SecretStr`: repr and ordinary JSON serialization
  mask it. Use `storage_record()` only for the existing tenant-scoped checkpoint
  persistence boundary, then `Checkpoint.model_validate(record)` to restore it.
  Store only adapter resume state, never credential material. Do not send this
  record to logs, API responses or audit. The example has no durable store.
- `batch.evidence()` is the explicit metadata-only projection: completion,
  record count, canonical byte count and checkpoint presence. The host adds
  trusted identity and its append-only audit event. Do not audit `model_dump()`
  of requests, rows or provider exceptions. Validation errors can contain input
  in structured `.errors()`; use fixed mapped codes or `include_input=False`.
- `ConnectorError` exposes a fixed `ErrorCode` and retryability. Translate
  provider failures without attaching raw messages or chained exceptions.
  Retryability is a hint to the existing dispatcher; it does not retry a call,
  advance a checkpoint, bypass dead-letter or promise exactly-once delivery.

## Existing host gates to reuse

These requirements apply before invoking any real adapter, including health
checks that dial a source. SDK validation adds no alternative trust path.

| Boundary | Existing owner and required mapping |
| --- | --- |
| Identity and tenancy | [`main.py`](../services/api/src/axis_api/main.py), [`tenant_admission.py`](../services/api/src/axis_api/tenant_admission.py): authenticate, bind tenant/actor and enforce operation scopes before constructing context. Never accept client-supplied context as authority. |
| Lifecycle and execution | [`connector_runs.py`](../services/api/src/axis_api/connector_runs.py): retain persisted `active_live`, live policy/runtime gates, idempotency, claims and checkpoint fencing on the live-sync path. Discovery/activated ingestion retain their own existing gates from the matrix. |
| Credentials | [`connector_credential_leases.py`](../services/api/src/axis_api/connector_credential_leases.py), [`connector_secret_resolution.py`](../services/api/src/axis_api/connector_secret_resolution.py): resolve only valid executed lease evidence and material server-side; supply source clients in memory. No new secret provider is implemented here. |
| Egress | [`connector_egress_policies.py`](../services/api/src/axis_api/connector_egress_policies.py), [`connector_execution.py`](../services/api/src/axis_api/connector_execution.py): reuse persisted approved endpoint/profile evidence and applicable dial-target checks. A descriptor or lease reference cannot change the target. |
| Resource binding | [`connector_source_activation.py`](../services/api/src/axis_api/connector_source_activation.py), [`connector_source_ingestion.py`](../services/api/src/axis_api/connector_source_ingestion.py): reconcile discovered selections with persisted activation fingerprints; do not let an adapter activate its own resource. |
| Payload, commit and audit | [`connector_source_extraction.py`](../services/api/src/axis_api/connector_source_extraction.py), [`connector_evidence_invariants.py`](../services/api/src/axis_api/connector_evidence_invariants.py): keep raw payloads in the governed sink, metadata-only evidence, append-only audit and checkpoint advancement after successful committed work. |
| Optional external writeback | No execution path is enabled. A future host must verify persisted approval, tenant/resource scope, current credentials/egress and durable idempotency before invoking the port. Existing Axis graph promotion is not source-write permission. |

No manifest fields, routes, environment flags, dependencies or production source
registrations change in this issue. Adapter code is trusted server-side code;
the protocol is not an isolation mechanism for unreviewed partner code.

## Verification limits

The SDK tests prove model validation, version/capability refusal, reference
behavior, checkpoint binding, bounded results and metadata projection. Existing
API/worker tests continue to own the actual authorization, credential, egress,
claim and audit gates. `make verify` also checks REST/OpenAPI compatibility.

NOT RUN for this contract: live provider I/O, production host adoption, external
writeback, cloud secret/object-store access, distributed checkpoint contention,
partner interoperability and hosted performance. The
[shared conformance suite and operational health model](connector-conformance.md)
add reusable fixture checks and metadata projections; production adoption and
source-specific certification still require separate evidence.
Record exact commands and results in the implementation PR; the reference
must not be used as evidence that another connector is production-ready.
