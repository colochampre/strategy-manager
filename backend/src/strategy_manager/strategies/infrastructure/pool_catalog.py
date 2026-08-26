"""Implements ``strategies.application.ports.PoolCatalogPort``.

``accounts`` owns ``capital_pools``; ``strategies`` only needs to know which
pools a strategy may legally point at. So the consumer declares the narrow
port and this adapter answers it — the same direction as ``StrategyPolicy
Adapter``, and the reason no ``accounts`` type appears in the strategies
application layer.

It reads through the request-scoped ORM session rather than through
``accounts.infrastructure.CapitalPoolRepository``, which takes a raw
connection because it runs in the startup lifespan before any session exists.
Registering a strategy happens inside a request, where the session is what is
available.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow
from strategy_manager.shared.domain.money import Currency, Venue


class SqlAlchemyPoolCatalog:
    """Reads the enabled pools a strategy is allowed to draw from."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enabled_pools(self) -> list[tuple[Venue, Currency]]:
        result = await self._session.execute(
            select(CapitalPoolRow.venue, CapitalPoolRow.settlement_currency).where(
                CapitalPoolRow.enabled.is_(True)
            )
        )
        return [
            (Venue(venue), Currency(currency)) for venue, currency in result.all()
        ]
