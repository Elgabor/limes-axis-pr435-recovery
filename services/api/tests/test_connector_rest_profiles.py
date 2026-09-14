import json

import pytest
from axis_sdk.connector_authoring.contracts import (
    Checkpoint,
    ConnectorError,
    ErrorCode,
    OperationContext,
    ReadBatch,
    ReadRequest,
    ResourceSelection,
)
from jsonschema import Draft202012Validator
from pydantic import SecretStr, ValidationError

from axis_api.connector_rest_profiles import RestSourceProfile, parse_rest_source_profile


@pytest.fixture
def profile_data():
    return {
        "endpoint_profile_id": "approved-orders-service",
        "endpoint_profile_revision": "e" * 64,
        "collection_id": "orders",
        "path_template": "/v1/accounts/{account}/orders",
        "query_parameters": [
            {"name": "status", "value_type": "string", "required": True},
            {"name": "limit", "value_type": "integer"},
            {"name": "archived", "value_type": "boolean"},
        ],
        "records_path": ["data", "orders"],
        "schema_fingerprint": "a" * 64,
        "pagination": {"kind": "opaque_cursor", "parameter": "after", "next_path": ["next"]},
    }


@pytest.fixture
def profile(profile_data):
    return RestSourceProfile.model_validate(profile_data)


@pytest.fixture
def read_request():
    return ReadRequest(
        context=OperationContext(
            tenant_id="tenant-a", connector_id="rest-a", actor_id="operator", operation_id="run-a"
        ),
        resource=ResourceSelection(
            resource_id="orders", schema_fingerprint="a" * 64, source_revision="b" * 64
        ),
    )


def checkpoint(profile, read_request, token="sensitive-next-position"):
    return profile.checkpoint(
        read_request.context,
        read_request.resource,
        SecretStr(token),
        path_values={"account": "example"},
        query_values={"status": "open"},
    )


def resume(profile, read_request):
    return profile.resume_cursor(
        read_request, path_values={"account": "example"}, query_values={"status": "open"}
    )


@pytest.mark.parametrize("kind", ["opaque_cursor", "next_link"])
def test_profile_round_trip_and_schema(profile_data, kind):
    if kind == "next_link":
        profile_data["pagination"] = {"kind": kind, "next_path": ["links", "next"]}
    profile = parse_rest_source_profile(profile_data)
    restored = RestSourceProfile.model_validate_json(profile.model_dump_json())
    assert profile == restored
    assert profile.digest() == restored.digest()
    assert profile.consistency == "mutable_traversal"
    assert profile.method == "GET"
    Draft202012Validator(RestSourceProfile.model_json_schema()).validate(
        profile.model_dump(mode="json")
    )


@pytest.mark.parametrize("change", [
    {"method": "POST"},
    {"headers": {"Authorization": "secret-fixture"}},
    {"base_url": "https://source.invalid"},
    {"records_path": ["$[*]"]},
    {"consistency": "snapshot"},
    {"version": "2.0"},
    {"limits": {"max_pages": 0}},
    {"limits": {"max_wire_bytes": 8_388_609}},
    {"limits": {"max_decoded_bytes": True}},
    {"limits": {"page": {"time_budget_seconds": 0}}},
    {"pagination": {"kind": "offset", "next_path": ["next"]}},
    {"pagination": {"kind": "next_link", "next_path": ["next"], "destination_policy": "any"}},
])
def test_unsupported_configuration_is_rejected(profile_data, change):
    with pytest.raises(ConnectorError) as error:
        parse_rest_source_profile(profile_data | change)
    assert error.value.code == ErrorCode.RESOURCE_MISMATCH
    assert "secret-fixture" not in str(error.value)


@pytest.mark.parametrize("template", [
    "https://source.invalid/orders", "//source.invalid/orders", "/a/../b", "/a/%2e%2e/b",
    "/orders?token=x", "/a#b", "/{account.name}", "/{x!r}", "/{x}/{x}", "/a\\b", "/a\nb",
])
def test_path_template_is_a_finite_grammar(profile_data, template):
    with pytest.raises(ConnectorError):
        parse_rest_source_profile(profile_data | {"path_template": template})


def test_query_declarations_cannot_replace_pagination(profile_data):
    for declarations in [
        [{"name": "after", "value_type": "string"}],
        [{"name": "status", "value_type": "string"}] * 2,
    ]:
        with pytest.raises(ConnectorError):
            parse_rest_source_profile(profile_data | {"query_parameters": declarations})


@pytest.mark.parametrize("path,query", [
    ({}, {"status": "open"}),
    ({"account": ".."}, {"status": "open"}),
    ({"account": "a/b"}, {"status": "open"}),
    ({"account": "example"}, {}),
    ({"account": "example"}, {"status": "open", "unknown": 1}),
    ({"account": "example"}, {"status": "open", "after": "override"}),
    ({"account": "example"}, {"status": "open", "limit": True}),
    ({"account": "example"}, {"status": "open", "limit": "5"}),
    ({"account": "example"}, {"status": "open", "archived": 1}),
    ({"account": "example"}, {"status": "x" * 1_025}),
    ({"account": "example"}, {"status": "\ud800"}),
    ({"account": "example"}, {"status": "open", "limit": 2**63}),
])
def test_selection_checks_declared_names_types_and_bounds(profile, path, query):
    with pytest.raises(ConnectorError):
        profile.selection_digest(path_values=path, query_values=query)


def test_selection_digest_is_order_independent_and_value_sensitive(profile):
    path = {"account": "example"}
    query = {"status": "open", "limit": 5, "archived": False}
    digest = profile.selection_digest(path_values=path, query_values=query)
    assert digest == profile.selection_digest(
        path_values=path, query_values=dict(reversed(list(query.items())))
    )
    assert digest != profile.selection_digest(path_values=path, query_values=query | {"limit": 6})


