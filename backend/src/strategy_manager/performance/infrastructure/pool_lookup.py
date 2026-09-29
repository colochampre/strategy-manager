"""``SqlAlchemyPoolLookup``: is this a pool that is configured?

``accounts`` owns ``capital_pools``; ``performance`` only needs to turn the
three strings of a URL into a ``PoolKey`` or say there is no such pool. The
consumer declares the question and this adapter answers it, the same direction
as ``strategies.infrastructure.pool_catalog``.

**Disabled pools are found.** A pool the owner switched off keeps its history,
and the history is still worth reading. "Unknown" means "not a row of
``capital_pools``", which also covers a value that is not an ``Exchange``,
``Venue`` or ``Currency`` at all, without that being a separate error.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.shared.domain.money import Currency, Exchange, Venue


class SqlAlchemyPoolLookup:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(self, exchange: str, venue: str, settlement_currency: str) -> PoolKey | None:
        found = (
            await self._session.execute(
                select(
                    CapitalPoolRow.exchange,
                    CapitalPoolRow.venue,
                    CapitalPoolRow.settlement_currency,
                ).where(
                    CapitalPoolRow.exchange == exchange,
                    CapitalPoolRow.venue == venue,
                    CapitalPoolRow.settlement_currency == settlement_currency,
                )
            )
        ).one_or_none()
        if found is None:
            return None
        return PoolKey(Exchange(found[0]), Venue(found[1]), Currency(found[2]))
