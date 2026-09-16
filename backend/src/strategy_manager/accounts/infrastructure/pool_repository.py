"""Reads ``capital_pools`` — the single source of truth for which pools
exist (design.md § Composition Root; no ``CONFIGURED_POOLS`` env list).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.models import CapitalPoolRow
from strategy_manager.shared.domain.money import Currency, Exchange, Venue


class CapitalPoolRepository:
    """Reads pool configuration directly from a raw DB connection — no ORM
    session required, so it can run inside ``main.py``'s startup lifespan
    before any request-scoped session exists."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_enabled(self) -> list[PoolConfig]:
        result = await self._conn.execute(
            select(CapitalPoolRow).where(CapitalPoolRow.enabled.is_(True))
        )
        return [
            PoolConfig(
                exchange=Exchange(row.exchange),
                venue=Venue(row.venue),
                settlement_currency=Currency(row.settlement_currency),
                min_order_size=row.min_order_size,
                enabled=row.enabled,
            )
            for row in result.all()
        ]
