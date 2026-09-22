"""Unit tests: ``FakeExchangeAdapter`` -- baseline place/fetch_fills
behaviour, plus its optional hook into ``FakeVenueBook`` (design.md § S4,
DRY_RUN paragraph: "updates only when ``FakeExchangeAdapter`` reveals a
fill").
"""

from decimal import Decimal

import pytest

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    OpenOrderSpec,
    OrderNotFound,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook


class FakeLedgerReader:
    async def __call__(self, pool: tuple[str, str, str]) -> list[tuple[str, Decimal]]:
        return []


async def test_fetch_fills_returns_the_fill_recorded_at_place_time() -> None:
    """Baseline behaviour, unaffected by the optional book: no book, no
    normalisation, nothing new."""
    adapter = FakeExchangeAdapter(exchange="bybit", fill_price=Decimal("100"))
    order = await adapter.build_open_order(
        OpenOrderSpec(
            side=OrderSide.BUY,
            client_order_id="c1",
            symbol="ETHUSDT.P",
            granted=Decimal("200"),
            price=Decimal("100"),
        )
    )
    await adapter.place(order)

    fills = await adapter.fetch_fills("c1", "ETHUSDT.P")

    assert len(fills) == 1
    assert fills[0].quantity == Decimal("2")


async def test_fetch_fills_with_no_such_order_still_raises_order_not_found() -> None:
    adapter = FakeExchangeAdapter(exchange="bybit")

    with pytest.raises(OrderNotFound):
        await adapter.fetch_fills("nope", "ETHUSDT.P")


async def test_a_buy_records_a_positive_delta_in_the_book() -> None:
    book = FakeVenueBook(FakeLedgerReader())
    adapter = FakeExchangeAdapter(exchange="bybit", fill_price=Decimal("100"), book=book)
    order = await adapter.build_open_order(
        OpenOrderSpec(
            side=OrderSide.BUY,
            client_order_id="c1",
            symbol="ETHUSDT.P",
            granted=Decimal("200"),
            price=Decimal("100"),
        )
    )
    await adapter.place(order)

    await adapter.fetch_fills("c1", "ETHUSDT.P")

    positions = await book.open_positions(("bybit", "usdt-m", "USDT"))
    assert positions == [("ETHUSDT", Decimal("2"))]


async def test_a_sell_records_a_negative_delta_in_the_book() -> None:
    book = FakeVenueBook(FakeLedgerReader())
    adapter = FakeExchangeAdapter(exchange="bybit", fill_price=Decimal("100"), book=book)
    order = await adapter.build_close_order(
        CloseOrderSpec(
            side=OrderSide.SELL,
            client_order_id="c2",
            symbol="ETHUSDT.P",
            base_size=Decimal("1.5"),
        )
    )
    await adapter.place(order)

    await adapter.fetch_fills("c2", "ETHUSDT.P")

    positions = await book.open_positions(("bybit", "usdt-m", "USDT"))
    assert positions == [("ETHUSDT", Decimal("-1.5"))]


async def test_no_book_configured_leaves_fetch_fills_unaffected() -> None:
    """The default (``book=None``) preserves every pre-S4 caller's
    behaviour exactly -- nothing about ``fetch_fills`` needs a book to run."""
    adapter = FakeExchangeAdapter(exchange="bybit", fill_price=Decimal("100"))
    order = await adapter.build_open_order(
        OpenOrderSpec(
            side=OrderSide.BUY,
            client_order_id="c1",
            symbol="ETHUSDT.P",
            granted=Decimal("200"),
            price=Decimal("100"),
        )
    )
    await adapter.place(order)

    fills = await adapter.fetch_fills("c1", "ETHUSDT.P")

    assert len(fills) == 1
