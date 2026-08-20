"""``BalanceSyncHandler``: the ``balance.sync`` job handler.

Self-scheduling, for the same reasons as ``SweepHandler``: no cron, no
external scheduler, each run enqueues its own successor. The two rules carried
over from that handler apply here unchanged — the successor is enqueued only
after the sync succeeds, so a transient failure retries instead of forking the
chain into two, and a sync that finds nothing changed still re-enqueues.

One difference matters. The sweeper's chain dying is a bookkeeping problem:
availability already excludes expired reservations, so nothing breaks. This
chain dying stops balances from being refreshed, and ``DbBalanceSource``
starts refusing reads once the last snapshot ages out. That is the designed
behaviour, not a bug — trading halts instead of running on fiction — but it
means this chain is the one worth alerting on.
"""

from datetime import timedelta
from typing import Protocol

from strategy_manager.accounts.application.sync_balances import SyncResult
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort


class SyncPort(Protocol):
    """What the handler needs from ``SyncBalances``, declared here so the
    handler never depends on the use case's construction."""

    async def sync(self) -> SyncResult: ...


class BalanceSyncHandler:
    def __init__(
        self,
        sync_balances: SyncPort,
        queue: JobQueuePort,
        clock: ClockPort,
        interval_seconds: float,
    ) -> None:
        self._sync_balances = sync_balances
        self._queue = queue
        self._clock = clock
        self._interval_seconds = interval_seconds

    async def handle(self, job: ClaimedJob) -> SyncResult:
        del job  # the sync covers every configured pool; there is no payload
        result = await self._sync_balances.sync()
        await self._queue.enqueue(
            Job(
                kind=JobKind.BALANCE_SYNC,
                run_after=self._clock.now() + timedelta(seconds=self._interval_seconds),
            )
        )
        return result
