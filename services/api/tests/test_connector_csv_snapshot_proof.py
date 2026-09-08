"""CSV snapshot characterization; no claim of durable legacy offset resume."""

import hashlib
from io import BytesIO
from types import SimpleNamespace

import pytest
from test_connector_live_sync import (
    FILE_CSV_CONNECTOR_ID,
    FILE_CSV_LEASE_ID,
    TENANT_ID,
    file_csv_field_mappings,
    file_csv_live_sync_input_summary,
    file_csv_live_sync_runtime,
)

from axis_api.connector_execution import ConnectorLiveSyncBatchRequest, ConnectorLiveSyncPlanRequest
from axis_api.object_storage import S3CompatibleObjectStore


def collect(runtime, filename):
    request = ConnectorLiveSyncPlanRequest(
        tenant_id=TENANT_ID,
        connector_id=FILE_CSV_CONNECTOR_ID,
        run_id="csv_proof_" + filename,
        execution_id="csv_proof_execution",
        executed_by="synthetic_test",
        credential_lease_id=FILE_CSV_LEASE_ID,
        field_mappings=file_csv_field_mappings(),
        input_summary=file_csv_live_sync_input_summary(filename),
    )
    plan = runtime.plan(request)
    assert plan.contract_version == "0.1"
    assert plan.descriptor.durable_resume == "not_verified"
    assert not plan.descriptor.incremental and not plan.descriptor.cdc
    batches, offset = [], 0
    for _ in range(10):
        batch = runtime.read_batch(
            ConnectorLiveSyncBatchRequest.model_validate(
                {
                    **request.model_dump(),
                    "offset": offset,
                    "batch_size": 2,
                }
            )
        )
        assert batch.status == "live_sync_batch_read"
        batches.append(batch)
        if batch.source_exhausted:
            break
        assert batch.next_offset > offset
        offset = batch.next_offset
    else:
        pytest.fail("bounded CSV reader did not stop")
    return batches


@pytest.mark.parametrize("cap", [3, 10])
def test_csv_immutable_fixture_generations_and_honest_caps(tmp_path, cap):
    original = "asset_id,asset_name,risk_level,order_id\n" + "".join(
        f"C{i},Confirmation L{i},low,L{i}\n" for i in range(1, 6)
    )
    revised = original.replace("Confirmation L2", "Corrected L2") + "C6,Confirmation L6,low,L6\n"
    first_path, second_path = tmp_path / "confirmations-v1.csv", tmp_path / "confirmations-v2.csv"
    first_path.write_text(original)
    second_path.write_text(revised)
    first_digest = hashlib.sha256(first_path.read_bytes()).hexdigest()
    runtime = file_csv_live_sync_runtime(tmp_path)
    runtime.file_csv_profile.max_rows = cap
    first = collect(runtime, first_path.name)
    second = collect(runtime, second_path.name)
    assert [len(batch.records) for batch in first] == ([2, 1] if cap == 3 else [2, 2, 1])
    assert sum(len(batch.records) for batch in second) == min(cap, 6)
    assert first[-1].completion_reason == ("row_limit" if cap == 3 else "unknown_legacy")
    assert all(batch.output_shape == "legacy_proposals" for batch in first + second)
    assert all(batch.completion_evidence == "bounded_or_unknown" for batch in first + second)
    assert hashlib.sha256(first_path.read_bytes()).hexdigest() == first_digest
    assert hashlib.sha256(second_path.read_bytes()).hexdigest() != first_digest
    assert [record.node_id for batch in second for record in batch.records] == [
        f"C{i}" for i in range(1, min(cap, 6) + 1)
    ]


@pytest.mark.parametrize("failure", ["none", "digest", "length", "read_error"])
def test_remote_object_verification_is_bounded_and_closes_stream(failure):
    payload = b'{"rows":[1,2]}'

    class Stream(BytesIO):
        released = False

        def read(self, size=-1):
            assert 0 < size <= 65536
            if failure == "read_error":
                raise OSError("synthetic storage failure")
            return super().read(size)

        def release_conn(self):
            self.released = True

    stream = Stream(payload)
    store = S3CompatibleObjectStore(
        client=SimpleNamespace(get_object=lambda *args: stream),
        bucket_name="synthetic",
        retention_mode="GOVERNANCE",
        retention_days=1,
        legal_hold_enabled=False,
    )
    digest = hashlib.sha256(payload).hexdigest() if failure != "digest" else "0" * 64
    if failure == "read_error":
        with pytest.raises(OSError):
            store.verify_json("synthetic.json", digest, len(payload))
    else:
        assert store.verify_json(
            "synthetic.json", digest, len(payload) + (failure == "length")
        ) == (failure == "none")
    assert stream.closed and stream.released
