"""``PionexExchangeAdapter`` — the translation layer, and the one distinction
in it that can lose a position.

``PlaceOrder`` treats ``ExchangeError`` as final: it releases the reservation
and marks the attempt terminal, after which the already-scheduled settlement
job returns ALREADY_SETTLED without asking the exchange anything. Correct for
a rejection. Catastrophic for a timeout — the order may be live, and this
system would have closed the only door left to finding out.

So the tests below are less about mapping fields than about which failures are
allowed through that door.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strategy_manager.execution.application.ports import ExchangeError, OrderNotFound
from strategy_manager.execution.domain.order import MarketBuy, MarketSell
from strategy_manager.execution.infrastructure.pionex_exchange import (
    PionexExchangeAdapter,
)
from strategy_manager.shared.infrastructure.pionex.errors import (
    PionexApiError,
    PionexOrderNotFound,
)
from strategy_manager.shared.infrastructure.pionex.fills import PionexFill
from strategy_manager.shared.infrastructure.pionex.trade_client import (
    PionexOrderAck,
)

CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


class FakeTradeClient:
    """Stands in for ``PionexTradeClient``, recording which method was called
    with what — the point being that a buy can only ever reach the buy
    method."""

    def __init__(
        self,
        *,
        place_raises: Exception | None = None,
        lookup_raises: Exception | None = None,
        fills: list[PionexFill] | None = None,
    ) -> None:
        self.buys: list[dict[str, object]] = []
        self.sells: list[dict[str, object]] = []
        self._place_raises = place_raises
        self._lookup_raises = lookup_raises
        self._fills = fills or []

    async def place_market_buy(
        self, *, symbol: str, client_order_id: str, quote_amount: Decimal
    ) -> PionexOrderAck:
        if self._place_raises is not None:
            raise self._place_raises
        self.buys.append({"symbol": symbol, "quote_amount": quote_amount})
        return PionexOrderAck(order_id="EX-1", client_order_id=client_order_id)

    async def place_market_sell(
        self, *, symbol: str, client_order_id: str, base_size: Decimal
    ) -> PionexOrderAck:
        if self._place_raises is not None:
            raise self._place_raises
        self.sells.append({"symbol": symbol, "base_size": base_size})
        return PionexOrderAck(order_id="EX-1", client_order_id=client_order_id)

    async def order_id_for(self, client_order_id: str) -> str:
        if self._lookup_raises is not None:
            raise self._lookup_raises
        return "EX-1"

    async def fills_for_order(self, order_id: str) -> list[PionexFill]:
        return self._fills


def _adapter(client: FakeTradeClient) -> PionexExchangeAdapter:
    return PionexExchangeAdapter(client)  # type: ignore[arg-type]


def test_the_adapter_is_live() -> None:
    """This flag is the whole reason ``DRY_RUN=false`` can start at all
    (CLAUDE.md rule 1)."""
    assert PionexExchangeAdapter.is_live is True


async def test_a_buy_reaches_the_buy_endpoint_carrying_the_quote_amount() -> None:
    client = FakeTradeClient()

    placed = await _adapter(client).place(
        MarketBuy(
            client_order_id=CLIENT_ORDER_ID,
            symbol="BTC_USDT",
            quote_amount=Decimal("100"),
        )
    )

    assert client.buys == [{"symbol": "BTC_USDT", "quote_amount": Decimal("100")}]
    assert client.sells == []
    assert placed.exchange_order_id == "EX-1"
    assert placed.client_order_id == CLIENT_ORDER_ID


async def test_a_sell_reaches_the_sell_endpoint_carrying_the_base_size() -> None:
    client = FakeTradeClient()

    await _adapter(client).place(
        MarketSell(
            client_order_id=CLIENT_ORDER_ID,
            symbol="BTC_USDT",
            base_size=Decimal("0.004"),
        )
    )

    assert client.sells == [{"symbol": "BTC_USDT", "base_size": Decimal("0.004")}]
    assert client.buys == []


async def test_a_rejection_pionex_actually_decided_becomes_an_exchange_error() -> None:
    """A ``result: false`` envelope carries a code: Pionex parsed the order and
    refused it. Releasing the reservation now is right — there is nothing out
    there to reconcile."""
    client = FakeTradeClient(
        place_raises=PionexApiError("insufficient balance", code="TRADE_BALANCE")
    )

    with pytest.raises(ExchangeError, match="insufficient balance"):
        await _adapter(client).place(
            MarketBuy(
                client_order_id=CLIENT_ORDER_ID,
                symbol="BTC_USDT",
                quote_amount=Decimal("100"),
            )
        )


async def test_a_4xx_is_a_decision_too() -> None:
    client = FakeTradeClient(
        place_raises=PionexApiError("bad request", http_status=400)
    )

    with pytest.raises(ExchangeError):
        await _adapter(client).place(
            MarketBuy(
                client_order_id=CLIENT_ORDER_ID,
                symbol="BTC_USDT",
                quote_amount=Decimal("100"),
            )
        )


@pytest.mark.parametrize(
    ("label", "error"),
    [
        ("a transport failure", PionexApiError("connection reset")),
        ("a server error", PionexApiError("gateway", http_status=502)),
        ("a reported timeout", PionexApiError("timeout", http_status=408)),
        ("throttling", PionexApiError("slow down", http_status=429)),
    ],
)
async def test_an_ambiguous_failure_is_never_reported_as_a_rejection(
    label: str, error: PionexApiError
) -> None:
    """THE test. None of these says whether the order reached Pionex. Raising
    ``ExchangeError`` here would release the capital backing a position that
    may well be open, and mark the attempt terminal so settlement never looks.

    Letting the original error through means the job fails and retries, and
    the settle job enqueued before the network call resolves the truth by
    client order id. The UNIQUE constraint on
    ``execution_attempts.reservation_id`` is what stops the retry from placing
    a second order.
    """
    client = FakeTradeClient(place_raises=error)

    with pytest.raises(PionexApiError) as caught:
        await _adapter(client).place(
            MarketBuy(
                client_order_id=CLIENT_ORDER_ID,
                symbol="BTC_USDT",
                quote_amount=Decimal("100"),
            )
        )

    assert not isinstance(caught.value, ExchangeError), label


async def test_a_missing_order_becomes_order_not_found() -> None:
    client = FakeTradeClient(lookup_raises=PionexOrderNotFound("no such order"))

    with pytest.raises(OrderNotFound):
        await _adapter(client).fetch_fills(CLIENT_ORDER_ID, "BTC_USDT")


async def test_a_failed_lookup_does_not_become_order_not_found() -> None:
    """``SettleExecution`` reads ``OrderNotFound`` as "the order never existed,
    release the capital". A failed lookup is not evidence of that."""
    client = FakeTradeClient(lookup_raises=PionexApiError("boom", http_status=503))

    with pytest.raises(PionexApiError) as caught:
        await _adapter(client).fetch_fills(CLIENT_ORDER_ID, "BTC_USDT")

    assert not isinstance(caught.value, OrderNotFound)


