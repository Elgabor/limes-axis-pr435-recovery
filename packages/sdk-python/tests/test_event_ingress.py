"""Offline event contract evidence; no source, broker, server or durable store is used."""

import hashlib
import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import SecretBytes, SecretStr, ValidationError

from axis_sdk.connector_authoring import (
    CURRENT_PROTOCOL,
    ConnectorError,
    OperationContext,
    ProtocolRange,
    ResourceSelection,
    SourceDescriptor,
    negotiate_protocol,
)
from axis_sdk.connector_authoring.events import (
    EVENT_PROTOCOL,
    EVENT_SUPPORTED_PROTOCOLS,
    EventError,
    EventErrorCode,
    EventObservation,
    EventOrderPolicy,
    classify_event,
)
from axis_sdk.connector_authoring.webhook_reference import (
    ReferenceWebhookAdapter,
    WebhookBinding,
    WebhookLimits,
    reference_schema_fingerprint,
    sign_reference_webhook,
)

NOW = datetime(2026, 9, 7, 0, 0, tzinfo=UTC)
KEY = SecretBytes(b"synthetic-example-key-only-00000000")


class OfflineAdmission:
    """Explicit fixture, not an example of a production authorization implementation."""

    def __init__(self, failure=None, capacity=10):
        self.failure = failure
        self.remaining = capacity
        self.calls = 0

    def admit(self, context, resource, *, payload_bytes):
        self.calls += 1
        if self.failure:
            raise self.failure
        if self.remaining == 0:
            raise EventError(EventErrorCode.RATE_LIMITED)
        self.remaining -= 1


@pytest.fixture
def binding():
    return WebhookBinding(
        tenant_id="tenant-a",
        actor_id="publisher-a",
        connector_id="event-reference",
        partition="partition-0",
        resource=ResourceSelection(
            resource_id="assets",
            schema_fingerprint=reference_schema_fingerprint(),
            source_revision=hashlib.sha256(b"synthetic-source-generation-1").hexdigest(),
        ),
    )


def context(binding, **overrides):
    return OperationContext(
        **{
            "tenant_id": binding.tenant_id,
            "actor_id": binding.actor_id,
            "connector_id": binding.connector_id,
            "operation_id": "attempt-1",
            "credential_lease_id": "host-verified-lease",
            "protocol": EVENT_PROTOCOL,
            **overrides,
        }
    )


def payload(binding, **overrides):
    return {
        "event_id": "event-1",
        "resource_id": binding.resource.resource_id,
        "source_revision": binding.resource.source_revision,
        "schema_fingerprint": binding.resource.schema_fingerprint,
        "partition": binding.partition,
        "position": 0,
        "occurred_at": NOW.isoformat(),
        "event_type": "asset.updated",
        "data": {"asset_id": "press-1", "asset_name": "Press 1"},
        **overrides,
    }


def receive(binding, *, data=None, body=None, admission=None, **overrides):
    body = json.dumps(data or payload(binding)).encode() if body is None else body
    timestamp = str(int(NOW.timestamp()))
    args = {
        "context": context(binding),
        "body": body,
        "timestamp": timestamp,
        "signature": sign_reference_webhook(binding, timestamp=timestamp, body=body, key=KEY),
        "key": KEY,
        "now": NOW,
        "admission": admission or OfflineAdmission(),
        **overrides,
    }
    return ReferenceWebhookAdapter(binding).validate(**args)


def observed(candidate, **overrides):
    return EventObservation(
        **{
            "event_key": candidate.event_key,
            "partition_key": candidate.partition_key,
            "history_complete": True,
            "capacity_available": True,
            **overrides,
        }
    )


def test_event_protocol_requires_explicit_host_opt_in(binding):
    adapter = ReferenceWebhookAdapter(binding)
    with pytest.raises(ConnectorError, match="^incompatible_protocol$"):
        negotiate_protocol(adapter.descriptor)
    assert (
        negotiate_protocol(
            adapter.descriptor,
            supported=EVENT_SUPPORTED_PROTOCOLS,
            required=frozenset({"event_ingress"}),
        )
        == EVENT_PROTOCOL
    )
    with pytest.raises(ValidationError, match="protocol 1.1"):
        SourceDescriptor(connector_id="bad", capabilities=frozenset({"event_ingress"}))
    with pytest.raises(ValidationError, match="protocol 1.1"):
        SourceDescriptor(
            connector_id="mixed",
            protocol=ProtocolRange(max_minor=1),
            capabilities=frozenset({"read", "event_ingress"}),
        )


