"""Unit tests: ``FakeExchangeAdapter`` -- baseline place/fetch_fills
behaviour, plus its optional hook into ``FakeVenueBook`` (design.md § S4,
DRY_RUN paragraph: "updates only when ``FakeExchangeAdapter`` reveals a
fill").
"""

from decimal import Decimal, InvalidOperation

import pytest

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
    OrderNotFound,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.futures_order import close_futures_order
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook
from strategy_manager.shared.domain.errors import InvariantViolation


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


# ---- an order with no usable price is refused, never defaulted (design § F) ----
#
# A price is usable when it is finite and above zero. ``place`` refuses a close
# whose reference price is not, and an order this adapter did not build.
# Nothing is ever substituted: not 1, not the entry price, not the last price.

UNUSABLE_CLOSE_PRICES = [
    pytest.param(None, id="absent"),
    pytest.param(Decimal("0"), id="zero"),
    pytest.param(Decimal("-0.4633"), id="negative"),
    pytest.param(Decimal("NaN"), id="nan"),
    pytest.param(Decimal("Infinity"), id="infinite"),
    pytest.param(Decimal("-Infinity"), id="negative-infinite"),
]


async def _place_capturing(
    adapter: FakeExchangeAdapter, order: PlaceableOrder
) -> BaseException | None:
    """The exception ``place`` raised, or ``None``: the test asserts on its TYPE,
    so an adapter that does not refuse fails on an assertion, not on an
    unrelated error."""
    try:
        await adapter.place(order)
    except Exception as exc:  # noqa: BLE001 - the type is exactly what is asserted
        return exc
    return None


async def _unpriceable_close(
    adapter: FakeExchangeAdapter, reference_price: Decimal | None, client_order_id: str = "close-1"
) -> PlaceableOrder:
    return await adapter.build_close_order(
        CloseOrderSpec(
            side=OrderSide.SELL,
            client_order_id=client_order_id,
            symbol=STX_PERP,
            base_size=Decimal("1250"),
            reference_price=reference_price,
        )
    )


@pytest.mark.parametrize("reference_price", UNUSABLE_CLOSE_PRICES)
async def test_a_close_whose_reference_price_is_unusable_is_refused_in_place_and_no_fill_exists(
    reference_price: Decimal | None,
) -> None:
    book = FakeVenueBook(FakeLedgerReader())
    adapter = FakeExchangeAdapter(
        exchange="bybit", book=book, fee_rate=Decimal("0"), fill_latency_polls=0
    )
    order = await _unpriceable_close(adapter, reference_price)

    raised = await _place_capturing(adapter, order)

    assert type(raised) is ExchangeError
    with pytest.raises(OrderNotFound):
        await adapter.fetch_fills("close-1", STX_PERP)
    assert await book.open_positions(("bybit", "usdt-m", "USDT")) == []


@pytest.mark.parametrize(
    ("reference_price", "named"),
    [
        pytest.param(None, "None", id="absent"),
        pytest.param(Decimal("0"), "0", id="zero"),
        pytest.param(Decimal("-0.4633"), "-0.4633", id="negative"),
        pytest.param(Decimal("NaN"), "NaN", id="nan"),
        pytest.param(Decimal("Infinity"), "Infinity", id="infinite"),
        pytest.param(Decimal("-Infinity"), "-Infinity", id="negative-infinite"),
    ],
)
async def test_the_message_names_the_value_and_says_the_alert_carried_no_usable_price(
    reference_price: Decimal | None, named: str
) -> None:
    adapter = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    order = await _unpriceable_close(adapter, reference_price)

    raised = await _place_capturing(adapter, order)

    assert type(raised) is ExchangeError
    message = str(raised)
    assert "the simulated exchange cannot price this order" in message
    assert "its alert carried no usable price" in message
    assert f"reference price: {named}" in message


