"""``ReadHeldBase``: implements ``execution.application.ports.HeldPositionPort``
by projecting one allocation's ledger rows into the signed base-currency
position it still holds.

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

**The result is signed, and used to be clamped at zero.** That clamp encoded
a true statement about spot -- a negative holding there is a bookkeeping
impossibility -- as though it were true everywhere. On a futures venue a
negative net IS a short: opened by a SELL, closed by buying the same quantity
back. Clamping reported every short as "nothing held", which made
``ClosePosition`` raise ``NothingRecordedYet`` and retry forever, leaving a
real leveraged position open with no way for this system to exit it.

Deciding what a negative means is the caller's, because only the caller knows
the venue. ``ClosePosition`` checks the sign against the side the signal
asked for and refuses a disagreement, which catches the spot bookkeeping error
the clamp used to hide.
"""

from decimal import Decimal
from uuid import UUID

from strategy_manager.ledger.application.ports import LedgerPositionReaderPort


class ReadHeldBase:
    """Implements ``execution.application.ports.HeldPositionPort``."""

    def __init__(self, reader: LedgerPositionReaderPort) -> None:
        self._reader = reader

    async def net_base(self, allocation_id: UUID, base_currency: str) -> Decimal:
        """Positive is long, negative is short, zero is flat."""
        return await self._reader.net_base_quantity(allocation_id, base_currency)