def test_signed_reference_event_requires_admission_and_produces_no_ack(binding):
    admission = OfflineAdmission()
    candidate = receive(binding, admission=admission)
    assert admission.calls == 1
    assert candidate.envelope.data["asset_id"] == "press-1"
    assert candidate.context == context(binding)
    assert set(candidate.evidence().model_dump()) == {
        "content_sha256",
        "byte_size",
        "position_present",
    }
    assert "Press 1" not in repr(candidate)
    assert "Press 1" not in candidate.model_dump_json()
    assert not hasattr(candidate, "acknowledged")


def test_candidate_bytes_are_immutable_after_validation(binding):
    candidate = receive(binding)
    original = candidate.evidence()
    detached = candidate.envelope
    detached.data["asset_name"] = "mutated"
    assert candidate.envelope.data["asset_name"] == "Press 1"
    assert candidate.evidence() == original
    with pytest.raises(ValidationError):
        candidate.event_bytes = SecretBytes(b"changed")


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"tenant_id": "tenant-b"}, "context_mismatch"),
        ({"actor_id": "publisher-b"}, "context_mismatch"),
        ({"connector_id": "other"}, "context_mismatch"),
        ({"credential_lease_id": None}, "context_mismatch"),
        ({"protocol": CURRENT_PROTOCOL}, "incompatible_protocol"),
    ],
)
def test_context_refusal_precedes_admission(binding, overrides, code):
    admission = OfflineAdmission()
    with pytest.raises(EventError, match=f"^{code}$"):
        receive(binding, context=context(binding, **overrides), admission=admission)
    assert admission.calls == 0


@pytest.mark.parametrize(
    "mutation", ["body", "signature", "unicode", "timestamp", "key", "binding"]
)
def test_signature_binds_exact_body_time_and_scope(binding, mutation):
    body = json.dumps(payload(binding)).encode()
    timestamp = str(int(NOW.timestamp()))
    signature = sign_reference_webhook(binding, timestamp=timestamp, body=body, key=KEY)
    args = {"body": body, "signature": signature}
    if mutation == "body":
        args["body"] = body.replace(b"Press 1", b"Press 2")
    elif mutation == "signature":
        args["signature"] = SecretStr("sha256=" + "0" * 64)
    elif mutation == "unicode":
        args["signature"] = SecretStr("non-ascii-\u00e8")
    elif mutation == "timestamp":
        args["timestamp"] = str(int(timestamp) - 1)
    elif mutation == "key":
        args["key"] = SecretBytes(b"another-synthetic-key-00000000000")
    else:
        binding = binding.model_copy(update={"actor_id": "other-publisher"})
    admission = OfflineAdmission()
    with pytest.raises(EventError, match="^authentication_failed$"):
        receive(binding, admission=admission, **args)
    assert admission.calls == 0


@pytest.mark.parametrize("delta", [301, -31])
def test_signature_age_is_not_event_occurrence_time(binding, delta):
    with pytest.raises(EventError, match="^authentication_failed$"):
        receive(binding, now=NOW + timedelta(seconds=delta))
    # Historical events are allowed only with a fresh, valid transport signature.
    candidate = receive(binding, data=payload(binding, occurred_at="2000-01-01T00:00:00Z"))
    assert candidate.envelope.occurred_at.year == 2000


@pytest.mark.parametrize("timestamp", ["1e10", "-1", "1.0", "9" * 13, "", "\n1"])
def test_invalid_signature_timestamps_fail_closed(binding, timestamp):
    with pytest.raises(EventError, match="^authentication_failed$"):
        receive(binding, timestamp=timestamp)


def test_oversized_body_is_rejected_before_admission(binding):
    admission = OfflineAdmission()
    with pytest.raises(EventError, match="^payload_too_large$"):
        receive(binding, body=b"x" * 65_537, admission=admission)
    assert admission.calls == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"content_type": "text/plain"},
        {"content_encoding": "gzip"},
    ],
)
def test_unsupported_wire_formats_are_rejected(binding, overrides):
    with pytest.raises(EventError, match="^invalid_envelope$"):
        receive(binding, **overrides)


