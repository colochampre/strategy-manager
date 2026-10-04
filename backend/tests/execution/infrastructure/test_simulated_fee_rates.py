"""Unit tests: the simulated taker fee rates table (design § E; spec:
trade-execution § "An Exchange With No Simulated Fee Rate Is Not Served In Dry
Run", scenario "The rates table holds exactly the two verified rates")."""

from decimal import Decimal

import pytest

from strategy_manager.execution.infrastructure.simulated_fee_rates import (
    SIMULATED_FEE_CURRENCY,
    SIMULATED_TAKER_FEE_RATES,
)
from strategy_manager.shared.domain.money import Exchange


def test_the_table_holds_exactly_bybit_at_0_00055_and_binance_at_0_0005() -> None:
    assert dict(SIMULATED_TAKER_FEE_RATES) == {
        "bybit": Decimal("0.00055"),
        "binance": Decimal("0.0005"),
    }


def test_no_other_exchange_has_a_rate() -> None:
    assert Exchange.PIONEX.value not in SIMULATED_TAKER_FEE_RATES
    assert set(SIMULATED_TAKER_FEE_RATES) == {Exchange.BYBIT.value, Exchange.BINANCE.value}


def test_the_fee_currency_is_usdt() -> None:
    assert SIMULATED_FEE_CURRENCY == "USDT"


def test_the_table_is_read_only() -> None:
    captured: BaseException | None = None
    try:
        SIMULATED_TAKER_FEE_RATES["pionex"] = Decimal("0.0005")  # type: ignore[index]
    except BaseException as exc:  # noqa: BLE001 - the type is what is asserted
        captured = exc

    assert type(captured) is TypeError
    assert "pionex" not in SIMULATED_TAKER_FEE_RATES


@pytest.mark.parametrize("exchange", sorted(SIMULATED_TAKER_FEE_RATES))
def test_every_rate_is_a_decimal_that_is_not_negative_and_below_one(exchange: str) -> None:
    rate = SIMULATED_TAKER_FEE_RATES[exchange]

    assert isinstance(rate, Decimal)
    assert Decimal("0") <= rate < Decimal("1")
