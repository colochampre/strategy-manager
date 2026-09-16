"""``SyncBalances``: reads the exchange and lands the result locally.

This is the only place in the system allowed to make a remote balance call.
It runs on the worker, outside any advisory lock, so exchange latency costs a
background job its time and never blocks an allocation.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from strategy_manager.accounts.application.ports import (
    BalanceSnapshotWriterPort,
    CommitPort,
    ExchangeBalanceReaderPort,
    PoolKey,
)


@dataclass(frozen=True, slots=True)
class SyncResult:
    synced: int


class SyncPort(Protocol):
    """One exchange's balance sync, as ``CompositeBalanceSync`` consumes it."""

    async def sync(self) -> SyncResult: ...


class SyncBalances:
    def __init__(
        self,
        pools: Sequence[PoolKey],
        reader: ExchangeBalanceReaderPort,
        snapshots: BalanceSnapshotWriterPort,
        commit: CommitPort,
    ) -> None:
        self._pools = pools
        self._reader = reader
        self._snapshots = snapshots
        self._commit = commit

    async def sync(self) -> SyncResult:
        """A failed read raises and writes nothing.

        Leaving the previous snapshot in place is what makes the freshness
        check meaningful: the old figure stays, keeps ageing, and blocks
        allocation once it crosses the limit. Writing a zero or a guess on
        failure would hide the outage behind a number that looks like data.
        """
        readings = await self._reader.read(self._pools)
        await self._snapshots.upsert(readings)
        await self._commit.commit()
        return SyncResult(synced=len(readings))


class CompositeBalanceSync:
    """Runs one ``SyncBalances`` per exchange, in order.

    Each exchange has its own reader, its own credential and its own account,
    so there is no single call that answers for all of them. They are kept
    separate rather than merged because a reader must only ever be handed the
    pools whose money its account actually holds.

    A failure is NOT swallowed: if one exchange's read fails, the whole job
    fails and the queue retries it. The snapshots already written stay, and
    the ones that did not keep ageing until they cross the freshness limit and
    halt their own pools -- which is the designed behaviour. Reporting partial
    success would leave a dead exchange looking healthy.
    """

    def __init__(self, syncs: Sequence[SyncPort]) -> None:
        self._syncs = syncs

    async def sync(self) -> SyncResult:
        synced = 0
        for one in self._syncs:
            result = await one.sync()
            synced += result.synced
        return SyncResult(synced=synced)
