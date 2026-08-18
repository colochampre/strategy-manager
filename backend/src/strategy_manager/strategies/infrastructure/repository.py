"""SQLAlchemy implementation of ``StrategyRepositoryPort``."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.domain.money import Currency, Venue
from strategy_manager.strategies.domain.strategy import (
    AllocationPercent,
    AllocationPolicy,
    FillMode,
    Strategy,
)
from strategy_manager.strategies.infrastructure.models import StrategyRow


class SqlAlchemyStrategyRepository:
    """Implements ``StrategyRepositoryPort`` against the ``strategies`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, strategy: Strategy) -> None:
        self._session.add(
            StrategyRow(
                id=strategy.id,
                name=strategy.name,
                venue=strategy.policy.venue.value,
                settlement_currency=strategy.policy.settlement_currency.value,
                enabled=strategy.enabled,
                fill_mode=strategy.policy.fill_mode.value,
                allocation_percent=strategy.policy.allocation_percent.value,
            )
        )
        await self._session.flush()

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        row = await self._session.get(StrategyRow, strategy_id)
        if row is None:
            return None
        return Strategy(
            id=row.id,
            name=row.name,
            policy=AllocationPolicy(
                venue=Venue(row.venue),
                settlement_currency=Currency(row.settlement_currency),
                fill_mode=FillMode(row.fill_mode),
                allocation_percent=AllocationPercent(row.allocation_percent),
            ),
            enabled=row.enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
