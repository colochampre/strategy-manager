"""``LazyVenuePositionReader``: defers building the real per-exchange venue
position reader until ``open_positions`` is actually called, and builds it
AT MOST ONCE thereafter (design.md § S4 correction, mirroring
``RefreshPoolBalance``'s own ``ReaderByExchange`` correction, design.md §
S3, 2026-09-21).
"""

from decimal import Decimal

from strategy_manager.reconciliation.domain.positions import VenuePosition
from strategy_manager.reconciliation.infrastructure.lazy_venue_position_reader import (
    LazyVenuePositionReader,
)

POOL = ("bybit", "usdt-m", "USDT")


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def open_positions(self, pool: tuple[str, str, str]) -> list[VenuePosition]:
        self.calls.append(pool)
        return [VenuePosition("ETHUSDT", Decimal("0.5"))]


async def test_the_factory_is_never_called_until_open_positions_is() -> None:
    build_count = 0
    real_reader = FakeReader()

    async def factory() -> FakeReader:
        nonlocal build_count
        build_count += 1
        return real_reader

    LazyVenuePositionReader("bybit", frozenset({"usdt-m"}), factory)

    assert build_count == 0


async def test_open_positions_builds_the_reader_exactly_once() -> None:
    build_count = 0
    real_reader = FakeReader()

    async def factory() -> FakeReader:
        nonlocal build_count
        build_count += 1
        return real_reader

    reader = LazyVenuePositionReader("bybit", frozenset({"usdt-m"}), factory)

    await reader.open_positions(POOL)
    await reader.open_positions(POOL)

    assert build_count == 1
    assert real_reader.calls == [POOL, POOL]


async def test_declares_the_exchange_and_venues_it_was_given() -> None:
    async def factory() -> FakeReader:
        return FakeReader()

    reader = LazyVenuePositionReader("binance", frozenset({"usdt-m"}), factory)

    assert reader.exchange == "binance"
    assert reader.venues == frozenset({"usdt-m"})


async def test_open_positions_returns_whatever_the_built_reader_answers() -> None:
    async def factory() -> FakeReader:
        return FakeReader()

    reader = LazyVenuePositionReader("bybit", frozenset({"usdt-m"}), factory)

    positions = await reader.open_positions(POOL)

    assert positions == [VenuePosition("ETHUSDT", Decimal("0.5"))]
