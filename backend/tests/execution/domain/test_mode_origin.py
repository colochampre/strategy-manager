"""Decision 28 and AD7: the pure part of the startup mode guard.

``fold_open_allocations`` decides what is OPEN, by the ledger's own rule (net
base quantity exactly zero under the base-fee rule, the one ``derive_trade``
and ``net_base_quantity`` use). ``find_mismatches`` decides which of those, and
which in-flight orders, disagree with the mode their reservation recorded.
``find_unclosable`` decides which real ones have no key that can close them.
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
    UnclosableAllocations,
    describe_refusal,
    find_mismatches,
    find_unclosable,
    fold_open_allocations,
)
from strategy_manager.shared.domain.mode import Mode

USER = UUID("99999999-1111-2222-3333-444444444444")
OTHER = UUID("88888888-1111-2222-3333-444444444444")


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
    user_id: UUID = USER,
    mode: Mode = Mode.SIMULATION,
) -> LedgerGroup:
    return LedgerGroup(
        allocation_id=allocation_id,
        user_id=user_id,
        mode=mode,
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
    mode: Mode,
    rehearsal: bool = False,
    live: bool = False,
    strategy_name: str = "Alpha",
    symbol: str = "SOLUSDT.P",
    allocation_id: UUID | None = None,
    user_id: UUID = USER,
    exchange: str = "bybit",
) -> OpenAllocationOrigin:
    return OpenAllocationOrigin(
        allocation_id=allocation_id or uuid4(),
        user_id=user_id,
        mode=mode,
        strategy_name=strategy_name,
        exchange=exchange,
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=symbol,
        holds_rehearsal_fill=rehearsal,
        holds_live_fill=live,
    )


def _in_flight(
    order_id: str, *, mode: Mode, strategy_name: str = "Beta"
) -> InFlightAttemptOrigin:
    return InFlightAttemptOrigin(
        attempt_id=uuid4(),
        mode=mode,
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


def test_an_open_allocation_carries_its_user_and_its_recorded_mode() -> None:
    opened = fold_open_allocations(
        [_group(uuid4(), rehearsal=False, user_id=OTHER, mode=Mode.LIVE)]
    )

    assert [(o.user_id, o.mode) for o in opened] == [(OTHER, Mode.LIVE)]


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


# --- find_mismatches: positions ------------------------------------------------


def test_a_reservation_recorded_live_refuses_rehearsal_fills() -> None:
    offender = _open(mode=Mode.LIVE, rehearsal=True)

    found = find_mismatches(open_allocations=[offender], in_flight=[])

    assert found == (
        ModeMismatch(
            kind=Kind.POSITION,
            origin=Origin.REHEARSAL,
            recorded=Mode.LIVE,
            identifier=offender.allocation_id,
            strategy_name="Alpha",
            pool="bybit/usdt-m/USDT",
            symbol="SOLUSDT.P",
        ),
    )


def test_a_reservation_recorded_live_accepts_live_fills() -> None:
    assert find_mismatches(open_allocations=[_open(mode=Mode.LIVE, live=True)], in_flight=[]) == ()


def test_a_reservation_recorded_simulation_refuses_a_live_fill() -> None:
    offender = _open(mode=Mode.SIMULATION, live=True)

    found = find_mismatches(open_allocations=[offender], in_flight=[])

    assert [(m.kind, m.origin, m.recorded, m.identifier) for m in found] == [
        (Kind.POSITION, Origin.LIVE, Mode.SIMULATION, offender.allocation_id)
    ]


def test_a_reservation_recorded_simulation_accepts_rehearsal_fills() -> None:
    allocation = _open(mode=Mode.SIMULATION, rehearsal=True)

    assert find_mismatches(open_allocations=[allocation], in_flight=[]) == ()


# --- find_mismatches: both kinds, and nothing at all ------------------------


def test_an_allocation_holding_both_kinds_refuses_whatever_it_recorded() -> None:
    for mode in Mode:
        mixed = _open(mode=mode, rehearsal=True, live=True)

        found = find_mismatches(open_allocations=[mixed], in_flight=[])

        assert [(m.origin, m.identifier) for m in found] == [
            (Origin.MIXED, mixed.allocation_id)
        ], mode


def test_nothing_open_and_nothing_in_flight_refuses_nothing() -> None:
    assert find_mismatches(open_allocations=[], in_flight=[]) == ()


def test_every_offender_is_reported_not_only_the_first() -> None:
    first = _open(mode=Mode.LIVE, rehearsal=True, strategy_name="Alpha")
    second = _open(mode=Mode.LIVE, rehearsal=True, strategy_name="Zeta")
    fine = _open(mode=Mode.LIVE, live=True, strategy_name="Live")

    found = find_mismatches(open_allocations=[second, fine, first], in_flight=[])

    assert [m.strategy_name for m in found] == ["Alpha", "Zeta"]


# --- find_mismatches: in-flight orders ----------------------------------------


def test_a_live_reservation_refuses_a_rehearsal_order_still_waiting_to_settle() -> None:
    order = _in_flight(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}", mode=Mode.LIVE)

    found = find_mismatches(open_allocations=[], in_flight=[order])

    assert [(m.kind, m.origin, m.recorded, m.identifier, m.strategy_name) for m in found] == [
        (Kind.ORDER, Origin.REHEARSAL, Mode.LIVE, order.attempt_id, "Beta")
    ]


def test_a_live_reservation_accepts_a_live_order_still_waiting_to_settle() -> None:
    order = _in_flight("8f0c2a3e-6a51-4c1b-9d0a-2f7c1e5b7a10", mode=Mode.LIVE)

    assert find_mismatches(open_allocations=[], in_flight=[order]) == ()


def test_a_simulated_reservation_refuses_a_live_order_still_waiting_to_settle() -> None:
    """The dangerous direction for an order: its settle would ask the fake
    exchange, get OrderNotFound, and release a reservation for an order that
    really filled."""
    order = _in_flight("1234567890123", mode=Mode.SIMULATION)

    found = find_mismatches(open_allocations=[], in_flight=[order])

    assert [(m.kind, m.origin, m.identifier) for m in found] == [
        (Kind.ORDER, Origin.LIVE, order.attempt_id)
    ]


def test_a_simulated_reservation_accepts_a_rehearsal_order_still_waiting_to_settle() -> None:
    order = _in_flight(f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}", mode=Mode.SIMULATION)

    assert find_mismatches(open_allocations=[], in_flight=[order]) == ()


# --- find_unclosable: a real position needs a key -------------------------------


def test_a_real_allocation_with_no_key_cannot_close() -> None:
    held = _open(mode=Mode.LIVE, live=True)

    found = find_unclosable(open_allocations=[held], trade_capable=[])

    assert found == (UnclosableAllocations(user_id=USER, exchange="bybit", allocations=1),)


def test_a_real_allocation_with_a_key_on_its_exchange_can_close() -> None:
    held = _open(mode=Mode.LIVE, live=True)

    assert find_unclosable(open_allocations=[held], trade_capable=[(USER, "bybit")]) == ()


def test_a_key_on_another_exchange_or_of_another_user_closes_nothing() -> None:
    held = _open(mode=Mode.LIVE, live=True)

    found = find_unclosable(
        open_allocations=[held], trade_capable=[(USER, "binance"), (OTHER, "bybit")]
    )

    assert [(item.user_id, item.exchange) for item in found] == [(USER, "bybit")]


def test_a_simulated_allocation_needs_no_key() -> None:
    held = _open(mode=Mode.SIMULATION, rehearsal=True)

    assert find_unclosable(open_allocations=[held], trade_capable=[]) == ()


def test_each_user_is_counted_per_exchange_and_ordered() -> None:
    opened = [
        _open(mode=Mode.LIVE, live=True, user_id=USER, exchange="bybit"),
        _open(mode=Mode.LIVE, live=True, user_id=USER, exchange="bybit"),
        _open(mode=Mode.LIVE, live=True, user_id=USER, exchange="binance"),
        _open(mode=Mode.LIVE, live=True, user_id=OTHER, exchange="bybit"),
    ]

    found = find_unclosable(open_allocations=opened, trade_capable=[])

    assert found == (
        UnclosableAllocations(user_id=OTHER, exchange="bybit", allocations=1),
        UnclosableAllocations(user_id=USER, exchange="binance", allocations=1),
        UnclosableAllocations(user_id=USER, exchange="bybit", allocations=2),
    )


# --- describe_refusal ----------------------------------------------------------


def _mismatch(
    origin: Origin,
    *,
    kind: Kind = Kind.POSITION,
    strategy_name: str = "Alpha",
    recorded: Mode = Mode.LIVE,
) -> ModeMismatch:
    return ModeMismatch(
        kind=kind,
        origin=origin,
        recorded=recorded,
        identifier=UUID("11111111-2222-3333-4444-555555555555"),
        strategy_name=strategy_name,
        pool="bybit/usdt-m/USDT",
        symbol="SOLUSDT.P",
    )


def test_the_refusal_names_strategy_pool_symbol_and_allocation_id() -> None:
    text = describe_refusal(mismatches=[_mismatch(Origin.REHEARSAL)], unclosable=[])

    for expected in (
        "Alpha",
        "bybit/usdt-m/USDT",
        "SOLUSDT.P",
        "11111111-2222-3333-4444-555555555555",
    ):
        assert expected in text


def test_the_refusal_says_what_was_recorded_and_what_the_fills_are() -> None:
    text = describe_refusal(
        mismatches=[_mismatch(Origin.REHEARSAL, recorded=Mode.LIVE)], unclosable=[]
    )

    assert "recorded LIVE" in text
    assert "rehearsal fills" in text


def test_the_refusal_no_longer_speaks_of_one_mode_for_the_process() -> None:
    text = describe_refusal(mismatches=[_mismatch(Origin.REHEARSAL)], unclosable=[])

    assert "DRY_RUN" not in text


def test_the_way_out_says_why_a_close_on_the_wrong_side_is_not_one() -> None:
    text = describe_refusal(mismatches=[_mismatch(Origin.LIVE)], unclosable=[])

    assert "by hand" in text
    assert "still be open" in text


def test_a_mixed_allocation_says_no_side_can_close_it() -> None:
    text = describe_refusal(mismatches=[_mismatch(Origin.MIXED)], unclosable=[])

    assert "both rehearsal and live" in text
    assert "no side" in text


def test_an_order_is_described_as_an_order_with_the_attempt_id() -> None:
    text = describe_refusal(
        mismatches=[_mismatch(Origin.REHEARSAL, kind=Kind.ORDER, strategy_name="Beta")],
        unclosable=[],
    )

    assert "order" in text
    assert "execution attempt 11111111-2222-3333-4444-555555555555" in text
    assert "Beta" in text


def test_every_offender_appears_in_the_one_message() -> None:
    text = describe_refusal(
        mismatches=[
            _mismatch(Origin.REHEARSAL, strategy_name="Alpha"),
            _mismatch(Origin.REHEARSAL, strategy_name="Zeta"),
        ],
        unclosable=[],
    )

    assert "Alpha" in text
    assert "Zeta" in text
    assert "2 " in text


def test_the_refusal_names_each_user_and_how_many_allocations_they_hold() -> None:
    text = describe_refusal(
        mismatches=[],
        unclosable=[
            UnclosableAllocations(user_id=USER, exchange="bybit", allocations=2),
            UnclosableAllocations(user_id=OTHER, exchange="binance", allocations=1),
        ],
    )

    assert f"user {USER}: 2 allocation(s) on bybit" in text
    assert f"user {OTHER}: 1 allocation(s) on binance" in text
    assert "3 real open allocation(s)" in text
    assert "trade-capable key" in text
    assert "disagree" not in text


def test_both_refusals_share_the_one_message() -> None:
    text = describe_refusal(
        mismatches=[_mismatch(Origin.REHEARSAL)],
        unclosable=[UnclosableAllocations(user_id=USER, exchange="bybit", allocations=1)],
    )

    assert "disagree" in text
    assert str(USER) in text
