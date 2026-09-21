"""``ReaderByExchange``: routes a single-pool balance read to whichever
exchange's LAZY reader factory is registered for it.

A factory represents a credential decrypt plus an HTTP client open (main.py's
real ``_bybit_reader``/``_binance_reader`` closures). Laziness is the whole
point of this class (design.md § S3 correction, 2026-09-21): the first S3
commit built BOTH exchanges' readers eagerly on every ``signal.process``
job, so a RELEASES signal paid for credentials/clients it never needed, and
a missing credential on ONE exchange raised at job entry and took the OTHER
exchange's signals down too -- exactly what ``exchange_for``'s own docstring
exists to prevent for trade clients. Each factory here is invoked at most
once per router, the first time its exchange is actually requested, and a
failing factory PROPAGATES rather than being swallowed, so
``RefreshPoolBalance`` -- the only caller -- can catch it and degrade
through FALLBACK/UNAVAILABLE exactly like any other reader failure.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strategy_manager.accounts.application.ports import PoolBalanceReading, PoolKey
from strategy_manager.accounts.infrastructure.reader_by_exchange import ReaderByExchange

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)


def _reading(pool: PoolKey) -> PoolBalanceReading:
    exchange, venue, currency = pool
    return PoolBalanceReading(
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        total=Decimal("100"),
        available=Decimal("100"),
        observed_at=NOW,
    )


class StubReader:
    def __init__(self) -> None:
        self.requested: list[Sequence[PoolKey]] = []

    async def read(self, pools: Sequence[PoolKey]) -> list[PoolBalanceReading]:
        self.requested.append(pools)
        return [_reading(pool) for pool in pools]


class SpyFactory:
    """Stands in for main.py's ``_bybit_reader``/``_binance_reader``
    closures: each call represents a credential decrypt + HTTP client open."""

    def __init__(self, reader: StubReader | None = None, raises: Exception | None = None) -> None:
        self._reader = reader or StubReader()
        self._raises = raises
        self.calls = 0

    async def __call__(self) -> StubReader:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._reader


async def test_a_pool_is_routed_to_its_own_exchanges_factory() -> None:
    bybit_factory = SpyFactory()
    binance_factory = SpyFactory()
    router = ReaderByExchange({"bybit": bybit_factory, "binance": binance_factory})

    result = await router.read([("bybit", "usdt-m", "USDT")])

    assert bybit_factory.calls == 1
    assert binance_factory.calls == 0
    assert result[0].exchange == "bybit"


async def test_a_different_pool_is_routed_to_its_own_factory_in_turn() -> None:
    """Triangulation: a second exchange must not fall through to the first
    factory registered."""
    bybit_factory = SpyFactory()
    binance_factory = SpyFactory()
    router = ReaderByExchange({"bybit": bybit_factory, "binance": binance_factory})

    result = await router.read([("binance", "usdt-m", "USDT")])

    assert binance_factory.calls == 1
    assert bybit_factory.calls == 0
    assert result[0].exchange == "binance"


async def test_an_unrequested_exchanges_factory_is_never_invoked() -> None:
    """The defect this class exists to fix: an exchange nobody asked about
    must never pay for a credential decrypt or an HTTP client open -- proven
    here by a factory that would raise if it were ever called."""
    bybit_factory = SpyFactory(raises=RuntimeError("no bybit credential stored"))
    binance_factory = SpyFactory()
    router = ReaderByExchange({"bybit": bybit_factory, "binance": binance_factory})

    await router.read([("binance", "usdt-m", "USDT")])

    assert bybit_factory.calls == 0


async def test_a_factory_is_built_at_most_once_per_router() -> None:
    """Once opened, the same reader (and the client/credential behind it) is
    reused rather than reopened on every read."""
    reader = StubReader()
    factory = SpyFactory(reader)
    router = ReaderByExchange({"bybit": factory})

    await router.read([("bybit", "usdt-m", "USDT")])
    await router.read([("bybit", "usdt-m", "USDT")])

    assert factory.calls == 1
    assert len(reader.requested) == 2


async def test_a_failing_factory_propagates_rather_than_being_swallowed() -> None:
    """So ``RefreshPoolBalance`` can catch it and degrade through
    FALLBACK/UNAVAILABLE, exactly like any other reader failure -- it must
    never raise out of job entry."""
    router = ReaderByExchange(
        {"bybit": SpyFactory(raises=RuntimeError("no active credential stored for 'bybit'"))}
    )

    with pytest.raises(RuntimeError, match="no active credential"):
        await router.read([("bybit", "usdt-m", "USDT")])


async def test_an_unregistered_exchange_raises_rather_than_silently_reading_nothing() -> None:
    router = ReaderByExchange({"bybit": SpyFactory()})

    with pytest.raises(ValueError, match="pionex"):
        await router.read([("pionex", "spot", "USDT")])
