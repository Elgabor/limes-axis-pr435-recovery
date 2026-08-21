"""Schedule-registration bootstrap tests with a thin in-memory fake Temporal client.

These tests never require a live Temporal (they run in the default suite). They
verify the create-or-update bootstrap is idempotent: a first pass creates each
schedule, a second pass updates in place with no duplicates, and the enable flag
controls the paused state.
"""

from __future__ import annotations

import pytest
from axis_api.config import Settings
from temporalio.client import Schedule, ScheduleAlreadyRunningError
from temporalio.service import RPCError, RPCStatusCode

from axis_worker.schedules import (
    AUDIT_RETENTION_SCHEDULE_ID,
    CONNECTOR_LIVE_SYNC_SCHEDULE_ID,
    SESSION_SWEEP_SCHEDULE_ID,
    TENANT_RECONCILIATION_SCHEDULE_ID,
    register_maintenance_schedules,
)

pytestmark = pytest.mark.asyncio


class FakeScheduleHandle:
    def __init__(self, store: dict[str, Schedule], schedule_id: str) -> None:
        self._store = store
        self._schedule_id = schedule_id
        self.update_calls = 0
        self.pause_calls = 0

    async def update(self, updater) -> None:
        self.update_calls += 1
        current = self._store[self._schedule_id]
        update = await updater(_FakeUpdateInput(_FakeDescription(current)))
        self._store[self._schedule_id] = update.schedule

    async def pause(self, *, note: str | None = None) -> None:
        self.pause_calls += 1
        try:
            schedule = self._store[self._schedule_id]
        except KeyError as exc:
            raise RPCError("schedule not found", RPCStatusCode.NOT_FOUND, b"") from exc
        schedule.state.paused = True
        schedule.state.note = note


class _FakeDescription:
    """Mirrors the ``ScheduleDescription`` seen by an update callback."""

    def __init__(self, schedule: Schedule) -> None:
        self.schedule = schedule


class _FakeUpdateInput:
    def __init__(self, description: _FakeDescription) -> None:
        self.description = description


class FakeScheduleClient:
    """In-memory stand-in for the schedule slice of ``temporalio.client.Client``."""

    def __init__(self) -> None:
        self.schedules: dict[str, Schedule] = {}
        self.create_calls: list[str] = []
        self.handles: dict[str, FakeScheduleHandle] = {}

    async def create_schedule(self, id: str, schedule: Schedule):
        self.create_calls.append(id)
        if id in self.schedules:
            raise ScheduleAlreadyRunningError()
        self.schedules[id] = schedule
        return self.get_schedule_handle(id)

    def get_schedule_handle(self, id: str) -> FakeScheduleHandle:
        handle = self.handles.get(id)
        if handle is None:
            handle = FakeScheduleHandle(self.schedules, id)
            self.handles[id] = handle
        return handle


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


ALL_IDS = {
    AUDIT_RETENTION_SCHEDULE_ID,
    SESSION_SWEEP_SCHEDULE_ID,
    TENANT_RECONCILIATION_SCHEDULE_ID,
}


async def test_register_creates_all_schedules_first_run() -> None:
    client = FakeScheduleClient()
    outcomes = await register_maintenance_schedules(
        client, _settings(), task_queue="axis-foundation"
    )

    assert set(outcomes) == ALL_IDS
    assert all(outcome == "created" for outcome in outcomes.values())
    assert set(client.schedules) == ALL_IDS


async def test_register_is_idempotent_updates_in_place_no_duplicates() -> None:
    client = FakeScheduleClient()
    settings = _settings()

    first = await register_maintenance_schedules(client, settings, task_queue="axis-foundation")
    assert all(outcome == "created" for outcome in first.values())

    second = await register_maintenance_schedules(client, settings, task_queue="axis-foundation")

    assert all(outcome == "updated" for outcome in second.values())
    # Still exactly one schedule per id: no duplicates were created.
    assert set(client.schedules) == ALL_IDS
    assert len(client.schedules) == 3
    # Each existing schedule was updated in place exactly once on the second pass.
    for schedule_id in ALL_IDS:
        assert client.handles[schedule_id].update_calls == 1


