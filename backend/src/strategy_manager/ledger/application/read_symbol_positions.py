"""``ReadSymbolPositions``: implements
``reconciliation.application.ports.LedgerSymbolPositionPort`` by projecting a
WHOLE POOL's ledger rows into one ``LedgerPosition`` per symbol.

Mirrors ``ReadHeldBase`` exactly, one level up: that class answers "what does
THIS allocation hold", grouped by nothing; this one answers "what does this
WHOLE POOL hold", grouped by symbol. Both are thin — the actual SQL aggregate
and the fee rule live in ``LedgerSymbolPositionReaderPort``'s implementation,
not here.

Real fills only (multi-user design AD7, tasks.md E.6): this is what the scan
compares with the venue, and a user who went live holding a simulated position
has nothing of it there, so counting it would raise a discrepancy over a position
that is exactly where it should be.
"""

from uuid import UUID

from strategy_manager.ledger.application.ports import LedgerSymbolPositionReaderPort
from strategy_manager.reconciliation.application.ports import PoolKey
from strategy_manager.reconciliation.domain.positions import LedgerPosition
from strategy_manager.shared.domain.mode import Mode


class ReadSymbolPositions:
    """Implements ``reconciliation.application.ports.LedgerSymbolPositionPort``."""

    def __init__(self, reader: LedgerSymbolPositionReaderPort) -> None:
        self._reader = reader

    async def net_positions_by_symbol(
        self, user_id: UUID, pool: PoolKey
    ) -> list[LedgerPosition]:
        exchange, venue, settlement_currency = pool
        return await self._reader.net_positions_by_symbol(
            user_id, exchange, venue, settlement_currency, mode=Mode.LIVE
        )
