"""The ``StrategySecretReaderPort`` adapter: one strategy's secret hash, by key.

The webhook's only read before it stores anything (multi-user design AD6; tasks.md
D.2). It selects the one column it needs from the one row, so nothing else about
the strategy (its author, its enablement, its archive) reaches ingress.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.strategies.infrastructure.models import StrategyRow


class SqlAlchemyStrategySecretReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def webhook_secret_hash(self, strategy_id: UUID) -> str | None:
        return (
            await self._session.execute(
                select(StrategyRow.webhook_secret_hash).where(StrategyRow.id == strategy_id)
            )
        ).scalar_one_or_none()
