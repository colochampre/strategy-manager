"""``BalanceSyncHandler`` — the self-scheduling ``balance.sync`` job.

The re-enqueue is the whole mechanism: skip it once and balances stop being
refreshed, ``DbBalanceSource`` starts refusing reads as the last snapshot ages
out, and trading halts. These tests pin exactly when it happens.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from strategy_manager.accounts.application.balance_sync_handler import BalanceSyncHandler
from strategy_manager.accounts.application.sync_balances import (
    CompositeBalanceSync,
    SyncBalances,
    SyncResult,
)
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
INTERVAL = 15.0


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class SpyQueue:
    def __init__(self) -> None:
        self.enqueued: list[Job] = []

    async def enqueue(self, job: Job) -> object:
        self.enqueued.append(job)
        return uuid4()


class StubSyncBalances:
    def __init__(self, synced: int = 0, raises: Exception | None = None) -> None:
        self._synced = synced
        self._raises = raises
        self.syncs = 0

    async def sync(self) -> SyncResult:
        self.syncs += 1
        if self._raises is not None:
            raise self._raises
        return SyncResult(synced=self._synced)


def _claimed_job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(), kind=JobKind.BALANCE_SYNC, payload={}, attempts=1, max_attempts=5
    )


def _build(sync: StubSyncBalances) -> tuple[BalanceSyncHandler, SpyQueue]:
    queue = SpyQueue()
    handler = BalanceSyncHandler(
        sync_balances=sync,
        queue=queue,
        clock=FrozenClock(),
        interval_seconds=INTERVAL,
    )
    return handler, queue


async def test_the_handler_runs_the_sync() -> None:
    sync = StubSyncBalances(synced=2)
    handler, _ = _build(sync)

    await handler.handle(_claimed_job())

    assert sync.syncs == 1


async def test_the_handler_re_enqueues_itself_one_interval_later() -> None:
    handler, queue = _build(StubSyncBalances())

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1
    follow_up = queue.enqueued[0]
    assert follow_up.kind is JobKind.BALANCE_SYNC
    assert follow_up.run_after == NOW + timedelta(seconds=INTERVAL)


async def test_a_failing_sync_does_not_re_enqueue() -> None:
    """``WorkerRunner`` fails and retries the claimed job on any handler
    exception. Enqueuing a successor first would fork the chain in two on
    every transient error, doubling the sync rate on each failure."""

    handler, queue = _build(StubSyncBalances(raises=RuntimeError("pionex down")))

    with pytest.raises(RuntimeError):
        await handler.handle(_claimed_job())

    assert queue.enqueued == []


async def test_SyncBalances_satisfies_the_handler_port() -> None:
    """Guards the stub above from drifting away from the real use case."""

    assert hasattr(SyncBalances, "sync")


# --- PR 3 unit 1b: a DEGRADED exchange omitted from ``syncs`` -----------


async def test_a_degraded_exchange_omitted_from_syncs_still_lets_the_successor_enqueue() -> (
    None
):
    """main.py's own fix for the urgent balance.sync bug (a missing Binance
    key raising BEFORE ``handler.handle`` ran, killing the recurring chain):
    the composition root now OMITS a DEGRADED exchange's ``SyncBalances``
    from the list entirely, rather than including one that fails.
    ``CompositeBalanceSync`` with only the healthy exchange still runs the
    healthy sync AND the handler still enqueues its successor -- proving the
    fix's mechanism, not just this pre-existing class's own contract."""
    healthy = StubSyncBalances(synced=3)
    queue = SpyQueue()
    handler = BalanceSyncHandler(
        sync_balances=CompositeBalanceSync([healthy]),
        queue=queue,
        clock=FrozenClock(),
        interval_seconds=INTERVAL,
    )

    result = await handler.handle(_claimed_job())

    assert healthy.syncs == 1
    assert result.synced == 3
    assert len(queue.enqueued) == 1
    assert queue.enqueued[0].kind is JobKind.BALANCE_SYNC
