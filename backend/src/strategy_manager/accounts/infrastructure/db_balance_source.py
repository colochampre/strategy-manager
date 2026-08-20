"""``DbBalanceSource``: the local ``BalanceSourcePort`` the port's own
docstring demands.

The allocation path reads this while holding ``pg_advisory_xact_lock`` for the
pool, so the read is a single primary-key lookup against a table in the same
database and the same transaction. No network, no second connection, nothing
that can block behind an exchange.

It refuses to answer with a stale figure. That refusal is the point: without
it, a dead sync job is invisible, and the allocator keeps sizing positions
against a balance that stopped being true.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.domain.errors import StaleBalanceSnapshot
from strategy_manager.accounts.infrastructure.models import PoolBalanceSnapshotRow
from strategy_manager.shared.application.ports import ClockPort


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

    async def read_balance(self, venue: str, settlement_currency: str) -> Decimal:
        row = await self._session.get(
            PoolBalanceSnapshotRow, (venue, settlement_currency)
        )
        if row is None:
            raise StaleBalanceSnapshot(
                f"no balance has ever been synced for ({venue}, {settlement_currency}); "
                "the balance.sync job has not run for this pool"
            )

        age = self._clock.now() - row.observed_at
        if age > self._max_age:
            raise StaleBalanceSnapshot(
                f"balance for ({venue}, {settlement_currency}) was observed "
                f"{age.total_seconds():.1f}s ago, past the "
                f"{self._max_age.total_seconds():.1f}s limit; refusing to size a "
                "trade against a balance that may no longer exist"
            )

        return row.available
