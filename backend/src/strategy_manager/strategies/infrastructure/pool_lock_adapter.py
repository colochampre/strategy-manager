"""Implements ``strategies.application.ports.PoolLockPort`` by delegating to
``allocation.infrastructure.advisory_lock.PgAdvisoryLockAdapter`` directly --
never reimplementing its SQL or its key derivation (design.md § 8, "same key
AllocateCapital takes"; tasks.md 2c.12, orchestrator binding requirement 1).

Deriving the lock key any other way would compile, satisfy every
fake-backed unit test, and silently serialize nothing against a concurrent
``AllocateCapital`` -- the whole point of taking this lock at all. Routing
through the exact same ``LockKey.from_pool_key`` call ``AllocateCapital``
itself makes is what makes the two locks provably the same lock, and
``test_archive_vs_allocate_concurrency.py`` is the proof: it fails the
moment this adapter's derivation drifts from allocation's own.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey as AllocationPoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.shared.domain.money import Currency, Exchange, Venue


class PoolLockAdapter:
    """Implements ``PoolLockPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._lock = PgAdvisoryLockAdapter(session)

    async def acquire(self, exchange: str, venue: str, settlement_currency: str) -> None:
        pool_key = AllocationPoolKey(
            exchange=Exchange(exchange),
            venue=Venue(venue),
            settlement_currency=Currency(settlement_currency),
        )
        await self._lock.acquire(LockKey.from_pool_key(pool_key))
