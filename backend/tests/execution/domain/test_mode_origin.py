"""Decision 28: the pure part of the ``DRY_RUN`` mode guard.

``fold_open_allocations`` decides what is OPEN, by the ledger's own rule (net
base quantity exactly zero under the base-fee rule, the one ``derive_trade``
and ``net_base_quantity`` use). ``find_mismatches`` decides which of those, and
which in-flight orders, belong to the OTHER mode.
"""

from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.domain.fill import REHEARSAL_ORDER_ID_PREFIX
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    Kind,
    LedgerGroup,
    ModeMismatch,
    OpenAllocationOrigin,
    Origin,
    describe_refusal,
    find_mismatches,
    fold_open_allocations,
)


def _group(
    allocation_id: UUID,
    *,
    side: str = "BUY",
    quantity: str = "1",
    fee: str = "0",
    fee_currency: str = "USDT",
    rehearsal: bool = True,
    symbol: str = "SOLUSDT.P",
    strategy_name: str = "Alpha",
    exchange: str = "bybit",
    venue: str = "usdt-m",
) -> LedgerGroup:
    return LedgerGroup(
        allocation_id=allocation_id,
        strategy_name=strategy_name,
        exchange=exchange,
        venue=venue,
        settlement_currency="USDT",
        symbol=symbol,
        side=side,
        fee_currency=fee_currency,
        rehearsal=rehearsal,
        quantity=Decimal(quantity),
        fee=Decimal(fee),
    )


def _open(
    *,
    rehearsal: bool = False,
    live: bool = False,
    strategy_name: str = "Alpha",
    symbol: str = "SOLUSDT.P",
    allocation_id: UUID | None = None,
) -> OpenAllocationOrigin:
    return OpenAllocationOrigin(
        allocation_id=allocation_id or uuid4(),
        strategy_name=strategy_name,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=symbol,
        holds_rehearsal_fill=rehearsal,
        holds_live_fill=live,
    )


def _in_flight(order_id: str, *, strategy_name: str = "Beta") -> InFlightAttemptOrigin:
    return InFlightAttemptOrigin(
        attempt_id=uuid4(),
        strategy_name=strategy_name,
        exchange="binance",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="ETHUSDT.P",
        exchange_order_id=order_id,
    )


# --- fold_open_allocations: "open" is the ledger's own rule ----------------


def test_an_allocation_with_only_a_rehearsal_buy_is_open_and_holds_a_rehearsal_fill() -> None:
    allocation = uuid4()

    opened = fold_open_allocations([_group(allocation, rehearsal=True)])

    assert len(opened) == 1
    assert opened[0].allocation_id == allocation
    assert opened[0].holds_rehearsal_fill is True
    assert opened[0].holds_live_fill is False
    assert (opened[0].strategy_name, opened[0].symbol) == ("Alpha", "SOLUSDT.P")


def test_an_allocation_with_only_a_live_buy_holds_a_live_fill() -> None:
    opened = fold_open_allocations([_group(uuid4(), rehearsal=False)])

    assert len(opened) == 1
    assert opened[0].holds_rehearsal_fill is False
    assert opened[0].holds_live_fill is True


def test_a_closed_rehearsal_allocation_is_not_open() -> None:
    """6d.4: net base exactly zero is closed, so a finished rehearsal round
    trip never blocks a live start."""
    allocation = uuid4()

    opened = fold_open_allocations(
        [
            _group(allocation, side="BUY", quantity="0.5"),
            _group(allocation, side="SELL", quantity="0.5"),
        ]
    )

    assert opened == ()


def test_a_remainder_however_small_keeps_the_allocation_open() -> None:
    """No tolerance: the ledger's definition, so the check agrees with
    ``net_positions_by_symbol`` and ``ClosePosition`` about what is held."""
    allocation = uuid4()

    opened = fold_open_allocations(
        [
            _group(allocation, side="BUY", quantity="0.5"),
            _group(allocation, side="SELL", quantity="0.499999999999999999"),
        ]
    )

    assert [o.allocation_id for o in opened] == [allocation]


def test_a_fee_charged_in_the_base_currency_leaves_a_remainder_the_sell_did_not_cover() -> None:
    """Pionex spot took a BUY's fee in the base coin: 1 bought, 0.001 kept by
    the venue, so selling 1 is short by 0.001 and the allocation is NOT flat.
    Selling what actually arrived (0.999) is."""
    allocation = uuid4()
    buy = _group(allocation, side="BUY", quantity="1", fee="0.001", fee_currency="sol")

    still_open = fold_open_allocations(
        [buy, _group(allocation, side="SELL", quantity="1")]
    )
    flat = fold_open_allocations(
        [buy, _group(allocation, side="SELL", quantity="0.999")]
    )

    assert [o.allocation_id for o in still_open] == [allocation]
    assert flat == ()


