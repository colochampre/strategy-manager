"""``ReadSymbolHoldings``: implements
``signals.application.ports.SymbolHoldingsPort`` by projecting one market's
ledger rows -- across every spelling it wears -- into one ``HeldAllocation``
per ``(strategy, allocation)`` still open on it.

Mirrors ``ReadSymbolPositions`` exactly, one level over: that class serves
``reconciliation`` a WHOLE POOL grouped by raw symbol; this one serves
``signals`` a single MARKET, its spellings merged, grouped by strategy.
Both are thin -- the actual SQL aggregate and the fee rule live in
``LedgerSymbolHoldingsReaderPort``'s implementation, not here.
"""

from strategy_manager.ledger.application.ports import LedgerSymbolHoldingsReaderPort
from strategy_manager.signals.application.ports import PoolKey
from strategy_manager.signals.domain.holding import HeldAllocation


class ReadSymbolHoldings:
    """Implements ``signals.application.ports.SymbolHoldingsPort``."""

    def __init__(self, reader: LedgerSymbolHoldingsReaderPort) -> None:
        self._reader = reader

    async def symbol_holdings(self, pool: PoolKey, symbol: str) -> list[HeldAllocation]:
        exchange, venue, settlement_currency = pool
        return await self._reader.symbol_holdings(exchange, venue, settlement_currency, symbol)