def test_checkpoint_round_trip_uses_existing_host_storage_contract(profile, read_request):
    candidate = checkpoint(profile, read_request)
    stored = Checkpoint.model_validate(candidate.storage_record())
    continued = ReadRequest(
        context=read_request.context, resource=read_request.resource, checkpoint=stored
    )
    assert resume(profile, continued).get_secret_value() == "sensitive-next-position"
    assert resume(profile, read_request) is None
    assert "sensitive-next-position" not in repr(candidate)
    assert "sensitive-next-position" not in candidate.model_dump_json()
    assert "sensitive-next-position" not in repr(resume(profile, continued))
    assert "example" not in candidate.cursor.get_secret_value()


@pytest.mark.parametrize("component,field,value", [
    ("context", "tenant_id", "tenant-b"),
    ("context", "connector_id", "rest-b"),
    ("context", "protocol", {"major": 1, "minor": 1}),
    ("resource", "resource_id", "other"),
    ("resource", "schema_fingerprint", "c" * 64),
    ("resource", "source_revision", "d" * 64),
])
def test_sdk_rejects_cross_scope_checkpoint(profile, read_request, component, field, value):
    data = read_request.model_dump(mode="json")
    data["checkpoint"] = checkpoint(profile, read_request).storage_record()
    data[component][field] = value
    with pytest.raises(ValidationError):
        ReadRequest.model_validate(data)


@pytest.mark.parametrize("change", [
    {"endpoint_profile_id": "new-endpoint"},
    {"endpoint_profile_revision": "f" * 64},
    {"path_template": "/v2/accounts/{account}/orders"},
    {"limits": {"max_pages": 2}},
])
def test_changed_profile_invalidates_resume(profile_data, profile, read_request, change):
    continued = ReadRequest(
        context=read_request.context,
        resource=read_request.resource,
        checkpoint=checkpoint(profile, read_request),
    )
    changed = RestSourceProfile.model_validate(profile_data | change)
    with pytest.raises(ConnectorError, match="^invalid_checkpoint$"):
        resume(changed, continued)


def test_changed_filter_and_path_values_invalidate_resume(profile, read_request):
    continued = ReadRequest(
        context=read_request.context,
        resource=read_request.resource,
        checkpoint=checkpoint(profile, read_request),
    )
    for path, query in [
        ({"account": "other"}, {"status": "open"}),
        ({"account": "example"}, {"status": "closed"}),
    ]:
        with pytest.raises(ConnectorError, match="^invalid_checkpoint$"):
            profile.resume_cursor(continued, path_values=path, query_values=query)


def test_new_operation_can_resume_without_making_a_new_checkpoint_authority(profile, read_request):
    continued = ReadRequest(
        context=OperationContext.model_validate(
            read_request.context.model_dump() | {"operation_id": "b"}
        ),
        resource=read_request.resource,
        checkpoint=checkpoint(profile, read_request),
    )
    assert resume(profile, continued).get_secret_value() == "sensitive-next-position"


@pytest.mark.parametrize("raw", ["secret-invalid-json", json.dumps({"secret-unknown-field": "x"})])
def test_malformed_cursor_errors_do_not_expose_values_or_field_names(profile, read_request, raw):
    candidate = Checkpoint.model_validate(
        checkpoint(profile, read_request).storage_record() | {"cursor": raw}
    )
    continued = ReadRequest(
        context=read_request.context, resource=read_request.resource, checkpoint=candidate
    )
    with pytest.raises(ConnectorError) as error:
        resume(profile, continued)
    assert str(error.value) == "invalid_checkpoint"
    assert error.value.__suppress_context__


@pytest.mark.parametrize("token", ["", "x" * 3_001, "\x00" * 1_000])
def test_oversized_or_invalid_cursor_encoding_has_safe_error(profile, read_request, token):
    with pytest.raises(ConnectorError, match="^invalid_checkpoint$"):
        checkpoint(profile, read_request, token)


def test_completion_and_evidence_reuse_sdk_semantics(profile, read_request):
    first = checkpoint(profile, read_request, "first")
    continued = ReadRequest(
        context=read_request.context, resource=read_request.resource, checkpoint=first
    )
    more = ReadBatch(
        records=({"id": "private-row-value"},),
        completion="more",
        checkpoint=checkpoint(profile, read_request, "second"),
    )
    more.validate_for(continued)
    assert "private-row-value" not in more.evidence().model_dump_json()
    assert "second" not in more.evidence().model_dump_json()
    with pytest.raises(ConnectorError, match="^no_progress$"):
        ReadBatch(records=(), completion="more", checkpoint=first).validate_for(continued)
    ReadBatch(records=(), completion="complete").validate_for(continued)
    ReadBatch(records=(), completion="truncated").validate_for(continued)
    with pytest.raises(ValidationError):
        ReadBatch(records=(), completion="truncated", checkpoint=first)


@pytest.mark.parametrize("change", [
    {"resource_id": "another-collection"},
    {"schema_fingerprint": "f" * 64},
])
def test_initial_selection_must_match_profile(profile, read_request, change):
    wrong = ResourceSelection.model_validate(read_request.resource.model_dump() | change)
    initial = ReadRequest(context=read_request.context, resource=wrong)
    with pytest.raises(ConnectorError, match="^resource_mismatch$"):
        resume(profile, initial)


def test_unknown_field_names_are_not_public_error_details(profile_data):
    with pytest.raises(ConnectorError) as error:
        parse_rest_source_profile(profile_data | {"secret-field-sentinel": "secret-value-sentinel"})
    assert str(error.value) == "resource_mismatch"
    assert error.value.__suppress_context__
