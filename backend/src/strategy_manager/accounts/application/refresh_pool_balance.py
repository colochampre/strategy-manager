"""``RefreshPoolBalance``: implements
``signals.application.ports.BalanceRefreshPort`` — the on-demand,
pre-allocation balance refresh (spec: capital-allocation § On-Demand Balance
Refresh Before Allocation; design.md § S3).

Called from ``ProcessSignalHandler._handle_consumes`` for exactly one pool,
right after the Existing-Position Guard and right before the sizing read --
the last remote call before the pool's advisory lock is acquired. It is NEVER
called at webhook ingress (CLAUDE.md rule 3): that endpoint only validates,
persists and returns 200.

A successful read is written and committed BEFORE the lock, exactly like
``SyncBalances`` -- so the periodic ``balance.sync`` heartbeat and this
on-demand refresh land through the same path, and ``DbBalanceSource`` (the
in-lock read) never has to know which one populated the row.

A failed read -- a timeout or any reader/transport error -- never raises.
Instead the existing snapshot's age decides what happens next: within
``fallback_max_age_seconds`` it is still usable (FALLBACK, logged as a
WARNING naming the pool, the reason and the age); past it, or if the pool was
never synced at all, the pool is UNAVAILABLE and the caller must refuse the
signal. The ERROR naming the signal, the strategy and the symbol is the
CALLER's job (``ProcessSignalHandler``), since only the caller has that
context -- this class only ever knows about a pool.
"""

import asyncio
import logging

from strategy_manager.accounts.application.ports import (
    BalanceSnapshotAgePort,
    BalanceSnapshotWriterPort,
    CommitPort,
    ExchangeBalanceReaderPort,
    PoolKey,
)
from strategy_manager.signals.application.ports import RefreshOutcome, RefreshStatus

logger = logging.getLogger(__name__)


class RefreshPoolBalance:
    def __init__(
        self,
        reader: ExchangeBalanceReaderPort,
        snapshots: BalanceSnapshotWriterPort,
        age: BalanceSnapshotAgePort,
        commit: CommitPort,
        timeout_seconds: float,
        fallback_max_age_seconds: float,
    ) -> None:
        self._reader = reader
        self._snapshots = snapshots
        self._age = age
        self._commit = commit
        self._timeout_seconds = timeout_seconds
        self._fallback_max_age_seconds = fallback_max_age_seconds

    async def refresh(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> RefreshOutcome:
        pool: PoolKey = (exchange, venue, settlement_currency)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                readings = await self._reader.read([pool])
        except Exception as exc:  # noqa: BLE001 - a timeout and a reader
            # failure degrade identically here: read the snapshot age and
            # decide FALLBACK vs UNAVAILABLE either way.
            return await self._on_failure(pool, reason=str(exc))

        await self._snapshots.upsert(readings)
        await self._commit.commit()
        return RefreshOutcome(status=RefreshStatus.FRESH)

    async def _on_failure(self, pool: PoolKey, reason: str) -> RefreshOutcome:
        exchange, venue, settlement_currency = pool
        age = await self._age.age_seconds(exchange, venue, settlement_currency)
        if age is not None and age <= self._fallback_max_age_seconds:
            logger.warning(
                "on-demand balance refresh failed for pool %s (%s); falling back "
                "to the %.1fs-old snapshot",
                pool,
                reason,
                age,
            )
            return RefreshOutcome(status=RefreshStatus.FALLBACK, age_seconds=age, reason=reason)

        return RefreshOutcome(status=RefreshStatus.UNAVAILABLE, age_seconds=age, reason=reason)