async def test_schedules_paused_when_disabled_and_active_when_enabled() -> None:
    disabled_client = FakeScheduleClient()
    await register_maintenance_schedules(
        disabled_client,
        _settings(AXIS_SCHEDULED_JOBS_ENABLED="false"),
        task_queue="axis-foundation",
    )
    assert all(schedule.state.paused for schedule in disabled_client.schedules.values())

    enabled_client = FakeScheduleClient()
    await register_maintenance_schedules(
        enabled_client,
        _settings(AXIS_SCHEDULED_JOBS_ENABLED="true"),
        task_queue="axis-foundation",
    )
    assert all(not schedule.state.paused for schedule in enabled_client.schedules.values())


async def test_disabled_master_switch_repauses_manually_unpaused_schedule() -> None:
    # First worker start with jobs disabled: schedules are created paused.
    client = FakeScheduleClient()
    disabled = _settings(AXIS_SCHEDULED_JOBS_ENABLED="false")
    await register_maintenance_schedules(client, disabled, task_queue="axis-foundation")
    assert all(schedule.state.paused for schedule in client.schedules.values())

    # An operator manually unpauses one schedule in the Temporal UI.
    unpaused = client.schedules[SESSION_SWEEP_SCHEDULE_ID]
    unpaused.state.paused = False

    # A worker restart with the master switch disabled must fail closed even if
    # the schedule was manually unpaused out of band.
    second = await register_maintenance_schedules(client, disabled, task_queue="axis-foundation")
    assert all(outcome == "updated" for outcome in second.values())
    assert all(schedule.state.paused for schedule in client.schedules.values())


async def test_disabling_master_switch_pauses_existing_active_schedules() -> None:
    client = FakeScheduleClient()
    enabled = _settings(AXIS_SCHEDULED_JOBS_ENABLED="true")
    await register_maintenance_schedules(client, enabled, task_queue="axis-foundation")
    assert all(not schedule.state.paused for schedule in client.schedules.values())

    disabled = _settings(AXIS_SCHEDULED_JOBS_ENABLED="false")
    await register_maintenance_schedules(client, disabled, task_queue="axis-foundation")

    assert all(schedule.state.paused for schedule in client.schedules.values())


async def test_update_preserves_operator_paused_state_when_flag_enabled() -> None:
    # Schedules created active (flag enabled).
    client = FakeScheduleClient()
    enabled = _settings(AXIS_SCHEDULED_JOBS_ENABLED="true")
    await register_maintenance_schedules(client, enabled, task_queue="axis-foundation")

    # Operator pauses one schedule; a restart must not force it back to active.
    client.schedules[AUDIT_RETENTION_SCHEDULE_ID].state.paused = True
    await register_maintenance_schedules(client, enabled, task_queue="axis-foundation")
    assert client.schedules[AUDIT_RETENTION_SCHEDULE_ID].state.paused is True
    assert client.schedules[SESSION_SWEEP_SCHEDULE_ID].state.paused is False


async def test_schedule_intervals_read_from_settings() -> None:
    client = FakeScheduleClient()
    settings = _settings(
        AXIS_SCHEDULED_AUDIT_RETENTION_INTERVAL_SECONDS="1000",
        AXIS_SCHEDULED_SESSION_SWEEP_INTERVAL_SECONDS="200",
        AXIS_SCHEDULED_TENANT_RECONCILIATION_INTERVAL_SECONDS="300",
    )
    await register_maintenance_schedules(client, settings, task_queue="axis-foundation")

    audit = client.schedules[AUDIT_RETENTION_SCHEDULE_ID]
    assert audit.spec.intervals[0].every.total_seconds() == 1000
    sweep = client.schedules[SESSION_SWEEP_SCHEDULE_ID]
    assert sweep.spec.intervals[0].every.total_seconds() == 200


