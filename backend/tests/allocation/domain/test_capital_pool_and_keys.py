"""Unit tests for ``CapitalPool.available`` (clamped at 0) and ``PoolKey`` /
``LockKey`` construction (tasks.md 4.3)."""

from decimal import Decimal

import pytest

from strategy_manager.allocation.domain.capital_pool import CapitalPool
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Venue

_KEY = PoolKey(venue=Venue.SPOT, settlement_currency=Currency.USDT)


def test_available_is_balance_minus_reserved_active() -> None:
    pool = CapitalPool(key=_KEY, balance=Decimal("1000"), reserved_active=Decimal("300"))

    assert pool.available == Decimal("700")


def test_available_clamps_at_zero_when_balance_equals_reserved() -> None:
    pool = CapitalPool(key=_KEY, balance=Decimal("1000"), reserved_active=Decimal("1000"))

    assert pool.available == Decimal("0")


def test_available_clamps_at_zero_never_negative() -> None:
    pool = CapitalPool(key=_KEY, balance=Decimal("500"), reserved_active=Decimal("700"))

    assert pool.available == Decimal("0")


def test_pool_key_is_frozen_and_holds_venue_and_currency() -> None:
    key = PoolKey(venue=Venue.COIN_M, settlement_currency=Currency.BTC)

    assert key.venue is Venue.COIN_M
    assert key.settlement_currency is Currency.BTC


def test_lock_key_holds_the_ordered_text_pair() -> None:
    key = LockKey(venue="spot", settlement_currency="USDT")

    assert key.venue == "spot"
    assert key.settlement_currency == "USDT"


def test_lock_key_rejects_an_empty_venue_or_currency() -> None:
    with pytest.raises(InvariantViolation):
        LockKey(venue="", settlement_currency="USDT")

    with pytest.raises(InvariantViolation):
        LockKey(venue="spot", settlement_currency="")


def test_lock_key_from_pool_key_derives_the_text_pair() -> None:
    pool_key = PoolKey(venue=Venue.COIN_M, settlement_currency=Currency.ETH)

    lock_key = LockKey.from_pool_key(pool_key)

    assert lock_key == LockKey(venue="coin-m", settlement_currency="ETH")
