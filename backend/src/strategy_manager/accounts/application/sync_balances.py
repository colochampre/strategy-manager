"""``SyncBalances``: reads the exchange and lands the result locally.

This is the only place in the system allowed to make a remote balance call.
It runs on the worker, outside any advisory lock, so exchange latency costs a
background job its time and never blocks an allocation.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from strategy_manager.accounts.application.ports import (
    BalanceSnapshotWriterPort,
    CommitPort,
    ExchangeBalanceReaderPort,
    PoolKey,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncResult:
    synced: int


class SyncPort(Protocol):
    """One ``(user, exchange)`` balance sync, as ``CompositeBalanceSync``
    consumes it. ``label`` names the pair in a log line."""

    @property
    def label(self) -> str: ...

    async def sync(self) -> SyncResult: ...


class SyncBalances:
    """One user's pools on one exchange (multi-user design AD9): ``pools`` are
    ``user_id``'s, and every reading is stored as that user's snapshot."""

    def __init__(
        self,
        user_id: UUID,
        pools: Sequence[PoolKey],
        reader: ExchangeBalanceReaderPort,
        snapshots: BalanceSnapshotWriterPort,
        commit: CommitPort,
    ) -> None:
        self._user_id = user_id
        self._pools = pools
        self._reader = reader
        self._snapshots = snapshots
        self._commit = commit

    @property
    def label(self) -> str:
        """The pair this sync answers for, as a log line may name it: the
        exchange and the user's id prefix, never an e-mail (AD9)."""
        exchanges = ", ".join(sorted({pool[0] for pool in self._pools}))
        return f"'{exchanges}' of user {str(self._user_id)[:8]}"

    async def sync(self) -> SyncResult:
        """A failed read raises and writes nothing.

        Leaving the previous snapshot in place is what makes the freshness
        check meaningful: the old figure stays, keeps ageing, and blocks
        allocation once it crosses the limit. Writing a zero or a guess on
        failure would hide the outage behind a number that looks like data.
        """
        readings = await self._reader.read(self._pools)
        await self._snapshots.upsert(self._user_id, readings)
        await self._commit.commit()
        return SyncResult(synced=len(readings))


class CompositeBalanceSync:
    """Runs one ``SyncBalances`` per ``(user, exchange)``, in order.

    Each pair has its own reader, its own credential and its own account, so
    there is no single call that answers for all of them. They are kept
    separate rather than merged because a reader must only ever be handed the
    pools whose money its account actually holds.

    A failure degrades its own pair only (multi-user design AD9, tasks.md
    B.7). It used to fail the whole job, so the queue retried every exchange;
    with one sync per user that let one user's broken key stall every user's
    balances, and exhaust the recurring chain. Now the failing pair is logged
    at WARNING, by its label and the exception's message, with no traceback,
    and every other pair still syncs. The outage is still not hidden: the
    failing pair wrote nothing, so its snapshot keeps ageing until it crosses
    the freshness limit, halts its own pools, and the staleness watchdog
    reports it.
    """

    def __init__(self, syncs: Sequence[SyncPort]) -> None:
        self._syncs = syncs

    async def sync(self) -> SyncResult:
        synced = 0
        for one in self._syncs:
            try:
                result = await one.sync()
            except Exception as exc:  # noqa: BLE001 -- isolated per pair, by design
                logger.warning(
                    "balance sync failed for %s: %s: %s; every other pair is still synced",
                    one.label,
                    type(exc).__name__,
                    exc,
                )
                continue
            synced += result.synced
        return SyncResult(synced=synced)
