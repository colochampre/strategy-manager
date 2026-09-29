"""What the operator panel shows for ONE pool: its configuration, the last
balance the exchange reported, what the allocator has already promised, and
what is left to allocate (design.md section 14, ``GET /pools``).

Pure ``Decimal``, no framework. Every figure is in the pool's own settlement
currency and nothing here combines two pools (CLAUDE.md rule 7): a pool is one
object, and there is deliberately no type that holds several.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

_ZERO = Decimal(0)


def allocatable(available: Decimal, reserved: Decimal) -> Decimal:
    """What a new signal could still be granted: the available balance less
    what live reservations already hold, never below zero.

    Clamped because ``reserved`` and ``available`` are read at different
    moments (a snapshot is refreshed on a schedule, reservations change on
    every signal), so the difference can be transiently negative and a negative
    "capital you can still use" is meaningless to a reader.
    """
    return max(_ZERO, available - reserved)


@dataclass(frozen=True, slots=True)
class BalanceView:
    """The latest snapshot of a pool. ``stale`` is true when the snapshot is
    older than the limit ``DbBalanceSource`` refuses to allocate against."""

    total: Decimal
    available: Decimal
    observed_at: datetime
    stale: bool


@dataclass(frozen=True, slots=True)
class PoolOverview:
    """One pool. ``balance`` is ``None`` for a pool nothing has ever synced, and
    then ``allocatable`` is ``None`` too: with no available balance to subtract
    from, the honest answer is "unknown", not zero."""

    exchange: str
    venue: str
    settlement_currency: str
    enabled: bool
    balance: BalanceView | None
    reserved: Decimal
    allocatable: Decimal | None