@pytest.mark.parametrize("body", [b"{}", b"[]", b"not-json", b"\xff", b'{"data":{},"data":{}}'])
def test_malformed_envelopes_have_fixed_errors(binding, body):
    with pytest.raises(EventError, match="^invalid_envelope$"):
        receive(binding, body=body)


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"tenant_id": "forged"}, "invalid_envelope"),
        ({"event_type": "machine.execute"}, "invalid_envelope"),
        ({"schema_fingerprint": "a" * 64}, "schema_mismatch"),
        ({"source_revision": "a" * 64}, "schema_mismatch"),
        ({"resource_id": "another"}, "schema_mismatch"),
        ({"partition": "another"}, "partition_mismatch"),
        ({"position": True}, "invalid_envelope"),
        ({"position": -1}, "invalid_envelope"),
        ({"data": {"asset_id": "secret-raw-value"}}, "invalid_envelope"),
    ],
)
def test_schema_binding_and_body_identity_refusals(binding, overrides, code):
    with pytest.raises(EventError, match=f"^{code}$") as error:
        receive(binding, data=payload(binding, **overrides))
    assert "secret-raw-value" not in str(error.value)


@pytest.mark.parametrize(
    "failure,code",
    [
        (EventError(EventErrorCode.ADMISSION_DENIED), "admission_denied"),
        (EventError(EventErrorCode.BACKPRESSURE), "backpressure"),
        (RuntimeError("provider-sensitive-detail"), "host_unavailable"),
    ],
)
def test_host_denial_and_failure_produce_no_candidate(binding, failure, code):
    with pytest.raises(EventError, match=f"^{code}$") as error:
        receive(binding, admission=OfflineAdmission(failure=failure))
    assert "provider-sensitive-detail" not in str(error.value)


def test_rate_budget_is_owned_by_host_and_never_reset_by_adapter(binding):
    admission = OfflineAdmission(capacity=1)
    receive(binding, admission=admission)
    with pytest.raises(EventError, match="^rate_limited$"):
        receive(binding, admission=admission)
    assert admission.calls == 2


def test_duplicate_lost_ack_and_changed_content(binding):
    first = receive(binding)
    policy = EventOrderPolicy(ordering="contiguous")
    assert classify_event(first, observed(first), policy).disposition == "new"
    committed = observed(
        first,
        known_content_sha256=first.evidence().content_sha256,
        committed_position=0,
        capacity_available=False,
    )
    retry = receive(binding, context=context(binding, operation_id="retry-attempt"))
    assert retry.event_key == first.event_key
    assert classify_event(retry, committed, policy).disposition == "duplicate"
    changed = receive(
        binding, data=payload(binding, data={"asset_id": "press-2", "asset_name": "P2"})
    )
    assert changed.event_key == first.event_key
    with pytest.raises(EventError, match="^duplicate_conflict$"):
        classify_event(changed, committed, policy)


def test_event_identity_does_not_change_with_json_formatting_or_timezone(binding):
    first = receive(binding)
    value = payload(binding, occurred_at="2026-09-07T02:00:00+02:00")
    second = receive(binding, body=json.dumps(value, indent=2).encode())
    assert first.evidence() == second.evidence()


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"event_key": "a" * 64}, "context_mismatch"),
        ({"partition_key": "a" * 64}, "context_mismatch"),
        ({"history_complete": False}, "history_unavailable"),
        ({"capacity_available": False}, "backpressure"),
        ({"committed_position": 0}, "position_rewind"),
    ],
)
def test_observation_scope_replay_history_and_capacity(binding, overrides, code):
    candidate = receive(binding)
    with pytest.raises(EventError, match=f"^{code}$"):
        classify_event(
            candidate, observed(candidate, **overrides), EventOrderPolicy(ordering="contiguous")
        )


def test_no_checkpoint_advance_before_host_commit(binding):
    candidate = receive(binding)
    state = observed(candidate)
    policy = EventOrderPolicy(ordering="contiguous")
    assert classify_event(candidate, state, policy).next_position == 0
    assert state.committed_position is None
    assert state.known_content_sha256 is None
    assert classify_event(candidate, state, policy).disposition == "new"


def test_ordering_design_vectors_for_webhook_kafka_and_mqtt(binding):
    gap = receive(binding, data=payload(binding, position=5))
    # Ordered webhook profile requires the next publisher position, buffering nothing in SDK.
    with pytest.raises(EventError, match="^position_gap$"):
        classify_event(
            gap, observed(gap, committed_position=3), EventOrderPolicy(ordering="contiguous")
        )
    # Kafka offsets can have numeric holes. The host still commits only a processed prefix.
    decision = classify_event(
        gap, observed(gap, committed_position=3), EventOrderPolicy(ordering="monotonic")
    )
    assert decision.next_position == 5
    # MQTT application IDs work without a broker-independent ordered sequence.
    unordered = receive(binding, data=payload(binding, position=None))
    assert (
        classify_event(
            unordered, observed(unordered), EventOrderPolicy(ordering="unordered")
        ).disposition
        == "new"
    )
    with pytest.raises(EventError, match="^invalid_envelope$"):
        classify_event(unordered, observed(unordered), EventOrderPolicy(ordering="contiguous"))