def test_a_fee_in_the_settlement_currency_does_not_touch_the_base_holding() -> None:
    allocation = uuid4()

    opened = fold_open_allocations(
        [
            _group(allocation, side="BUY", quantity="1", fee="0.5", fee_currency="USDT"),
            _group(allocation, side="SELL", quantity="1", fee="0.5", fee_currency="USDT"),
        ]
    )

    assert opened == ()


def test_an_open_and_a_close_under_two_spellings_are_one_closed_allocation() -> None:
    """Grouped by allocation, never by symbol: an allocation opened as
    ``SOLUSDT.P`` and closed as ``SOLUSDT`` is flat, not two open halves."""
    allocation = uuid4()

    opened = fold_open_allocations(
        [
            _group(allocation, side="BUY", symbol="SOLUSDT.P"),
            _group(allocation, side="SELL", symbol="SOLUSDT"),
        ]
    )

    assert opened == ()


def test_an_allocation_with_both_kinds_of_fill_reports_both() -> None:
    allocation = uuid4()

    opened = fold_open_allocations(
        [
            _group(allocation, side="BUY", quantity="2", rehearsal=False),
            _group(allocation, side="SELL", quantity="1", rehearsal=True),
        ]
    )

    assert len(opened) == 1
    assert opened[0].holds_rehearsal_fill is True
    assert opened[0].holds_live_fill is True


def test_each_allocation_is_judged_on_its_own_rows() -> None:
    closed, held = uuid4(), uuid4()

    opened = fold_open_allocations(
        [
            _group(closed, side="BUY"),
            _group(closed, side="SELL"),
            _group(held, side="BUY", strategy_name="Gamma", rehearsal=False),
        ]
    )

    assert [(o.allocation_id, o.strategy_name) for o in opened] == [(held, "Gamma")]


def test_a_symbol_whose_base_currency_cannot_be_split_fails_closed_as_open() -> None:
    """``base_currency_of`` refuses a symbol not quoted in the pool's currency.
    The base-fee rule cannot be applied, so the allocation is reported rather
    than assumed flat: a guard that guesses 'closed' is the one that lets a
    real position through."""
    allocation = uuid4()

    opened = fold_open_allocations(
        [
            _group(allocation, side="BUY", symbol="WEIRD"),
            _group(allocation, side="SELL", symbol="WEIRD"),
        ]
    )

    assert [o.allocation_id for o in opened] == [allocation]


# --- find_mismatches: DRY_RUN=false --------------------------------------


def test_live_mode_refuses_an_open_allocation_holding_a_rehearsal_fill() -> None:
    offender = _open(rehearsal=True)

    found = find_mismatches(dry_run=False, open_allocations=[offender], in_flight=[])

    assert found == (
        ModeMismatch(
            kind=Kind.POSITION,
            origin=Origin.REHEARSAL,
            identifier=offender.allocation_id,
            strategy_name="Alpha",
            pool="bybit/usdt-m/USDT",
            symbol="SOLUSDT.P",
        ),
    )


def test_live_mode_accepts_an_open_allocation_holding_only_live_fills() -> None:
    assert find_mismatches(
        dry_run=False, open_allocations=[_open(live=True)], in_flight=[]
    ) == ()


# --- find_mismatches: DRY_RUN=true ---------------------------------------


def test_dry_run_refuses_an_open_allocation_holding_a_live_fill() -> None:
    offender = _open(live=True)

    found = find_mismatches(dry_run=True, open_allocations=[offender], in_flight=[])

    assert [(m.kind, m.origin, m.identifier) for m in found] == [
        (Kind.POSITION, Origin.LIVE, offender.allocation_id)
    ]


def test_dry_run_accepts_an_open_allocation_holding_only_rehearsal_fills() -> None:
    assert find_mismatches(
        dry_run=True, open_allocations=[_open(rehearsal=True)], in_flight=[]
    ) == ()


# --- find_mismatches: both kinds, and nothing at all ------------------------


def test_an_allocation_holding_both_kinds_refuses_in_either_mode() -> None:
    mixed = _open(rehearsal=True, live=True)

    for dry_run in (True, False):
        found = find_mismatches(dry_run=dry_run, open_allocations=[mixed], in_flight=[])
        assert [(m.origin, m.identifier) for m in found] == [
            (Origin.MIXED, mixed.allocation_id)
        ], dry_run


def test_nothing_open_and_nothing_in_flight_refuses_nothing() -> None:
    for dry_run in (True, False):
        assert find_mismatches(dry_run=dry_run, open_allocations=[], in_flight=[]) == ()


