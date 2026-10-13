"""``SqlAlchemyOpenPositionFactsSource``: the facts the mode guard's reader does
not carry (design addendum "open positions", section C, steps 3 and 4).

STUB: typed and importable, and it answers nothing. Replaced by the real
statements in the GREEN commit.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.performance.application.ports import PositionFacts, SubmittedOrder


class SqlAlchemyOpenPositionFactsSource:
    """Implements ``OpenPositionFactsSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def position_facts(self, allocation_ids: Sequence[UUID]) -> Mapping[UUID, PositionFacts]:
        return {}

    async def submitted_orders(self) -> Sequence[SubmittedOrder]:
        return []
