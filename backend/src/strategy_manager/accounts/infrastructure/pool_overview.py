"""``SqlAlchemyPoolOverview``: every configured pool with its last balance
snapshot and its live reservations (design.md section 14, ``GET /pools``).

**Where "reserved" is read.** It is not recomputed here. It is
``SqlAlchemyReservationRepository.sum_active`` (allocation/infrastructure/
repository.py), the very query ``AllocateCapital`` runs under the pool lock
(allocation/application/allocate_capital.py, ``reserved_active``): reservations
of the pool in PENDING or SUBMITTED whose ``expires_at`` is still in the future.
Reusing the method means the panel and the allocator cannot disagree about what
is reserved.

**Every pool, enabled or not.** ``capital_pools`` is the source of truth for
which pools exist; a disabled one is listed with ``enabled=false`` so the panel
can say so instead of hiding it. The snapshot join is OUTER for the same reason
``SqlAlchemyStaleSnapshotReader`` uses one: a pool nothing has synced is the
worst-off one, and an inner join would make it vanish.

One query for the pools and their snapshots, one ``sum_active`` per pool. The
pools number in the single digits. Nothing here sums across pools (rule 7).
"""

from datetime import timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.domain.pool_overview import (
    BalanceView,
    PoolOverview,
    allocatable,
)
from strategy_manager.accounts.infrastructure.models import (
    CapitalPoolRow,
    PoolBalanceSnapshotRow,
)
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.shared.application.ports import ClockPort


class SqlAlchemyPoolOverview:
    def __init__(
        self, session: AsyncSession, clock: ClockPort, snapshot_max_age_seconds: float
    ) -> None:
        self._session = session
        self._clock = clock
        self._max_age = timedelta(seconds=snapshot_max_age_seconds)

    async def list_pools(self) -> list[PoolOverview]:
        now = self._clock.now()
        rows = (
            await self._session.execute(
                select(CapitalPoolRow, PoolBalanceSnapshotRow)
                .outerjoin(
                    PoolBalanceSnapshotRow,
                    and_(
                        CapitalPoolRow.exchange == PoolBalanceSnapshotRow.exchange,
                        CapitalPoolRow.venue == PoolBalanceSnapshotRow.venue,
                        CapitalPoolRow.settlement_currency
                        == PoolBalanceSnapshotRow.settlement_currency,
                    ),
                )
                .order_by(
                    CapitalPoolRow.exchange,
                    CapitalPoolRow.venue,
                    CapitalPoolRow.settlement_currency,
                )
            )
        ).all()

        reservations = SqlAlchemyReservationRepository(self._session)
        pools: list[PoolOverview] = []
        for pool, snapshot in rows:
            reserved = await reservations.sum_active(
                pool.exchange, pool.venue, pool.settlement_currency, now
            )
            balance = (
                None
                if snapshot is None
                else BalanceView(
                    total=snapshot.total,
                    available=snapshot.available,
                    observed_at=snapshot.observed_at,
                    stale=now - snapshot.observed_at > self._max_age,
                )
            )
            pools.append(
                PoolOverview(
                    exchange=pool.exchange,
                    venue=pool.venue,
                    settlement_currency=pool.settlement_currency,
                    enabled=pool.enabled,
                    balance=balance,
                    reserved=reserved,
                    allocatable=(
                        None if balance is None else allocatable(balance.available, reserved)
                    ),
                )
            )
        return pools
