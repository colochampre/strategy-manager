"""``DbBalanceSource``: the local ``BalanceSourcePort`` the port's own
docstring demands.

The allocation path reads this while holding ``pg_advisory_xact_lock`` for the
pool, so the read is a single indexed lookup against two tables in the same
database and the same transaction. No network, no second connection, nothing
that can block behind an exchange.

It refuses to answer with a stale figure. That refusal is the point: without
it, a dead sync job is invisible, and the allocator keeps sizing positions
against a balance that stopped being true.

**The snapshot read is ``user_id``'s** (multi-user design AD8). A snapshot is
keyed by its pool's id since migration ``0030``, so the read joins
``capital_pools`` on ``pool_id`` and filters by the pool's ``user_id``: another
user's snapshot on the same market is never an answer. Columns are selected,
not the entity, so a row cached in the session's identity map never answers for
a fresh read.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.application.ports import PoolFunds
from strategy_manager.accounts.domain.errors import StaleBalanceSnapshot
from strategy_manager.accounts.infrastructure.models import (
    CapitalPoolRow,
    PoolBalanceSnapshotRow,
)
from strategy_manager.shared.application.ports import ClockPort


async def _snapshot(
    session: AsyncSession,
    user_id: UUID,
    exchange: str,
    venue: str,
    settlement_currency: str,
) -> tuple[Decimal, Decimal, datetime] | None:
    """``user_id``'s snapshot of the pool on that market, as ``(total,
    available, observed_at)``, or ``None``."""
    result = await session.execute(
        select(
            PoolBalanceSnapshotRow.total,
            PoolBalanceSnapshotRow.available,
            PoolBalanceSnapshotRow.observed_at,
        )
        .join(CapitalPoolRow, CapitalPoolRow.id == PoolBalanceSnapshotRow.pool_id)
        .where(
            CapitalPoolRow.user_id == user_id,
            CapitalPoolRow.exchange == exchange,
            CapitalPoolRow.venue == venue,
            CapitalPoolRow.settlement_currency == settlement_currency,
        )
    )
    row = result.one_or_none()
    if row is None:
        return None
    total, available, observed_at = row
    return total, available, observed_at


class DbBalanceSource:
    """Implements ``BalanceSourcePort`` from ``pool_balance_snapshots``."""

    def __init__(
        self,
        session: AsyncSession,
        clock: ClockPort,
        max_age_seconds: float,
    ) -> None:
        self._session = session
        self._clock = clock
        self._max_age = timedelta(seconds=max_age_seconds)

    async def read_balance(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> PoolFunds:
        snapshot = await _snapshot(
            self._session, user_id, exchange, venue, settlement_currency
        )
        if snapshot is None:
            raise StaleBalanceSnapshot(
                f"no balance has ever been synced for ({exchange}, {venue}, "
                f"{settlement_currency}) of user {str(user_id)[:8]}; the balance.sync "
                "job has not run for this pool"
            )

        total, available, observed_at = snapshot
        age = self._clock.now() - observed_at
        if age > self._max_age:
            raise StaleBalanceSnapshot(
                f"balance for ({exchange}, {venue}, {settlement_currency}) was observed "
                f"{age.total_seconds():.1f}s ago, past the "
                f"{self._max_age.total_seconds():.1f}s limit; refusing to size a "
                "trade against a balance that may no longer exist"
            )

        return PoolFunds(total=total, available=available)


class DbBalanceSnapshotAge:
    """Implements ``BalanceSnapshotAgePort`` from the same
    ``pool_balance_snapshots`` table as ``DbBalanceSource``, WITHOUT that
    class's freshness refusal: ``RefreshPoolBalance`` (application/accounts)
    needs the raw age itself to decide FALLBACK vs UNAVAILABLE after an
    on-demand refresh fails, not an exception (design.md § S3). The pool is
    ``user_id``'s, exactly as for ``DbBalanceSource``.
    """

    def __init__(self, session: AsyncSession, clock: ClockPort) -> None:
        self._session = session
        self._clock = clock

    async def age_seconds(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> float | None:
        snapshot = await _snapshot(
            self._session, user_id, exchange, venue, settlement_currency
        )
        if snapshot is None:
            return None
        return (self._clock.now() - snapshot[2]).total_seconds()