async def test_a_fill_maps_onto_the_ledgers_own_shape() -> None:
    client = FakeTradeClient(
        fills=[
            PionexFill(
                fill_id="F-1",
                order_id="EX-1",
                symbol="BTC_USDT",
                side="BUY",
                price=Decimal("50010.12345678"),
                size=Decimal("0.00199960"),
                fee=Decimal("0.05001012"),
                fee_coin="USDT",
                timestamp_ms=1787313600123,
            )
        ]
    )

    fills = await _adapter(client).fetch_fills(CLIENT_ORDER_ID, "BTC_USDT")

    assert fills[0].exchange_order_id == "EX-1"
    assert fills[0].exchange_fill_id == "F-1"
    assert fills[0].quantity == Decimal("0.00199960")
    assert fills[0].price == Decimal("50010.12345678")
    assert fills[0].fee_currency == "USDT"
    assert fills[0].filled_at == datetime(2026, 8, 21, 12, 0, 0, 123000, tzinfo=UTC)


async def test_the_fill_timestamp_keeps_its_milliseconds() -> None:
    """No float division stands between the exchange's timestamp and a ledger
    row that can never be corrected."""
    client = FakeTradeClient(
        fills=[
            PionexFill(
                fill_id="F-1",
                order_id="EX-1",
                symbol="BTC_USDT",
                side="BUY",
                price=Decimal("1"),
                size=Decimal("1"),
                fee=Decimal("0"),
                fee_coin="USDT",
                timestamp_ms=1787313600999,
            )
        ]
    )

    fills = await _adapter(client).fetch_fills(CLIENT_ORDER_ID, "BTC_USDT")

    assert fills[0].filled_at.microsecond == 999000
    assert fills[0].filled_at.tzinfo is UTC


async def test_pionexs_real_permission_refusal_is_definitive() -> None:
    """Captured live on 2026-08-24 placing a real order with a read-only key:
    HTTP 200, ``result: false``, ``code: AUTH_UNAVAILABLE``, message
    "have no right".

    Classifying it as definitive was then verified the only way that counts —
    looking the client order id up afterwards. Pionex had no order under it and
    the balance was unchanged to the last of its 26 decimals. So releasing the
    reservation is right: the capital is genuinely free.

    Note this arrives as HTTP 200. Keying the decision on the status line
    instead of the envelope's code would have read a definitive refusal as an
    ambiguous one and left the reservation held.
    """
    client = FakeTradeClient(
        place_raises=PionexApiError("have no right", code="AUTH_UNAVAILABLE")
    )

    with pytest.raises(ExchangeError, match="have no right"):
        await _adapter(client).place(
            MarketBuy(
                client_order_id=CLIENT_ORDER_ID,
                symbol="ETH_USDT",
                quote_amount=Decimal("10"),
            )
        )
