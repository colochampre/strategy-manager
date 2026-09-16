"""Unit tests for FakeBalanceSource — the stand-in BalanceSourcePort until a
real Pionex balance adapter exists (design.md component inventory)."""

from decimal import Decimal

import pytest

from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.shared.domain.errors import InvariantViolation


async def test_read_balance_returns_the_configured_amount() -> None:
    source = FakeBalanceSource()
    source.set_balance("pionex", "spot", "USDT", Decimal("1000"))

    funds = await source.read_balance("pionex", "spot", "USDT")

    assert funds.total == Decimal("1000")
    assert funds.available == Decimal("1000")


async def test_set_funds_keeps_total_and_availability_apart() -> None:
    source = FakeBalanceSource()
    source.set_funds(
        "bybit", "usdt-m", "USDT", total=Decimal("1000"), available=Decimal("400")
    )

    funds = await source.read_balance("bybit", "usdt-m", "USDT")

    assert (funds.total, funds.available) == (Decimal("1000"), Decimal("400"))


async def test_the_same_venue_on_two_exchanges_is_two_pools() -> None:
    """The whole point of keying by exchange: Bybit's usdt-m/USDT and
    Binance's are different money and must not read each other's balance."""
    source = FakeBalanceSource()
    source.set_balance("bybit", "usdt-m", "USDT", Decimal("1000"))
    source.set_balance("binance", "usdt-m", "USDT", Decimal("642"))

    bybit = await source.read_balance("bybit", "usdt-m", "USDT")
    binance = await source.read_balance("binance", "usdt-m", "USDT")

    assert (bybit.available, binance.available) == (Decimal("1000"), Decimal("642"))


async def test_read_balance_raises_for_unconfigured_pool() -> None:
    source = FakeBalanceSource()

    with pytest.raises(InvariantViolation):
        await source.read_balance("pionex", "coin-m", "BTC")


async def test_constructor_accepts_initial_balances() -> None:
    source = FakeBalanceSource({("bybit", "usdt-m", "USDT"): Decimal("500")})

    funds = await source.read_balance("bybit", "usdt-m", "USDT")

    assert funds.available == Decimal("500")
