"""Unit tests: ``operation_fees`` -- the fees of one operation, in the pool's
settlement currency, and the fees in every other currency listed on their own
(design.md, addendum "a strategy's operations", section B; CLAUDE.md rule 7).

Nothing is converted: a fee in another currency keeps its currency and its own
sum. Pure ``Decimal`` domain, no I/O.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.derive_trade import derive_trade
from strategy_manager.performance.domain.operation import FeeAmount, operation_fees

OPENED = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
CLOSED = datetime(2026, 9, 2, 11, 30, tzinfo=UTC)
STRATEGY = uuid4()


def _group(
    allocation_id: UUID,
    *,
    side: str,
    fee: str,
    fee_currency: str = "USDT",
    quantity: str = "10",
    notional: str = "100",
    at: datetime = OPENED,
) -> FillGroup:
    return FillGroup(
        allocation_id=allocation_id,
        strategy_id=STRATEGY,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="STXUSDT.P" if side == "BUY" else "STXUSDT",
        side=side,
        fee_currency=fee_currency,
        quantity=Decimal(quantity),
        notional=Decimal(notional),
        fee=Decimal(fee),
        first_filled_at=at,
        last_filled_at=at,
        pool_total_at_open=Decimal("1000"),
        rehearsal=False,
    )


def test_fees_sum_every_fill_of_both_sides_in_the_settlement_currency() -> None:
    a = uuid4()
    groups = [
        _group(a, side="BUY", fee="0.31", at=OPENED),
        _group(a, side="SELL", fee="0.32", at=CLOSED),
    ]

    fees = operation_fees(groups)

    assert fees.fees == Decimal("0.63")
    assert fees.other_fees == ()


def test_the_fees_equal_the_amount_derive_trade_subtracts_from_pnl() -> None:
    """A base-currency fee is not subtracted again by ``derive_trade`` (it is in
    the notional difference), so it is not in ``fees`` either: 100 STX bought
    with 1 STX taken as the fee, 99 sold."""
    a = uuid4()
    groups = [
        _group(
            a,
            side="BUY",
            fee="1",
            fee_currency="STX",
            quantity="100",
            notional="1000",
            at=OPENED,
        ),
        _group(a, side="SELL", fee="0.30", quantity="99", notional="1089", at=CLOSED),
    ]
    trade = derive_trade(groups)
    assert trade is not None

    fees = operation_fees(groups)

    assert fees.fees == Decimal("0.30")
    assert trade.pnl == Decimal("1089") - Decimal("1000") - fees.fees


def test_other_currency_fees_are_listed_once_per_currency_with_own_sum_sorted() -> None:
    a = uuid4()
    groups = [
        _group(a, side="BUY", fee="0.00005", fee_currency="BNB", at=OPENED),
        _group(a, side="SELL", fee="0.00007", fee_currency="bnb", at=CLOSED),
        _group(a, side="SELL", fee="0.4", fee_currency="AAA", at=CLOSED),
    ]

    fees = operation_fees(groups)

    assert fees.other_fees == (
        FeeAmount(currency="AAA", amount=Decimal("0.4")),
        FeeAmount(currency="BNB", amount=Decimal("0.00012")),
    )
    assert fees.fees == Decimal("0")


def test_a_zero_sum_other_fee_is_not_listed() -> None:
    a = uuid4()
    groups = [
        _group(a, side="BUY", fee="0", fee_currency="BNB", at=OPENED),
        _group(a, side="SELL", fee="0.2", at=CLOSED),
    ]

    fees = operation_fees(groups)

    assert fees.other_fees == ()
    assert fees.fees == Decimal("0.2")


def test_nothing_is_converted_and_the_settlement_currency_is_not_among_the_other_fees() -> None:
    a = uuid4()
    groups = [
        _group(a, side="BUY", fee="0.5", fee_currency="usdt", at=OPENED),
        _group(a, side="SELL", fee="0.00012", fee_currency="BNB", at=CLOSED),
    ]

    fees = operation_fees(groups)

    assert fees.fees == Decimal("0.5")
    assert fees.other_fees == (FeeAmount(currency="BNB", amount=Decimal("0.00012")),)
