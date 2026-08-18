"""Implements ``AdvisoryLockPort`` via ``pg_advisory_xact_lock`` — runs on the
same session, inside the caller's already-open transaction. The lock is
released only by that transaction's commit or rollback (design.md § Interfaces
/ Contracts; spec: capital-allocation § Serialized Allocation Decision).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.lock_key import LockKey


class PgAdvisoryLockAdapter:
    """Implements ``allocation.application.AdvisoryLockPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire(self, key: LockKey) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:venue), hashtext(:settlement_currency))"),
            {"venue": key.venue, "settlement_currency": key.settlement_currency},
        )
