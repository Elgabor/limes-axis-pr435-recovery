import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, Field, model_validator
from temporalio.client import Client
from temporalio.exceptions import TemporalError
from temporalio.service import RPCError, RPCStatusCode

from axis_api.demo import ApprovalDecision
from axis_api.telemetry import inject_trace_context

_APPROVAL_DECISION_EVENT_NAMESPACE = UUID("1b8091cc-fc94-5e86-bc86-f51629b07e0a")
APPROVAL_DECISION_SCHEMA_VERSION = "axis.approval-decision.v1"
APPROVAL_DECISION_SIGNAL_NAME = "approval_decided_v1"


class WorkflowSignalRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    decision: ApprovalDecision
    decision_event_id: UUID | None = None
    actor_id: str | None = Field(default=None, min_length=1)
    note: str | None = Field(default=None, max_length=600)
    decided_at: datetime | None = None
    signal_name: str = Field(default=APPROVAL_DECISION_SIGNAL_NAME, min_length=1)

    @model_validator(mode="after")
    def populate_stable_decision_event_id(self) -> "WorkflowSignalRequest":
        if self.decision_event_id is None:
            event_key = "\x1f".join((self.tenant_id, self.workflow_id, self.approval_id))
            self.decision_event_id = uuid5(_APPROVAL_DECISION_EVENT_NAMESPACE, event_key)
        return self

    @property
    def approved(self) -> bool:
        return self.decision == ApprovalDecision.APPROVE

    @property
    def runtime_payload(self) -> dict:
        return {
            "schema_version": APPROVAL_DECISION_SCHEMA_VERSION,
            "decision_event_id": str(self.decision_event_id),
            "tenant_id": self.tenant_id,
            "workflow_id": self.workflow_id,
            "approval_id": self.approval_id,
            "decision": self.decision.value,
            "approved": self.approved,
            "actor_id": self.actor_id,
            "note": self.note,
            "decided_at": self.decided_at.isoformat() if self.decided_at is not None else None,
        }

    @property
    def audit_payload(self) -> dict:
        return dict(self.runtime_payload)


class WorkflowSignalResult(BaseModel):
    workflow_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    signal_name: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


class WorkflowActionSignalRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    action_run_id: UUID
    idempotency_key: str = Field(min_length=1)
    approval_id: str | None = None
    execution_mode: str = Field(min_length=1)
    signal_name: str = Field(default="action_requested", min_length=1)
    payload: dict = Field(default_factory=dict)

    @property
    def runtime_payload(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "action_id": self.action_id,
            "action_run_id": str(self.action_run_id),
            "idempotency_key": self.idempotency_key,
            "approval_id": self.approval_id,
            "execution_mode": self.execution_mode,
            "payload": self.payload,
        }

    @property
    def audit_payload(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_run_id": str(self.action_run_id),
            "idempotency_key": self.idempotency_key,
            "approval_id": self.approval_id,
            "execution_mode": self.execution_mode,
            "payload_field_names": sorted(self.payload.keys()),
        }


class WorkflowConnectorManualImportSignalRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    import_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    import_mode: str = Field(min_length=1)
    decision: ApprovalDecision
    proposal_ids: list[str] = Field(default_factory=list)
    graph_mutation_status: str = Field(default="not_applied", min_length=1)
    signal_name: str = Field(default="connector_manual_import_decided", min_length=1)

    @property
    def approved(self) -> bool:
        return self.decision == ApprovalDecision.APPROVE

    @property
    def runtime_payload(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "connector_id": self.connector_id,
            "import_id": self.import_id,
            "idempotency_key": self.idempotency_key,
            "approval_id": self.approval_id,
            "import_mode": self.import_mode,
            "decision": self.decision.value,
            "approved": self.approved,
            "proposal_ids": self.proposal_ids,
            "graph_mutation_status": self.graph_mutation_status,
        }

    @property
    def audit_payload(self) -> dict:
        return {
            "connector_id": self.connector_id,
            "import_id": self.import_id,
            "idempotency_key": self.idempotency_key,
            "approval_id": self.approval_id,
            "import_mode": self.import_mode,
            "decision": self.decision.value,
            "approved": self.approved,
            "proposal_ids": self.proposal_ids,
            "proposal_count": len(self.proposal_ids),
            "graph_mutation_status": self.graph_mutation_status,
        }


