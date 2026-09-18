"""``ReadSymbolPositions``: implements
``reconciliation.application.ports.LedgerSymbolPositionPort`` by projecting a
WHOLE POOL's ledger rows into one ``LedgerPosition`` per symbol.

Mirrors ``ReadHeldBase`` exactly, one level up: that class answers "what does
THIS allocation hold", grouped by nothing; this one answers "what does this
WHOLE POOL hold", grouped by symbol. Both are thin — the actual SQL aggregate
and the fee rule live in ``LedgerSymbolPositionReaderPort``'s implementation,
not here.
"""

from strategy_manager.ledger.application.ports import LedgerSymbolPositionReaderPort
from strategy_manager.reconciliation.application.ports import PoolKey
from strategy_manager.reconciliation.domain.positions import LedgerPosition


class ReadSymbolPositions:
    """Implements ``reconciliation.application.ports.LedgerSymbolPositionPort``."""

    def __init__(self, reader: LedgerSymbolPositionReaderPort) -> None:
        self._reader = reader

    async def net_positions_by_symbol(self, pool: PoolKey) -> list[LedgerPosition]:
        exchange, venue, settlement_currency = pool
        return await self._reader.net_positions_by_symbol(
            exchange, venue, settlement_currency
        )
