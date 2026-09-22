"""``FakeVenuePositionReader``: implements ``VenuePositionReaderPort`` over
``FakeVenueBook`` -- wired only under DRY_RUN (design.md § S4), so the REAL
branch of orphan classification is reachable in rehearsal exactly as it is
live.
"""

from decimal import Decimal

from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook
from strategy_manager.reconciliation.domain.positions import VenuePosition
from strategy_manager.reconciliation.infrastructure.fake_venue_position_reader import (
    FakeVenuePositionReader,
)

POOL = ("bybit", "usdt-m", "USDT")


class FakeLedgerReader:
    def __init__(self, *rows: tuple[str, Decimal]) -> None:
        self._rows = list(rows)

    async def __call__(self, pool: tuple[str, str, str]) -> list[tuple[str, Decimal]]:
        return self._rows


async def test_translates_the_books_positions_into_venue_positions() -> None:
    book = FakeVenueBook(FakeLedgerReader(("ETHUSDT", Decimal("0.5"))))
    reader = FakeVenuePositionReader(
        exchange="bybit", venues=frozenset({"usdt-m"}), book=book
    )

    positions = await reader.open_positions(POOL)

    assert positions == [VenuePosition("ETHUSDT", Decimal("0.5"))]


async def test_declares_its_own_exchange_and_venues() -> None:
    """Consulted by the registry at construction time, exactly like every
    real venue position reader."""
    book = FakeVenueBook(FakeLedgerReader())
    reader = FakeVenuePositionReader(
        exchange="binance", venues=frozenset({"usdt-m"}), book=book
    )

    assert reader.exchange == "binance"
    assert reader.venues == frozenset({"usdt-m"})


async def test_reads_the_whole_pool_the_book_currently_knows() -> None:
    book = FakeVenueBook(
        FakeLedgerReader(("ETHUSDT", Decimal("0.5")), ("BTCUSDT", Decimal("-1")))
    )
    reader = FakeVenuePositionReader(
        exchange="bybit", venues=frozenset({"usdt-m"}), book=book
    )

    positions = await reader.open_positions(POOL)

    assert {p.symbol for p in positions} == {"ETHUSDT", "BTCUSDT"}