def test_tenant_generation_and_partition_are_part_of_scoped_identity(binding):
    first = receive(binding)
    other_binding = binding.model_copy(update={"tenant_id": "tenant-b"})
    second = receive(other_binding)
    assert first.event_key != second.event_key
    assert first.partition_key != second.partition_key
    new_resource = binding.resource.model_copy(update={"source_revision": "b" * 64})
    third = receive(binding.model_copy(update={"resource": new_resource}))
    assert third.event_key != first.event_key


def test_reference_refuses_unknown_schema_at_construction(binding):
    resource = binding.resource.model_copy(update={"schema_fingerprint": "b" * 64})
    with pytest.raises(EventError, match="^schema_mismatch$"):
        ReferenceWebhookAdapter(binding.model_copy(update={"resource": resource}))


@pytest.mark.parametrize(
    "code,retryable",
    [
        (EventErrorCode.INVALID_ENVELOPE, False),
        (EventErrorCode.DUPLICATE_CONFLICT, False),
        (EventErrorCode.RATE_LIMITED, True),
        (EventErrorCode.BACKPRESSURE, True),
    ],
)
def test_retry_hints_do_not_schedule_work(code, retryable):
    assert EventError(code).retryable is retryable


def test_limits_require_finite_positive_profile():
    with pytest.raises(ValidationError):
        WebhookLimits(max_body_bytes=0)
    with pytest.raises(ValidationError):
        WebhookLimits(signature_max_age_seconds=301)


@pytest.mark.parametrize("admission", [None, object()])
def test_missing_host_admission_cannot_produce_candidate(binding, admission):
    body = json.dumps(payload(binding)).encode()
    timestamp = str(int(NOW.timestamp()))
    with pytest.raises(EventError, match="^host_unavailable$"):
        ReferenceWebhookAdapter(binding).validate(
            context=context(binding), body=body, timestamp=timestamp,
            signature=sign_reference_webhook(binding, timestamp=timestamp, body=body, key=KEY),
            key=KEY, now=NOW, admission=admission,
        )


def test_short_key_and_naive_clock_fail_closed(binding):
    with pytest.raises(EventError, match="^authentication_failed$"):
        receive(binding, key=SecretBytes(b"short"))
    with pytest.raises(EventError, match="^authentication_failed$"):
        receive(binding, now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("occurred_at", [
    "9999-12-31T23:59:59-01:00", "0001-01-01T00:00:00+01:00",
])
def test_event_time_outside_utc_range_has_fixed_error(binding, occurred_at):
    with pytest.raises(EventError, match="^invalid_envelope$"):
        receive(binding, data=payload(binding, occurred_at=occurred_at))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_json_is_rejected(binding, value):
    with pytest.raises(EventError, match="^invalid_envelope$"):
        receive(binding, data=payload(binding, data={"asset_id": "id", "asset_name": value}))


def test_partition_change_cannot_disguise_same_event_as_new(binding):
    first = receive(binding)
    other = binding.model_copy(update={"partition": "partition-1"})
    changed = receive(other)
    assert first.event_key == changed.event_key
    assert first.partition_key != changed.partition_key
    # The host looks up the global resource event receipt and the current partition separately.
    receipt = observed(changed, known_content_sha256=first.evidence().content_sha256)
    with pytest.raises(EventError, match="^duplicate_conflict$"):
        classify_event(changed, receipt, EventOrderPolicy(ordering="contiguous"))


def test_unordered_profile_cannot_silently_discard_position(binding):
    candidate = receive(binding)
    with pytest.raises(EventError, match="^invalid_envelope$"):
        classify_event(candidate, observed(candidate), EventOrderPolicy(ordering="unordered"))


def test_example_prints_only_offline_metadata(capsys):
    example = Path(__file__).parents[1] / "examples" / "event_ingress.py"
    runpy.run_path(str(example), run_name="__main__")
    result = json.loads(capsys.readouterr().out)
    assert result["boundary"] == "offline_validation_only"
    assert result["decision"] == "new"
    assert set(result["evidence"]) == {"content_sha256", "byte_size", "position_present"}