async def test_an_order_the_exchange_did_not_build_is_refused() -> None:
    """A futures order made by hand: no price was ever remembered for its
    client order id, so there is nothing to fill it at."""
    adapter = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    made_by_hand = close_futures_order(
        side=OrderSide.SELL,
        client_order_id="by-hand",
        symbol=STX_PERP,
        base_size=Decimal("1250"),
    )

    raised = await _place_capturing(adapter, made_by_hand)

    assert type(raised) is ExchangeError
    assert "the simulated exchange cannot price this order" in str(raised)
    with pytest.raises(OrderNotFound):
        await adapter.fetch_fills("by-hand", STX_PERP)


async def test_a_positive_absurd_price_is_filled_at() -> None:
    """A price no market trades near is still the price the alert carried,
    which is what decision 45 asks the fill to be."""
    adapter = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    order = await _unpriceable_close(adapter, Decimal("9999999.5"))

    await adapter.place(order)
    [fill] = await adapter.fetch_fills("close-1", STX_PERP)

    assert fill.price == Decimal("9999999.5")


@pytest.mark.parametrize("fixed_fill_price", [None, Decimal("5")], ids=["alert-mode", "fixed-mode"])
@pytest.mark.parametrize("symbol", [STX_PERP, STX_SPOT], ids=["futures", "spot"])
@pytest.mark.parametrize(
    ("price", "refusal"),
    [
        pytest.param(Decimal("0"), InvariantViolation, id="zero"),
        pytest.param(Decimal("-1"), InvariantViolation, id="negative"),
        # Observed 2026-10-04 (9q.11): a NaN price does not reach the domain's own
        # check -- the ``decimal`` module raises its comparison error first.
        pytest.param(Decimal("NaN"), InvalidOperation, id="nan"),
    ],
)
async def test_an_opening_order_with_a_non_positive_price_never_reaches_a_fill_in_either_mode(
    fixed_fill_price: Decimal | None,
    symbol: str,
    price: Decimal,
    refusal: type[Exception],
) -> None:
    """Today's behaviour, unchanged (design P8): the domain refuses to size the
    order at BUILD, before any fill can exist, and no price is substituted. The
    open is retried by its job until the attempts run out; that is carried, not
    decided, here."""
    adapter = FakeExchangeAdapter(
        exchange="bybit", fill_price=fixed_fill_price, fee_rate=Decimal("0")
    )
    raised: BaseException | None = None
    try:
        await adapter.build_open_order(
            OpenOrderSpec(
                side=OrderSide.BUY,
                client_order_id="open-1",
                symbol=symbol,
                granted=Decimal("564"),
                price=price,
            )
        )
    except Exception as exc:  # noqa: BLE001 - the type is exactly what is asserted
        raised = exc

    assert type(raised) is refusal
    with pytest.raises(OrderNotFound):
        await adapter.fetch_fills("open-1", symbol)


# ---- the fee: the venue's taker rate on the notional, in USDT (design § E) -----
#
# fee = quantity x price x rate, taken inside a 60-digit context and quantised
# to 18 places half-even (the scale of ``ledger_entries.fee``), on both sides.

BYBIT_RATE = Decimal("0.00055")
BINANCE_RATE = Decimal("0.0005")


async def _round_trip(
    adapter: FakeExchangeAdapter,
    *,
    open_price: Decimal = Decimal("0.4512"),
    close_price: Decimal = Decimal("0.4633"),
) -> tuple[Fill, Fill]:
    opened = await _open_and_fill(
        adapter,
        symbol=STX_PERP,
        side=OrderSide.BUY,
        price=open_price,
        granted=Decimal("564"),
    )
    closed = await _close_and_fill(
        adapter,
        symbol=STX_PERP,
        side=OrderSide.SELL,
        base_size=opened.quantity,
        reference_price=close_price,
    )
    return opened, closed


async def _fee_of_a_close(
    rate: Decimal, *, quantity: Decimal, price: Decimal, symbol: str = STX_PERP
) -> Fill:
    return await _close_and_fill(
        _stx_adapter(fee_rate=rate),
        symbol=symbol,
        side=OrderSide.SELL,
        base_size=quantity,
        reference_price=price,
    )


