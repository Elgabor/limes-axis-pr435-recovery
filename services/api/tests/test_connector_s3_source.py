import hashlib
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import pytest
from axis_sdk.connector_authoring.contracts import (
    ConnectorError,
    DiscoveryRequest,
    OperationContext,
    ReadLimits,
    ReadRequest,
)
from pydantic import ValidationError

from axis_api.connector_s3_source import S3ObjectSource
from axis_api.s3_source_profile import S3_SOURCE_CONNECTOR_ID, S3SourceProfile


@pytest.fixture
def s3_profile():
    return S3SourceProfile(
        tenant_id="s3-tenant",
        profile_id="s3-fixture",
        endpoint="http://127.0.0.1:19335",
        allow_insecure_local=True,
        bucket="source-fixture",
        prefix="approved/",
        credential_secret_ref="env://AXIS_S3_FIXTURE_CREDENTIALS",
        private_endpoint_ref="fixture-endpoint",
    )


class ObjectResponse(BytesIO):
    def __init__(self, content, metadata):
        super().__init__(content)
        self.status = 200
        self.headers = {"ETag": f'"{metadata.etag}"', "Content-Length": str(metadata.size)}
        self.released = False

    def release_conn(self):
        self.released = True


class MemoryS3:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.gets = []
        self.responses = []
        self.fail_list = False
        self.partial = False

    def bucket_exists(self, _bucket):
        return True

    def list_objects(self, _bucket, *, prefix, recursive):
        assert recursive
        for key, content in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield SimpleNamespace(
                    object_name=key,
                    size=len(content),
                    etag=hashlib.md5(content).hexdigest(),
                    is_dir=False,
                )
        if self.fail_list:
            raise OSError("private provider details")

    def get_object(self, _bucket, key, *, request_headers):
        self.gets.append(key)
        content = self.objects[key]
        item = SimpleNamespace(size=len(content), etag=hashlib.md5(content).hexdigest())
        assert request_headers == {"If-Match": f'"{item.etag}"'}
        result = ObjectResponse(content[:-1] if self.partial else content, item)
        self.responses.append(result)
        return result


def read_request(source, checkpoint=None, **limits):
    return ReadRequest(
        context=OperationContext(
            tenant_id=source.profile.tenant_id,
            connector_id=S3_SOURCE_CONNECTOR_ID,
            actor_id="operator",
            operation_id="operation",
        ),
        resource=source.selection,
        checkpoint=checkpoint,
        limits=ReadLimits(**limits),
    )


def test_incremental_content_and_absence_are_payload_events(s3_profile):
    client = MemoryS3(
        {
            "approved/a.json": b'{"private":"first"}',
            "outside/no.json": b"ignored",
            "approved/program.exe": b"ignored",
        }
    )
    source = S3ObjectSource(s3_profile, client)
    first = source.read(read_request(source))
    assert len(first.records) == 1
    assert first.records[0]["content_sha256"] == hashlib.sha256(b'{"private":"first"}').hexdigest()
    assert "private" not in first.evidence().model_dump_json()
    assert client.gets == ["approved/a.json"]
    second_source = S3ObjectSource(s3_profile, client, inventory=source.next_inventory)
    second = second_source.read(read_request(second_source, first.checkpoint))
    assert second.records == ()
    assert len(client.gets) == 1
    client.objects["approved/a.json"] = b"changed"
    third_source = S3ObjectSource(s3_profile, client, inventory=second_source.next_inventory)
    third = third_source.read(read_request(third_source, second.checkpoint))
    assert third.records[0]["kind"] == "upsert"
    del client.objects["approved/a.json"]
    fourth_source = S3ObjectSource(s3_profile, client, inventory=third_source.next_inventory)
    fourth = fourth_source.read(read_request(fourth_source, third.checkpoint))
    assert fourth.records == (
        {
            "object_id": first.records[0]["object_id"],
            "object_key": None,
            "kind": "observed_absent",
            "content_sha256": third.records[0]["content_sha256"],
            "size_bytes": 0,
            "content_base64": None,
        },
    )
    assert fourth_source.next_inventory == {}
    assert all(response.closed and response.released for response in client.responses)


def test_committed_inventory_resumes_bounded_pages_without_duplicate_payloads(s3_profile):
    client = MemoryS3({f"approved/{i}.json": str(i).encode() for i in range(3)})
    inventory, checkpoint, records = {}, None, []
    for _ in range(3):
        source = S3ObjectSource(s3_profile, client, inventory=inventory)
        page = source.read(read_request(source, checkpoint, max_records=1))
        records.extend(page.records)
        inventory, checkpoint = source.next_inventory, page.checkpoint
    assert page.completion == "complete"
    assert len({r["object_id"] for r in records}) == 3
    assert len(client.gets) == 3


def test_failed_or_truncated_listing_never_emits_absence(s3_profile):
    client = MemoryS3({"approved/a.json": b"old"})
    original = S3ObjectSource(s3_profile, client)
    page = original.read(read_request(original))
    client.objects = {}
    client.fail_list = True
    source = S3ObjectSource(s3_profile, client, inventory=original.next_inventory)
    with pytest.raises(ConnectorError, match="source_unavailable") as error:
        source.read(read_request(source, page.checkpoint))
    assert "private" not in str(error.value)
    assert source.next_inventory is None


