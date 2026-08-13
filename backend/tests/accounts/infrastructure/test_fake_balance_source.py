"""Unit tests for FakeBalanceSource — the stand-in BalanceSourcePort until a
real Pionex balance adapter exists (design.md component inventory)."""

from decimal import Decimal

import pytest

from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.shared.domain.errors import InvariantViolation


async def test_read_balance_returns_the_configured_amount() -> None:
    source = FakeBalanceSource()
    source.set_balance("spot", "USDT", Decimal("1000"))

    balance = await source.read_balance("spot", "USDT")

    assert balance == Decimal("1000")


async def test_read_balance_raises_for_unconfigured_pool() -> None:
    source = FakeBalanceSource()

    with pytest.raises(InvariantViolation):
        await source.read_balance("coin-m", "BTC")


async def test_constructor_accepts_initial_balances() -> None:
    source = FakeBalanceSource({("usdt-m", "USDT"): Decimal("500")})

    balance = await source.read_balance("usdt-m", "USDT")

    assert balance == Decimal("500")
