"""``ReadHeldBase``: implements ``execution.application.ports.HeldPositionPort``
by projecting one allocation's ledger rows into the base currency it still
holds.

This is CLAUDE.md rule 6 in use rather than in principle — "positions are a
projection" over the append-only ledger, and this is the smallest useful
projection there is: how much of the base currency did this allocation end up
with, and therefore how much can be sold to close it.

Three things go into that number and leaving any of them out sells the wrong
amount:

- every BUY fill's quantity, added. A market order can come back as several
  fills at different prices, and the ledger keeps one row per fill precisely
  so this sum is exact rather than an average.
- every SELL fill's quantity, subtracted. Normally there are none before a
  close, but a partially-closed or re-signalled position must not be
  double-sold.
- fees charged IN THE BASE CURRENCY, subtracted. If Pionex took its cut in BTC
  on a BTC_USDT buy, less BTC arrived than was bought, and trying to sell the
  purchased quantity is an order the exchange rejects for insufficient
  balance. Fees in the quote currency, or in a third token, do not touch the
  base holding and are correctly ignored here.

The result is clamped at zero. A negative holding is not a short position — it
is a bookkeeping impossibility, and sending it anywhere as an order size would
be worse than refusing.
"""

from decimal import Decimal
from uuid import UUID

from strategy_manager.ledger.application.ports import LedgerPositionReaderPort


class ReadHeldBase:
    """Implements ``execution.application.ports.HeldPositionPort``."""

    def __init__(self, reader: LedgerPositionReaderPort) -> None:
        self._reader = reader

    async def base_held(self, allocation_id: UUID, base_currency: str) -> Decimal:
        held = await self._reader.net_base_quantity(allocation_id, base_currency)
        return max(held, Decimal(0))
