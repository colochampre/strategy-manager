"""Unit tests: ``sides_overlap`` -- whether an operation's opening side finished
filling strictly before its closing side began (design.md, addendum "a
strategy's operations", section G, "Fills that disagree in side").

The system cannot produce an overlap (an allocation is closed whole, after it
is open), so the check exists only to be noticed if it ever happens. A tie
counts as an overlap: ``derive_trade`` breaks it in favour of BUY, so which
side "opened" would rest on the tie-break.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.performance.domain.closed_trade import Direction, FillGroup
from strategy_manager.performance.domain.operation import sides_overlap

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
T1 = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
T3 = datetime(2026, 9, 1, 13, 0, tzinfo=UTC)
STRATEGY = uuid4()


def _group(allocation_id: UUID, side: str, first: datetime, last: datetime) -> FillGroup:
    return FillGroup(
        allocation_id=allocation_id,
        strategy_id=STRATEGY,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="STXUSDT.P" if side == "BUY" else "STXUSDT",
        side=side,
        fee_currency="USDT",
        quantity=Decimal("1"),
        notional=Decimal("10"),
        fee=Decimal("0"),
        first_filled_at=first,
        last_filled_at=last,
        pool_total_at_open=Decimal("1000"),
        rehearsal=False,
    )


def test_a_tie_between_the_openers_last_fill_and_the_closers_first_is_an_overlap() -> None:
    a = uuid4()
    groups = [_group(a, "BUY", T0, T1), _group(a, "SELL", T1, T2)]

    assert sides_overlap(groups, Direction.LONG) is True


def test_an_opener_whose_last_fill_is_after_the_closers_first_is_an_overlap() -> None:
    a = uuid4()
    groups = [_group(a, "BUY", T0, T2), _group(a, "SELL", T1, T3)]

    assert sides_overlap(groups, Direction.LONG) is True


def test_a_clean_round_trip_is_not_an_overlap() -> None:
    a = uuid4()
    groups = [_group(a, "BUY", T0, T1), _group(a, "SELL", T2, T3)]

    assert sides_overlap(groups, Direction.LONG) is False


def test_a_shorts_opening_side_is_its_sell_side() -> None:
    a = uuid4()
    clean = [_group(a, "SELL", T0, T1), _group(a, "BUY", T2, T3)]
    overlapping = [_group(a, "SELL", T0, T2), _group(a, "BUY", T1, T3)]

    assert sides_overlap(clean, Direction.SHORT) is False
    assert sides_overlap(overlapping, Direction.SHORT) is True
