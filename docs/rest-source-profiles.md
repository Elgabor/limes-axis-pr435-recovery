# REST source profile contract

This is the offline contract slice of [#336](https://github.com/Limes-Labs/limes-axis/issues/336),
implemented for [#859](https://github.com/Limes-Labs/limes-axis/issues/859).
It does not register a connector, open a connection or enable ingestion.

[`connector_rest_profiles.py`](../services/api/src/axis_api/connector_rest_profiles.py)
uses the existing [connector authoring protocol](connector-authoring.md).
Profile version `1.0` is distinct from SDK protocol `1.0`; the latter is unchanged.
The existing [capability matrix](connector-capabilities.md) remains authoritative
for executable source support.

## Profile and selection

A profile declares an opaque registered endpoint-profile ID **and its exact
revision digest**, collection ID, GET path template, typed query declarations,
record-member path, declared schema fingerprint, pagination mode and hard limits.
It contains neither a URL to dial nor credentials, headers or executable selectors.
The host must look up that endpoint reference and revalidate its current revision,
lease, policy and resource binding before any future I/O.

Path templates contain literal segments or whole named segments such as
`/v1/accounts/{account}/orders`. Supplied path values are bounded literal segments;
slashes, percent encoding, dot traversal and URL/query fragments are unsupported.
Query values support exact string, signed 64-bit integer and boolean types. No
implicit coercion is performed; undeclared names and caller-supplied pagination
parameters are rejected. Record and continuation selectors are finite member-name
tuples such as `("data", "orders")`, not JSONPath or code.

Supported pagination declarations are `opaque_cursor` and `next_link`. Next links
are restricted to the same registered endpoint; the future transport must validate
the actual destination before using them. A declaration is not enforcement.
Only `mutable_traversal` consistency is supported. A schema fingerprint or a
recorded source revision does not imply snapshot isolation or CDC. The declared
fingerprint must resolve to the host's approved schema before records are accepted.

## Checkpoints and evidence

`profile.checkpoint(context, resource, SecretStr(token), path_values=..., query_values=...)`
returns the existing SDK `Checkpoint`. The host still owns persistence and commits
progress only after durable batch acceptance. Its protected cursor envelope binds
the full profile digest and selected path/query values in addition to the SDK's
tenant, connector, protocol, collection, schema and source-revision bindings.
Changing the endpoint revision, filters, profile or selection therefore invalidates
resume, while a new operation ID can resume committed progress under fresh authority.

`profile.resume_cursor(request, path_values=..., query_values=...)` validates those
bindings before returning a `SecretStr`, or `None` for an initial request. Tokens
are opaque; invalid/expired provider tokens require explicit recovery by the host.
Neither hashes nor checkpoint possession constitute an authorization grant.

Only `Checkpoint.storage_record()` deliberately exposes the envelope for the
existing protected checkpoint store. Ordinary repr/JSON masks it. Use
`ReadBatch.evidence()` for metadata-only evidence, never serialize a batch into
audit. SDK `more`, `complete` and `truncated` semantics remain unchanged.

Use `parse_rest_source_profile()` at an untrusted configuration boundary. It maps
validation failures to a fixed error code, including unknown field names. Do not
return or log raw Pydantic `.errors()`, chained exception context, profile query
values or storage records. `hide_input_in_errors` alone does not sanitize those
structured errors. Treat validation errors from direct model construction as
internal only.

Limits are declarations for the future reader/host: SDK row/record-byte and elapsed
budgets, page-count, wire-byte and decoded-body bounds. Every page is bounded;
the host must additionally bound total work across a traversal and its retries.
This module does not run timers, count network bytes or enforce job admission.

## Verification and next owners

From a complete locked checkout, run:

```sh
make test-api PYTEST_ARGS='tests/test_connector_rest_profiles.py -q'
make docs-check
```

The tests exercise both profile modes, strict validation, revision/filter binding,
safe errors, cursor storage round-trips and the actual SDK completion/evidence
semantics. They require no provider, database or network access.

[#860](https://github.com/Limes-Labs/limes-axis/issues/860) owns bounded transport;
[#861](https://github.com/Limes-Labs/limes-axis/issues/861) owns fenced durable host
adoption; [#862](https://github.com/Limes-Labs/limes-axis/issues/862) owns end-to-end
conformance. OAuth, external writes, source discovery execution, schedules and UI
remain outside this contract. No runtime ownership or trust boundary is changed.
