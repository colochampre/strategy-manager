"""STUB (12f.9.11, RED commit): answers a minimum of zero and no snapshot for every
pool, and reads nothing."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.application.ports import PoolSizing
from strategy_manager.shared.application.ports import ClockPort


class SqlAlchemyPoolSizing:
    def __init__(
        self, session: AsyncSession, clock: ClockPort, snapshot_max_age_seconds: float
    ) -> None:
        self._session = session
        self._clock = clock
        self._snapshot_max_age_seconds = snapshot_max_age_seconds

    async def read(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> PoolSizing | None:
        return PoolSizing(min_order_size=Decimal(0), snapshot=None)
