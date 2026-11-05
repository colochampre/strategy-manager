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
    """Claims jobs and dispatches each to a registered handler: one at a time on
    its first loop, and beside it on ``lanes`` more, for a user's trading jobs."""

    def __init__(
        self,
        queue_factory: QueueFactory,
        handlers: Mapping[JobKind, JobHandler],
        poll_interval_seconds: float,
        lanes: int = 0,
    ) -> None:
        self._queue_factory = queue_factory
        self._handlers = dict(handlers)
        self._poll_interval_seconds = poll_interval_seconds
        self._lanes = lanes

    async def run_once(self, *, lane_only: bool = False) -> bool:
        """Claim and process at most one job. Returns whether one was found.

        ``lane_only`` is a lane's claim: only a user's trading jobs, kept one at a
        time per user by the queue (tasks.md G.7)."""
        async with self._queue_factory() as queue:
            claimed = await queue.claim(lane_only=True) if lane_only else await queue.claim()
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
                # Said out loud, not only written to ``jobs.last_error``. The
                # watchdog reports a job that exhausted ``max_attempts``; a
                # handler that threw once and succeeded on redelivery never
                # reaches that, so until this line the whole event lived in a
                # column nobody reads. The lost half of a concurrent
                # redelivery is exactly that shape: it raises a UNIQUE
                # violation, the retry resumes, and nothing is wrong — but
                # nothing said it happened either.
                #
                # The message is the same string ``fail()`` already persists,
                # with no traceback and no locals: a traceback out of this
                # loop once printed a database DSN.
                logger.warning(
                    "job %s (%s) failed on attempt %s of %s and will be retried "
                    "if attempts remain: %s",
                    claimed.id,
                    claimed.kind.value,
                    claimed.attempts,
                    claimed.max_attempts,
                    exc,
                )
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

        With ``lanes``, that many more loops run beside this one, each claiming only
        a user's trading jobs, so one signal's subscribers are worked in parallel
        (tasks.md G.7). They share one ``TaskGroup``: an error out of any loop ends
        them all and reaches the caller, inside an ``ExceptionGroup``, as an error out
        of the one loop ended the process before.
        """
        if self._lanes <= 0:
            await self._loop(stop_event, on_tick, lane_only=False)
            return
        async with asyncio.TaskGroup() as group:
            group.create_task(self._loop(stop_event, on_tick, lane_only=False))
            for _ in range(self._lanes):
                group.create_task(self._loop(stop_event, None, lane_only=True))

    async def _loop(
        self, stop_event: asyncio.Event, on_tick: TickHook | None, *, lane_only: bool
    ) -> None:
        while not stop_event.is_set():
            if on_tick is not None:
                try:
                    await on_tick()
                except Exception:  # noqa: BLE001 - maintenance must never kill the loop
                    # Same reasoning as the handler guard below: this process is
                    # the only thing executing signals, and a hook that cannot
                    # reach the database must not take that down with it.
                    logger.exception("worker tick hook failed; the claim loop continues")

            processed = await self.run_once(lane_only=lane_only)
            if not processed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self._poll_interval_seconds
                    )
