"""``ReadOpenPositions``: decoration and shape, with fakes (design addendum "open
positions", section C; spec "A Position Element Carries Its Identity, Its Pool,
Its Origin And Its Figures", "A Position Or An Order The Facts Cannot Decorate
Keeps Its Row", "An Order In Flight Is Served With Its Origin").

The guard's reader says WHICH rows exist; the facts only decorate them. A row the
facts cannot decorate keeps its shape (``NO_FACTS``, an order with no strategy id,
action or time). The statements run in the design's order: in-flight, open,
submitted, facts, disagreements; the facts statements only when something is open.

Symbols (rule R7): the ledger's fills are ``STXUSDT.P``, the discrepancy row is
``STXUSDT``, an attempt is ``STXUSDT.P``; the guard's element joins raw spellings
as ``STXUSDT / STXUSDT.P``.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
    Origin,
)
from strategy_manager.performance.application.ports import PositionFacts, SubmittedOrder
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.performance.domain.closed_trade import Direction
from strategy_manager.performance.domain.open_position import (
    DiscrepancyRow,
    FiguresMissing,
    OpenPositionFigures,
    OpenState,
    OrderAction,
    OrderOrigin,
    PoolLabel,
)
from strategy_manager.performance.domain.operation import FeeAmount
from tests.performance.fakes import FakeDisagreementSource, FakeFactsSource, FakeOpenStateReader
from tests.performance.open_state_cases import (
    POOL,
    T0,
    fill_aggregate,
    in_flight_element,
    open_element,
    position_facts,
    submitted_order,
)

STRATEGY = UUID("11111111-aaaa-bbbb-cccc-000000000001")


async def _read(
    opened: Sequence[OpenAllocationOrigin] = (),
    in_flight: Sequence[InFlightAttemptOrigin] = (),
    *,
    facts: Mapping[UUID, PositionFacts] | None = None,
    submitted: Sequence[SubmittedOrder] = (),
    rows: Sequence[DiscrepancyRow] = (),
) -> OpenState:
    calls: list[str] = []
    reader = FakeOpenStateReader(opened, in_flight, calls=calls)
    facts_source = FakeFactsSource(facts, submitted, calls=calls)
    disagreements = FakeDisagreementSource(rows, calls=calls)
    return await ReadOpenPositions(reader, facts_source, disagreements).read()


# --- a position, decorated -----------------------------------------------------


async def test_a_position_carries_what_its_fills_and_its_reservation_say() -> None:
    allocation = uuid4()
    element = open_element(
        rehearsal=False, live=True, allocation_id=allocation, symbol="STXUSDT / STXUSDT.P"
    )
    groups = (
        fill_aggregate(allocation, STRATEGY, quantity="2", price="10", fee="0.02", at=T0),
        fill_aggregate(
            allocation,
            STRATEGY,
            side="SELL",
            quantity="0.5",
            price="12",
            symbol="STXUSDT",
            fee="0.01",
            at=T0 + timedelta(minutes=5),
            fill_count=2,
        ),
        fill_aggregate(
            allocation,
            STRATEGY,
            quantity="1",
            price="15",
            fee="0.001",
            fee_currency="stx",
            at=T0 + timedelta(minutes=1),
        ),
    )
    facts = {allocation: position_facts(allocation, STRATEGY, groups, margin="20", leverage="3")}

    state = await _read([element], facts=facts)

    (position,) = state.positions
    assert position.allocation_id == allocation
    assert position.strategy_id == STRATEGY
    assert position.strategy_name == "Alpha"
    assert position.strategy_archived is False
    assert position.pool == POOL
    assert position.markets == ("STXUSDT",)
    assert position.origin is Origin.LIVE
    assert position.figures_missing is None
    with localcontext() as context:
        context.prec = 60
        entry = Decimal(35) / Decimal(3)
    assert position.figures == OpenPositionFigures(
        side=Direction.LONG,
        base_currency="STX",
        size=Decimal("2.499"),
        opened_size=Decimal("3"),
        entry_price=entry,
    )
    assert position.opened_at == T0
    assert position.fill_count == 4
    assert position.fees == Decimal("0.03")
    assert position.other_fees == (FeeAmount(currency="STX", amount=Decimal("0.001")),)
    assert position.margin_granted == Decimal("20")
    assert position.leverage == Decimal("3")
    assert position.reservation_status == "FILLED"
    assert position.venue_disagreement is None


async def test_a_spot_position_has_no_leverage_and_a_rehearsal_one_has_one() -> None:
    spot, rehearsal = uuid4(), uuid4()
    elements = [
        open_element(rehearsal=False, live=True, allocation_id=spot),
        open_element(rehearsal=True, live=False, allocation_id=rehearsal),
    ]
    facts = {
        spot: position_facts(spot, STRATEGY, (fill_aggregate(spot, STRATEGY),), leverage=None),
        rehearsal: position_facts(
            rehearsal, STRATEGY, (fill_aggregate(rehearsal, STRATEGY),), leverage="1.00000000"
        ),
    }

    state = await _read(elements, facts=facts)

    first, second = state.positions
    assert first.leverage is None
    assert second.leverage == Decimal(1)
    assert (first.origin, second.origin) == (Origin.LIVE, Origin.REHEARSAL)


async def test_a_reservation_that_is_not_filled_is_served_as_stored() -> None:
    allocation = uuid4()
    element = open_element(rehearsal=False, live=True, allocation_id=allocation)
    facts = {
        allocation: position_facts(
            allocation, STRATEGY, (fill_aggregate(allocation, STRATEGY),), status="EXPIRED"
        )
    }

    state = await _read([element], facts=facts)

    (position,) = state.positions
    assert position.reservation_status == "EXPIRED"
    assert position.margin_granted == Decimal("20")


async def test_the_pool_served_is_the_elements_and_never_the_reservations() -> None:
    allocation = uuid4()
    element = open_element(rehearsal=False, live=True, allocation_id=allocation)
    reservation_pool = PoolLabel("binance", "usdt-m", "USDT")
    facts = {
        allocation: position_facts(
            allocation,
            STRATEGY,
            (fill_aggregate(allocation, STRATEGY),),
            reservation_pool=reservation_pool,
        )
    }

    state = await _read([element], facts=facts)

    (position,) = state.positions
    assert position.pool == POOL


async def test_the_strategy_served_is_the_reservations() -> None:
    allocation, other = uuid4(), uuid4()
    element = open_element(rehearsal=False, live=True, allocation_id=allocation)
    groups = (fill_aggregate(allocation, other),)
    facts = {allocation: position_facts(allocation, STRATEGY, groups, archived=True)}

    state = await _read([element], facts=facts)

    (position,) = state.positions
    assert position.strategy_id == STRATEGY
    assert position.strategy_archived is True


async def test_fills_that_name_a_symbol_that_cannot_be_split_keep_the_row_with_a_reason() -> None:
    allocation = uuid4()
    element = open_element(rehearsal=False, live=True, allocation_id=allocation, symbol="XYZBTC")
    groups = (fill_aggregate(allocation, STRATEGY, symbol="XYZBTC", fee="0.02"),)
    facts = {allocation: position_facts(allocation, STRATEGY, groups)}

    state = await _read([element], facts=facts)

    (position,) = state.positions
    assert position.figures is None
    assert position.figures_missing is FiguresMissing.UNRESOLVED_SYMBOL
    assert position.markets == ("XYZBTC",)
    assert position.opened_at == T0
    assert position.fees == Decimal("0.02")
    assert position.margin_granted == Decimal("20")
    assert position.leverage == Decimal("3")


# --- a position, undecorated ---------------------------------------------------


async def test_a_position_with_no_facts_is_built_from_the_readers_element() -> None:
    allocation, decorated = uuid4(), uuid4()
    undecorated = open_element(
        rehearsal=True,
        live=False,
        allocation_id=allocation,
        name="Gamma",
        exchange="binance",
        symbol="STXUSDT / STXUSDT.P",
    )
    other = open_element(rehearsal=False, live=True, allocation_id=decorated)
    facts = {
        decorated: position_facts(decorated, STRATEGY, (fill_aggregate(decorated, STRATEGY),))
    }

    state = await _read([undecorated, other], facts=facts)

    first, second = state.positions
    assert first.allocation_id == allocation
    assert first.figures_missing is FiguresMissing.NO_FACTS
    assert first.figures is None
    assert first.strategy_name == "Gamma"
    assert first.pool == PoolLabel("binance", "usdt-m", "USDT")
    assert first.origin is Origin.REHEARSAL
    assert first.markets == ("STXUSDT",)
    assert first.strategy_id is None
    assert first.strategy_archived is None
    assert first.opened_at is None
    assert first.fill_count == 0
    assert first.fees is None
    assert first.other_fees == ()
    assert first.margin_granted is None
    assert first.leverage is None
    assert first.reservation_status is None
    assert second.figures_missing is None  # the neighbour is decorated


async def test_the_readers_string_is_split_normalised_deduplicated_and_sorted() -> None:
    elements = [
        open_element(rehearsal=False, live=True, symbol="STXUSDT / STXUSDT.P"),
        open_element(rehearsal=False, live=True, symbol="SOLUSDT.P / AAVEUSDT / SOLUSDT_PERP"),
        open_element(rehearsal=False, live=True, symbol="XYZBTC"),
    ]

    state = await _read(elements)

    assert [p.markets for p in state.positions] == [
        ("STXUSDT",),
        ("AAVEUSDT", "SOLUSDT"),
        ("XYZBTC",),
    ]


async def test_facts_with_no_fills_leave_the_position_as_if_it_had_no_facts() -> None:
    allocation = uuid4()
    element = open_element(rehearsal=False, live=True, allocation_id=allocation)
    facts = {allocation: position_facts(allocation, STRATEGY, ())}

    state = await _read([element], facts=facts)

    (position,) = state.positions
    assert position.figures_missing is FiguresMissing.NO_FACTS
    assert position.strategy_id is None


# --- the venue mark ------------------------------------------------------------


def _row(
    *allocations: UUID,
    pool: PoolLabel = POOL,
    symbol: str = "STXUSDT",
    status: str = "CONFIRMED",
) -> DiscrepancyRow:
    return DiscrepancyRow(
        discrepancy_id=uuid4(),
        pool=pool,
        symbol=symbol,
        status=status,
        venue_net_base=Decimal("0"),
        ledger_net_base=Decimal("0.82"),
        open_allocation_ids=tuple(allocations),
        last_observed_at=datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
        resolved_at=None,
    )


async def test_a_confirmed_row_marks_the_positions_it_names_and_only_those() -> None:
    marked, also_marked, unmarked, undecorated = uuid4(), uuid4(), uuid4(), uuid4()
    elements = [
        open_element(rehearsal=False, live=True, allocation_id=a)
        for a in (marked, also_marked, unmarked, undecorated)
    ]
    facts = {
        a: position_facts(a, STRATEGY, (fill_aggregate(a, STRATEGY, symbol="STXUSDT.P"),))
        for a in (marked, also_marked, unmarked)
    }
    row = _row(marked, also_marked, undecorated)

    state = await _read(elements, facts=facts, rows=[row])

    by_id = {p.allocation_id: p for p in state.positions}
    for allocation in (marked, also_marked, undecorated):
        mark = by_id[allocation].venue_disagreement
        assert mark is not None
        assert mark.discrepancy_id == row.discrepancy_id
        assert mark.allocation_count == 3
        assert (mark.venue_net_base, mark.ledger_net_base) == (Decimal(0), Decimal("0.82"))
    assert by_id[unmarked].venue_disagreement is None
    assert by_id[undecorated].figures_missing is FiguresMissing.NO_FACTS


async def test_a_stale_row_or_an_observed_one_or_one_of_another_pool_marks_nothing() -> None:
    allocation, gone = uuid4(), uuid4()
    element = open_element(rehearsal=True, live=False, allocation_id=allocation)
    groups = (fill_aggregate(allocation, STRATEGY),)
    facts = {allocation: position_facts(allocation, STRATEGY, groups)}
    rows = [
        _row(gone),
        _row(allocation, status="OBSERVED"),
        _row(allocation, pool=PoolLabel("binance", "usdt-m", "USDT")),
    ]

    state = await _read([element], facts=facts, rows=rows)

    (position,) = state.positions
    assert position.venue_disagreement is None


# --- an order in flight --------------------------------------------------------


async def test_an_order_is_decorated_from_the_submitted_read_by_attempt_id() -> None:
    attempt, other = uuid4(), uuid4()
    sent = T0 + timedelta(hours=1)
    elements = [
        in_flight_element(rehearsal=False, attempt_id=attempt, name="Beta", symbol="STXUSDT.P"),
        in_flight_element(rehearsal=True, attempt_id=other, symbol="ETHUSDT.P"),
    ]
    submitted = [
        submitted_order(
            other, opening=False, symbol="ETHUSDT_PERP", created_at=sent, strategy_id=STRATEGY
        ),
        submitted_order(
            attempt,
            opening=True,
            symbol="STXUSDT_PERP",
            created_at=sent,
            strategy_id=STRATEGY,
            archived=True,
        ),
    ]

    state = await _read(in_flight=elements, submitted=submitted)

    first, second = state.orders
    assert (first.attempt_id, second.attempt_id) == (attempt, other)
    assert first.strategy_id == STRATEGY
    assert first.strategy_name == "Beta"
    assert first.strategy_archived is True
    assert first.pool == POOL
    assert first.market == "STXUSDT"
    assert first.action is OrderAction.OPEN
    assert first.origin is OrderOrigin.LIVE
    assert first.submitted_at == sent
    assert second.action is OrderAction.CLOSE
    assert second.origin is OrderOrigin.REHEARSAL
    assert second.market == "ETHUSDT"
    assert len(state.orders) == 2  # the submitted read did not add a second row for either


async def test_an_order_the_submitted_read_has_no_row_for_keeps_its_row() -> None:
    attempt = uuid4()
    element = in_flight_element(
        rehearsal=False, attempt_id=attempt, name="Beta", exchange="binance", symbol="STXUSDT.P"
    )

    state = await _read(in_flight=[element], submitted=[])

    (order,) = state.orders
    assert order.attempt_id == attempt
    assert order.strategy_id is None
    assert order.strategy_archived is None
    assert order.action is None
    assert order.submitted_at is None
    assert order.strategy_name == "Beta"
    assert order.pool == PoolLabel("binance", "usdt-m", "USDT")
    assert order.market == "STXUSDT"
    assert order.origin is OrderOrigin.LIVE


async def test_a_submitted_attempt_the_reader_did_not_return_is_one_more_order() -> None:
    in_reader, no_id, rehearsal, live = uuid4(), uuid4(), uuid4(), uuid4()
    sent = T0 + timedelta(minutes=7)
    elements = [in_flight_element(rehearsal=False, attempt_id=in_reader)]
    submitted = [
        submitted_order(no_id, order_id=None, symbol="STXUSDT_PERP", created_at=sent),
        submitted_order(in_reader, strategy_id=STRATEGY),
        submitted_order(rehearsal, order_id="fake-order-9", opening=False, symbol="SOLUSDT.P"),
        submitted_order(live, order_id="1234567", symbol="AAVEUSDT"),
    ]

    state = await _read(in_flight=elements, submitted=submitted)

    assert [o.attempt_id for o in state.orders] == [in_reader, no_id, rehearsal, live]
    _, unknown, fake, real = state.orders
    assert unknown.origin is OrderOrigin.UNKNOWN
    assert unknown.market == "STXUSDT"
    assert unknown.action is OrderAction.OPEN
    assert unknown.submitted_at == sent
    assert fake.origin is OrderOrigin.REHEARSAL
    assert fake.action is OrderAction.CLOSE
    assert real.origin is OrderOrigin.LIVE


async def test_an_extra_order_whose_parent_row_is_missing_has_no_strategy() -> None:
    attempt = uuid4()
    submitted = [
        submitted_order(
            attempt, strategy_id=None, name=None, archived=None, reservation_pool=None
        )
    ]

    state = await _read(submitted=submitted)

    assert [o.attempt_id for o in state.orders] == [attempt], "the attempt is one more order"
    (order,) = state.orders
    assert (order.strategy_id, order.strategy_name, order.strategy_archived) == (None, None, None)
    assert order.action is OrderAction.OPEN
    assert order.pool == POOL


# --- the statements ------------------------------------------------------------


async def test_with_nothing_open_the_facts_statements_do_not_run() -> None:
    calls: list[str] = []
    reader = FakeOpenStateReader([], [], calls=calls)

    await ReadOpenPositions(
        reader, FakeFactsSource(calls=calls), FakeDisagreementSource(calls=calls)
    ).read()

    assert calls == ["in_flight", "open", "submitted"]


async def test_the_statements_run_in_the_designs_order_once_each() -> None:
    first, second = uuid4(), uuid4()
    calls: list[str] = []
    reader = FakeOpenStateReader(
        [
            open_element(rehearsal=False, live=True, allocation_id=first),
            open_element(rehearsal=False, live=True, allocation_id=second),
        ],
        [in_flight_element(rehearsal=False)],
        calls=calls,
    )
    facts = FakeFactsSource(calls=calls)

    await ReadOpenPositions(reader, facts, FakeDisagreementSource(calls=calls)).read()

    assert calls == ["in_flight", "open", "submitted", "facts", "disagreements"]
    assert facts.asked_ids == [[first, second]]
