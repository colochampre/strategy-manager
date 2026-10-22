"""Implements ``BalanceSnapshotWriterPort`` against ``pool_balance_snapshots``.

The write is a single ``INSERT ... ON CONFLICT DO UPDATE`` over the whole
batch, so a sync either lands entirely or not at all. A partial batch would
leave some pools fresh and others stale with nothing recording which is which.

**Every reading is the snapshot of ``user_id``'s pool on its market** (multi-user
design AD8). A snapshot is keyed by its pool's id since migration ``0030``, and
two users may each hold a pool on the same market, so the market alone no longer
says which row to write. The ids are looked up first, from ``capital_pools``
filtered by ``user_id``; another user's pool on the same market is never written.
A market that user has no pool on raises before anything is written: the
composite FK used to refuse it, and the lookup is what refuses it now.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from strategy_manager.accounts.application.ports import PoolBalanceReading, PoolKey
from strategy_manager.accounts.infrastructure.models import (
    CapitalPoolRow,
    PoolBalanceSnapshotRow,
)
from strategy_manager.shared.domain.errors import InvariantViolation


class SqlAlchemyBalanceSnapshotRepository:
    """Upserts one row per pool."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, user_id: UUID, readings: Sequence[PoolBalanceReading]) -> None:
        if not readings:
            return

        pool_ids = await self._pool_ids(
            user_id,
            {(r.exchange, r.venue, r.settlement_currency) for r in readings},
        )

        statement = insert(PoolBalanceSnapshotRow).values(
            [
                {
                    "pool_id": pool_ids[
                        (reading.exchange, reading.venue, reading.settlement_currency)
                    ],
                    "user_id": user_id,
                    "exchange": reading.exchange,
                    "venue": reading.venue,
                    "settlement_currency": reading.settlement_currency,
                    "total": reading.total,
                    "available": reading.available,
                    "observed_at": reading.observed_at,
                }
                for reading in readings
            ]
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["pool_id"],
                set_={
                    "exchange": statement.excluded.exchange,
                    "total": statement.excluded.total,
                    "available": statement.excluded.available,
                    "observed_at": statement.excluded.observed_at,
                    "updated_at": func.now(),
                },
            )
        )

    async def _pool_ids(self, user_id: UUID, markets: set[PoolKey]) -> dict[PoolKey, int]:
        """The id of ``user_id``'s pool on each market. Raises, naming the
        markets, when that user holds no pool on one of them."""
        rows = await self._session.execute(
            select(
                CapitalPoolRow.id,
                CapitalPoolRow.exchange,
                CapitalPoolRow.venue,
                CapitalPoolRow.settlement_currency,
            ).where(
                CapitalPoolRow.user_id == user_id,
                tuple_(
                    CapitalPoolRow.exchange,
                    CapitalPoolRow.venue,
                    CapitalPoolRow.settlement_currency,
                ).in_(sorted(markets)),
            )
        )
        found: dict[PoolKey, int] = {
            (row.exchange, row.venue, row.settlement_currency): row.id for row in rows.all()
        }
        missing = markets - found.keys()
        if missing:
            raise InvariantViolation(
                f"user {str(user_id)[:8]} has no pool on {sorted(missing)}; "
                "a balance reading cannot be stored for a pool that does not exist"
            )
        return found
