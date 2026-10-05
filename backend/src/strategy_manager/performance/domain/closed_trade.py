"""The performance module's vocabulary: what the ledger says about one
allocation (``FillGroup``), and what a completed trade is (``ClosedTrade``).

Everything is ``Decimal`` and in the pool's NATIVE settlement currency
(CLAUDE.md rule 7). Nothing here converts a currency and nothing sums across
pools; ``usd_rate_at_fill`` is not even a field.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class Direction(StrEnum):
    """Which way a trade was opened: ``LONG`` when its earliest leg was a BUY,
    ``SHORT`` when it was a SELL. The ledger's ``side`` of the opening leg
    expressed as a position sign, so a reader of a trade list does not have to
    know that a futures trade opened by selling is a short."""

    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True, slots=True)
class FillGroup:
    """One aggregate row of the ledger: every fill of one allocation on one
    ``side`` and one ``symbol`` spelling, written with one origin (``rehearsal``)
    and whose fee was charged in one ``fee_currency``.

    Fills are aggregated in SQL (hundreds to thousands of trades, not
    millions of rows) and folded into trades by ``derive_trade``. ``symbol`` is
    ONE of the spellings the group's fills were written under: an allocation
    opened as ``SOLUSDT.P`` and closed by a booked fill written as ``SOLUSDT``
    has groups spelled differently, and nothing here may depend on which.

    ``pool_total_at_open`` comes from the allocation's reservation and is
    ``None`` on every reservation written before migration 0026.

    ``rehearsal`` is true when the group's fills were written by the simulated
    exchange (their fill id carries the rehearsal prefix). It has no default: a
    builder that forgets to say which origin it means must not compile.
    """

    allocation_id: UUID
    strategy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    side: str
    fee_currency: str
    quantity: Decimal
    notional: Decimal
    fee: Decimal
    first_filled_at: datetime
    last_filled_at: datetime
    pool_total_at_open: Decimal | None
    rehearsal: bool


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """One allocation whose position netted to exactly zero: a realized PnL.

    ``pnl`` is in ``settlement_currency``. It is complete only when
    ``fees_complete`` is true: a fee charged in a THIRD currency (neither the
    settlement currency nor the base) is not converted, so it is missing from
    ``pnl`` and the flag says so.

    ``pair`` is the ``market_key`` of the allocation's symbol, so the two
    spellings of one market are one pair. ``direction`` is how the trade was
    opened (see ``Direction`` and ``derive_trade``). ``pool_total_at_open`` is the
    denominator of the trade's return; ``None`` means the trade has no return.
    """

    allocation_id: UUID
    strategy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    pair: str
    direction: Direction
    opened_at: datetime
    closed_at: datetime
    pnl: Decimal
    fees_complete: bool
    pool_total_at_open: Decimal | None