@pytest.mark.parametrize("failure", ["oversized", "partial", "too_many", "byte_budget"])
def test_read_limits_and_incomplete_object_leave_no_candidate(s3_profile, failure):
    client = MemoryS3({"approved/a.json": b"payload"})
    limits = {}
    if failure == "oversized":
        s3_profile = s3_profile.model_copy(update={"max_object_bytes": 2})
    elif failure == "partial":
        client.partial = True
    elif failure == "too_many":
        s3_profile = s3_profile.model_copy(update={"max_objects": 1})
        client.objects["approved/b.json"] = b"two"
    else:
        limits["max_bytes"] = 10
    source = S3ObjectSource(s3_profile, client)
    with pytest.raises(ConnectorError):
        source.read(read_request(source, **limits))
    assert source.next_inventory is None
    assert all(response.closed and response.released for response in client.responses)


def test_checkpoint_cannot_cross_tenant_or_changed_prefix(s3_profile):
    source = S3ObjectSource(s3_profile, MemoryS3({"approved/a.json": b"a"}))
    page = source.read(read_request(source))
    committed_inventory = deepcopy(source.next_inventory)
    changed = S3ObjectSource(s3_profile.model_copy(update={"prefix": "different/"}), source.client)
    with pytest.raises(ValidationError):
        read_request(changed, page.checkpoint)
    bad_request = read_request(source).model_copy(
        update={"context": read_request(source).context.model_copy(update={"tenant_id": "other"})}
    )
    with pytest.raises(ConnectorError, match="context_mismatch"):
        source.read(bad_request)
    corrupt = committed_inventory
    corrupt[next(iter(corrupt))]["content_sha256"] = "not-a-digest"
    with pytest.raises(ConnectorError, match="invalid_checkpoint"):
        S3ObjectSource(s3_profile, source.client, inventory=corrupt)


@pytest.mark.parametrize(
    "changes",
    [
        {"endpoint": "https://user:secret@example.invalid"},
        {"prefix": ""},
        {"prefix": "../"},
        {"endpoint": "http://example.invalid", "allow_insecure_local": True},
        {"allowed_suffixes": [".exe"]},
    ],
)
def test_profile_rejects_unreviewed_transport_or_scope(s3_profile, changes):
    with pytest.raises(ValidationError):
        S3SourceProfile.model_validate({**s3_profile.model_dump(), **changes})


def test_discovery_exposes_one_pinned_collection_without_reading_payload(s3_profile):
    source = S3ObjectSource(s3_profile, MemoryS3({"approved/a.json": b"private"}))
    result = source.discover(DiscoveryRequest(context=read_request(source).context))
    assert result.resources[0].resource_id == s3_profile.resource_name
    assert result.resources[0].source_revision == s3_profile.revision
    assert {field.name for field in result.resources[0].fields if field.nullable} == {
        "object_key",
        "content_base64",
    }
    assert source.client.gets == []


def test_inventory_stays_bounded_when_entire_prefix_is_replaced(s3_profile):
    profile = s3_profile.model_copy(update={"max_objects": 2})
    client = MemoryS3({"approved/a.json": b"a", "approved/b.json": b"b"})
    source = S3ObjectSource(profile, client)
    first = source.read(read_request(source))
    inventory, checkpoint = source.next_inventory, first.checkpoint
    client.objects = {"approved/c.json": b"c", "approved/d.json": b"d"}
    kinds = []
    for _ in range(4):
        following = S3ObjectSource(profile, client, inventory=inventory)
        page = following.read(read_request(following, checkpoint, max_records=1))
        kinds.append(page.records[0]["kind"])
        inventory, checkpoint = following.next_inventory, page.checkpoint
        assert len(inventory) <= 2
    assert kinds == ["observed_absent", "observed_absent", "upsert", "upsert"]
    assert page.completion == "complete"


def test_expired_credential_budget_prevents_source_calls(s3_profile):
    client = MemoryS3({"approved/a.json": b"a"})
    source = S3ObjectSource(s3_profile, client, clock=lambda: 10, authorization_deadline=9)
    with pytest.raises(ConnectorError, match="time_budget_exceeded"):
        source.read(read_request(source))
    assert client.gets == [] and source.next_inventory is None


def test_source_changed_between_listing_and_get_is_retried_without_progress(s3_profile):
    client = MemoryS3({"approved/a.json": b"first"})
    original = client.get_object

    def changed(bucket, key, *, request_headers):
        response = original(bucket, key, request_headers=request_headers)
        response.headers["ETag"] = '"new-version"'
        return response

    client.get_object = changed
    source = S3ObjectSource(s3_profile, client)
    with pytest.raises(ConnectorError, match="source_unavailable"):
        source.read(read_request(source))
    assert source.next_inventory is None
    assert client.responses[0].closed and client.responses[0].released


@pytest.mark.parametrize(
    "key", ["approved/./a.json", "approved/../a.json", "approved/a\\b.json", "approved/a\nb.json"]
)
def test_object_scope_rejects_noncanonical_keys_before_get(s3_profile, key):
    client = MemoryS3({key: b"fixture"})
    source = S3ObjectSource(s3_profile, client)
    with pytest.raises(ConnectorError, match="resource_mismatch"):
        source.read(read_request(source))
    assert client.gets == [] and source.next_inventory is None
