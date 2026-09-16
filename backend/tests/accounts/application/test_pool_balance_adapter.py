"""Unit tests for PoolBalanceAdapter, mapping a startup-loaded PoolConfig
snapshot plus a FakeBalanceSource to allocation.application.PoolBalancePort
(tasks.md 3.11)."""

from decimal import Decimal

import pytest

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue


def _pools() -> dict[tuple[str, str], PoolConfig]:
    return {
        ("spot", "USDT"): PoolConfig(
            exchange=Exchange.PIONEX,
            venue=Venue.SPOT,
            settlement_currency=Currency.USDT,
            min_order_size=Decimal("10"),
        )
    }


async def test_read_combines_pool_config_and_live_balance() -> None:
    balance_source = FakeBalanceSource()
    balance_source.set_funds("spot", "USDT", total=Decimal("1000"), available=Decimal("700"))
    adapter = PoolBalanceAdapter(_pools(), balance_source)

    pool_balance = await adapter.read("spot", "USDT")

    assert pool_balance.total == Decimal("1000")
    assert pool_balance.available == Decimal("700")
    assert pool_balance.min_order_size == Decimal("10")


async def test_read_raises_for_unconfigured_pool() -> None:
    adapter = PoolBalanceAdapter(_pools(), FakeBalanceSource())

    with pytest.raises(InvariantViolation):
        await adapter.read("coin-m", "BTC")
