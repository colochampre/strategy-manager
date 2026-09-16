"""SQLAlchemy implementation of ``StrategyRepositoryPort``."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
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
                exchange=strategy.policy.exchange.value,
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
        return None if row is None else _to_domain(row)

    async def list_all(self) -> list[Strategy]:
        """Ordered by name so the listing is stable between calls. Creation
        order would put a renamed strategy somewhere the reader does not
        expect, and there are tens of these, not thousands."""
        result = await self._session.execute(
            select(StrategyRow).order_by(StrategyRow.name)
        )
        return [_to_domain(row) for row in result.scalars().all()]

    async def update(self, strategy: Strategy) -> None:
        """Writes only the mutable fields.

        ``exchange``, ``venue`` and ``settlement_currency`` are deliberately absent: a
        strategy cannot be moved between capital pools (see
        ``UpdateStrategy``), and leaving them out of the statement means this
        adapter cannot do it even if a caller asks.
        """
        row = await self._session.get(StrategyRow, strategy.id)
        if row is None:
            raise LookupError(f"no strategy row under id {strategy.id}")

        row.name = strategy.name
        row.enabled = strategy.enabled
        row.fill_mode = strategy.policy.fill_mode.value
        row.allocation_percent = strategy.policy.allocation_percent.value
        row.updated_at = datetime.now(UTC)
        await self._session.flush()


def _to_domain(row: StrategyRow) -> Strategy:
    return Strategy(
        id=row.id,
        name=row.name,
        policy=AllocationPolicy(
            exchange=Exchange(row.exchange),
            venue=Venue(row.venue),
            settlement_currency=Currency(row.settlement_currency),
            fill_mode=FillMode(row.fill_mode),
            allocation_percent=AllocationPercent(row.allocation_percent),
        ),
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
