"""What an open position and an order in flight are, for the panel's list
(design addendum "open positions", decision 65, sections C, D and E).

Pure ``Decimal`` over the aggregates of ONE allocation. The imports are the
standard library, ``execution.domain.mode_origin``, ``execution.domain.fill``,
``execution.domain.market_symbol`` and ``performance.domain.closed_trade`` and
``.operation``: no framework and no I/O. Nothing here converts a currency and
nothing sums two pools (CLAUDE.md rule 7).

**The decision that a row exists is not made here.** The guard's fold
(``fold_open_allocations``) says which allocations are open; this module only
derives what a row SHOWS. Everything below answers a reason instead of raising,
and no function of it can remove a row (design section B, point 3).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from uuid import UUID

from strategy_manager.execution.domain.fill import REHEARSAL_ORDER_ID_PREFIX
from strategy_manager.execution.domain.market_symbol import base_currency_of, market_key
from strategy_manager.execution.domain.mode_origin import OpenAllocationOrigin, Origin
from strategy_manager.performance.domain.closed_trade import Direction
from strategy_manager.performance.domain.operation import QUOTIENT_DIGITS, FeeAmount
from strategy_manager.shared.domain.errors import InvariantViolation

_ZERO = Decimal(0)
_BUY = "BUY"
# The status of the reconciliation's discrepancy that marks a position (the
# owner's decision says CONFIRMED; an OBSERVED row marks nothing).
CONFIRMED = "CONFIRMED"


class FiguresMissing(StrEnum):
    """Why the five figures of a position are absent (design section D)."""

    UNRESOLVED_SYMBOL = "UNRESOLVED_SYMBOL"
    SEVERAL_MARKETS = "SEVERAL_MARKETS"
    FLIPPED = "FLIPPED"
    NO_FACTS = "NO_FACTS"
    INCONSISTENT = "INCONSISTENT"


class OrderAction(StrEnum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class OrderOrigin(StrEnum):
    """By the order id's prefix; ``UNKNOWN`` when no order id is recorded yet."""

    REHEARSAL = "rehearsal"
    LIVE = "live"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PoolLabel:
    """A pool as the guard labels it: three strings, as stored."""

    exchange: str
    venue: str
    settlement_currency: str


@dataclass(frozen=True, slots=True)
class FillAggregate:
    """One row of the fills statement: everything one allocation did on one side
    of one symbol spelling, in one fee currency, in one pool, under one
    strategy id.

    It is NOT a ``FillGroup``: that type requires a ``rehearsal`` flag, and this
    read has none to give (the origin is the guard's alone). It carries the pool
    and the strategy id because the read compares every group with the
    reservation's (design section C).

    It satisfies ``operation_fees``' parameter: ``settlement_currency``,
    ``fee_currency`` and ``fee``.
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
    fill_count: int


@dataclass(frozen=True, slots=True)
class OpenPositionFigures:
    """Derived together or not at all."""

    side: Direction
    base_currency: str
    size: Decimal
    opened_size: Decimal
    entry_price: Decimal


@dataclass(frozen=True, slots=True)
class DiscrepancyRow:
    """One row of ``reconciliation_discrepancies`` as the mark reads it: the
    pool, the market and the allocations it lists, its status and whether it is
    resolved. The adapter fills it from the reconciliation's own record."""

    discrepancy_id: UUID
    pool: PoolLabel
    symbol: str
    status: str
    venue_net_base: Decimal
    ledger_net_base: Decimal
    open_allocation_ids: tuple[UUID, ...]
    last_observed_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class VenueDisagreement:
    """The mark of a position the venue disagrees on (design section E)."""

    discrepancy_id: UUID
    venue_net_base: Decimal
    ledger_net_base: Decimal
    allocation_count: int
    last_observed_at: datetime


@dataclass(frozen=True, slots=True)
class OpenPosition:
    """One open allocation. ``strategy_id``, ``strategy_archived``,
    ``opened_at``, ``fees``, ``margin_granted``, ``leverage`` and
    ``reservation_status`` are ``None`` only with ``NO_FACTS``: a zero would say
    the position paid no fee."""

    allocation_id: UUID
    strategy_id: UUID | None
    strategy_name: str
    strategy_archived: bool | None
    pool: PoolLabel
    markets: tuple[str, ...]
    origin: Origin
    figures: OpenPositionFigures | None
    figures_missing: FiguresMissing | None
    opened_at: datetime | None
    fill_count: int
    fees: Decimal | None
    other_fees: tuple[FeeAmount, ...]
    margin_granted: Decimal | None
    leverage: Decimal | None
    reservation_status: str | None
    venue_disagreement: VenueDisagreement | None


@dataclass(frozen=True, slots=True)
class InFlightOrder:
    """One ``SUBMITTED`` attempt. ``strategy_id``, ``strategy_archived``,
    ``action`` and ``submitted_at`` are ``None`` on an order the facts could not
    decorate; ``strategy_name`` is ``None`` only when the attempt's parent row is
    missing."""

    attempt_id: UUID
    strategy_id: UUID | None
    strategy_name: str | None
    strategy_archived: bool | None
    pool: PoolLabel
    market: str
    action: OrderAction | None
    origin: OrderOrigin
    submitted_at: datetime | None


@dataclass(frozen=True, slots=True)
class OpenState:
    positions: tuple[OpenPosition, ...]
    orders: tuple[InFlightOrder, ...]


