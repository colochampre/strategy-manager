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
and filled before the second read shows twice for one refresh, never missing).
"""

from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)
from strategy_manager.performance.application.ports import (
    ConfirmedDisagreementSourcePort,
    OpenPositionFactsSourcePort,
    OpenStateSourcePort,
)
from strategy_manager.performance.domain.open_position import (
    FiguresMissing,
    InFlightOrder,
    OpenPosition,
    OpenState,
    OrderOrigin,
    PoolLabel,
    origin_of,
)

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

        # One row per element, unconditionally. Do not add a branch here.
        positions = tuple(_position_from_reader(element) for element in opened)
        orders = tuple(_order_from_reader(element) for element in in_flight)
        return OpenState(positions=positions, orders=orders)


def _position_from_reader(element: OpenAllocationOrigin) -> OpenPosition:
    """The shape of a position the facts cannot decorate (``NO_FACTS``): its
    name, pool, markets and origin are the reader's own; everything the facts
    would have said is null, never a zero."""
    return OpenPosition(
        allocation_id=element.allocation_id,
        strategy_id=None,
        strategy_name=element.strategy_name,
        strategy_archived=None,
        pool=PoolLabel(element.exchange, element.venue, element.settlement_currency),
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


def _order_from_reader(element: InFlightAttemptOrigin) -> InFlightOrder:
    """The shape of an order the submitted-orders read has no row for: the
    reader's own attempt id, name, pool, symbol and order id; no strategy id,
    action or time."""
    return InFlightOrder(
        attempt_id=element.attempt_id,
        strategy_id=None,
        strategy_name=element.strategy_name,
        strategy_archived=None,
        pool=PoolLabel(element.exchange, element.venue, element.settlement_currency),
        market=market_key(element.symbol),
        action=None,
        origin=OrderOrigin.REHEARSAL if element.rehearsal else OrderOrigin.LIVE,
        submitted_at=None,
    )


def _markets_of(reader_symbol: str) -> tuple[str, ...]:
    """The reader's string (``STXUSDT / STXUSDT.P``) as market keys: split on the
    reader's separator, each piece through ``market_key``, duplicates dropped,
    sorted. One market opened as ``STXUSDT.P`` and booked as ``STXUSDT`` is
    written once."""
    return tuple(
        sorted({market_key(piece) for piece in reader_symbol.split(_READER_SEPARATOR)})
    )
