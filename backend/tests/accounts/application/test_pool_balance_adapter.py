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


def _pools() -> dict[tuple[str, str, str], PoolConfig]:
    return {
        ("pionex", "spot", "USDT"): PoolConfig(
            exchange=Exchange.PIONEX,
            venue=Venue.SPOT,
            settlement_currency=Currency.USDT,
            min_order_size=Decimal("10"),
        )
    }


async def test_read_combines_pool_config_and_live_balance() -> None:
    balance_source = FakeBalanceSource()
    balance_source.set_funds(
        "pionex", "spot", "USDT", total=Decimal("1000"), available=Decimal("700")
    )
    adapter = PoolBalanceAdapter(_pools(), balance_source)

    pool_balance = await adapter.read("pionex", "spot", "USDT")

    assert pool_balance.total == Decimal("1000")
    assert pool_balance.available == Decimal("700")
    assert pool_balance.min_order_size == Decimal("10")


async def test_read_raises_for_unconfigured_pool() -> None:
    adapter = PoolBalanceAdapter(_pools(), FakeBalanceSource())

    with pytest.raises(InvariantViolation):
        await adapter.read("pionex", "coin-m", "BTC")


async def test_the_same_venue_on_another_exchange_is_not_this_pool() -> None:
    """``(bybit, spot, USDT)`` is not ``(pionex, spot, USDT)``. Resolving it
    to the configured one would size a Bybit strategy from Pionex's wallet."""
    adapter = PoolBalanceAdapter(_pools(), FakeBalanceSource())

    with pytest.raises(InvariantViolation):
        await adapter.read("bybit", "spot", "USDT")
