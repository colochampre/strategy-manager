"""``VenueFillReaderRegistry`` — mirrors ``VenuePositionReaderRegistry``
exactly, including its refusal rule: an unserved pool RAISES, there is no
fallback."""

from datetime import datetime

import pytest

from strategy_manager.reconciliation.application.ports import PoolKey, VenueFill
from strategy_manager.reconciliation.infrastructure.venue_fill_reader_registry import (
    UnservedFillPoolError,
    VenueFillReaderRegistry,
)


class FakeReader:
    def __init__(self, exchange: str, venues: frozenset[str]) -> None:
        self.exchange = exchange
        self.venues = venues

    async def fills_in_window(
        self, pool: PoolKey, symbol: str, start: datetime, end: datetime
    ) -> list[VenueFill]:
        return []


def test_routes_to_the_reader_that_declares_the_pool() -> None:
    bybit = FakeReader("bybit", frozenset({"usdt-m"}))
    binance = FakeReader("binance", frozenset({"usdt-m"}))
    registry = VenueFillReaderRegistry([bybit, binance])

    assert registry.for_pool("bybit", "usdt-m") is bybit
    assert registry.for_pool("binance", "usdt-m") is binance


def test_an_unserved_pool_raises_never_falls_back() -> None:
    registry = VenueFillReaderRegistry([FakeReader("bybit", frozenset({"usdt-m"}))])

    with pytest.raises(UnservedFillPoolError, match="binance/usdt-m"):
        registry.for_pool("binance", "usdt-m")


def test_two_readers_claiming_the_same_pool_raises_at_construction() -> None:
    with pytest.raises(UnservedFillPoolError, match="bybit/usdt-m"):
        VenueFillReaderRegistry(
            [
                FakeReader("bybit", frozenset({"usdt-m"})),
                FakeReader("bybit", frozenset({"usdt-m"})),
            ]
        )


def test_pools_and_readers_expose_the_full_routing_table() -> None:
    bybit = FakeReader("bybit", frozenset({"usdt-m"}))
    registry = VenueFillReaderRegistry([bybit])

    assert registry.pools == frozenset({("bybit", "usdt-m")})
    assert registry.readers == {("bybit", "usdt-m"): bybit}
