"""Opt-in actual MinIO input; only loopback and a unique temporary bucket."""

import json
import os
from io import BytesIO
from uuid import uuid4

import pytest
from test_connector_s3_ingestion import host, host_engine  # noqa: F401
from test_connector_s3_source import read_request, s3_profile  # noqa: F401

from axis_api.connector_s3_ingestion import S3Credentials, minio_source_client
from axis_api.connector_s3_source import S3ObjectSource
from axis_api.s3_source_profile import S3SourceProfile

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("AXIS_RUN_S3_MINIO") != "1", reason="local MinIO opt-in"),
]


@pytest.fixture
def minio_input():
    profile = S3SourceProfile(
        tenant_id="s3-tenant",
        profile_id="s3-fixture",
        endpoint="http://127.0.0.1:19335",
        allow_insecure_local=True,
        bucket=f"axis-335-{uuid4().hex}",
        prefix="approved/",
        credential_secret_ref="env://AXIS_S3_FIXTURE_CREDENTIALS",
        private_endpoint_ref="fixture-endpoint",
        max_objects=2000,
    )
    credentials = S3Credentials(access_key="axis335fixture", secret_key="axis335fixturepassword")
    with minio_source_client(profile, credentials) as client:
        client.make_bucket(profile.bucket)
        try:
            yield profile, client
        finally:
            for item in client.list_objects(profile.bucket, recursive=True):
                client.remove_object(profile.bucket, item.object_name)
            client.remove_bucket(profile.bucket)


def put(profile, client, key, content):
    client.put_object(profile.bucket, key, BytesIO(content), len(content))


def test_real_minio_incremental_update_absence_and_prefix(minio_input):
    profile, client = minio_input
    reads = []
    original_get = client.get_object

    def counted_get(bucket, key, **kwargs):
        reads.append(key)
        return original_get(bucket, key, **kwargs)

    client.get_object = counted_get
    put(profile, client, "approved/a.json", b'{"value":1}')
    put(profile, client, "outside/a.json", b"excluded")
    put(profile, client, "approved/a.exe", b"excluded")
    source = S3ObjectSource(profile, client)
    first = source.read(read_request(source))
    assert len(first.records) == 1
    assert len(reads) == 1
    # The host accepts this candidate only after committing its payload.
    second_source = S3ObjectSource(profile, client, inventory=source.next_inventory)
    second = second_source.read(read_request(second_source, first.checkpoint))
    assert second.records == ()
    assert len(reads) == 1
    put(profile, client, "approved/a.json", b'{"value":2}')
    third_source = S3ObjectSource(profile, client, inventory=second_source.next_inventory)
    third = third_source.read(read_request(third_source, second.checkpoint))
    assert third.records[0]["content_sha256"] != first.records[0]["content_sha256"]
    assert len(reads) == 2
    client.remove_object(profile.bucket, "approved/a.json")
    fourth_source = S3ObjectSource(profile, client, inventory=third_source.next_inventory)
    fourth = fourth_source.read(read_request(fourth_source, third.checkpoint))
    assert fourth.records[0]["kind"] == "observed_absent"
    assert fourth_source.next_inventory == {}
    assert len(reads) == 2


def test_real_minio_listing_crosses_provider_page_before_absence(minio_input):
    profile, client = minio_input
    for index in range(1002):
        put(profile, client, f"approved/{index:04d}.json", b"{}")
    source = S3ObjectSource(profile, client)
    first = source.read(read_request(source, max_records=1000))
    assert len(first.records) == 1000 and first.completion == "more"
    following = S3ObjectSource(profile, client, inventory=source.next_inventory)
    second = following.read(read_request(following, first.checkpoint))
    assert len(second.records) == 2 and second.completion == "complete"
    assert len(following.next_inventory) == 1002


def test_real_minio_through_host_checkpoint_and_payload_commit(minio_input, host):  # noqa: F811
    from test_connector_s3_ingestion import dispatch, state, submit

    from axis_api.connector_secret_resolution import EnvLeaseScopedSecretResolver

    profile, client = minio_input
    # Preserve the already activated host profile and its unique fixture bucket.
    original = host.profile
    client.make_bucket(original.bucket)
    try:
        put(original, client, "approved/host.json", b'{"value":"real-minio"}')
        host.runtime.client_factory = minio_source_client
        host.runtime.resolver = EnvLeaseScopedSecretResolver(
            {
                "AXIS_S3_FIXTURE_CREDENTIALS": json.dumps(
                    {"access_key": "axis335fixture", "secret_key": "axis335fixturepassword"}
                )
            }
        )
        submit(host)
        assert dispatch(host).completed == 1
        assert state(host)[0] == 1 and state(host)[2][0].row_count == 1
        submit(host, "incremental")
        assert dispatch(host).completed == 1
        assert state(host)[2][-1].row_count == 0
    finally:
        for item in client.list_objects(original.bucket, recursive=True):
            client.remove_object(original.bucket, item.object_name)
        client.remove_bucket(original.bucket)
