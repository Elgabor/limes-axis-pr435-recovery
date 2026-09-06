"""Run the synthetic in-memory connector; no Axis authorization or source I/O occurs."""

from axis_sdk.connector_authoring import (
    DiscoveryRequest,
    OperationContext,
    ReadLimits,
    ReadRequest,
    SourceConnector,
    negotiate_protocol,
)
from axis_sdk.connector_authoring.reference import ReferenceConnector


def main() -> None:
    source: SourceConnector = ReferenceConnector("offline-example")
    version = negotiate_protocol(
        source.descriptor, required=frozenset({"discovery", "read", "health"}),
    )
    context = OperationContext(
        tenant_id="offline-example",
        connector_id=source.descriptor.connector_id,
        actor_id="offline-example",
        operation_id="offline-example",
        protocol=version,
    )
    discovery = source.discover(DiscoveryRequest(context=context))
    resource = discovery.resources[0].selection()
    checkpoint = None
    while True:
        request = ReadRequest(
            context=context, resource=resource, checkpoint=checkpoint,
            limits=ReadLimits(max_records=2),
        )
        batch = source.read(request)
        batch.validate_for(request)
        print(batch.evidence().model_dump_json())
        # This example has no durable store. A real host commits rows, evidence and
        # checkpoint under its existing claim/transaction boundary before advancing.
        checkpoint = batch.checkpoint
        if batch.completion != "more":
            break


if __name__ == "__main__":
    main()
