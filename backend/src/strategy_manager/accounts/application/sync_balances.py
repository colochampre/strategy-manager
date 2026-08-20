"""``SyncBalances``: reads the exchange and lands the result locally.

This is the only place in the system allowed to make a remote balance call.
It runs on the worker, outside any advisory lock, so exchange latency costs a
background job its time and never blocks an allocation.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from strategy_manager.accounts.application.ports import (
    BalanceSnapshotWriterPort,
    CommitPort,
    ExchangeBalanceReaderPort,
    PoolKey,
)


@dataclass(frozen=True, slots=True)
class SyncResult:
    synced: int


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
