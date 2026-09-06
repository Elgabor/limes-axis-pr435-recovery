from __future__ import annotations

import asyncio
import runpy
from typing import Any

import pytest
from axis_api.config import Settings

import axis_worker.runtime as runtime_module
from axis_worker.runtime import (
    build_approval_decision_outbox_dispatcher,
    optional_approval_decision_outbox_dispatcher,
    run_worker_with_optional_outbox,
)


class _Result:
    claimed = 0


def test_package_entry_point_delegates_once_to_runtime(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(runtime_module, "main", lambda: calls.append("main"))
    runpy.run_module("axis_worker", run_name="__main__")
    assert calls == ["main"]


class _BlockingDispatcher:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.calls = 0

    async def run_once(self) -> _Result:
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        return _Result()


class _ReturningWorker:
    def __init__(self, wait_until: asyncio.Event | None = None) -> None:
        self.wait_until = wait_until
        self.calls = 0

    async def run(self) -> None:
        self.calls += 1
        if self.wait_until is not None:
            await self.wait_until.wait()


@pytest.mark.asyncio
async def test_disabled_supervision_runs_only_temporal_worker() -> None:
    worker = _ReturningWorker()

    await run_worker_with_optional_outbox(
        worker,
        dispatcher=None,
        dispatch_interval_seconds=5,
    )

    assert worker.calls == 1


@pytest.mark.asyncio
async def test_temporal_worker_and_dispatcher_run_concurrently_and_shutdown_cleanly() -> None:
    dispatcher = _BlockingDispatcher()
    worker = _ReturningWorker(wait_until=dispatcher.started)

    await run_worker_with_optional_outbox(
        worker,
        dispatcher=dispatcher,
        dispatch_interval_seconds=5,
    )

    assert worker.calls == 1
    assert dispatcher.calls == 1
    assert dispatcher.cancelled.is_set()


@pytest.mark.asyncio
async def test_worker_failure_cancels_dispatcher_and_propagates() -> None:
    dispatcher = _BlockingDispatcher()

    class FailingWorker:
        async def run(self) -> None:
            await dispatcher.started.wait()
            raise RuntimeError("worker stopped")

    with pytest.raises(RuntimeError, match="worker stopped"):
        await run_worker_with_optional_outbox(
            FailingWorker(),
            dispatcher=dispatcher,
            dispatch_interval_seconds=5,
        )

    assert dispatcher.cancelled.is_set()


def test_disabled_setting_does_not_construct_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(settings: Settings):
        raise AssertionError("disabled dispatcher must not allocate DB or Temporal clients")

    monkeypatch.setattr(
        runtime_module,
        "build_approval_decision_outbox_dispatcher",
        fail_if_called,
    )

    dispatcher = optional_approval_decision_outbox_dispatcher(
        Settings(AXIS_APPROVAL_DECISION_OUTBOX_DISPATCH_ENABLED=False)
    )

    assert dispatcher is None


def test_enabled_setting_constructs_dispatcher_with_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    session_factory = object()

    class FakeWorkflowRuntime:
        def __init__(self, config) -> None:
            captured["workflow_config"] = config

    class FakeDispatcher:
        def __init__(self, **kwargs) -> None:
            captured["dispatcher_kwargs"] = kwargs

    monkeypatch.setattr(runtime_module, "create_session_factory", lambda settings: session_factory)
    monkeypatch.setattr(runtime_module, "TemporalWorkflowSignalRuntime", FakeWorkflowRuntime)
    monkeypatch.setattr(runtime_module, "ApprovalDecisionOutboxDispatcher", FakeDispatcher)
    settings = Settings(
        AXIS_TEMPORAL_ADDRESS="temporal.internal:7233",
        AXIS_TEMPORAL_NAMESPACE="enterprise",
        AXIS_TEMPORAL_SIGNAL_TIMEOUT_SECONDS=7.5,
    )

    dispatcher = build_approval_decision_outbox_dispatcher(settings)

    assert isinstance(dispatcher, FakeDispatcher)
    workflow_config = captured["workflow_config"]
    assert workflow_config.address == "temporal.internal:7233"
    assert workflow_config.namespace == "enterprise"
    assert workflow_config.signal_timeout_seconds == 7.5
    dispatcher_kwargs = captured["dispatcher_kwargs"]
    assert dispatcher_kwargs["settings"] is settings
    assert dispatcher_kwargs["session_factory"] is session_factory
    assert isinstance(dispatcher_kwargs["workflow_runtime"], FakeWorkflowRuntime)
