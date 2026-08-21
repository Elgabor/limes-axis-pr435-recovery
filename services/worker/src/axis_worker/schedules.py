"""Idempotent Temporal Schedule registration for scheduled maintenance jobs.

Uses the modern Temporal Python SDK Schedule API (``temporalio>=1.24`` ships it;
the repo pins 1.29). Each maintenance job maps to one Schedule whose interval is
read from the shared ``axis_api.config.Settings`` and whose overlap policy is
``SKIP`` — a slow run never overlaps its successor, which, combined with each
job's own idempotency, makes repeated/overlapping invocations safe.

``register_maintenance_schedules`` is create-or-update idempotent: on first run it
creates each Schedule; on subsequent runs it updates the existing Schedule in
place (interval/overlap/paused) without creating duplicates. Optional schedules
that were previously created are paused when their feature is disabled. The
Temporal client is used behind a narrow :class:`ScheduleClientPort` protocol so
tests can drive a thin in-memory fake and never require a live Temporal.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from axis_api.config import Settings
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleHandle,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode

from axis_worker.workflows.connector_live_sync_workflows import (
    ConnectorScheduledLiveSyncWorkflow,
)
from axis_worker.workflows.maintenance_workflows import (
    AuditRetentionDeletionWorkflow,
    OrphanedSessionSweepWorkflow,
    TenantStateReconciliationWorkflow,
)

AUDIT_RETENTION_SCHEDULE_ID = "axis-audit-retention-deletion"
SESSION_SWEEP_SCHEDULE_ID = "axis-orphaned-session-sweep"
TENANT_RECONCILIATION_SCHEDULE_ID = "axis-tenant-state-reconciliation"
CONNECTOR_LIVE_SYNC_SCHEDULE_ID = "axis-connector-scheduled-live-sync"
CONNECTOR_LIVE_SYNC_DISABLED_NOTE = (
    "Paused by axis-worker because scheduled connector live sync is disabled."
)


class ScheduleClientPort(Protocol):
    """Narrow slice of ``temporalio.client.Client`` used for schedule registration."""

    async def create_schedule(self, id: str, schedule: Schedule) -> ScheduleHandle: ...

    def get_schedule_handle(self, id: str) -> ScheduleHandle: ...


@dataclass(frozen=True)
class ScheduledJobSpec:
    schedule_id: str
    workflow: Callable[..., Awaitable[object]]
    workflow_id: str
    interval_seconds: int


def build_scheduled_job_specs(settings: Settings) -> list[ScheduledJobSpec]:
    specs = [
        ScheduledJobSpec(
            schedule_id=AUDIT_RETENTION_SCHEDULE_ID,
            workflow=AuditRetentionDeletionWorkflow.run,
            workflow_id="axis-audit-retention-deletion-run",
            interval_seconds=settings.scheduled_audit_retention_interval_seconds,
        ),
        ScheduledJobSpec(
            schedule_id=SESSION_SWEEP_SCHEDULE_ID,
            workflow=OrphanedSessionSweepWorkflow.run,
            workflow_id="axis-orphaned-session-sweep-run",
            interval_seconds=settings.scheduled_session_sweep_interval_seconds,
        ),
        ScheduledJobSpec(
            schedule_id=TENANT_RECONCILIATION_SCHEDULE_ID,
            workflow=TenantStateReconciliationWorkflow.run,
            workflow_id="axis-tenant-state-reconciliation-run",
            interval_seconds=settings.scheduled_tenant_reconciliation_interval_seconds,
        ),
    ]
    if settings.connector_scheduled_live_sync_enabled:
        # A flag-off deployment does not create a new paused schedule. The
        # registration pass separately pauses one that it previously managed.
        specs.append(
            ScheduledJobSpec(
                schedule_id=CONNECTOR_LIVE_SYNC_SCHEDULE_ID,
                workflow=ConnectorScheduledLiveSyncWorkflow.run,
                workflow_id="axis-connector-scheduled-live-sync-run",
                interval_seconds=settings.connector_scheduled_live_sync_interval_seconds,
            )
        )
    return specs


def _build_schedule(spec: ScheduledJobSpec, *, task_queue: str, paused: bool) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            spec.workflow,
            id=spec.workflow_id,
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(seconds=spec.interval_seconds))],
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        state=ScheduleState(
            note="Managed by axis-worker scheduled maintenance bootstrap.",
            paused=paused,
        ),
    )


async def _create_or_update_schedule(
    client: ScheduleClientPort,
    spec: ScheduledJobSpec,
    *,
    task_queue: str,
    scheduled_jobs_enabled: bool,
) -> str:
    """Create the schedule, or update its definition in place if it exists.

    Returns ``"created"`` or ``"updated"``. Idempotent: repeated calls converge
    the persisted schedule's action/interval/overlap without ever creating a
    duplicate.

    The master enable flag is a fail-closed kill switch. Disabled schedules are
    always reconciled to paused, including schedules that already exist. When
    enabled, the operator's current paused state is preserved so reconciliation
    never reactivates a schedule that an operator paused in Temporal.
    """
    try:
        await client.create_schedule(
            spec.schedule_id,
            _build_schedule(
                spec,
                task_queue=task_queue,
                paused=not scheduled_jobs_enabled,
            ),
        )
        return "created"
    except ScheduleAlreadyRunningError:
        handle = client.get_schedule_handle(spec.schedule_id)

        async def _updater(schedule_input: ScheduleUpdateInput) -> ScheduleUpdate:
            existing_paused = schedule_input.description.schedule.state.paused
            effective_paused = not scheduled_jobs_enabled or existing_paused
            return ScheduleUpdate(
                schedule=_build_schedule(spec, task_queue=task_queue, paused=effective_paused)
            )

        await handle.update(_updater)
        return "updated"


async def _pause_schedule_if_present(
    client: ScheduleClientPort,
    schedule_id: str,
    *,
    note: str,
) -> bool:
    """Pause a previously managed schedule without creating it when absent."""
    handle = client.get_schedule_handle(schedule_id)
    try:
        await handle.pause(note=note)
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
    return True


async def register_maintenance_schedules(
    client: ScheduleClientPort,
    settings: Settings,
    *,
    task_queue: str,
) -> dict[str, str]:
    """Create/update every maintenance schedule idempotently.

    ``AXIS_SCHEDULED_JOBS_ENABLED=false`` forces every managed schedule to the
    paused state, including existing schedules. Disabling optional connector
    live sync also pauses its existing schedule without creating one when
    absent. When the master flag is true, reconciliation preserves the current
    operator pause state and never automatically reactivates a paused schedule.
    """
    outcomes: dict[str, str] = {}
    for spec in build_scheduled_job_specs(settings):
        outcomes[spec.schedule_id] = await _create_or_update_schedule(
            client,
            spec,
            task_queue=task_queue,
            scheduled_jobs_enabled=settings.scheduled_jobs_enabled,
        )
    if not settings.connector_scheduled_live_sync_enabled:
        connector_paused = await _pause_schedule_if_present(
            client,
            CONNECTOR_LIVE_SYNC_SCHEDULE_ID,
            note=CONNECTOR_LIVE_SYNC_DISABLED_NOTE,
        )
        if connector_paused:
            outcomes[CONNECTOR_LIVE_SYNC_SCHEDULE_ID] = "paused"
    return outcomes
