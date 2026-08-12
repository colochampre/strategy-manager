from decimal import Decimal

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Money, Venue


def test_currency_and_venue_values_match_db_constraints() -> None:
    assert Currency.USDT == "USDT"
    assert Currency.BTC == "BTC"
    assert Currency.ETH == "ETH"
    assert Venue.SPOT == "spot"
    assert Venue.USDT_M == "usdt-m"
    assert Venue.COIN_M == "coin-m"


def test_money_stores_amount_and_currency() -> None:
    money = Money(Decimal("100.5"), Currency.USDT)

    assert money.amount == Decimal("100.5")
    assert money.currency == Currency.USDT


def test_money_rejects_non_decimal_amount() -> None:
    with pytest.raises(InvariantViolation):
        Money(100.5, Currency.USDT)  # type: ignore[arg-type]


def test_money_addition_sums_same_currency() -> None:
    total = Money(Decimal("10"), Currency.USDT) + Money(Decimal("5"), Currency.USDT)

    assert total == Money(Decimal("15"), Currency.USDT)


def test_money_subtraction_of_same_currency() -> None:
    remainder = Money(Decimal("10"), Currency.BTC) - Money(Decimal("4"), Currency.BTC)

    assert remainder == Money(Decimal("6"), Currency.BTC)


def test_money_addition_rejects_currency_mismatch() -> None:
    with pytest.raises(InvariantViolation):
        Money(Decimal("10"), Currency.USDT) + Money(Decimal("5"), Currency.BTC)


def test_money_comparison_within_same_currency() -> None:
    assert Money(Decimal("5"), Currency.ETH) < Money(Decimal("10"), Currency.ETH)
    assert Money(Decimal("10"), Currency.ETH) >= Money(Decimal("10"), Currency.ETH)


def test_money_comparison_rejects_currency_mismatch() -> None:
    with pytest.raises(InvariantViolation):
        _ = Money(Decimal("5"), Currency.ETH) < Money(Decimal("5"), Currency.BTC)