async def test_a_bybit_round_trip_is_charged_0_00055_on_both_sides_in_usdt() -> None:
    opened, closed = await _round_trip(_stx_adapter(fee_rate=BYBIT_RATE))

    assert opened.quantity == Decimal("1250")
    assert opened.quantity * opened.price == Decimal("564")
    assert opened.fee == Decimal("0.3102")
    assert closed.quantity * closed.price == Decimal("579.125")
    assert closed.fee == Decimal("0.31851875")
    assert opened.fee_currency == "USDT"
    assert closed.fee_currency == "USDT"
    # The fee is in USDT, never in the base coin: the holding is untouched and
    # the close, sized from the ledger, nets the open to zero.
    assert closed.quantity == opened.quantity == Decimal("1250")


async def test_a_binance_round_trip_is_charged_0_0005_on_both_sides() -> None:
    opened, closed = await _round_trip(_stx_adapter(exchange="binance", fee_rate=BINANCE_RATE))

    assert opened.fee == Decimal("0.282")
    assert closed.fee == Decimal("0.2895625")
    assert opened.fee_currency == closed.fee_currency == "USDT"
    assert closed.quantity == opened.quantity


async def test_the_fee_is_on_the_notional_and_not_on_the_quantity() -> None:
    fill = await _fee_of_a_close(BYBIT_RATE, quantity=Decimal("1250"), price=Decimal("0.4512"))

    assert fill.fee == Decimal("0.3102")
    assert fill.fee != fill.quantity * BYBIT_RATE  # 0.6875, the quantity alone


async def test_the_fee_is_quantised_to_18_places_half_even() -> None:
    """The unrounded product of 10 x 0.123456789012345678 x 0.00055 is
    0.000679012339567901229."""
    fill = await _fee_of_a_close(
        BYBIT_RATE, quantity=Decimal("10"), price=Decimal("0.123456789012345678")
    )

    assert fill.fee == Decimal("0.000679012339567901")
    assert fill.fee.as_tuple().exponent == -18


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        # 1.5e-18: the tie rounds to the EVEN neighbour, 2e-18.
        (Decimal("0.000000000000003"), Decimal("0.000000000000000002")),
        # 2.5e-18: the tie rounds to the EVEN neighbour, 2e-18 (not 3e-18).
        (Decimal("0.000000000000005"), Decimal("0.000000000000000002")),
    ],
)
async def test_a_tie_rounds_to_the_even_digit(quantity: Decimal, expected: Decimal) -> None:
    fill = await _fee_of_a_close(BINANCE_RATE, quantity=quantity, price=Decimal("1"))

    # 3e-15 x 1 x 0.0005 = 1.5e-18 and 5e-15 x 1 x 0.0005 = 2.5e-18: the products
    # ARE the ties.
    assert fill.fee == expected


async def test_a_product_of_more_than_28_significant_digits_is_rounded_once_and_not_twice() -> None:
    """Chosen so that the two orders of rounding disagree. Rate 0.5, quantity 1,
    price 2.99999999999999999999999999998e-18: the exact product is
    1.49999999999999999999999999999e-18 (30 significant digits).

    Rounded ONCE to 18 places it is 1e-18. Rounded first to 28 significant
    digits it becomes 1.5e-18, and the tie then goes to the even 2e-18."""
    fill = await _fee_of_a_close(
        Decimal("0.5"),
        quantity=Decimal("1"),
        price=Decimal("2.99999999999999999999999999998e-18"),
    )

    assert fill.fee == Decimal("0.000000000000000001")


async def test_a_fee_below_half_the_last_place_quantises_to_zero() -> None:
    fill = await _fee_of_a_close(
        BYBIT_RATE, quantity=Decimal("1"), price=Decimal("0.0000000000000004")
    )

    # 1 x 4e-16 x 0.00055 = 2.2e-19, below 0.5e-18.
    assert fill.fee == Decimal("0")
    assert fill.fee_currency == "USDT"


