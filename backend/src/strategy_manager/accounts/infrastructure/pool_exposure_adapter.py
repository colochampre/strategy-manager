"""Implements ``accounts.application.ports.PoolExposurePort`` (owner decision 22).

``StrategyExposureAdapter`` answers "does THIS strategy hold exposure on its
pool?" for archiving. Deleting an exchange's key asks the question of the whole
pool, so this adapter composes the same three provider repositories (ledger
holdings, reservations, execution attempts) WITHOUT a strategy filter, and adds
the strategies still enabled, which archiving never has to ask about because it
has already refused an enabled one.

It reads; it never writes and never locks. The caller (``DeleteCredential``)
holds the pool's advisory lock across the read, which is what makes the answer
stay true until the credential is deactivated.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.application.ports import EnabledStrategy, PoolExposure, PoolKey
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.infrastructure.models import StrategyRow


class PoolExposureAdapter:
    """Implements ``PoolExposurePort``."""

    def __init__(
        self,
        session: AsyncSession,
        ledger: SqlAlchemyLedgerRepository,
        symbol_holdings: ReadSymbolHoldings,
        reservations: SqlAlchemyReservationRepository,
        attempts: SqlAlchemyExecutionAttemptRepository,
    ) -> None:
        self._session = session
        self._ledger = ledger
        self._symbol_holdings = symbol_holdings
        self._reservations = reservations
        self._attempts = attempts

    @classmethod
    def over(cls, session: AsyncSession) -> "PoolExposureAdapter":
        """The real wiring over one session, the way the router builds it."""
        ledger = SqlAlchemyLedgerRepository(session)
        return cls(
            session,
            ledger,
            ReadSymbolHoldings(ledger),
            SqlAlchemyReservationRepository(session),
            SqlAlchemyExecutionAttemptRepository(session),
        )

    async def exposure(self, pool: PoolKey) -> PoolExposure:
        exchange, venue, settlement_currency = pool

        enabled = await self._session.execute(
            select(StrategyRow.id, StrategyRow.name)
            .where(
                StrategyRow.exchange == exchange,
                StrategyRow.venue == venue,
                StrategyRow.settlement_currency == settlement_currency,
                StrategyRow.enabled.is_(True),
            )
            .order_by(StrategyRow.name)
        )

        # Every RAW symbol any strategy has ever recorded a fill under in this
        # pool, normalized and deduped into MARKETS here (the repository does
        # not), so a market opened under one spelling and closable under
        # another is checked once, under all of them.
        raw_symbols = await self._ledger.distinct_symbols_for_pool(
            exchange, venue, settlement_currency
        )
        markets = {market_key(symbol) for symbol in raw_symbols}

        # Per allocation, never summed per symbol: ``symbol_holdings`` groups by
        # ``(strategy_id, allocation_id)`` with ``HAVING net_base != 0`` across
        # the whole pool, so two allocations on one market, one closed and one
        # open, are told apart. No strategy filter here: that is the widening.
        symbols: set[str] = set()
        allocations: list[UUID] = []
        for market in sorted(markets):
            for holding in await self._symbol_holdings.symbol_holdings(pool, market):
                symbols.add(market)
                allocations.append(holding.allocation_id)

        return PoolExposure(
            enabled_strategies=tuple(
                EnabledStrategy(id=row.id, name=row.name) for row in enabled.all()
            ),
            symbols=frozenset(symbols),
            allocations=tuple(allocations),
            live_reservations=tuple(
                await self._reservations.live_for_pool(exchange, venue, settlement_currency)
            ),
            in_flight_attempts=tuple(
                await self._attempts.submitted_for_pool(exchange, venue, settlement_currency)
            ),
        )