def test_every_offender_is_reported_not_only_the_first() -> None:
    first, second = _open(rehearsal=True, strategy_name="Alpha"), _open(
        rehearsal=True, strategy_name="Zeta"
    )
    fine = _open(live=True, strategy_name="Live")

    found = find_mismatches(
        dry_run=False, open_allocations=[second, fine, first], in_flight=[]
    )

    assert [m.strategy_name for m in found] == ["Alpha", "Zeta"]


# --- find_mismatches: in-flight orders ----------------------------------------


def test_live_mode_refuses_a_rehearsal_order_still_waiting_to_settle() -> None:
    order = _in_flight(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}")

    found = find_mismatches(dry_run=False, open_allocations=[], in_flight=[order])

    assert [(m.kind, m.origin, m.identifier, m.strategy_name) for m in found] == [
        (Kind.ORDER, Origin.REHEARSAL, order.attempt_id, "Beta")
    ]


def test_live_mode_accepts_a_live_order_still_waiting_to_settle() -> None:
    order = _in_flight("8f0c2a3e-6a51-4c1b-9d0a-2f7c1e5b7a10")

    assert find_mismatches(dry_run=False, open_allocations=[], in_flight=[order]) == ()


def test_dry_run_refuses_a_live_order_still_waiting_to_settle() -> None:
    """The dangerous direction for an order: its settle would ask the fake
    exchange, get OrderNotFound, and release a reservation for an order that
    really filled."""
    order = _in_flight("1234567890123")

    found = find_mismatches(dry_run=True, open_allocations=[], in_flight=[order])

    assert [(m.kind, m.origin, m.identifier) for m in found] == [
        (Kind.ORDER, Origin.LIVE, order.attempt_id)
    ]


def test_dry_run_accepts_a_rehearsal_order_still_waiting_to_settle() -> None:
    order = _in_flight(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}")

    assert find_mismatches(dry_run=True, open_allocations=[], in_flight=[order]) == ()


# --- describe_refusal ----------------------------------------------------------


def _mismatch(
    origin: Origin, *, kind: Kind = Kind.POSITION, strategy_name: str = "Alpha"
) -> ModeMismatch:
    return ModeMismatch(
        kind=kind,
        origin=origin,
        identifier=UUID("11111111-2222-3333-4444-555555555555"),
        strategy_name=strategy_name,
        pool="bybit/usdt-m/USDT",
        symbol="SOLUSDT.P",
    )


def test_the_refusal_names_strategy_pool_symbol_and_allocation_id() -> None:
    text = describe_refusal(dry_run=False, mismatches=[_mismatch(Origin.REHEARSAL)])

    for expected in (
        "Alpha",
        "bybit/usdt-m/USDT",
        "SOLUSDT.P",
        "11111111-2222-3333-4444-555555555555",
    ):
        assert expected in text


def test_the_refusal_states_the_mode_and_the_way_out() -> None:
    live = describe_refusal(dry_run=False, mismatches=[_mismatch(Origin.REHEARSAL)])
    rehearsal = describe_refusal(dry_run=True, mismatches=[_mismatch(Origin.LIVE)])

    assert "DRY_RUN is false" in live
    assert "DRY_RUN is true" in rehearsal
    assert "rehearsal" in live
    assert "live" in rehearsal
    # The way out is the same instruction in both, and names both modes: close
    # it where it was opened, then flip.
    for text in (live, rehearsal):
        assert "close" in text
        assert "DRY_RUN=true" in text
        assert "DRY_RUN=false" in text
        assert "then flip" in text


def test_the_dangerous_direction_says_why_a_fake_close_is_not_a_way_out() -> None:
    text = describe_refusal(dry_run=True, mismatches=[_mismatch(Origin.LIVE)])

    assert "still be open" in text


def test_a_mixed_allocation_says_neither_mode_can_close_it() -> None:
    text = describe_refusal(dry_run=False, mismatches=[_mismatch(Origin.MIXED)])

    assert "both rehearsal and live" in text
    assert "neither mode" in text


def test_an_order_is_described_as_an_order_with_the_attempt_id() -> None:
    text = describe_refusal(
        dry_run=False,
        mismatches=[_mismatch(Origin.REHEARSAL, kind=Kind.ORDER, strategy_name="Beta")],
    )

    assert "order" in text
    assert "execution attempt 11111111-2222-3333-4444-555555555555" in text
    assert "Beta" in text


def test_every_offender_appears_in_the_one_message() -> None:
    text = describe_refusal(
        dry_run=False,
        mismatches=[
            _mismatch(Origin.REHEARSAL, strategy_name="Alpha"),
            _mismatch(Origin.REHEARSAL, strategy_name="Zeta"),
        ],
    )

    assert "Alpha" in text
    assert "Zeta" in text
    assert "2 " in text
