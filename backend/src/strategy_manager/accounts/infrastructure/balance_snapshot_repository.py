"""Implements ``BalanceSnapshotWriterPort`` against ``pool_balance_snapshots``.

The write is a single ``INSERT ... ON CONFLICT DO UPDATE`` over the whole
batch, so a sync either lands entirely or not at all. A partial batch would
leave some pools fresh and others stale with nothing recording which is which.
"""

from collections.abc import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from strategy_manager.accounts.application.ports import PoolBalanceReading
from strategy_manager.accounts.infrastructure.models import PoolBalanceSnapshotRow


class SqlAlchemyBalanceSnapshotRepository:
    """Upserts one row per pool."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, readings: Sequence[PoolBalanceReading]) -> None:
        if not readings:
            return

        statement = insert(PoolBalanceSnapshotRow).values(
            [
                {
                    "venue": reading.venue,
                    "settlement_currency": reading.settlement_currency,
                    "available": reading.available,
                    "observed_at": reading.observed_at,
                }
                for reading in readings
            ]
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["venue", "settlement_currency"],
                set_={
                    "available": statement.excluded.available,
                    "observed_at": statement.excluded.observed_at,
                    "updated_at": func.now(),
                },
            )
        )