async def test_connector_live_sync_schedule_absent_when_flag_disabled() -> None:
    client = FakeScheduleClient()
    outcomes = await register_maintenance_schedules(
        client, _settings(), task_queue="axis-foundation"
    )

    # Flag-off keeps today's exact schedule set: no new schedule appears.
    assert set(outcomes) == ALL_IDS
    assert CONNECTOR_LIVE_SYNC_SCHEDULE_ID not in client.schedules


async def test_connector_live_sync_schedule_registered_behind_flag() -> None:
    client = FakeScheduleClient()
    settings = _settings(
        AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED="true",
        AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_INTERVAL_SECONDS="600",
        AXIS_SCHEDULED_JOBS_ENABLED="true",
    )
    outcomes = await register_maintenance_schedules(client, settings, task_queue="axis-foundation")

    assert set(outcomes) == ALL_IDS | {CONNECTOR_LIVE_SYNC_SCHEDULE_ID}
    schedule = client.schedules[CONNECTOR_LIVE_SYNC_SCHEDULE_ID]
    assert schedule.spec.intervals[0].every.total_seconds() == 600
    assert schedule.state.paused is False


async def test_connector_live_sync_schedule_created_paused_without_master_flag() -> None:
    client = FakeScheduleClient()
    settings = _settings(
        AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED="true",
        AXIS_SCHEDULED_JOBS_ENABLED="false",
    )
    await register_maintenance_schedules(client, settings, task_queue="axis-foundation")

    # The master scheduled-jobs flag still seeds the created paused state.
    assert client.schedules[CONNECTOR_LIVE_SYNC_SCHEDULE_ID].state.paused is True


async def test_disabling_connector_live_sync_pauses_existing_schedule() -> None:
    client = FakeScheduleClient()
    enabled = _settings(
        AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED="true",
        AXIS_SCHEDULED_JOBS_ENABLED="true",
    )
    await register_maintenance_schedules(client, enabled, task_queue="axis-foundation")
    assert client.schedules[CONNECTOR_LIVE_SYNC_SCHEDULE_ID].state.paused is False

    disabled = _settings(
        AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED="false",
        AXIS_SCHEDULED_JOBS_ENABLED="true",
    )
    outcomes = await register_maintenance_schedules(client, disabled, task_queue="axis-foundation")

    assert outcomes[CONNECTOR_LIVE_SYNC_SCHEDULE_ID] == "paused"
    assert client.schedules[CONNECTOR_LIVE_SYNC_SCHEDULE_ID].state.paused is True
    assert all(not client.schedules[schedule_id].state.paused for schedule_id in ALL_IDS)


async def test_disabled_connector_live_sync_reconciliation_is_idempotent() -> None:
    client = FakeScheduleClient()
    enabled = _settings(
        AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED="true",
        AXIS_SCHEDULED_JOBS_ENABLED="true",
    )
    await register_maintenance_schedules(client, enabled, task_queue="axis-foundation")

    disabled = _settings(
        AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED="false",
        AXIS_SCHEDULED_JOBS_ENABLED="true",
    )
    first = await register_maintenance_schedules(client, disabled, task_queue="axis-foundation")
    second = await register_maintenance_schedules(client, disabled, task_queue="axis-foundation")

    assert first[CONNECTOR_LIVE_SYNC_SCHEDULE_ID] == "paused"
    assert second[CONNECTOR_LIVE_SYNC_SCHEDULE_ID] == "paused"
    assert set(client.schedules) == ALL_IDS | {CONNECTOR_LIVE_SYNC_SCHEDULE_ID}
    assert client.schedules[CONNECTOR_LIVE_SYNC_SCHEDULE_ID].state.paused is True
    assert client.handles[CONNECTOR_LIVE_SYNC_SCHEDULE_ID].pause_calls == 2
