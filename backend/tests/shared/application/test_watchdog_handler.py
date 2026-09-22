"""``WatchdogHandler`` — the self-scheduling ``watchdog.check`` job.

Same shape as ``JobsPurgeHandler``/``SweepHandler``: no cron, each run enqueues
its own successor, and the successor is written only after the check returns
without raising, so a transient failure retries instead of forking the chain.

The one thing this handler has that the others do not is a MEMORY. A FAILED
job row is never purged, so "what failed since the last time anyone looked"
needs a previous timestamp, and the chain carries its own: each run hands its
``checked_at`` to its successor in the payload. That is deliberately the only
state — no table, no column, nothing to migrate — and losing it costs one
window, not the check.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.watchdog import WatchdogReport
from strategy_manager.shared.application.watchdog_handler import WatchdogHandler

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
INTERVAL = 300.0


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class SpyQueue:
    def __init__(self) -> None:
        self.enqueued: list[Job] = []

    async def enqueue(self, job: Job) -> UUID:
        self.enqueued.append(job)
        return uuid4()


class SpyWatchdog:
    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises
        self.calls: list[datetime | None] = []

    async def check(self, since: datetime | None = None) -> WatchdogReport:
        self.calls.append(since)
        if self._raises is not None:
            raise self._raises
        return WatchdogReport(
            checked_at=NOW,
            stale_pools=(),
            unscheduled_kinds=(),
            failures=(),
            dropped_alerts=0,
        )


def _claimed_job(payload: dict[str, Any] | None = None) -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        kind=JobKind.WATCHDOG_CHECK,
        payload=payload if payload is not None else {},
        attempts=1,
        max_attempts=5,
    )


def _build(watchdog: SpyWatchdog) -> tuple[WatchdogHandler, SpyQueue]:
    queue = SpyQueue()
    handler = WatchdogHandler(
        watchdog=watchdog,  # type: ignore[arg-type]
        queue=queue,
        clock=FrozenClock(),
        interval_seconds=INTERVAL,
    )
    return handler, queue


async def test_the_chain_enqueues_its_own_successor_one_interval_out() -> None:
    handler, queue = _build(SpyWatchdog())

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1
    successor = queue.enqueued[0]
    assert successor.kind == JobKind.WATCHDOG_CHECK
    assert successor.run_after == NOW + timedelta(seconds=INTERVAL)


async def test_the_successor_carries_this_run_s_timestamp_as_its_window() -> None:
    handler, queue = _build(SpyWatchdog())

    await handler.handle(_claimed_job())

    assert queue.enqueued[0].payload == {"since": NOW.isoformat()}


async def test_the_payload_timestamp_is_the_window_the_check_is_given() -> None:
    watchdog = SpyWatchdog()
    handler, _ = _build(watchdog)
    previous = NOW - timedelta(seconds=INTERVAL)

    await handler.handle(_claimed_job({"since": previous.isoformat()}))

    assert watchdog.calls == [previous]


async def test_a_seeded_job_carries_no_window_and_says_so() -> None:
    """``RecurringJobSeeder`` enqueues an EMPTY payload — both on a first
    start and when reviving a chain that died. That is the one case where the
    previous run is genuinely unknown, and the use case owns the fallback."""
    watchdog = SpyWatchdog()
    handler, _ = _build(watchdog)

    await handler.handle(_claimed_job({}))

    assert watchdog.calls == [None]


@pytest.mark.parametrize("since", ["not-a-timestamp", "", 17, None])
async def test_a_malformed_window_is_ignored_rather_than_killing_the_chain(
    since: object,
) -> None:
    """A watchdog that dies of its own bookkeeping is worse than one that
    re-reads a few minutes of history: the chain it belongs to is the one
    nothing else is watching."""
    watchdog = SpyWatchdog()
    handler, queue = _build(watchdog)

    await handler.handle(_claimed_job({"since": since}))

    assert watchdog.calls == [None]
    assert len(queue.enqueued) == 1


async def test_a_naive_timestamp_is_ignored_too() -> None:
    """Every clock in this system is timezone-aware, so a naive value did not
    come from a previous run — and comparing one against an aware ``now``
    raises inside the query rather than at the boundary."""
    watchdog = SpyWatchdog()
    handler, _ = _build(watchdog)

    await handler.handle(_claimed_job({"since": "2026-09-21T11:55:00"}))

    assert watchdog.calls == [None]


async def test_no_successor_is_enqueued_when_the_check_raises() -> None:
    """The job then FAILs and retries with its attempt count intact. Enqueuing
    first would fork the chain in two on the first transient fault."""
    handler, queue = _build(SpyWatchdog(raises=RuntimeError("database is gone")))

    with pytest.raises(RuntimeError):
        await handler.handle(_claimed_job())

    assert queue.enqueued == []
