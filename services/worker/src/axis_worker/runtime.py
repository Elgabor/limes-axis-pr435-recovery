"""Worker runtime entry point: connect to Temporal, register schedules, poll.

This is the process that ``make`` / docker-compose runs. On startup it:

1. builds the shared ``axis_api.config.Settings`` (same env the API reads);
2. connects to Temporal;
3. idempotently creates/updates the maintenance Schedules (paused unless
   ``AXIS_SCHEDULED_JOBS_ENABLED`` is true);
4. optionally starts the process-local approval-decision outbox dispatcher;
5. runs a Temporal :class:`~temporalio.worker.Worker` on the ``axis-foundation``
   task queue hosting the approval workflow plus the scheduled maintenance
   workflows and their DB-owning activities.

Kept import-light and side-effect free at module load so tests can import the
pieces without connecting to Temporal.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Protocol

from axis_api.approval_outbox import ApprovalDecisionOutboxDispatcher
from axis_api.config import Settings
from axis_api.connector_s3_ingestion import S3IngestionRuntime
from axis_api.connector_source_extraction import SelfHostedPostgresExtractionRuntime
from axis_api.connector_source_ingestion import (
    ObservationFreshnessIngestionRuntime,
    SourceIngestionOutboxDispatcher,
)
from axis_api.db import create_session_factory
from axis_api.object_storage import build_connector_export_object_store
from axis_api.telemetry import shutdown_providers
from axis_api.workflow_runtime import (
    TemporalWorkflowSignalConfig,
    TemporalWorkflowSignalRuntime,
)
from temporalio.client import Client
from temporalio.worker import Worker

from axis_worker.approval_outbox_loop import (
    Dispatcher,
    DispatchResult,
    run_approval_decision_outbox_loop,
    run_source_ingestion_loop,
)
from axis_worker.connector_live_sync_activities import ConnectorLiveSyncActivities
from axis_worker.maintenance_activities import MaintenanceActivities
from axis_worker.schedules import register_maintenance_schedules
from axis_worker.telemetry import (
    WorkerTelemetryRuntime,
    configure_worker_telemetry,
)
from axis_worker.temporal_adapter import TemporalAdapterConfig
from axis_worker.workflows.approval_workflow import ApprovalWorkflow
from axis_worker.workflows.connector_live_sync_workflows import (
    ConnectorScheduledLiveSyncWorkflow,
)
from axis_worker.workflows.maintenance_workflows import (
    AuditRetentionDeletionWorkflow,
    OrphanedSessionSweepWorkflow,
    TenantStateReconciliationWorkflow,
)

logger = logging.getLogger("axis_worker.runtime")

WORKFLOWS = [
    ApprovalWorkflow,
    AuditRetentionDeletionWorkflow,
    OrphanedSessionSweepWorkflow,
    TenantStateReconciliationWorkflow,
    ConnectorScheduledLiveSyncWorkflow,
]


class RunnableWorker(Protocol):
    async def run(self) -> None: ...


def adapter_config_from_settings(settings: Settings) -> TemporalAdapterConfig:
    return TemporalAdapterConfig(
        address=settings.temporal_address,
        namespace=settings.temporal_namespace,
    )


def build_approval_decision_outbox_dispatcher(
    settings: Settings,
) -> ApprovalDecisionOutboxDispatcher:
    """Build the DB and Temporal dependencies owned by the delivery loop."""

    workflow_runtime = TemporalWorkflowSignalRuntime(
        TemporalWorkflowSignalConfig(
            address=settings.temporal_address,
            namespace=settings.temporal_namespace,
            signal_timeout_seconds=settings.temporal_signal_timeout_seconds,
        )
    )
    return ApprovalDecisionOutboxDispatcher(
        settings=settings,
        session_factory=create_session_factory(settings),
        workflow_runtime=workflow_runtime,
    )


def optional_approval_decision_outbox_dispatcher(
    settings: Settings,
) -> ApprovalDecisionOutboxDispatcher | None:
    """Return a dispatcher only when the dedicated worker switch is enabled."""

    if not settings.approval_decision_outbox_dispatch_enabled:
        return None
    return build_approval_decision_outbox_dispatcher(settings)


class _InstrumentedIngestionDispatcher:
    """Emit metadata-only counters for one governed ingestion dispatch pass."""

    def __init__(
        self,
        inner: Dispatcher,
        telemetry: WorkerTelemetryRuntime,
    ) -> None:
        self._inner = inner
        self._telemetry = telemetry

    async def run_once(self) -> DispatchResult:
        result = await self._inner.run_once()
        for outcome in ("completed", "retried", "dead_lettered", "fenced"):
            count = getattr(result, outcome, 0)
            if count:
                self._telemetry.source_ingestion_stage_counter.add(
                    count,
                    {"outcome": outcome},
                )
        return result


def optional_source_ingestion_dispatcher(
    settings: Settings,
    telemetry: WorkerTelemetryRuntime | None = None,
) -> Dispatcher | None:
    """Return the governed source ingestion dispatcher when enabled.

    The validation-stage runtime never dials a source; it re-checks pinned
    fingerprints against Axis' own observations and records that no extraction
    happened.  A future extraction runtime implements the same port.  When a
    telemetry runtime is supplied, dispatch passes emit outcome counters.
    """

    if not settings.source_ingestion_dispatch_enabled:
        return None
    extraction_runtime = None
    s3_runtime = None
    if settings.source_ingestion_extraction_enabled:
        # Real bounded extraction through the canonical object-store seam;
        # never constructed when either gate is off.
        object_store = build_connector_export_object_store(settings)
        extraction_runtime = SelfHostedPostgresExtractionRuntime(
            settings=settings, object_store=object_store,
        )
        if settings.s3_source_ingestion_enabled:
            s3_runtime = S3IngestionRuntime(settings, object_store=object_store)
    dispatcher = SourceIngestionOutboxDispatcher(
        settings=settings,
        session_factory=create_session_factory(settings),
        runtime=ObservationFreshnessIngestionRuntime(),
        extraction_runtime=extraction_runtime,
        s3_runtime=s3_runtime,
    )
    if telemetry is not None:
        return _InstrumentedIngestionDispatcher(dispatcher, telemetry)
    return dispatcher


async def run_worker_with_optional_outbox(
    worker: RunnableWorker,
    *,
    dispatcher: Dispatcher | None,
    dispatch_interval_seconds: float,
    ingestion_dispatcher: Dispatcher | None = None,
    ingestion_dispatch_interval_seconds: float = 15.0,
) -> None:
    """Run Temporal polling while supervising the optional sibling loops.

    Each outbox loop catches and retries operational exceptions internally.  The
    Temporal worker remains the lifetime owner: when it returns, fails, or is
    cancelled, the sibling loops are cancelled and awaited before control leaves
    this function.
    """

    tasks = []
    if dispatcher is not None:
        tasks.append(
            asyncio.create_task(
                run_approval_decision_outbox_loop(
                    dispatcher,
                    interval_seconds=dispatch_interval_seconds,
                ),
                name="approval-decision-outbox-dispatcher",
            )
        )
    if ingestion_dispatcher is not None:
        tasks.append(
            asyncio.create_task(
                run_source_ingestion_loop(
                    ingestion_dispatcher,
                    interval_seconds=ingestion_dispatch_interval_seconds,
                ),
                name="source-ingestion-dispatcher",
            )
        )
    if not tasks:
        await worker.run()
        return

    try:
        await worker.run()
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


async def run_worker(settings: Settings | None = None) -> None:
    settings = settings or Settings()
    config = adapter_config_from_settings(settings)
    telemetry = configure_worker_telemetry(settings)
    logger.info("axis-worker telemetry enabled=%s", telemetry.enabled)
    client = await Client.connect(config.address, namespace=config.namespace)

    outcomes = await register_maintenance_schedules(
        client, settings, task_queue=config.task_queue
    )
    logger.info(
        "scheduled maintenance schedules reconciled enabled=%s outcomes=%s",
        settings.scheduled_jobs_enabled,
        outcomes,
    )

    activities = MaintenanceActivities(settings, telemetry=telemetry)
    live_sync_activities = ConnectorLiveSyncActivities(settings, telemetry=telemetry)
    worker = Worker(
        client,
        task_queue=config.task_queue,
        workflows=WORKFLOWS,
        activities=[
            activities.run_audit_retention_deletion,
            activities.run_orphaned_session_sweep,
            activities.run_tenant_state_reconciliation,
            live_sync_activities.list_scheduled_live_sync_candidates,
            live_sync_activities.claim_scheduled_live_sync_checkpoint,
            live_sync_activities.execute_scheduled_live_sync,
            live_sync_activities.release_scheduled_live_sync_claim,
        ],
    )
    dispatcher = optional_approval_decision_outbox_dispatcher(settings)
    if dispatcher is not None:
        logger.info(
            "approval-decision outbox dispatcher enabled interval_seconds=%s",
            settings.approval_decision_outbox_dispatch_interval_seconds,
        )
    else:
        logger.info("approval-decision outbox dispatcher disabled")
    ingestion_dispatcher = optional_source_ingestion_dispatcher(
        settings, telemetry=telemetry
    )
    if ingestion_dispatcher is not None:
        logger.info(
            "source-ingestion dispatcher enabled interval_seconds=%s",
            settings.source_ingestion_dispatch_interval_seconds,
        )
    else:
        logger.info("source-ingestion dispatcher disabled")
    logger.info("axis-worker started task_queue=%s", config.task_queue)
    try:
        await run_worker_with_optional_outbox(
            worker,
            dispatcher=dispatcher,
            dispatch_interval_seconds=settings.approval_decision_outbox_dispatch_interval_seconds,
            ingestion_dispatcher=ingestion_dispatcher,
            ingestion_dispatch_interval_seconds=(
                settings.source_ingestion_dispatch_interval_seconds
            ),
        )
    finally:
        if telemetry.enabled:
            shutdown_providers(telemetry.tracer_provider, telemetry.meter_provider)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
