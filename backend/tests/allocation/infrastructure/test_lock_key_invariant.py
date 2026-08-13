"""Unit tests for the pure lock-key collision check (spec: capital-allocation
§ Startup Lock-Key Collision Invariant; tasks.md 3.13)."""

from decimal import Decimal

import pytest

from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    LockKeyPair,
    PoolLockKeyCollisionError,
    assert_lock_key_pairs_distinct,
)
from strategy_manager.shared.domain.money import Currency, Venue


def _pool(venue: Venue, currency: Currency) -> PoolConfig:
    return PoolConfig(venue=venue, settlement_currency=currency, min_order_size=Decimal("1"))


def test_distinct_pairs_do_not_raise() -> None:
    pairs = [
        LockKeyPair(pool=_pool(Venue.SPOT, Currency.USDT), k1=1, k2=2),
        LockKeyPair(pool=_pool(Venue.USDT_M, Currency.USDT), k1=3, k2=4),
    ]

    assert_lock_key_pairs_distinct(pairs)  # no raise


def test_shared_pair_raises_collision_error() -> None:
    pairs = [
        LockKeyPair(pool=_pool(Venue.COIN_M, Currency.BTC), k1=1937348485, k2=-1182514593),
        LockKeyPair(pool=_pool(Venue.COIN_M, Currency.ETH), k1=1937348485, k2=-1182514593),
    ]

    with pytest.raises(PoolLockKeyCollisionError):
        assert_lock_key_pairs_distinct(pairs)


def test_shared_k1_with_different_k2_does_not_raise() -> None:
    """Proves the check compares the (k1, k2) pair, never k1 alone — matches
    the real coin-m/BTC vs coin-m/ETH case, which share k1 (tasks.md 3.14)."""
    pairs = [
        LockKeyPair(pool=_pool(Venue.COIN_M, Currency.BTC), k1=1937348485, k2=-1182514593),
        LockKeyPair(pool=_pool(Venue.COIN_M, Currency.ETH), k1=1937348485, k2=273220054),
    ]

    assert_lock_key_pairs_distinct(pairs)  # no raise
