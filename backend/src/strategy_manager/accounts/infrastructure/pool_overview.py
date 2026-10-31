"""``SqlAlchemyPoolOverview``: every configured pool with its last balance
snapshot and its live reservations (design.md section 14, ``GET /pools``).

**Where "reserved" is read.** It is not recomputed here. It is
``SqlAlchemyReservationRepository.sum_active`` (allocation/infrastructure/
repository.py), the very query ``AllocateCapital`` runs under the pool lock
(allocation/application/allocate_capital.py, ``reserved_active``): reservations
of the pool in PENDING or SUBMITTED whose ``expires_at`` is still in the future.
Reusing the method means the panel and the allocator cannot disagree about what
is reserved. It takes the mode the user's next opening would run in, since capital
is counted per mode (decision 26).

**Every pool, enabled or not.** ``capital_pools`` is the source of truth for
which pools exist; a disabled one is listed with ``enabled=false`` so the panel
can say so instead of hiding it. The snapshot join is OUTER for the same reason
``SqlAlchemyStaleSnapshotReader`` uses one: a pool nothing has synced is the
worst-off one, and an inner join would make it vanish.

One query for the pools and their snapshots, one ``sum_active`` per pool. The
pools number in the single digits. Nothing here sums across pools (rule 7).

**Only ``user_id``'s pools** (multi-user design AD8): another user's pool on the
same market is never listed, and a snapshot is joined to its pool by ``pool_id``
(migration ``0030``), so it is always that pool's own. The reservations summed
per pool are that user's too: another user's reservations on the same market
hold that user's capital, not this pool's.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
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
from strategy_manager.shared.domain.mode import Mode


class SqlAlchemyPoolOverview:
    def __init__(
        self, session: AsyncSession, clock: ClockPort, snapshot_max_age_seconds: float
    ) -> None:
        self._session = session
        self._clock = clock
        self._max_age = timedelta(seconds=snapshot_max_age_seconds)

    async def list_pools(self, user_id: UUID, mode: Mode) -> list[PoolOverview]:
        now = self._clock.now()
        rows = (
            await self._session.execute(
                select(CapitalPoolRow, PoolBalanceSnapshotRow)
                .outerjoin(
                    PoolBalanceSnapshotRow,
                    PoolBalanceSnapshotRow.pool_id == CapitalPoolRow.id,
                )
                .where(CapitalPoolRow.user_id == user_id)
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
                user_id, pool.exchange, pool.venue, pool.settlement_currency, mode, now
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
