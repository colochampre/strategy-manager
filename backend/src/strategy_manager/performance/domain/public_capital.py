"""A strategy's public capital: one figure (tasks.md F.4, decision 30).

It adds everyone trading the strategy live, its author among them, and names
none of them. It is derived, never stored: each share of the latest balance of
that subscriber's pool, the same arithmetic that sizes an opening. So it is
capital assigned and not capital in use, and the same money can stand behind
several strategies, because strategies compete for one pool.

All seats of a strategy sit in pools of its one market, so the sum is in one
settlement currency (CLAUDE.md rule 7).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.allocation.domain.percent import requested_from_percent


@dataclass(frozen=True, slots=True)
class LiveSeat:
    """One subscription trading live. ``balance`` is its pool's latest total,
    ``None`` for a pool no balance has been read for."""

    share: Decimal
    balance: Decimal | None


def public_capital(seats: Iterable[LiveSeat]) -> Decimal:
    """Each seat's share of its balance, rounded down as an opening is. A pool
    with no balance read adds nothing, and nobody live adds up to zero."""
    return sum(
        (
            requested_from_percent(seat.balance, seat.share)
            for seat in seats
            if seat.balance is not None
        ),
        Decimal(0),
    )
