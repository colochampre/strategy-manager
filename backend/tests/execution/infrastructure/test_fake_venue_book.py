"""Unit tests: ``FakeVenueBook`` -- DRY_RUN's in-memory stand-in for a
venue's own reported net position (design.md § S4, DRY_RUN paragraph).

Keyed by ``(exchange, market)``: ``FakeExchangeAdapter``, which is what
calls ``record_fill``, only ever knows its own exchange and an order's
symbol -- never a settlement currency or a venue.
"""

from decimal import Decimal

from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook

POOL = ("bybit", "usdt-m", "USDT")


class FakeLedgerReader:
    def __init__(self, *rows: tuple[str, Decimal]) -> None:
        self._rows = list(rows)
        self.calls: list[tuple[str, str, str]] = []

    async def __call__(self, pool: tuple[str, str, str]) -> list[tuple[str, Decimal]]:
        self.calls.append(pool)
        return self._rows


async def test_seeds_from_the_ledger_the_first_time_a_pool_is_read() -> None:
    """A worker restart must not turn an already-open DRY_RUN position into
    a ghost -- the first answer for a never-before-seen market is whatever
    the ledger already says is open on it."""
    reader = FakeLedgerReader(("ETHUSDT.P", Decimal("0.5")))
    book = FakeVenueBook(reader)

    positions = await book.open_positions(POOL)

    assert positions == [("ETHUSDT", Decimal("0.5"))]


async def test_seeds_only_once_per_pool() -> None:
    reader = FakeLedgerReader(("ETHUSDT", Decimal("0.5")))
    book = FakeVenueBook(reader)

    await book.open_positions(POOL)
    await book.open_positions(POOL)

    assert reader.calls == [POOL]


async def test_record_fill_moves_the_net_by_the_signed_delta() -> None:
    reader = FakeLedgerReader()
    book = FakeVenueBook(reader)
    await book.open_positions(POOL)  # seeds flat, nothing open yet

    book.record_fill("bybit", "ETHUSDT.P", Decimal("0.5"))
    positions = await book.open_positions(POOL)

    assert positions == [("ETHUSDT", Decimal("0.5"))]


async def test_record_fill_normalises_a_different_spelling_than_the_seed() -> None:
    """Binding testing lesson (owner, 2026-09-21): the seed and the fill use
    DIFFERENT spellings on purpose -- proves the book keys by market, not by
    raw string."""
    reader = FakeLedgerReader(("ETHUSDT_PERP", Decimal("0.5")))
    book = FakeVenueBook(reader)
    await book.open_positions(POOL)

    book.record_fill("bybit", "ETHUSDT.P", Decimal("0.25"))
    positions = await book.open_positions(POOL)

    assert positions == [("ETHUSDT", Decimal("0.75"))]


async def test_record_fill_before_any_seed_starts_from_flat() -> None:
    """A brand-new market has no prior ledger fact to seed from -- the fill
    itself is the founding fact."""
    reader = FakeLedgerReader()
    book = FakeVenueBook(reader)

    book.record_fill("bybit", "BTCUSDT", Decimal("-0.1"))
    positions = await book.open_positions(POOL)

    assert positions == [("BTCUSDT", Decimal("-0.1"))]


async def test_inject_manufactures_a_venue_side_move_for_rehearsal() -> None:
    """Test-only: rehearses a ghost by moving the venue's own net without a
    matching fill."""
    reader = FakeLedgerReader(("ETHUSDT", Decimal("0.5")))
    book = FakeVenueBook(reader)
    await book.open_positions(POOL)

    book.inject("bybit", "ETHUSDT", Decimal("-0.5"))
    positions = await book.open_positions(POOL)

    assert positions == [("ETHUSDT", Decimal("0"))]


async def test_a_different_exchange_never_leaks_into_this_pools_answer() -> None:
    reader = FakeLedgerReader(("ETHUSDT", Decimal("0.5")))
    book = FakeVenueBook(reader)
    await book.open_positions(POOL)
    book.record_fill("binance", "ETHUSDT", Decimal("9"))

    positions = await book.open_positions(POOL)

    assert positions == [("ETHUSDT", Decimal("0.5"))]
