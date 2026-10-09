"""``SqlAlchemyPoolSizing``: a pool's minimum order and its latest balance snapshot,
read for the share preview (design.md, unit 12f addendum, section H).

**One SELECT, and it is read-only.** The ``capital_pools`` row is OUTER-joined to its
``pool_balance_snapshots`` row on the three-part key, for the reason
``SqlAlchemyPoolOverview`` gives: a pool nothing has synced is the worst-off one, and
an inner join would make it vanish and read like a pool that does not exist. That
case is told apart on purpose: no ``capital_pools`` row answers ``None``, a pool with
a row and no snapshot answers a ``PoolSizing`` whose ``snapshot`` is ``None``.

**The TOTAL, never ``available``.** A share is sized from the total (owner decision
2026-09-15, ``allocation/domain/percent.py``); the free part is not even selected.

**Stale is marked, not refused.** The rule is the one ``SqlAlchemyPoolOverview``
applies, strictly (``now - observed_at > max_age``). Unlike the worker's balance
reader, nothing here raises on a stale snapshot: a display must show it and say so.

No lock, no write, no exchange and no credential: the API process decrypts nothing.
"""

from datetime import timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import (
    CapitalPoolRow,
    PoolBalanceSnapshotRow,
)
from strategy_manager.allocation.application.ports import PoolSizing, SizingSnapshot
from strategy_manager.shared.application.ports import ClockPort


class SqlAlchemyPoolSizing:
    def __init__(
        self, session: AsyncSession, clock: ClockPort, snapshot_max_age_seconds: float
    ) -> None:
        self._session = session
        self._clock = clock
        self._max_age = timedelta(seconds=snapshot_max_age_seconds)

    async def read(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> PoolSizing | None:
        row = (
            await self._session.execute(
                select(CapitalPoolRow.min_order_size, PoolBalanceSnapshotRow)
                .select_from(CapitalPoolRow)
                .outerjoin(
                    PoolBalanceSnapshotRow,
                    and_(
                        CapitalPoolRow.exchange == PoolBalanceSnapshotRow.exchange,
                        CapitalPoolRow.venue == PoolBalanceSnapshotRow.venue,
                        CapitalPoolRow.settlement_currency
                        == PoolBalanceSnapshotRow.settlement_currency,
                    ),
                )
                .where(
                    CapitalPoolRow.exchange == exchange,
                    CapitalPoolRow.venue == venue,
                    CapitalPoolRow.settlement_currency == settlement_currency,
                )
            )
        ).one_or_none()
        if row is None:
            return None

        minimum, snapshot = row
        if snapshot is None:
            return PoolSizing(min_order_size=minimum, snapshot=None)
        return PoolSizing(
            min_order_size=minimum,
            snapshot=SizingSnapshot(
                total=snapshot.total,
                observed_at=snapshot.observed_at,
                stale=self._clock.now() - snapshot.observed_at > self._max_age,
            ),
        )