class WorkflowConnectorEvidenceSnapshotExportSignalRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    export_request_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    decision: ApprovalDecision
    connector_id: str | None = None
    snapshot_id: str | None = None
    requested_snapshot_count: int = Field(ge=0)
    export_status: str = Field(min_length=1)
    storage_status: str = Field(default="not_written", min_length=1)
    redaction_policy: str = Field(min_length=1)
    signal_name: str = Field(
        default="connector_evidence_snapshot_export_decided",
        min_length=1,
    )

    @property
    def approved(self) -> bool:
        return self.decision == ApprovalDecision.APPROVE

    @property
    def runtime_payload(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "export_request_id": self.export_request_id,
            "idempotency_key": self.idempotency_key,
            "approval_id": self.approval_id,
            "decision": self.decision.value,
            "approved": self.approved,
            "connector_id": self.connector_id,
            "snapshot_id": self.snapshot_id,
            "requested_snapshot_count": self.requested_snapshot_count,
            "export_status": self.export_status,
            "storage_status": self.storage_status,
            "redaction_policy": self.redaction_policy,
        }

    @property
    def audit_payload(self) -> dict:
        return self.runtime_payload


class WorkflowSignalRuntime(Protocol):
    async def signal_approval_decision(
        self,
        request: WorkflowSignalRequest,
    ) -> WorkflowSignalResult:
        ...

    async def signal_action_run(
        self,
        request: WorkflowActionSignalRequest,
    ) -> WorkflowSignalResult:
        ...

    async def signal_connector_manual_import(
        self,
        request: WorkflowConnectorManualImportSignalRequest,
    ) -> WorkflowSignalResult:
        ...

    async def signal_connector_evidence_snapshot_export(
        self,
        request: WorkflowConnectorEvidenceSnapshotExportSignalRequest,
    ) -> WorkflowSignalResult:
        ...


