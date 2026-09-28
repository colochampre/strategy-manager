"""Implements ``strategies.application.ports.StrategyExposurePort`` by
composing ledger ``ReadSymbolHoldings``, reservations and attempts,
following the ``InFlightWorkAdapter`` precedent (design.md's component
inventory § strategies/infrastructure; tasks.md 2c.12) -- provider owns the
adapter, ``strategies`` (the consumer) declared the port, one level up from
how ``InFlightWorkAdapter`` itself composes ``execution`` and
``allocation``'s own repositories.

This adapter composes THREE provider repositories, one level wider than
``InFlightWorkAdapter``'s two, because ``ArchiveStrategy`` needs the whole
picture ``AllocateCapital``'s Existing-Position Guard never has to ask for
in one call: the ledger's own open positions, not merely whether
in-flight WORK exists.
"""

from uuid import UUID

from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.application.ports import PoolKey, StrategyExposure


class StrategyExposureAdapter:
    """Implements ``StrategyExposurePort``."""

    def __init__(
        self,
        ledger: SqlAlchemyLedgerRepository,
        symbol_holdings: ReadSymbolHoldings,
        reservations: SqlAlchemyReservationRepository,
        attempts: SqlAlchemyExecutionAttemptRepository,
    ) -> None:
        self._ledger = ledger
        self._symbol_holdings = symbol_holdings
        self._reservations = reservations
        self._attempts = attempts

    async def exposure(self, strategy_id: UUID, pool: PoolKey) -> StrategyExposure:
        exchange, venue, settlement_currency = pool

        # Every RAW symbol this strategy has ever recorded a fill under in
        # this pool, normalized and deduped into MARKETS here -- not in the
        # repository (``distinct_symbols_for_strategy``'s own docstring) --
        # so a market this strategy opened under one spelling and would
        # close under another is checked exactly once, under both.
        raw_symbols = await self._ledger.distinct_symbols_for_strategy(
            exchange, venue, settlement_currency, strategy_id
        )
        markets = {market_key(symbol) for symbol in raw_symbols}

        # Per-allocation, never summed per symbol (the multiplicity lesson,
        # design.md § 8, tasks.md 2c.11): ``symbol_holdings`` already groups
        # by ``(strategy_id, allocation_id)`` with ``HAVING net_base != 0``,
        # so two allocations on the SAME market -- one closed, one still
        # open -- both surface here rather than netting each other out.
        symbols: set[str] = set()
        allocations: list[UUID] = []
        for market in markets:
            holdings = await self._symbol_holdings.symbol_holdings(pool, market)
            for holding in holdings:
                if holding.strategy_id != strategy_id:
                    continue
                symbols.add(market)
                allocations.append(holding.allocation_id)

        live_reservations = await self._reservations.live_for_strategy(
            exchange, venue, settlement_currency, strategy_id
        )
        in_flight_attempts = await self._attempts.submitted_for_strategy(
            exchange, venue, settlement_currency, strategy_id
        )

        return StrategyExposure(
            symbols=frozenset(symbols),
            allocations=tuple(allocations),
            live_reservations=tuple(live_reservations),
            in_flight_attempts=tuple(in_flight_attempts),
        )