def open_position_figures(
    groups: Sequence[FillAggregate],
) -> OpenPositionFigures | FiguresMissing:
    """The five figures of ONE allocation, or the reason they cannot be derived.
    Never raises for a row: a figure that cannot be derived is a reason, and the
    row stays (design section D; section K row 9).

    The net is the guard's arithmetic, written a second time for display only:
    the base quantity bought, minus the base quantity sold, minus every fee
    charged in the base currency (compared upper-cased). The DECISION that a row
    exists is the fold's; ``FiguresMissing.INCONSISTENT`` is what a row shows if
    the two ever disagree.

    The reasons are tried in this order, so that each is true when it is given:
    no groups at all (``INCONSISTENT``), a symbol that cannot be split
    (``UNRESOLVED_SYMBOL``, since the base-fee rule needs it), several market
    keys (``SEVERAL_MARKETS``), a net of exactly zero (``INCONSISTENT``), a net
    whose sign is the opposite of the earliest fill's side (``FLIPPED``), and a
    held side with no quantity or notional above zero (``INCONSISTENT``). The
    entry price divides only after that last check.
    """
    if not groups:
        return FiguresMissing.INCONSISTENT

    try:
        bases = [base_currency_of(g.symbol, g.settlement_currency).upper() for g in groups]
    except InvariantViolation:
        return FiguresMissing.UNRESOLVED_SYMBOL
    if len({market_key(g.symbol) for g in groups}) > 1:
        return FiguresMissing.SEVERAL_MARKETS

    net = _ZERO
    for group, base in zip(groups, bases, strict=True):
        net += group.quantity if group.side == _BUY else -group.quantity
        if group.fee_currency.upper() == base:
            net -= group.fee
    if net == _ZERO:
        return FiguresMissing.INCONSISTENT

    long = net > _ZERO
    earliest = min(groups, key=lambda g: (g.first_filled_at, g.side != _BUY))
    if (earliest.side == _BUY) != long:
        return FiguresMissing.FLIPPED

    held = [g for g in groups if (g.side == _BUY) == long]
    opened_size = sum((g.quantity for g in held), _ZERO)
    notional = sum((g.notional for g in held), _ZERO)
    if opened_size <= _ZERO or notional <= _ZERO:
        return FiguresMissing.INCONSISTENT

    with localcontext() as context:
        context.prec = QUOTIENT_DIGITS
        entry_price = notional / opened_size
    return OpenPositionFigures(
        side=Direction.LONG if long else Direction.SHORT,
        base_currency=bases[0],
        size=abs(net),
        opened_size=opened_size,
        entry_price=entry_price,
    )


def origin_of(allocation: OpenAllocationOrigin) -> Origin:
    """The guard's origin of an open allocation, from its two flags: both,
    ``MIXED``; rehearsal only, ``REHEARSAL``; otherwise ``LIVE``. This is the
    mapping ``find_mismatches`` applies (``mode_origin.py``), so the panel and the
    guard's refusal name an origin alike. It is the ONLY place the panel decides
    an origin: no second test of the rehearsal prefix exists (K row 5)."""
    if allocation.holds_rehearsal_fill and allocation.holds_live_fill:
        return Origin.MIXED
    if allocation.holds_rehearsal_fill:
        return Origin.REHEARSAL
    return Origin.LIVE


def order_origin(exchange_order_id: str | None) -> OrderOrigin:
    """The origin of an order from its order id: the simulated exchange's prefix
    is a rehearsal order, any other id is live, and no id yet is ``UNKNOWN`` (the
    id is written after the order is sent, so that is a normal short state and a
    lasting one after a crash in between). The test is the guard's own
    (``InFlightAttemptOrigin.rehearsal``): a prefix, not a substring."""
    if exchange_order_id is None:
        return OrderOrigin.UNKNOWN
    if exchange_order_id.startswith(REHEARSAL_ORDER_ID_PREFIX):
        return OrderOrigin.REHEARSAL
    return OrderOrigin.LIVE


def venue_disagreement_for(
    allocation_id: UUID, pool: PoolLabel, rows: Sequence[DiscrepancyRow]
) -> VenueDisagreement | None:
    """The mark of a position the venue disagrees on, or ``None``.

    The KEY is the allocation id inside the pool: a row marks a position when it
    is an open ``CONFIRMED`` row of the position's pool that lists the position's
    allocation id. The market is not the key, and no origin filter exists. A
    confirmed row can outlive the allocation it named (rows are not resolved
    while ``DRY_RUN`` is on), and a later position on the same market would
    inherit a mark that was never about it; an allocation id cannot be inherited
    (K row 1).

    When more than one such row lists the allocation (stored data at fault), the
    most recently observed one is used, the id breaking a tie, so that the answer
    does not depend on the order the rows arrive in."""
    matching = [
        row
        for row in rows
        if row.status == CONFIRMED
        and row.resolved_at is None
        and row.pool == pool
        and allocation_id in row.open_allocation_ids
    ]
    if not matching:
        return None
    row = max(matching, key=lambda r: (r.last_observed_at, r.discrepancy_id))
    return VenueDisagreement(
        discrepancy_id=row.discrepancy_id,
        venue_net_base=row.venue_net_base,
        ledger_net_base=row.ledger_net_base,
        allocation_count=len(set(row.open_allocation_ids)),
        last_observed_at=row.last_observed_at,
    )
