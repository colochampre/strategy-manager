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
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook


class FakeLedgerReader:
    async def __call__(self, pool: tuple[str, str, str]) -> list[tuple[str, Decimal]]:
        return []


async def test_fetch_fills_returns_the_fill_recorded_at_place_time() -> None:
    """Baseline behaviour, unaffected by the optional book: no book, no
    normalisation, nothing new."""
    adapter = FakeExchangeAdapter(
        exchange="bybit", fill_price=Decimal("100"),
        fee_rate=Decimal("0"),
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

    fills = await adapter.fetch_fills("c1", "ETHUSDT.P")

    assert len(fills) == 1
    assert fills[0].quantity == Decimal("2")


async def test_fetch_fills_with_no_such_order_still_raises_order_not_found() -> None:
    adapter = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))

    with pytest.raises(OrderNotFound):
        await adapter.fetch_fills("nope", "ETHUSDT.P")


async def test_a_buy_records_a_positive_delta_in_the_book() -> None:
    book = FakeVenueBook(FakeLedgerReader())
    adapter = FakeExchangeAdapter(
        exchange="bybit", fill_price=Decimal("100"), book=book,
        fee_rate=Decimal("0"),
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

    await adapter.fetch_fills("c1", "ETHUSDT.P")

    positions = await book.open_positions(("bybit", "usdt-m", "USDT"))
    assert positions == [("ETHUSDT", Decimal("2"))]


async def test_a_sell_records_a_negative_delta_in_the_book() -> None:
    book = FakeVenueBook(FakeLedgerReader())
    adapter = FakeExchangeAdapter(
        exchange="bybit", fill_price=Decimal("100"), book=book,
        fee_rate=Decimal("0"),
    )
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
        exchange="bybit", fill_price=Decimal("100"), fill_latency_polls=3, fee_rate=Decimal("0")
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
        exchange="bybit",
        fill_price=Decimal("100"),
        book=book,
        fill_latency_polls=3,
        fee_rate=Decimal("0"),
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
    adapter = FakeExchangeAdapter(
        exchange="bybit", fill_price=Decimal("100"),
        fee_rate=Decimal("0"),
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

    fills = await adapter.fetch_fills("c1", "ETHUSDT.P")

    assert len(fills) == 1
    assert adapter.is_revealed("c1") is True


async def test_no_book_configured_leaves_fetch_fills_unaffected() -> None:
    """The default (``book=None``) preserves every pre-S4 caller's
    behaviour exactly -- nothing about ``fetch_fills`` needs a book to run."""
    adapter = FakeExchangeAdapter(
        exchange="bybit", fill_price=Decimal("100"),
        fee_rate=Decimal("0"),
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

    fills = await adapter.fetch_fills("c1", "ETHUSDT.P")

    assert len(fills) == 1


async def test_fake_fill_ids_use_the_named_rehearsal_prefix_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Performance reads exclude rehearsal fills by ``REHEARSAL_FILL_ID_PREFIX``
    (design.md § 12). The exclusion only works if the fake mints its ids with
    that SAME constant, so this patches the constant the adapter uses and
    watches the minted id follow it: a second, literal ``"fake-fill-"`` in
    the adapter would ignore the patch and leave the exclusion pointing at
    ids nobody mints any more.
    """
    from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
    from strategy_manager.execution.infrastructure import fake_exchange

    async def mint() -> str:
        adapter = FakeExchangeAdapter(
            exchange="bybit", fill_price=Decimal("100"),
            fee_rate=Decimal("0"),
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
        return (await adapter.fetch_fills("c1", "ETHUSDT.P"))[0].exchange_fill_id

    # The value is a data contract: rows already in the ledger carry it.
    assert REHEARSAL_FILL_ID_PREFIX == "fake-fill-"
    assert (await mint()).startswith(REHEARSAL_FILL_ID_PREFIX)

    monkeypatch.setattr(fake_exchange, "REHEARSAL_FILL_ID_PREFIX", "rehearsal-probe-")

    assert (await mint()).startswith("rehearsal-probe-")


async def test_fake_order_ids_use_the_named_rehearsal_prefix_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mode guard (decision 28) tells a rehearsal order still waiting to
    settle from a live one by ``REHEARSAL_ORDER_ID_PREFIX``. It only works if
    the fake mints its order ids with that SAME constant, so this patches the
    constant the adapter uses and watches the minted id follow it."""
    from strategy_manager.execution.domain.fill import REHEARSAL_ORDER_ID_PREFIX
    from strategy_manager.execution.infrastructure import fake_exchange

    async def mint() -> str:
        adapter = FakeExchangeAdapter(
            exchange="bybit", fill_price=Decimal("100"),
            fee_rate=Decimal("0"),
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
        return (await adapter.place(order)).exchange_order_id

    # The value is a data contract: attempts already written carry it.
    assert REHEARSAL_ORDER_ID_PREFIX == "fake-order-"
    assert (await mint()).startswith(REHEARSAL_ORDER_ID_PREFIX)

    monkeypatch.setattr(fake_exchange, "REHEARSAL_ORDER_ID_PREFIX", "rehearsal-probe-")

    assert (await mint()).startswith("rehearsal-probe-")


# ---- decision 45: a fill is priced at the price of its alert ------------------
#
# Spec: trade-execution § "A Simulated Fill Is Priced At The Alert's Stored
# Price". ``fill_price=None`` (the default) is the alert-price mode; an explicit
# ``Decimal`` is the fixed mode every test that pins a price uses.

STX_SPOT = "STXUSDT"
STX_PERP = "STXUSDT.P"
ZERO_RATE = Decimal("0")


def _stx_adapter(
    *, exchange: str = "bybit", fill_price: Decimal | None = None, fee_rate: Decimal = ZERO_RATE
) -> FakeExchangeAdapter:
    return FakeExchangeAdapter(exchange=exchange, fill_price=fill_price, fee_rate=fee_rate)


async def _fill_of(adapter: FakeExchangeAdapter, order: PlaceableOrder, symbol: str) -> Fill:
    await adapter.place(order)
    [fill] = await adapter.fetch_fills(order.client_order_id, symbol)
    return fill


async def _open_and_fill(
    adapter: FakeExchangeAdapter,
    *,
    symbol: str,
    side: OrderSide,
    price: Decimal,
    granted: Decimal = Decimal("564"),
    client_order_id: str = "open-1",
) -> Fill:
    order = await adapter.build_open_order(
        OpenOrderSpec(
            side=side,
            client_order_id=client_order_id,
            symbol=symbol,
            granted=granted,
            price=price,
        )
    )
    return await _fill_of(adapter, order, symbol)


async def _close_and_fill(
    adapter: FakeExchangeAdapter,
    *,
    symbol: str,
    side: OrderSide,
    base_size: Decimal,
    reference_price: Decimal | None,
    client_order_id: str = "close-1",
) -> Fill:
    order = await adapter.build_close_order(
        CloseOrderSpec(
            side=side,
            client_order_id=client_order_id,
            symbol=symbol,
            base_size=base_size,
            reference_price=reference_price,
        )
    )
    return await _fill_of(adapter, order, symbol)


EIGHTEEN_PLACES = Decimal("0.123456789012345678")


@pytest.mark.parametrize(
    "kind",
    [
        "spot buy that opens",
        "spot sell that opens",
        "futures open long",
        "futures open short",
        "spot sell that closes",
        "futures reduce-only close",
    ],
)
async def test_every_kind_of_order_fills_at_its_alert_price_to_the_last_place(kind: str) -> None:
    adapter = _stx_adapter()
    if kind == "spot buy that opens":
        fill = await _open_and_fill(
            adapter, symbol=STX_SPOT, side=OrderSide.BUY, price=EIGHTEEN_PLACES
        )
    elif kind == "spot sell that opens":
        fill = await _open_and_fill(
            adapter, symbol=STX_SPOT, side=OrderSide.SELL, price=EIGHTEEN_PLACES
        )
    elif kind == "futures open long":
        fill = await _open_and_fill(
            adapter, symbol=STX_PERP, side=OrderSide.BUY, price=EIGHTEEN_PLACES
        )
    elif kind == "futures open short":
        fill = await _open_and_fill(
            adapter, symbol=STX_PERP, side=OrderSide.SELL, price=EIGHTEEN_PLACES
        )
    elif kind == "spot sell that closes":
        fill = await _close_and_fill(
            adapter,
            symbol=STX_SPOT,
            side=OrderSide.SELL,
            base_size=Decimal("100"),
            reference_price=EIGHTEEN_PLACES,
        )
    else:
        fill = await _close_and_fill(
            adapter,
            symbol=STX_PERP,
            side=OrderSide.SELL,
            base_size=Decimal("100"),
            reference_price=EIGHTEEN_PLACES,
        )

    assert fill.price == Decimal("0.123456789012345678")
    assert str(fill.price) == "0.123456789012345678"


async def test_a_19_decimal_price_is_filled_as_given_and_never_rounded_by_the_adapter() -> None:
    """The rounding to 18 places belongs to the database column, once, at
    ingress: the adapter fills whatever it was handed."""
    nineteen = Decimal("0.1234567890123456789")
    adapter = _stx_adapter()

    fill = await _open_and_fill(adapter, symbol=STX_PERP, side=OrderSide.BUY, price=nineteen)

    assert fill.price == nineteen
    assert str(fill.price) == "0.1234567890123456789"


async def test_a_binance_exchange_fills_at_the_alert_price() -> None:
    adapter = _stx_adapter(exchange="binance")

    fill = await _open_and_fill(
        adapter, symbol=STX_PERP, side=OrderSide.BUY, price=Decimal("0.4512")
    )

    assert fill.price == Decimal("0.4512")


async def test_a_close_is_priced_at_the_closing_alert_not_the_opening_one() -> None:
    adapter = _stx_adapter()
    opened = await _open_and_fill(
        adapter, symbol=STX_PERP, side=OrderSide.BUY, price=Decimal("0.4512")
    )

    closed = await _close_and_fill(
        adapter,
        symbol=STX_PERP,
        side=OrderSide.SELL,
        base_size=opened.quantity,
        reference_price=Decimal("0.4633"),
    )

    assert opened.price == Decimal("0.4512")
    assert closed.price == Decimal("0.4633")


async def test_two_orders_built_before_either_is_placed_each_fill_at_their_own_price() -> None:
    adapter = _stx_adapter()
    order_x = await adapter.build_open_order(
        OpenOrderSpec(
            side=OrderSide.BUY,
            client_order_id="x",
            symbol=STX_PERP,
            granted=Decimal("564"),
            price=Decimal("0.4512"),
        )
    )
    order_y = await adapter.build_open_order(
        OpenOrderSpec(
            side=OrderSide.BUY,
            client_order_id="y",
            symbol=STX_PERP,
            granted=Decimal("564"),
            price=Decimal("0.4633"),
        )
    )

    fill_y = await _fill_of(adapter, order_y, STX_PERP)
    fill_x = await _fill_of(adapter, order_x, STX_PERP)

    assert fill_y.price == Decimal("0.4633")
    assert fill_x.price == Decimal("0.4512")


async def test_an_alert_priced_exactly_one_is_filled_at_one_and_the_later_close_is_not() -> None:
    adapter = _stx_adapter()
    opened = await _open_and_fill(
        adapter, symbol=STX_PERP, side=OrderSide.BUY, price=Decimal("1")
    )

    closed = await _close_and_fill(
        adapter,
        symbol=STX_PERP,
        side=OrderSide.SELL,
        base_size=opened.quantity,
        reference_price=Decimal("0.4633"),
    )

    assert opened.price == Decimal("1")
    assert closed.price == Decimal("0.4633")


async def test_a_futures_open_is_sized_so_that_its_notional_equals_the_capital_granted() -> None:
    adapter = _stx_adapter()

    fill = await _open_and_fill(
        adapter,
        symbol=STX_PERP,
        side=OrderSide.BUY,
        price=Decimal("0.4512"),
        granted=Decimal("564"),
    )

    assert fill.quantity == Decimal("1250")
    assert fill.quantity * fill.price == Decimal("564")


async def test_a_spot_buy_fills_the_granted_amount_over_the_alert_price() -> None:
    adapter = _stx_adapter()

    fill = await _open_and_fill(
        adapter,
        symbol=STX_SPOT,
        side=OrderSide.BUY,
        price=Decimal("0.4"),
        granted=Decimal("100"),
    )

    assert fill.quantity == Decimal("250")
    assert fill.quantity * fill.price == Decimal("100")


async def test_a_dry_run_sizes_at_leverage_one_and_the_gross_result_is_one_leverage_th() -> None:
    """Owner answer to decision 45's second question: a dry run keeps sizing at
    1x. Alerts at 0.4512 then 0.4633 on 1250 STXUSDT earn 15.125 gross, never
    the 45.375 that 3x would. The adapter holds no client, so it cannot read
    a venue's leverage."""
    adapter = _stx_adapter()

    opened = await _open_and_fill(
        adapter,
        symbol=STX_PERP,
        side=OrderSide.BUY,
        price=Decimal("0.4512"),
        granted=Decimal("564"),
    )
    closed = await _close_and_fill(
        adapter,
        symbol=STX_PERP,
        side=OrderSide.SELL,
        base_size=opened.quantity,
        reference_price=Decimal("0.4633"),
    )

    gross = closed.quantity * closed.price - opened.quantity * opened.price
    assert opened.quantity == Decimal("1250")
    assert gross == Decimal("15.125")
    assert gross != Decimal("45.375")
    assert FakeExchangeAdapter.FAKE_LEVERAGE == Decimal("1")
    assert not any(hasattr(adapter, name) for name in ("_client", "client", "leverage_for"))


async def test_the_default_is_the_alert_price_mode() -> None:
    assert _stx_adapter().fixed_fill_price is None


async def test_an_explicit_fill_price_is_the_fixed_mode_and_every_order_fills_at_it() -> None:
    """Today's behaviour, kept for every test that pins a price: the fixed
    price wins over whatever price an order carries or remembers."""
    adapter = _stx_adapter(fill_price=Decimal("100"))

    opened = await _open_and_fill(
        adapter, symbol=STX_PERP, side=OrderSide.BUY, price=Decimal("0.4512")
    )
    closed = await _close_and_fill(
        adapter,
        symbol=STX_PERP,
        side=OrderSide.SELL,
        base_size=opened.quantity,
        reference_price=Decimal("0.4633"),
    )

    assert adapter.fixed_fill_price == Decimal("100")
    assert opened.price == Decimal("100")
    assert closed.price == Decimal("100")
