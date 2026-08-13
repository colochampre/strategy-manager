"""Startup Lock-Key Collision Invariant (spec: capital-allocation § Startup
Lock-Key Collision Invariant; design.md § Composition Root, invariant 1).

``capital_pools`` is the single source of truth for which pools exist — this
enumerates it directly via ``CapitalPoolRepository``, never a
``CONFIGURED_POOLS`` env list.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from strategy_manager.accounts.domain.pool_config import PoolConfig


class PoolLockKeyCollisionError(Exception):
    """Raised when two configured pools hash to the same advisory-lock key
    pair. Startup MUST abort before accepting traffic."""


@dataclass(frozen=True, slots=True)
class LockKeyPair:
    """A pool paired with its already-computed ``hashtext`` values."""

    pool: PoolConfig
    k1: int
    k2: int


def assert_lock_key_pairs_distinct(pairs: Sequence[LockKeyPair]) -> None:
    """Pure check: no I/O. Raises on the first duplicate ``(k1, k2)`` pair —
    comparing the full pair, never ``k1`` alone (coin-m/BTC and coin-m/ETH
    are verified to share ``k1`` while differing in ``k2``)."""

    seen: dict[tuple[int, int], PoolConfig] = {}
    for pair in pairs:
        key = (pair.k1, pair.k2)
        collision = seen.get(key)
        if collision is not None:
            raise PoolLockKeyCollisionError(
                f"pools ({collision.venue}, {collision.settlement_currency}) and "
                f"({pair.pool.venue}, {pair.pool.settlement_currency}) both hash to "
                f"lock key {key}"
            )
        seen[key] = pair.pool


async def assert_pool_lock_keys_distinct(
    conn: AsyncConnection, pools: Iterable[PoolConfig]
) -> None:
    """DB-backed check: computes each pool's real ``hashtext`` pair, then
    delegates to the pure invariant."""

    pairs: list[LockKeyPair] = []
    for pool in pools:
        result = await conn.execute(
            text("SELECT hashtext(:venue), hashtext(:currency)"),
            {"venue": pool.venue.value, "currency": pool.settlement_currency.value},
        )
        k1, k2 = result.one()
        pairs.append(LockKeyPair(pool=pool, k1=k1, k2=k2))
    assert_lock_key_pairs_distinct(pairs)