async def test_a_spot_shaped_buy_is_charged_the_same_rate() -> None:
    """No spot pool exists on either exchange; a symbol with no contract marker
    builds a spot order here and is charged the same taker rate (design § M)."""
    adapter = _stx_adapter(fee_rate=BYBIT_RATE)

    fill = await _open_and_fill(
        adapter,
        symbol=STX_SPOT,
        side=OrderSide.BUY,
        price=Decimal("0.4"),
        granted=Decimal("100"),
    )

    assert fill.quantity == Decimal("250")
    assert fill.fee == Decimal("0.055")


@pytest.mark.parametrize("rate", [Decimal("-0.00055"), Decimal("1"), Decimal("1.5")])
def test_a_rate_below_zero_or_of_one_or_more_is_refused_at_construction(rate: Decimal) -> None:
    """The design says "refused" and names no exception type; the project's own
    precondition error is chosen (recorded for review)."""
    raised: BaseException | None = None
    try:
        FakeExchangeAdapter(exchange="bybit", fee_rate=rate)
    except Exception as exc:  # noqa: BLE001 - the type is exactly what is asserted
        raised = exc

    assert type(raised) is InvariantViolation


@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("0.9999999")])
def test_a_rate_of_zero_and_one_just_below_one_are_accepted(rate: Decimal) -> None:
    adapter = FakeExchangeAdapter(exchange="bybit", fee_rate=rate)

    assert adapter.exchange == "bybit"


async def test_a_zero_rate_charges_nothing() -> None:
    opened, closed = await _round_trip(_stx_adapter(fee_rate=Decimal("0")))

    assert opened.fee == Decimal("0")
    assert closed.fee == Decimal("0")
    assert opened.fee_currency == closed.fee_currency == "USDT"


# ---- a market not quoted in USDT is refused, not charged (design § E) ----------
#
# The fee is charged in USDT and only the two USDT-M rates are verified (rule 7:
# a fee is never converted). The adapter is handed a symbol and never the pool,
# so what it can check is the market.


@pytest.mark.parametrize("symbol", ["ETHBTC", "BTCUSD"])
async def test_a_market_not_quoted_in_usdt_is_refused_in_place(symbol: str) -> None:
    adapter = _stx_adapter(fee_rate=BYBIT_RATE)
    order = await adapter.build_open_order(
        OpenOrderSpec(
            side=OrderSide.BUY,
            client_order_id="open-1",
            symbol=symbol,
            granted=Decimal("564"),
            price=Decimal("0.4512"),
        )
    )

    raised = await _place_capturing(adapter, order)

    assert type(raised) is ExchangeError
    message = str(raised)
    assert "charges its fee in USDT" in message
    assert "not quoted in it" in message
    assert symbol in message
    with pytest.raises(OrderNotFound):
        await adapter.fetch_fills("open-1", symbol)


@pytest.mark.parametrize("symbol", ["STXUSDT", "STXUSDT.P", "STX_USDT", "STX_USDT_PERP"])
async def test_each_usdt_spelling_is_filled_and_charged(symbol: str) -> None:
    adapter = _stx_adapter(fee_rate=BYBIT_RATE)

    fill = await _open_and_fill(
        adapter, symbol=symbol, side=OrderSide.BUY, price=Decimal("0.4512")
    )

    assert fill.price == Decimal("0.4512")
    assert fill.fee == (fill.quantity * Decimal("0.4512") * BYBIT_RATE).quantize(Decimal("1e-18"))
    assert fill.fee > 0
    assert fill.fee_currency == "USDT"


async def test_a_refused_order_leaves_nothing_remembered() -> None:
    adapter = _stx_adapter(fee_rate=BYBIT_RATE)
    order = await adapter.build_open_order(
        OpenOrderSpec(
            side=OrderSide.BUY,
            client_order_id="open-1",
            symbol="ETHBTC",
            granted=Decimal("564"),
            price=Decimal("0.4512"),
        )
    )

    raised = await _place_capturing(adapter, order)

    assert type(raised) is ExchangeError
    assert adapter._reference_prices == {}