class WorkflowSignalError(RuntimeError):
    def __init__(self, reason: str, *, may_be_closed: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.may_be_closed = may_be_closed


def _with_trace_context(payload: dict) -> dict:
    """Return ``payload`` augmented with the active W3C trace context.

    When telemetry is enabled and a request span is recording, this adds a
    ``traceparent`` (and, if present, ``tracestate``) key so the signalled
    workflow/activity on the worker can continue the originating trace. When
    telemetry is disabled the current span is non-recording and the propagator
    injects nothing, so the payload is returned unchanged.
    """

    return inject_trace_context(dict(payload))


@dataclass(frozen=True)
class TemporalWorkflowSignalConfig:
    address: str = "localhost:7233"
    namespace: str = "default"
    signal_timeout_seconds: float = 2.0


class TemporalWorkflowSignalRuntime:
    adapter_name = "axis-temporal-adapter"

    def __init__(self, config: TemporalWorkflowSignalConfig) -> None:
        self.config = config
        self._client: Client | None = None

    async def client(self) -> Client:
        if self._client is None:
            self._client = await Client.connect(
                self.config.address,
                namespace=self.config.namespace,
            )
        return self._client

    async def signal_approval_decision(
        self,
        request: WorkflowSignalRequest,
    ) -> WorkflowSignalResult:
        try:
            client = await self.client()
            handle = client.get_workflow_handle(request.workflow_id)
            await handle.signal(
                request.signal_name,
                request.runtime_payload,
                rpc_timeout=timedelta(seconds=self.config.signal_timeout_seconds),
            )
        except RPCError as exc:
            raise WorkflowSignalError(
                exc.__class__.__name__,
                may_be_closed=exc.status
                in {RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION},
            ) from exc
        except (OSError, RuntimeError, TemporalError) as exc:
            raise WorkflowSignalError(exc.__class__.__name__) from exc

        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="approval_signaled",
            adapter=self.adapter_name,
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )

    async def get_approval_decision_result(self, workflow_id: str) -> dict | None:
        """Return a completed workflow result for crash-window reconciliation.

        A short local timeout prevents a racing, still-open execution from
        turning the dispatcher into an unbounded long poll.
        """
        try:
            client = await self.client()
            handle = client.get_workflow_handle(workflow_id)
            async with asyncio.timeout(self.config.signal_timeout_seconds):
                result = await handle.result(
                    rpc_timeout=timedelta(seconds=self.config.signal_timeout_seconds)
                )
        except TimeoutError:
            return None
        except (OSError, RuntimeError, TemporalError, RPCError) as exc:
            raise WorkflowSignalError(exc.__class__.__name__) from exc
        return result if isinstance(result, dict) else None

    async def signal_action_run(
        self,
        request: WorkflowActionSignalRequest,
    ) -> WorkflowSignalResult:
        try:
            client = await self.client()
            handle = client.get_workflow_handle(request.workflow_id)
            await handle.signal(
                request.signal_name,
                _with_trace_context(request.runtime_payload),
                rpc_timeout=timedelta(seconds=self.config.signal_timeout_seconds),
            )
        except (OSError, RuntimeError, TemporalError, RPCError) as exc:
            raise WorkflowSignalError(exc.__class__.__name__) from exc

        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="action_signal_requested",
            adapter=self.adapter_name,
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )

    async def signal_connector_manual_import(
        self,
        request: WorkflowConnectorManualImportSignalRequest,
    ) -> WorkflowSignalResult:
        try:
            client = await self.client()
            handle = client.get_workflow_handle(request.workflow_id)
            await handle.signal(
                request.signal_name,
                _with_trace_context(request.runtime_payload),
                rpc_timeout=timedelta(seconds=self.config.signal_timeout_seconds),
            )
        except (OSError, RuntimeError, TemporalError, RPCError) as exc:
            raise WorkflowSignalError(exc.__class__.__name__) from exc

        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="manual_import_signal_requested",
            adapter=self.adapter_name,
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )

    async def signal_connector_evidence_snapshot_export(
        self,
        request: WorkflowConnectorEvidenceSnapshotExportSignalRequest,
    ) -> WorkflowSignalResult:
        try:
            client = await self.client()
            handle = client.get_workflow_handle(request.workflow_id)
            await handle.signal(
                request.signal_name,
                _with_trace_context(request.runtime_payload),
                rpc_timeout=timedelta(seconds=self.config.signal_timeout_seconds),
            )
        except (OSError, RuntimeError, TemporalError, RPCError) as exc:
            raise WorkflowSignalError(exc.__class__.__name__) from exc

        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="export_request_signal_requested",
            adapter=self.adapter_name,
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )


class DeferredWorkflowSignalRuntime:
    adapter_name = "axis-deferred-workflow-adapter"

    async def signal_approval_decision(
        self,
        request: WorkflowSignalRequest,
    ) -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="runtime_signal_deferred",
            adapter=self.adapter_name,
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )

    async def signal_action_run(
        self,
        request: WorkflowActionSignalRequest,
    ) -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="runtime_signal_deferred",
            adapter=self.adapter_name,
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )

    async def signal_connector_manual_import(
        self,
        request: WorkflowConnectorManualImportSignalRequest,
    ) -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="runtime_signal_deferred",
            adapter=self.adapter_name,
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )

    async def signal_connector_evidence_snapshot_export(
        self,
        request: WorkflowConnectorEvidenceSnapshotExportSignalRequest,
    ) -> WorkflowSignalResult:
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="runtime_signal_deferred",
            adapter=self.adapter_name,
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )


def workflow_signal_failure_result(
    request: (
        WorkflowSignalRequest
        | WorkflowActionSignalRequest
        | WorkflowConnectorManualImportSignalRequest
        | WorkflowConnectorEvidenceSnapshotExportSignalRequest
    ),
    reason: str,
    adapter: str = TemporalWorkflowSignalRuntime.adapter_name,
) -> WorkflowSignalResult:
    return WorkflowSignalResult(
        workflow_id=request.workflow_id,
        status="runtime_signal_unavailable",
        adapter=adapter,
        signal_name=request.signal_name,
        payload={**request.audit_payload, "reason": reason},
    )
