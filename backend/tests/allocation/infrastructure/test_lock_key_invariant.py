"""Unit tests for the pure lock-key collision check (spec: capital-allocation
§ Startup Lock-Key Collision Invariant; tasks.md 3.13)."""

from decimal import Decimal
from uuid import UUID

import pytest

from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    LockKeyPair,
    PoolLockKeyCollisionError,
    assert_lock_key_pairs_distinct,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.owner import OWNER_ID


def _pool(venue: Venue, currency: Currency) -> PoolConfig:
    return PoolConfig(
        exchange=Exchange.BYBIT,
        venue=venue,
        settlement_currency=currency,
        user_id=OWNER_ID,
        min_order_size=Decimal("1"),
    )


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


def test_the_collision_message_names_both_pools_and_both_users() -> None:
    other = PoolConfig(
        exchange=Exchange.BYBIT,
        venue=Venue.USDT_M,
        settlement_currency=Currency.USDT,
        user_id=UUID("b2b2b2b2-0000-4000-8000-000000000001"),
        min_order_size=Decimal("1"),
    )
    pairs = [
        LockKeyPair(pool=_pool(Venue.USDT_M, Currency.USDT), k1=7, k2=8),
        LockKeyPair(pool=other, k1=7, k2=8),
    ]

    with pytest.raises(PoolLockKeyCollisionError) as raised:
        assert_lock_key_pairs_distinct(pairs)

    message = str(raised.value)
    assert str(OWNER_ID)[:8] in message
    assert "b2b2b2b2" in message
    assert str(OWNER_ID) not in message


def test_shared_k1_with_different_k2_does_not_raise() -> None:
    """Proves the check compares the (k1, k2) pair, never k1 alone — matches
    the real coin-m/BTC vs coin-m/ETH case, which share k1 (tasks.md 3.14)."""
    pairs = [
        LockKeyPair(pool=_pool(Venue.COIN_M, Currency.BTC), k1=1937348485, k2=-1182514593),
        LockKeyPair(pool=_pool(Venue.COIN_M, Currency.ETH), k1=1937348485, k2=273220054),
    ]

    assert_lock_key_pairs_distinct(pairs)  # no raise
