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


async def test_fill_latency_polls_returns_no_fills_for_the_first_n_calls() -> None:
    """design.md § S5 testing, "Timing": rehearses an order whose fill is
    not published on the exchange's first few answers."""
    adapter = FakeExchangeAdapter(
        exchange="bybit", fill_price=Decimal("100"), fill_latency_polls=3
    )
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

    first = await adapter.fetch_fills("c1", "ETHUSDT.P")
    second = await adapter.fetch_fills("c1", "ETHUSDT.P")
    third = await adapter.fetch_fills("c1", "ETHUSDT.P")

    assert first == []
    assert second == []
    assert third == []
    assert adapter.is_revealed("c1") is False


async def test_fill_latency_polls_reveals_the_fill_past_the_nth_call() -> None:
    book = FakeVenueBook(FakeLedgerReader())
    adapter = FakeExchangeAdapter(
        exchange="bybit", fill_price=Decimal("100"), book=book, fill_latency_polls=3
    )
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
    for _ in range(3):
        await adapter.fetch_fills("c1", "ETHUSDT.P")
        assert adapter.is_revealed("c1") is False

    fourth = await adapter.fetch_fills("c1", "ETHUSDT.P")

    assert len(fourth) == 1
    assert fourth[0].quantity == Decimal("2")
    assert adapter.is_revealed("c1") is True
    # The book only sees the fill once it is actually revealed -- not on any
    # of the three empty polls before it.
    positions = await book.open_positions(("bybit", "usdt-m", "USDT"))
    assert positions == [("ETHUSDT", Decimal("2"))]


async def test_default_fill_latency_reveals_immediately() -> None:
    """``fill_latency_polls=0`` (the default) preserves every caller that
    predates it: ``is_revealed`` is already True after the first call."""
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
    assert adapter.is_revealed("c1") is True


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
