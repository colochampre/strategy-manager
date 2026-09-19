"""The worker process's claim loop and handler registry.

Decoupled from ``PostgresJobQueue``: it depends on a ``queue_factory`` — an
async context manager that yields a ``JobQueuePort`` (typically one bound to
a fresh session per iteration) — so the dispatch/ack/fail logic is testable
without a database.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager

from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.application.ports import JobQueuePort

logger = logging.getLogger(__name__)

JobHandler = Callable[[ClaimedJob], Awaitable[None]]
QueueFactory = Callable[[], AbstractAsyncContextManager[JobQueuePort]]

# Periodic maintenance that rides this loop rather than running beside it. The
# loop already ticks at the poll interval, so a hook here is how something
# recurring gets a heartbeat without a second task, a thread or a scheduler —
# and without a second process that could itself die unnoticed. The return
# value is ignored; the hook is expected to be self-describing in its own logs.
TickHook = Callable[[], Awaitable[object]]


class WorkerRunner:
    """Claims one job at a time and dispatches it to a registered handler."""

    def __init__(
        self,
        queue_factory: QueueFactory,
        handlers: Mapping[JobKind, JobHandler],
        poll_interval_seconds: float,
    ) -> None:
        self._queue_factory = queue_factory
        self._handlers = dict(handlers)
        self._poll_interval_seconds = poll_interval_seconds

    async def run_once(self) -> bool:
        """Claim and process at most one job. Returns whether one was found."""
        async with self._queue_factory() as queue:
            claimed = await queue.claim()
            if claimed is None:
                return False

            handler = self._handlers.get(claimed.kind)
            if handler is None:
                await queue.fail(
                    claimed.id, f"No handler registered for job kind '{claimed.kind.value}'"
                )
                return True

            try:
                await handler(claimed)
            except Exception as exc:  # noqa: BLE001 - any handler failure must retry, never crash the loop
                await queue.fail(claimed.id, str(exc))
                return True

            await queue.ack(claimed.id)
            return True

    async def run_forever(
        self, stop_event: asyncio.Event, on_tick: TickHook | None = None
    ) -> None:
        """Poll until ``stop_event`` is set, sleeping only when idle.

        ``on_tick`` runs once per iteration, before the claim. It decides for
        itself whether it is due — this loop only offers it a heartbeat.
        """
        while not stop_event.is_set():
            if on_tick is not None:
                try:
                    await on_tick()
                except Exception:  # noqa: BLE001 - maintenance must never kill the loop
                    # Same reasoning as the handler guard below: this process is
                    # the only thing executing signals, and a hook that cannot
                    # reach the database must not take that down with it.
                    logger.exception("worker tick hook failed; the claim loop continues")

            processed = await self.run_once()
            if not processed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self._poll_interval_seconds
                    )
