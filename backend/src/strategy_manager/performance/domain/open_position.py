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

THIS FILE IS THE STUB of task op.1.7: every type is final, and the three
functions answer wrongly on purpose, so that the tests that follow fail on an
assertion and not on a missing name.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from strategy_manager.execution.domain.mode_origin import OpenAllocationOrigin, Origin
from strategy_manager.performance.domain.closed_trade import Direction
from strategy_manager.performance.domain.operation import FeeAmount


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
    """STUB (op.1.7): answers wrongly. Replaced by task op.1.12."""
    return FiguresMissing.INCONSISTENT


def origin_of(allocation: OpenAllocationOrigin) -> Origin:
    """STUB (op.1.7): answers wrongly. Replaced by task op.1.15."""
    return Origin.LIVE


def order_origin(exchange_order_id: str | None) -> OrderOrigin:
    """STUB (op.1.7): answers wrongly. Replaced by task op.1.17."""
    return OrderOrigin.UNKNOWN


def venue_disagreement_for(
    allocation_id: UUID, pool: PoolLabel, rows: Sequence[DiscrepancyRow]
) -> VenueDisagreement | None:
    """STUB (op.1.7): answers wrongly. Replaced by task op.1.15."""
    return None
