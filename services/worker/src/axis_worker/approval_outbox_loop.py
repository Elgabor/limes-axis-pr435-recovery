"""Process-local delivery loop for transactional approval decisions.

Approval decisions are committed to the API database before they are sent to
Temporal.  This loop owns the delivery side of that boundary.  It deliberately
runs beside the Temporal worker rather than as a Temporal Schedule: using the
system being delivered to as the scheduler would make an unavailable Temporal
cluster unable to drive its own recovery.

The reusable dispatcher owns claiming, delivery, retry backoff, and durable
state transitions.  This module only provides process lifecycle semantics:

* drain immediately while work is available;
* sleep between empty polls;
* isolate operational failures and retry them;
* propagate cancellation promptly during worker shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger("axis_worker.approval_outbox_loop")


class DispatchResult(Protocol):
    """Minimum result surface needed by the process loop."""

    claimed: int


class Dispatcher(Protocol):
    """Structural contract shared by the supervised dispatch loops."""

    async def run_once(self) -> DispatchResult: ...


async def run_dispatch_loop(
    dispatcher: Dispatcher,
    *,
    interval_seconds: float,
    logger: logging.Logger,
) -> None:
    """Continuously run ``dispatcher`` until the surrounding worker cancels it.

    A successful batch that claimed rows is followed immediately by another
    batch so a deployment can catch up without adding one poll interval per
    batch.  ``sleep(0)`` still yields to the Temporal worker.  Empty batches and
    failures wait for the configured interval, preventing a hot loop when the
    database or Temporal is unavailable.

    Shared by every outbox-style sibling loop; the caller supplies the logger so
    operational logs name the boundary that actually failed.
    """

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    while True:
        try:
            result = await dispatcher.run_once()
            claimed = result.claimed
            if isinstance(claimed, bool) or not isinstance(claimed, int) or claimed < 0:
                raise ValueError(
                    "dispatcher result must expose a non-negative integer claimed count"
                )
        except asyncio.CancelledError:
            logger.info("dispatcher stopping")
            raise
        except Exception:
            logger.exception(
                "dispatch failed; retrying in %.3fs",
                interval_seconds,
            )
            await asyncio.sleep(interval_seconds)
            continue

        if claimed:
            logger.info(
                "batch processed claimed=%s",
                claimed,
            )

        await asyncio.sleep(0 if claimed else interval_seconds)


async def run_approval_decision_outbox_loop(
    dispatcher: Dispatcher,
    *,
    interval_seconds: float,
) -> None:
    await run_dispatch_loop(
        dispatcher,
        interval_seconds=interval_seconds,
        logger=logger,
    )


_source_ingestion_logger = logging.getLogger("axis_worker.source_ingestion_loop")


async def run_source_ingestion_loop(
    dispatcher: Dispatcher,
    *,
    interval_seconds: float,
) -> None:
    """Process-lifecycle loop for governed source ingestion dispatch."""

    await run_dispatch_loop(
        dispatcher,
        interval_seconds=interval_seconds,
        logger=_source_ingestion_logger,
    )
