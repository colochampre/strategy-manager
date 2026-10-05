"""Unit tests: ``derive_trade`` / ``derive_trades`` -- folding the ledger's
per-(allocation, side, fee currency) aggregates into closed trades (design.md
section 11; spec: performance-reporting section Realized PnL).

Pure ``Decimal`` domain, no I/O. Every expected figure is an exact ``Decimal``.

**Binding testing lesson**: a symbol has three spellings (TradingView
``STXUSDT.P``, venue bare ``STXUSDT``, Pionex ``STXUSDT_PERP``). The two legs
of one trade below are written under DIFFERENT spellings on purpose.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.performance.domain.closed_trade import Direction, FillGroup
from strategy_manager.performance.domain.derive_trade import derive_trade, derive_trades

OPENED = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
CLOSED = datetime(2026, 9, 2, 11, 30, tzinfo=UTC)
STRATEGY = uuid4()


def _group(
    *,
    allocation_id: UUID,
    side: str,
    quantity: str,
    notional: str,
    fee: str = "0",
    fee_currency: str = "USDT",
    symbol: str = "SOLUSDT.P",
    settlement_currency: str = "USDT",
    filled_at: datetime = OPENED,
    pool_total_at_open: str | None = "1000",
    venue: str = "usdt-m",
    exchange: str = "bybit",
) -> FillGroup:
    return FillGroup(
        allocation_id=allocation_id,
        strategy_id=STRATEGY,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        symbol=symbol,
        side=side,
        fee_currency=fee_currency,
        quantity=Decimal(quantity),
        notional=Decimal(notional),
        fee=Decimal(fee),
        first_filled_at=filled_at,
        last_filled_at=filled_at,
        pool_total_at_open=None if pool_total_at_open is None else Decimal(pool_total_at_open),
        rehearsal=False,
    )


def test_realized_pnl_long_trade_100_to_106_with_settlement_fee() -> None:
    """Spec scenario: opened at 100, closed at 106, fees 0.5 USDT -> 5.5."""
    a = uuid4()
    groups = [
        _group(allocation_id=a, side="BUY", quantity="1", notional="100", fee="0.25"),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="1",
            notional="106",
            fee="0.25",
            symbol="SOLUSDT",
            filled_at=CLOSED,
        ),
    ]

    trade = derive_trade(groups)

    assert trade is not None
    assert trade.pnl == Decimal("5.5")
    assert trade.fees_complete is True
    assert trade.settlement_currency == "USDT"
    assert trade.opened_at == OPENED
    assert trade.closed_at == CLOSED
    assert trade.pool_total_at_open == Decimal("1000")
    assert trade.strategy_id == STRATEGY


def test_realized_pnl_of_a_losing_short_is_signed_and_fees_still_subtract() -> None:
    """Triangulates the first case with a different shape: a SHORT (sold at
    106, bought back at 112) loses 6 and pays 1.5 in fees -> -7.5. A formula
    that only knew "sell minus buy" for longs would not survive this."""
    a = uuid4()
    groups = [
        _group(allocation_id=a, side="SELL", quantity="2", notional="106", fee="0.5"),
        _group(
            allocation_id=a,
            side="BUY",
            quantity="2",
            notional="112",
            fee="1",
            filled_at=CLOSED,
        ),
    ]

    trade = derive_trade(groups)

    assert trade is not None
    assert trade.pnl == Decimal("-7.5")


def test_third_currency_fee_flagged_fees_complete_false_not_converted() -> None:
    """A BNB fee is neither the USDT settlement currency nor the SOL base. It
    is NOT converted (no rate is read), so it is absent from pnl and the trade
    says so -- 6 gross less the 0.25 USDT fee only."""
    a = uuid4()
    groups = [
        _group(allocation_id=a, side="BUY", quantity="1", notional="100", fee="0.25"),
        _group(
            allocation_id=a,
            side="BUY",
            quantity="1",
            notional="100",
            fee="0.004",
            fee_currency="BNB",
        ),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="2",
            notional="206",
            symbol="SOLUSDT",
            filled_at=CLOSED,
        ),
    ]

    trade = derive_trade(groups)

    assert trade is not None
    assert trade.pnl == Decimal("5.75")
    assert trade.fees_complete is False


def test_zero_third_currency_fee_does_not_flag_the_trade() -> None:
    """A BNB fee of exactly zero lost nothing, so the trade is still complete.
    Without this, the flag would fire on every venue that always reports a
    fee currency."""
    a = uuid4()
    groups = [
        _group(allocation_id=a, side="BUY", quantity="1", notional="100", fee_currency="BNB"),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="1",
            notional="101",
            filled_at=CLOSED,
        ),
    ]

    trade = derive_trade(groups)

    assert trade is not None
    assert trade.fees_complete is True
    assert trade.pnl == Decimal("1")


def test_base_currency_fee_not_subtracted_again_already_in_notional_diff() -> None:
    """Pionex spot: buying 1 SOL costs 0.001 SOL in fees, so 0.999 SOL arrives
    and 0.999 is sold. The fee already shows in the notional difference; the
    close only nets to zero BECAUSE the base fee is part of the net-base rule.
    pnl is 105.895 - 100, not 5.895 - 0.001."""
    a = uuid4()
    groups = [
        _group(
            allocation_id=a,
            side="BUY",
            quantity="1",
            notional="100",
            fee="0.001",
            fee_currency="SOL",
            symbol="SOL_USDT",
        ),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="0.999",
            notional="105.895",
            symbol="SOL_USDT",
            filled_at=CLOSED,
        ),
    ]

    trade = derive_trade(groups)

    assert trade is not None
    assert trade.pnl == Decimal("5.895")
    assert trade.fees_complete is True


def test_base_currency_fee_is_recognised_case_insensitively() -> None:
    """The fee currency is whatever the venue called it. A ``sol`` fee that
    was compared case-sensitively would leave 0.001 in the net, so a closed
    trade would be read as open."""
    a = uuid4()
    groups = [
        _group(
            allocation_id=a,
            side="BUY",
            quantity="1",
            notional="100",
            fee="0.001",
            fee_currency="sol",
            symbol="SOL_USDT",
        ),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="0.999",
            notional="105.895",
            symbol="SOL_USDT",
            filled_at=CLOSED,
        ),
    ]

    assert derive_trade(groups) is not None


def test_open_allocation_yields_no_realized_pnl_counted_as_open() -> None:
    open_alloc, closed_alloc = uuid4(), uuid4()
    groups = [
        _group(allocation_id=open_alloc, side="BUY", quantity="1", notional="100"),
        _group(allocation_id=closed_alloc, side="BUY", quantity="1", notional="50"),
        _group(
            allocation_id=closed_alloc,
            side="SELL",
            quantity="1",
            notional="55",
            filled_at=CLOSED,
        ),
    ]

    assert derive_trade([groups[0]]) is None

    derived = derive_trades(groups)

    assert [t.allocation_id for t in derived.closed] == [closed_alloc]
    assert derived.closed[0].pnl == Decimal("5")
    assert derived.open_trade_count == 1


def test_partial_close_counted_as_open_not_closed() -> None:
    """Bought 2, sold 1: still holding 1. Its half-realized 'pnl' is not a
    trade's PnL, so it is open. Selling MORE than was bought is also not a
    close (the position flipped), and equally open."""
    partial, over = uuid4(), uuid4()
    groups = [
        _group(allocation_id=partial, side="BUY", quantity="2", notional="200"),
        _group(
            allocation_id=partial,
            side="SELL",
            quantity="1",
            notional="110",
            filled_at=CLOSED,
        ),
        _group(allocation_id=over, side="BUY", quantity="1", notional="100"),
        _group(
            allocation_id=over,
            side="SELL",
            quantity="1.5",
            notional="165",
            filled_at=CLOSED,
        ),
    ]

    derived = derive_trades(groups)

    assert derived.closed == ()
    assert derived.open_trade_count == 2


def test_closed_means_exactly_zero_net_base_with_no_tolerance() -> None:
    """The definition is the ledger's own (``net_positions_by_symbol`` drops a
    group only when its net is exactly zero). One unit in the last place of a
    venue step left over means the position is still there."""
    a = uuid4()
    groups = [
        _group(allocation_id=a, side="BUY", quantity="0.006", notional="14.8"),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="0.005",
            notional="12.3",
            filled_at=CLOSED,
        ),
    ]

    assert derive_trade(groups) is None


def test_rehearsal_fill_excluded_from_derivation() -> None:
    """The source strips ``fake-fill-`` rows before the domain sees anything.
    An allocation opened by a rehearsal fill and closed by a real one arrives
    here as a lone SELL. That must not be read as a trade whose PnL is the
    whole sale: it is a position the domain cannot see the open of, so it is
    open, and no realized PnL is invented."""
    a = uuid4()
    lone_live_sell = _group(
        allocation_id=a, side="SELL", quantity="1", notional="106", filled_at=CLOSED
    )

    assert derive_trade([lone_live_sell]) is None

    derived = derive_trades([lone_live_sell])

    assert derived.closed == ()
    assert derived.open_trade_count == 1


@pytest.mark.parametrize("close_spelling", ["SOLUSDT", "SOLUSDT_PERP", "solusdt"])
def test_pair_derived_from_market_key_of_allocation_fills_spelling_merge(
    close_spelling: str,
) -> None:
    """Fills spelled ``SOLUSDT.P`` on the open and another spelling on the
    booked close are ONE allocation and ONE pair, ``SOLUSDT`` (F4). Grouping
    the raw symbol would have counted two."""
    a = uuid4()
    groups = [
        _group(allocation_id=a, side="BUY", quantity="1", notional="100", symbol="SOLUSDT.P"),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="1",
            notional="103",
            symbol=close_spelling,
            filled_at=CLOSED,
        ),
    ]

    derived = derive_trades(groups)

    assert len(derived.closed) == 1
    assert derived.closed[0].pair == "SOLUSDT"
    assert derived.closed[0].pnl == Decimal("3")


def test_pool_identity_and_missing_capital_carry_through_to_the_trade() -> None:
    a = uuid4()
    groups = [
        _group(
            allocation_id=a,
            side="BUY",
            quantity="1",
            notional="100",
            pool_total_at_open=None,
            exchange="pionex",
            venue="spot",
            symbol="SOL_USDT",
        ),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="1",
            notional="101",
            pool_total_at_open=None,
            exchange="pionex",
            venue="spot",
            symbol="SOL_USDT",
            filled_at=CLOSED,
        ),
    ]

    trade = derive_trade(groups)

    assert trade is not None
    assert (trade.exchange, trade.venue, trade.settlement_currency) == ("pionex", "spot", "USDT")
    assert trade.pool_total_at_open is None
    assert trade.pair == "SOL_USDT"


def test_an_underivable_symbol_is_reported_not_raised_and_not_dropped_silently() -> None:
    """A symbol not quoted in the pool's currency cannot yield a base
    currency. One such row must not take down the whole pool's read, and must
    not vanish either: it is returned by id so the caller can log it."""
    bad, good = uuid4(), uuid4()
    groups = [
        _group(allocation_id=bad, side="BUY", quantity="1", notional="1", symbol="BTCEUR"),
        _group(allocation_id=good, side="BUY", quantity="1", notional="100"),
        _group(
            allocation_id=good, side="SELL", quantity="1", notional="104", filled_at=CLOSED
        ),
    ]

    derived = derive_trades(groups)

    assert derived.unresolved_allocation_ids == (bad,)
    assert [t.allocation_id for t in derived.closed] == [good]
    assert derived.open_trade_count == 0


# --- direction: the side of the allocation's earliest leg ------------------------


def test_a_trade_opened_by_a_buy_is_long() -> None:
    a = uuid4()
    groups = [
        _group(allocation_id=a, side="BUY", quantity="1", notional="100"),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="1",
            notional="106",
            symbol="SOLUSDT",
            filled_at=CLOSED,
        ),
    ]

    trade = derive_trade(groups)

    assert trade is not None
    assert trade.direction == Direction.LONG


def test_a_trade_opened_by_a_sell_is_short() -> None:
    """A futures short: SELL first (spelled ``SOLUSDT.P``), BUY to close (booked
    as ``SOLUSDT``). Its PnL is positive when the price fell."""
    a = uuid4()
    groups = [
        _group(allocation_id=a, side="SELL", quantity="1", notional="100"),
        _group(
            allocation_id=a,
            side="BUY",
            quantity="1",
            notional="94",
            symbol="SOLUSDT",
            filled_at=CLOSED,
        ),
    ]

    trade = derive_trade(groups)

    assert trade is not None
    assert trade.direction == Direction.SHORT
    assert trade.pnl == Decimal("6")


def test_direction_follows_the_earliest_leg_not_the_order_the_groups_arrive_in() -> None:
    """The source orders groups by side (BUY before SELL), which says nothing
    about time. Both orders of the same two legs give the same answer."""
    a = uuid4()
    opened_short = _group(allocation_id=a, side="SELL", quantity="1", notional="100")
    closed_by_buy = _group(
        allocation_id=a,
        side="BUY",
        quantity="1",
        notional="94",
        symbol="SOLUSDT",
        filled_at=CLOSED,
    )

    forward = derive_trade([opened_short, closed_by_buy])
    backward = derive_trade([closed_by_buy, opened_short])

    assert forward is not None and backward is not None
    assert forward.direction == backward.direction == Direction.SHORT


def test_direction_reads_the_first_fill_of_a_side_split_over_several_fee_currencies() -> None:
    """The SELL side is two groups (fees in two currencies), the earlier one
    listed last. The BUY sits between them in time, so only the earliest group
    of the whole allocation says which way it was opened."""
    a = uuid4()
    at = lambda hour, minute: datetime(2026, 9, 1, hour, minute, tzinfo=UTC)  # noqa: E731
    groups = [
        _group(allocation_id=a, side="BUY", quantity="1", notional="94", filled_at=at(10, 3)),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="0.5",
            notional="50",
            fee_currency="USDT",
            filled_at=at(10, 5),
        ),
        _group(
            allocation_id=a,
            side="SELL",
            quantity="0.5",
            notional="50",
            fee_currency="USDC",
            filled_at=at(10, 0),
        ),
    ]

    trade = derive_trade(groups)

    assert trade is not None
    assert trade.direction == Direction.SHORT


def test_legs_at_the_same_instant_resolve_the_same_way_whatever_the_order() -> None:
    """A tie has no earliest leg. The answer must still not depend on which
    group the source happened to return first: BUY wins, in either order."""
    a = uuid4()
    buy = _group(allocation_id=a, side="BUY", quantity="1", notional="100")
    sell = _group(allocation_id=a, side="SELL", quantity="1", notional="100")

    first = derive_trade([buy, sell])
    second = derive_trade([sell, buy])

    assert first is not None and second is not None
    assert first.direction == second.direction == Direction.LONG


def test_derive_trades_carries_each_allocations_own_direction() -> None:
    long_id, short_id = uuid4(), uuid4()
    groups = [
        _group(allocation_id=long_id, side="BUY", quantity="1", notional="100"),
        _group(
            allocation_id=long_id, side="SELL", quantity="1", notional="103", filled_at=CLOSED
        ),
        _group(allocation_id=short_id, side="SELL", quantity="2", notional="200"),
        _group(
            allocation_id=short_id, side="BUY", quantity="2", notional="190", filled_at=CLOSED
        ),
    ]

    derived = derive_trades(groups)

    directions = {t.allocation_id: t.direction for t in derived.closed}
    assert directions == {long_id: Direction.LONG, short_id: Direction.SHORT}


def test_direction_compares_when_each_side_started_not_when_it_finished() -> None:
    """A SELL scaled out over 10:00-10:30 and a BUY at 10:10: the SELL started
    first, so the trade was opened short, although the SELL FINISHED after the
    BUY started."""
    a = uuid4()
    at = lambda minute: datetime(2026, 9, 1, 10, minute, tzinfo=UTC)  # noqa: E731
    sell = replace(
        _group(allocation_id=a, side="SELL", quantity="1", notional="100", filled_at=at(0)),
        last_filled_at=at(30),
    )
    buy = _group(allocation_id=a, side="BUY", quantity="1", notional="94", filled_at=at(10))

    trade = derive_trade([buy, sell])

    assert trade is not None
    assert trade.direction == Direction.SHORT
