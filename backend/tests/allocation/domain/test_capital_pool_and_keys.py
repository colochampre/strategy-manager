"""Unit tests for ``CapitalPool.available`` (clamped at 0) and ``PoolKey`` /
``LockKey`` construction (tasks.md 4.3)."""

from decimal import Decimal
from uuid import UUID

import pytest

from strategy_manager.allocation.domain.capital_pool import CapitalPool
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.owner import OWNER_ID

_KEY = PoolKey(exchange=Exchange.PIONEX, venue=Venue.SPOT, settlement_currency=Currency.USDT)


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
    key = PoolKey(exchange=Exchange.PIONEX, venue=Venue.COIN_M, settlement_currency=Currency.BTC)

    assert key.venue is Venue.COIN_M
    assert key.settlement_currency is Currency.BTC


def test_lock_key_holds_the_ordered_text_pair() -> None:
    key = LockKey(exchange="pionex", venue="spot", settlement_currency="USDT", user_id=OWNER_ID)

    assert key.venue == "spot"
    assert key.settlement_currency == "USDT"


def test_lock_key_rejects_an_empty_venue_or_currency() -> None:
    with pytest.raises(InvariantViolation):
        LockKey(exchange=Exchange.BYBIT, venue="", settlement_currency="USDT", user_id=OWNER_ID)

    with pytest.raises(InvariantViolation):
        LockKey(exchange="pionex", venue="spot", settlement_currency="", user_id=OWNER_ID)


def test_lock_key_rejects_an_empty_user() -> None:
    with pytest.raises(InvariantViolation):
        LockKey(exchange="pionex", venue="spot", settlement_currency="USDT", user_id=UUID(int=0))


def test_lock_key_from_pool_key_derives_the_text_pair() -> None:
    pool_key = PoolKey(
        exchange=Exchange.PIONEX,
        venue=Venue.COIN_M,
        settlement_currency=Currency.ETH,
    )

    lock_key = LockKey.from_pool_key(OWNER_ID, pool_key)

    assert lock_key == LockKey(
        exchange="pionex", venue="coin-m", settlement_currency="ETH", user_id=OWNER_ID
    )


def test_two_users_on_one_market_get_different_hash_inputs() -> None:
    pool_key = PoolKey(
        exchange=Exchange.BYBIT, venue=Venue.USDT_M, settlement_currency=Currency.USDT
    )

    owner = LockKey.from_pool_key(OWNER_ID, pool_key)
    other = LockKey.from_pool_key(UUID("00000000-0000-4000-8000-0000000000b2"), pool_key)

    assert (owner.first, owner.second) != (other.first, other.second)


def test_one_user_on_one_market_always_gets_the_same_hash_inputs() -> None:
    pool_key = PoolKey(
        exchange=Exchange.BYBIT, venue=Venue.USDT_M, settlement_currency=Currency.USDT
    )

    first = LockKey.from_pool_key(OWNER_ID, pool_key)
    second = LockKey.from_pool_key(OWNER_ID, pool_key)

    assert (first.first, first.second) == (second.first, second.second)
