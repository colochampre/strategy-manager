"""``ReadAvailablePairs``: exists -> available_pairs -> sorted (design addendum § F).

The use case answers a pool that is a ``capital_pools`` row, enabled or not, and
refuses a made-up one BEFORE the catalogue is asked: a path value must never
cause a venue call or a cache entry. Errors the catalogue raises pass through
untouched; mapping them to a status is the router's job.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.strategies.application.ports import PoolKey
from strategy_manager.strategies.application.read_available_pairs import (
    ReadAvailablePairs,
    UnknownPool,
)
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
)
from strategy_manager.strategies.infrastructure.pool_catalog import SqlAlchemyPoolCatalog
from tests.owner import OWNER_ID, seed_other_user, seed_pool

POOL: PoolKey = ("bybit", "usdt-m", "USDT")


class _Pools:
    """Knows ``known`` as ``OWNER_ID``'s pools, and no other user's."""

    def __init__(self, *known: PoolKey) -> None:
        self._known = set(known)
        self.enabled_asked = 0
        self.users_asked: list[UUID] = []

    async def enabled_pools(self, user_id: UUID) -> list[tuple[object, object, object]]:
        self.enabled_asked += 1
        return []  # no pool is ENABLED: the disabled-pool case

    async def exists(self, user_id: UUID, pool: PoolKey) -> bool:
        self.users_asked.append(user_id)
        return user_id == OWNER_ID and pool in self._known


class _Catalog:
    def __init__(self, pairs: frozenset[str] = frozenset(), failure: Exception | None = None):
        self.asked: list[PoolKey] = []
        self._pairs = pairs
        self._failure = failure

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]:
        self.asked.append(pool)
        if self._failure is not None:
            raise self._failure
        return self._pairs


async def test_an_unknown_pool_raises_before_the_catalogue_is_asked() -> None:
    catalog = _Catalog(frozenset({"BTCUSDT"}))
    use_case = ReadAvailablePairs(_Pools(POOL), catalog)  # type: ignore[arg-type]

    with pytest.raises(UnknownPool):
        await use_case.execute(OWNER_ID, ("bybit", "usdt-m", "BTC"))

    assert catalog.asked == []


async def test_a_disabled_pool_is_answered() -> None:
    pools = _Pools(POOL)  # exists, but enabled_pools() is empty
    catalog = _Catalog(frozenset({"BTCUSDT", "ETHUSDT"}))
    use_case = ReadAvailablePairs(pools, catalog)  # type: ignore[arg-type]

    result = await use_case.execute(OWNER_ID, POOL)

    assert result == ["BTCUSDT", "ETHUSDT"]
    assert catalog.asked == [POOL]
    assert pools.enabled_asked == 0


async def test_pairs_are_returned_sorted() -> None:
    catalog = _Catalog(frozenset({"STXUSDT", "AAVEUSDT", "ETHUSDT", "BTCUSDT"}))
    use_case = ReadAvailablePairs(_Pools(POOL), catalog)  # type: ignore[arg-type]

    assert await use_case.execute(OWNER_ID, POOL) == [
        "AAVEUSDT",
        "BTCUSDT",
        "ETHUSDT",
        "STXUSDT",
    ]


@pytest.mark.parametrize("failure", [PairCatalogNotServed("x"), PairCatalogUnavailable("x")])
async def test_a_catalogue_refusal_passes_through_unchanged(failure: Exception) -> None:
    use_case = ReadAvailablePairs(_Pools(POOL), _Catalog(failure=failure))  # type: ignore[arg-type]

    with pytest.raises(type(failure)):
        await use_case.execute(OWNER_ID, POOL)


async def test_another_users_pool_is_unknown_to_this_user() -> None:
    """The pool exists, but it is the owner's. A second user asking for it is
    told it is unknown, the catalogue is never asked, and the question was put
    for that second user (multi-user design AD8)."""
    other = uuid4()
    pools = _Pools(POOL)
    catalog = _Catalog(frozenset({"BTCUSDT"}))
    use_case = ReadAvailablePairs(pools, catalog)  # type: ignore[arg-type]

    with pytest.raises(UnknownPool):
        await use_case.execute(other, POOL)

    assert pools.users_asked == [other]
    assert catalog.asked == []


@pytest.mark.integration
async def test_sql_pool_catalog_exists_is_true_for_enabled_and_disabled_rows_only(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "UPDATE capital_pools SET enabled = false "
                "WHERE exchange = 'pionex' AND venue = 'spot'"
            )
        )
        await session.commit()

        catalog = SqlAlchemyPoolCatalog(session)

        assert await catalog.exists(OWNER_ID, ("bybit", "usdt-m", "USDT")) is True  # enabled
        assert await catalog.exists(OWNER_ID, ("pionex", "spot", "USDT")) is True  # disabled
        assert await catalog.exists(OWNER_ID, ("bybit", "usdt-m", "BTC")) is False
        assert await catalog.exists(OWNER_ID, ("bybit", "usdt-m", "usdt")) is False  # wrong case
        assert await catalog.exists(OWNER_ID, ("binance", "usdt-m", "USDT")) is False  # not a row


@pytest.mark.integration
async def test_sql_pool_catalog_exists_never_answers_with_another_users_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A second user holds a pool on ``binance/usdt-m/USDT``, a market the owner
    has none on; the second user holds none on bybit, where the owner does. Each
    user's question is answered by their own rows alone."""
    binance: PoolKey = ("binance", "usdt-m", "USDT")
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await seed_pool(session, binance, user_id=other)
        await session.commit()

        catalog = SqlAlchemyPoolCatalog(session)

        assert await catalog.exists(OWNER_ID, binance) is False
        assert await catalog.exists(other, binance) is True
        assert await catalog.exists(other, POOL) is False
        assert await catalog.exists(OWNER_ID, POOL) is True
