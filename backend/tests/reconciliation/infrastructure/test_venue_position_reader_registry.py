"""``VenuePositionReaderRegistry`` — which reader serves a given pool.

Mirrors ``test_exchange_registry.py`` on the execution side: an unserved pool
raises rather than falling back to any reader, and two readers claiming the
same pool is refused at construction time rather than resolved arbitrarily.
"""

import pytest

from strategy_manager.reconciliation.application.ports import (
    PoolKey,
    VenuePosition,
)
from strategy_manager.reconciliation.infrastructure.venue_position_reader_registry import (
    UnservedPoolError,
    VenuePositionReaderRegistry,
)


class FakeReader:
    def __init__(self, exchange: str, venues: frozenset[str]) -> None:
        self.exchange = exchange
        self.venues = venues

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        return []


def test_routes_to_the_reader_registered_for_the_pool() -> None:
    bybit = FakeReader("bybit", frozenset({"usdt-m"}))
    binance = FakeReader("binance", frozenset({"usdt-m"}))
    registry = VenuePositionReaderRegistry([bybit, binance])

    assert registry.for_pool("bybit", "usdt-m") is bybit
    assert registry.for_pool("binance", "usdt-m") is binance


def test_an_unserved_pool_raises_rather_than_falling_back() -> None:
    registry = VenuePositionReaderRegistry([FakeReader("bybit", frozenset({"usdt-m"}))])

    with pytest.raises(UnservedPoolError, match="pionex/spot"):
        registry.for_pool("pionex", "spot")


def test_two_readers_claiming_the_same_pool_are_refused_at_construction() -> None:
    first = FakeReader("bybit", frozenset({"usdt-m"}))
    second = FakeReader("bybit", frozenset({"usdt-m"}))

    with pytest.raises(UnservedPoolError, match="bybit/usdt-m"):
        VenuePositionReaderRegistry([first, second])


def test_pools_exposes_every_registered_route() -> None:
    registry = VenuePositionReaderRegistry(
        [FakeReader("bybit", frozenset({"usdt-m"})), FakeReader("binance", frozenset({"usdt-m"}))]
    )

    assert registry.pools == {("bybit", "usdt-m"), ("binance", "usdt-m")}


def test_a_reader_serving_multiple_venues_is_routed_by_each() -> None:
    reader = FakeReader("pionex", frozenset({"spot", "coin-m"}))
    registry = VenuePositionReaderRegistry([reader])

    assert registry.for_pool("pionex", "spot") is reader
    assert registry.for_pool("pionex", "coin-m") is reader
