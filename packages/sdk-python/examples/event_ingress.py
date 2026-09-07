"""Offline webhook contract example. No HTTP listener, durable acceptance or source I/O."""

import hashlib
import json
from datetime import UTC, datetime

from pydantic import SecretBytes

from axis_sdk.connector_authoring import OperationContext, ResourceSelection, negotiate_protocol
from axis_sdk.connector_authoring.events import (
    EVENT_SUPPORTED_PROTOCOLS,
    EventEnvelope,
    EventObservation,
    EventOrderPolicy,
    canonical_event_bytes,
    classify_event,
)
from axis_sdk.connector_authoring.webhook_reference import (
    ReferenceWebhookAdapter,
    WebhookBinding,
    reference_schema_fingerprint,
    sign_reference_webhook,
)


class OfflineAdmissionFixture:
    """Fixture only. A real host must enforce current persisted admission gates."""

    def admit(self, context, resource, *, payload_bytes):
        return None


def main() -> None:
    now = datetime(2026, 9, 7, tzinfo=UTC)
    binding = WebhookBinding(
        tenant_id="offline", actor_id="offline", connector_id="offline-webhook",
        partition="partition-0", resource=ResourceSelection(
            resource_id="assets",
            source_revision=hashlib.sha256(b"offline-generation-1").hexdigest(),
            schema_fingerprint=reference_schema_fingerprint(),
        ),
    )
    adapter = ReferenceWebhookAdapter(binding)
    version = negotiate_protocol(
        adapter.descriptor, supported=EVENT_SUPPORTED_PROTOCOLS,
        required=frozenset({"event_ingress"}),
    )
    context = OperationContext(
        tenant_id=binding.tenant_id, actor_id=binding.actor_id, connector_id=binding.connector_id,
        operation_id="offline-attempt", credential_lease_id="offline-fixture", protocol=version,
    )
    event = EventEnvelope(
        event_id="event-1", resource_id=binding.resource.resource_id,
        source_revision=binding.resource.source_revision,
        schema_fingerprint=binding.resource.schema_fingerprint,
        partition=binding.partition, position=0, occurred_at=now, event_type="asset.updated",
        data={"asset_id": "press-1", "asset_name": "Synthetic press"},
    )
    body = canonical_event_bytes(event)
    key = SecretBytes(b"synthetic-example-key-only-00000000")
    timestamp = str(int(now.timestamp()))
    candidate = adapter.validate(
        context=context, body=body, timestamp=timestamp, now=now, key=key,
        signature=sign_reference_webhook(binding, timestamp=timestamp, body=body, key=key),
        admission=OfflineAdmissionFixture(),
    )
    # Synthetic facts only. Production reads these under the existing transaction/claim fence.
    observation = EventObservation(
        event_key=candidate.event_key, partition_key=candidate.partition_key,
        history_complete=True, capacity_available=True,
    )
    decision = classify_event(candidate, observation, EventOrderPolicy(ordering="contiguous"))
    print(json.dumps({
        "boundary": "offline_validation_only", "decision": decision.disposition,
        "evidence": candidate.evidence().model_dump(),
    }))
    # Do not ACK here: no payload, receipt, outbox, audit or watermark was committed.


if __name__ == "__main__":
    main()
