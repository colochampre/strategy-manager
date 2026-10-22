"""``SqlAlchemyStaleSnapshotReader``: enabled pools whose balance is not fresh.

Implements the watchdog's ``StaleSnapshotPort`` from the same
``pool_balance_snapshots`` table ``DbBalanceSource`` reads, and from
``capital_pools``, which is the source of truth for which pools exist. The
adapter lives here because ``accounts`` owns both tables; the port is declared
by its consumer in ``shared.application.watchdog``.

**The join is OUTER, and that is the behaviour.** The worst-off pool is the one
with no snapshot row at all — nothing has ever synced it — and an inner join
answers for that pool with no row, which reads exactly like health. It comes
back with ``age_seconds=None`` instead, so the message can tell a lapsed sync
apart from a pool that was never synced once.

**Disabled pools are excluded.** A disabled pool is money this system was told
to ignore, and it will have no fresh snapshot by construction, so including it
would mean an ERROR every run for a configuration that is working as asked.

This reads only what ``balance.sync`` WROTE. It never asks a venue: that is the
whole difference between a watchdog and one more thing an exchange's socket can
hang.

**A global sweep, on purpose** (multi-user design AD9): the watchdog is the
admin's, and it reports every user's stale pools. It takes no ``user_id``;
instead each ``StalePool`` carries its pool's owner, and a snapshot is joined to
its pool by ``pool_id`` (migration ``0030``), so a user whose sync works never
hides another user's pool on the same market that nothing has synced.
"""

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import (
    CapitalPoolRow,
    PoolBalanceSnapshotRow,
)
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.application.watchdog import StalePool


class SqlAlchemyStaleSnapshotReader:
    """Implements ``StaleSnapshotPort``."""

    def __init__(self, session: AsyncSession, clock: ClockPort) -> None:
        self._session = session
        self._clock = clock

    async def stale_pools(self, max_age_seconds: float) -> list[StalePool]:
        now = self._clock.now()
        cutoff = now - timedelta(seconds=max_age_seconds)

        result = await self._session.execute(
            select(
                CapitalPoolRow.user_id,
                CapitalPoolRow.exchange,
                CapitalPoolRow.venue,
                CapitalPoolRow.settlement_currency,
                PoolBalanceSnapshotRow.observed_at,
            )
            .select_from(CapitalPoolRow)
            .outerjoin(
                PoolBalanceSnapshotRow,
                PoolBalanceSnapshotRow.pool_id == CapitalPoolRow.id,
            )
            .where(CapitalPoolRow.enabled.is_(True))
            .where(
                or_(
                    PoolBalanceSnapshotRow.observed_at.is_(None),
                    # Strictly older than the cutoff: the bound is a ceiling on
                    # acceptable age, not the first age that is unacceptable.
                    PoolBalanceSnapshotRow.observed_at < cutoff,
                )
            )
            .order_by(
                CapitalPoolRow.exchange,
                CapitalPoolRow.venue,
                CapitalPoolRow.settlement_currency,
                CapitalPoolRow.user_id,
            )
        )

        return [
            StalePool(
                user_id=row.user_id,
                exchange=row.exchange,
                venue=row.venue,
                settlement_currency=row.settlement_currency,
                age_seconds=(
                    None
                    if row.observed_at is None
                    else (now - row.observed_at).total_seconds()
                ),
            )
            for row in result.all()
        ]
