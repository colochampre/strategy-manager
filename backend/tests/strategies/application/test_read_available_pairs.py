"""``ReadAvailablePairs``: exists -> available_pairs -> sorted (design addendum § F).

The use case answers a pool that is a ``capital_pools`` row, enabled or not, and
refuses a made-up one BEFORE the catalogue is asked: a path value must never
cause a venue call or a cache entry. Errors the catalogue raises pass through
untouched; mapping them to a status is the router's job.
"""

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

POOL: PoolKey = ("bybit", "usdt-m", "USDT")


class _Pools:
    def __init__(self, *known: PoolKey) -> None:
        self._known = set(known)
        self.enabled_asked = 0

    async def enabled_pools(self) -> list[tuple[object, object, object]]:
        self.enabled_asked += 1
        return []  # no pool is ENABLED: the disabled-pool case

    async def exists(self, pool: PoolKey) -> bool:
        return pool in self._known


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
        await use_case.execute(("bybit", "usdt-m", "BTC"))

    assert catalog.asked == []


async def test_a_disabled_pool_is_answered() -> None:
    pools = _Pools(POOL)  # exists, but enabled_pools() is empty
    catalog = _Catalog(frozenset({"BTCUSDT", "ETHUSDT"}))
    use_case = ReadAvailablePairs(pools, catalog)  # type: ignore[arg-type]

    result = await use_case.execute(POOL)

    assert result == ["BTCUSDT", "ETHUSDT"]
    assert catalog.asked == [POOL]
    assert pools.enabled_asked == 0


async def test_pairs_are_returned_sorted() -> None:
    catalog = _Catalog(frozenset({"STXUSDT", "AAVEUSDT", "ETHUSDT", "BTCUSDT"}))
    use_case = ReadAvailablePairs(_Pools(POOL), catalog)  # type: ignore[arg-type]

    assert await use_case.execute(POOL) == ["AAVEUSDT", "BTCUSDT", "ETHUSDT", "STXUSDT"]


@pytest.mark.parametrize("failure", [PairCatalogNotServed("x"), PairCatalogUnavailable("x")])
async def test_a_catalogue_refusal_passes_through_unchanged(failure: Exception) -> None:
    use_case = ReadAvailablePairs(_Pools(POOL), _Catalog(failure=failure))  # type: ignore[arg-type]

    with pytest.raises(type(failure)):
        await use_case.execute(POOL)


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

        assert await catalog.exists(("bybit", "usdt-m", "USDT")) is True  # enabled
        assert await catalog.exists(("pionex", "spot", "USDT")) is True  # disabled
        assert await catalog.exists(("bybit", "usdt-m", "BTC")) is False
        assert await catalog.exists(("bybit", "usdt-m", "usdt")) is False  # wrong case
        assert await catalog.exists(("binance", "usdt-m", "USDT")) is False  # not a row
