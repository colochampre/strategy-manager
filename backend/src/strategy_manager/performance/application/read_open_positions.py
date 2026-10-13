"""``ReadOpenPositions``: every open position and every in-flight order of the
system (design addendum "open positions", decision 65, section C).

**The invariant (section B).** The answer holds exactly one row per element of
the mode guard's own reader: one position per element of
``open_allocations()`` and one order per element of ``in_flight_attempts()``.
Nothing else decides that a row exists. The facts read afterwards only DECORATE
a row; they never remove one, and there is no branch in this module that
filters, groups or merges either sequence. An empty answer therefore means the
guard's two inputs were empty.

The sequence is the design's: the in-flight read first, then the open-allocations
read, on purpose (should the snapshot ever be lost, an order read as in flight
and filled before the second read shows twice for one refresh, never missing);
then every ``SUBMITTED`` attempt; then, only when something is open, the facts of
the open allocations and the confirmed disagreements. Each is one statement,
never one per row.

A row the facts cannot decorate stays, built from the reader's own element.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from uuid import UUID

from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)
from strategy_manager.performance.application.ports import (
    ConfirmedDisagreementSourcePort,
    OpenPositionFactsSourcePort,
    OpenStateSourcePort,
    PositionFacts,
    SubmittedOrder,
)
from strategy_manager.performance.domain.open_position import (
    DiscrepancyRow,
    FiguresMissing,
    InFlightOrder,
    OpenPosition,
    OpenPositionFigures,
    OpenState,
    OrderAction,
    OrderOrigin,
    PoolLabel,
    open_position_figures,
    order_origin,
    origin_of,
    venue_disagreement_for,
)
from strategy_manager.performance.domain.operation import operation_fees

# ``fold_open_allocations`` joins the RAW spellings of an allocation's symbols
# with this separator (``mode_origin.py``).
_READER_SEPARATOR = " / "


class ReadOpenPositions:
    def __init__(
        self,
        state: OpenStateSourcePort,
        facts: OpenPositionFactsSourcePort,
        disagreements: ConfirmedDisagreementSourcePort,
    ) -> None:
        self._state = state
        self._facts = facts
        self._disagreements = disagreements

    async def read(self) -> OpenState:
        # Step 1, then step 2: in that order on purpose (section C).
        in_flight = await self._state.in_flight_attempts()
        opened = await self._state.open_allocations()
        submitted = await self._facts.submitted_orders()

        facts: Mapping[UUID, PositionFacts] = {}
        rows: Sequence[DiscrepancyRow] = ()
        if opened:
            facts = await self._facts.position_facts([e.allocation_id for e in opened])
            rows = await self._disagreements.confirmed_open()

        # One row per element, unconditionally. Do not add a branch here.
        positions = tuple(
            _position(element, facts.get(element.allocation_id), rows) for element in opened
        )
        submitted_by_attempt = {row.attempt_id: row for row in submitted}
        orders = tuple(
            _order(element, submitted_by_attempt.get(element.attempt_id)) for element in in_flight
        )
        # The reader cannot judge an attempt that has no order id yet. It is one
        # more order, not a replacement for any of the reader's.
        returned = {element.attempt_id for element in in_flight}
        extra = tuple(
            _order_from_submitted(row) for row in submitted if row.attempt_id not in returned
        )
        return OpenState(positions=positions, orders=orders + extra)


def _position(
    element: OpenAllocationOrigin,
    facts: PositionFacts | None,
    rows: Sequence[DiscrepancyRow],
) -> OpenPosition:
    if facts is None or not facts.groups:
        position = _position_from_reader(element)
    else:
        position = _position_from_facts(element, facts)
    pool = position.pool
    return replace(
        position, venue_disagreement=venue_disagreement_for(element.allocation_id, pool, rows)
    )


def _position_from_facts(element: OpenAllocationOrigin, facts: PositionFacts) -> OpenPosition:
    groups = facts.groups
    figures = open_position_figures(groups)
    fees = operation_fees(groups)
    return OpenPosition(
        allocation_id=element.allocation_id,
        strategy_id=facts.strategy_id,
        strategy_name=element.strategy_name,
        strategy_archived=facts.strategy_archived,
        pool=_pool_of(element),
        markets=tuple(sorted({market_key(group.symbol) for group in groups})),
        origin=origin_of(element),
        figures=figures if isinstance(figures, OpenPositionFigures) else None,
        figures_missing=figures if isinstance(figures, FiguresMissing) else None,
        opened_at=min(group.first_filled_at for group in groups),
        fill_count=sum(group.fill_count for group in groups),
        fees=fees.fees,
        other_fees=fees.other_fees,
        margin_granted=facts.margin_granted,
        leverage=facts.leverage,
        reservation_status=facts.reservation_status,
        venue_disagreement=None,
    )


def _position_from_reader(element: OpenAllocationOrigin) -> OpenPosition:
    """The shape of a position the facts cannot decorate (``NO_FACTS``): its
    name, pool, markets and origin are the reader's own; everything the facts
    would have said is null, never a zero."""
    return OpenPosition(
        allocation_id=element.allocation_id,
        strategy_id=None,
        strategy_name=element.strategy_name,
        strategy_archived=None,
        pool=_pool_of(element),
        markets=_markets_of(element.symbol),
        origin=origin_of(element),
        figures=None,
        figures_missing=FiguresMissing.NO_FACTS,
        opened_at=None,
        fill_count=0,
        fees=None,
        other_fees=(),
        margin_granted=None,
        leverage=None,
        reservation_status=None,
        venue_disagreement=None,
    )


def _order(element: InFlightAttemptOrigin, row: SubmittedOrder | None) -> InFlightOrder:
    order = _order_from_reader(element)
    if row is None:
        return order
    return replace(
        order,
        strategy_id=row.strategy_id,
        strategy_archived=row.strategy_archived,
        action=OrderAction.OPEN if row.opening else OrderAction.CLOSE,
        submitted_at=row.created_at,
    )


def _order_from_reader(element: InFlightAttemptOrigin) -> InFlightOrder:
    """The shape of an order the submitted-orders read has no row for: the
    reader's own attempt id, name, pool, symbol and order id; no strategy id,
    action or time."""
    return InFlightOrder(
        attempt_id=element.attempt_id,
        strategy_id=None,
        strategy_name=element.strategy_name,
        strategy_archived=None,
        pool=_pool_of(element),
        market=market_key(element.symbol),
        action=None,
        origin=OrderOrigin.REHEARSAL if element.rehearsal else OrderOrigin.LIVE,
        submitted_at=None,
    )


def _order_from_submitted(row: SubmittedOrder) -> InFlightOrder:
    return InFlightOrder(
        attempt_id=row.attempt_id,
        strategy_id=row.strategy_id,
        strategy_name=row.strategy_name,
        strategy_archived=row.strategy_archived,
        pool=row.pool,
        market=market_key(row.symbol),
        action=OrderAction.OPEN if row.opening else OrderAction.CLOSE,
        origin=order_origin(row.exchange_order_id),
        submitted_at=row.created_at,
    )


def _pool_of(element: OpenAllocationOrigin | InFlightAttemptOrigin) -> PoolLabel:
    """The guard's own pool label of an element. Never replaced by the
    reservation's (design section C)."""
    return PoolLabel(element.exchange, element.venue, element.settlement_currency)


def _markets_of(reader_symbol: str) -> tuple[str, ...]:
    """The reader's string (``STXUSDT / STXUSDT.P``) as market keys: split on the
    reader's separator, each piece through ``market_key``, duplicates dropped,
    sorted. One market opened as ``STXUSDT.P`` and booked as ``STXUSDT`` is
    written once."""
    return tuple(
        sorted({market_key(piece) for piece in reader_symbol.split(_READER_SEPARATOR)})
    )
