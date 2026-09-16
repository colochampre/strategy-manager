"""Unit tests for the PoolConfig VO (design.md § accounts/domain/pool_config.py)."""

from decimal import Decimal

import pytest

from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue


def test_pool_config_stores_venue_currency_and_min_order_size() -> None:
    pool = PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        min_order_size=Decimal("10"),
    )

    assert pool.exchange == Exchange.PIONEX
    assert pool.venue == Venue.SPOT
    assert pool.settlement_currency == Currency.USDT
    assert pool.min_order_size == Decimal("10")
    assert pool.enabled is True


def test_pool_config_can_be_disabled() -> None:
    pool = PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.COIN_M,
        settlement_currency=Currency.BTC,
        min_order_size=Decimal("0.0001"),
        enabled=False,
    )

    assert pool.enabled is False


def test_pool_config_rejects_zero_min_order_size() -> None:
    with pytest.raises(InvariantViolation):
        PoolConfig(
            exchange=Exchange.PIONEX,
            venue=Venue.SPOT,
            settlement_currency=Currency.USDT,
            min_order_size=Decimal("0"),
        )


def test_pool_config_rejects_negative_min_order_size() -> None:
    with pytest.raises(InvariantViolation):
        PoolConfig(
            exchange=Exchange.PIONEX,
            venue=Venue.SPOT,
            settlement_currency=Currency.USDT,
            min_order_size=Decimal("-5"),
        )
