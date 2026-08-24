"""``PionexTradeClient`` — order submission and the two-hop fill lookup.

The first test in here is the one that would have cost a live debugging
session. POST signing had never been exercised: the signature is computed over
the JSON body, so if the client hands ``httpx`` a dict and lets it
re-serialize, one space of difference makes every order fail authentication
with an error that says nothing about whitespace.
"""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.pionex.errors import (
    PionexApiError,
    PionexOrderNotFound,
)
from strategy_manager.shared.infrastructure.pionex.signer import (
    KEY_HEADER,
    SIGNATURE_HEADER,
    PionexSigner,
)
from strategy_manager.shared.infrastructure.pionex.symbols import SYMBOLS_PATH
from strategy_manager.shared.infrastructure.pionex.trade_client import (
    FILLS_BY_ORDER_ID_PATH,
    NEW_ORDER_PATH,
    ORDER_BY_CLIENT_ORDER_ID_PATH,
    PionexTradeClient,
)

CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

ACK: dict[str, Any] = {
    "result": True,
    "timestamp": 1787313600000,
    "data": {"orderId": 1234567890, "clientOrderId": CLIENT_ORDER_ID},
}

FILLS: dict[str, Any] = {
    "result": True,
    "data": {
        "fills": [
            {
                "id": "F-1",
                "orderId": "1234567890",
                "symbol": "BTC_USDT",
                "side": "BUY",
                "role": "TAKER",
                "price": "50010.12345678",
                "size": "0.00199960",
                "fee": "0.05001012",
                "feeCoin": "USDT",
                "timestamp": 1787313600123,
            }
        ]
    },
}


# Verified against the live account on 2026-08-24. These four numbers decide
# whether an order is accepted at all, and both legs of a round trip violate
# them by default: balances carry more precision than orders may, and ledger
# fills carry more than the base currency allows.
SYMBOLS: dict[str, Any] = {
    "result": True,
    "data": {
        "symbols": [
            {
                "symbol": "BTC_USDT",
                "type": "SPOT",
                "baseCurrency": "BTC",
                "quoteCurrency": "USDT",
                "basePrecision": 6,
                "quotePrecision": 2,
                "amountPrecision": 8,
                "minTradeSize": "0.000001",
                "minAmount": "10",
            }
        ]
    },
}


def _client(
    signer: PionexSigner,
    responses: dict[str, httpx.Response],
    recorded: list[httpx.Request],
) -> PionexTradeClient:
    """The symbol catalog answers by default: every placing path consults it
    before it can know what precision the order may carry."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.url.path == SYMBOLS_PATH:
            return httpx.Response(200, json=SYMBOLS)
        return responses[request.url.path]

    http = httpx.AsyncClient(
        base_url="https://api.pionex.com",
        transport=httpx.MockTransport(handler),
    )
    return PionexTradeClient(http, signer)


@pytest.fixture
def recorded() -> list[httpx.Request]:
    return []


async def test_the_transmitted_body_is_byte_identical_to_the_signed_one(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """POST signing covers the body. If the client re-serializes the payload
    after signing it — which ``httpx``'s ``json=`` argument does, with a space
    after every separator — the signature no longer matches what was sent and
    every order is rejected as unauthenticated."""
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    await client.place_market_buy(
        symbol="BTC_USDT",
        client_order_id=CLIENT_ORDER_ID,
        quote_amount=Decimal("100"),
    )

    order = _order_request(recorded)
    sent = order.content.decode()
    signed = signer.sign("POST", NEW_ORDER_PATH, body=sent)

    assert " " not in sent
    assert order.headers[SIGNATURE_HEADER] == signed.headers[SIGNATURE_HEADER]
    assert order.headers[KEY_HEADER] == "test-key-abcd"


async def test_a_market_buy_sends_amount_and_never_size(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The conditional that makes this whole adapter shape necessary: Pionex
    denominates a market BUY in the quote currency."""
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    ack = await client.place_market_buy(
        symbol="BTC_USDT",
        client_order_id=CLIENT_ORDER_ID,
        quote_amount=Decimal("100"),
    )

    body = json.loads(_order_request(recorded).content)
    assert body == {
        "symbol": "BTC_USDT",
        "side": "BUY",
        "type": "MARKET",
        "clientOrderId": CLIENT_ORDER_ID,
        "amount": "100",
    }
    assert "size" not in body
    assert ack.order_id == "1234567890"


async def test_a_market_sell_sends_size_and_never_amount(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    await client.place_market_sell(
        symbol="BTC_USDT",
        client_order_id=CLIENT_ORDER_ID,
        base_size=Decimal("0.004"),
    )

    body = json.loads(_order_request(recorded).content)
    assert body["size"] == "0.004"
    assert "amount" not in body


async def test_a_size_is_sent_as_a_plain_decimal_not_scientific_notation(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """``str(Decimal("1E-6"))`` is ``'0.000001'``, but a size out of a division
    can normalise to an exponent form Pionex would reject."""
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    await client.place_market_sell(
        symbol="BTC_USDT",
        client_order_id=CLIENT_ORDER_ID,
        base_size=Decimal("1") / Decimal("1000000"),
    )

    size = json.loads(_order_request(recorded).content)["size"]
    assert size == "0.000001"
    assert "E" not in size.upper()


async def test_a_buy_amount_is_truncated_to_the_symbols_precision(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """A granted amount is a percentage of an exchange balance, and Pionex
    reports balances with far more precision than it accepts on an order. The
    live spot balance carried 26 decimals; ``amountPrecision`` is 8. Untouched,
    every buy would be refused."""
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    await client.place_market_buy(
        symbol="BTC_USDT",
        client_order_id=CLIENT_ORDER_ID,
        quote_amount=Decimal("90.105606580776785293876389408"),
    )

    assert json.loads(_order_request(recorded).content)["amount"] == "90.10560658"


async def test_rounding_is_always_down_on_both_legs(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """Up is never safe. A buy rounded up spends capital the allocation engine
    never granted. A sell rounded up asks for more of the base currency than
    the account holds, which is refused for insufficient balance — and leaves a
    position open while this system believes it closed."""
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    await client.place_market_buy(
        symbol="BTC_USDT",
        client_order_id=CLIENT_ORDER_ID,
        quote_amount=Decimal("10.999999999"),
    )
    assert json.loads(_order_request(recorded).content)["amount"] == "10.99999999"

    recorded.clear()
    await client.place_market_sell(
        symbol="BTC_USDT",
        client_order_id=CLIENT_ORDER_ID,
        base_size=Decimal("0.0039999999"),
    )
    assert json.loads(_order_request(recorded).content)["size"] == "0.003999"


async def test_an_order_below_the_symbols_minimum_never_leaves_the_process(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """Pionex would reject it anyway. Refusing locally names the actual number
    and the actual limit, instead of arriving as an opaque rejection code."""
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    with pytest.raises(PionexApiError, match="at least 10"):
        await client.place_market_buy(
            symbol="BTC_USDT",
            client_order_id=CLIENT_ORDER_ID,
            quote_amount=Decimal("1"),
        )

    with pytest.raises(PionexApiError, match="at least 0.000001"):
        await client.place_market_sell(
            symbol="BTC_USDT",
            client_order_id=CLIENT_ORDER_ID,
            base_size=Decimal("0.0000001"),
        )

    assert [r for r in recorded if r.url.path == NEW_ORDER_PATH] == []


async def test_an_unlisted_symbol_is_refused(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    with pytest.raises(PionexApiError, match="does not list"):
        await client.place_market_buy(
            symbol="DOGE_USDT",
            client_order_id=CLIENT_ORDER_ID,
            quote_amount=Decimal("100"),
        )


async def test_the_symbol_catalog_is_fetched_once_per_client(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """One extra GET on a job that is about to place an order is the right
    trade for numbers that decide whether it is accepted. Once is enough."""
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    for _ in range(3):
        await client.place_market_buy(
            symbol="BTC_USDT",
            client_order_id=CLIENT_ORDER_ID,
            quote_amount=Decimal("100"),
        )

    assert len([r for r in recorded if r.url.path == SYMBOLS_PATH]) == 1


async def test_an_echoed_client_order_id_that_does_not_match_is_refused(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The client order id is the only handle that makes an in-flight order
    recoverable. If Pionex names a different one, settlement would go looking
    for an order that does not exist under the id we recorded."""
    payload = {
        "result": True,
        "data": {"orderId": 1, "clientOrderId": "some-other-id"},
    }
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=payload)}, recorded)

    with pytest.raises(PionexApiError, match="cannot be tracked by our own id"):
        await client.place_market_buy(
            symbol="BTC_USDT",
            client_order_id=CLIENT_ORDER_ID,
            quote_amount=Decimal("100"),
        )


async def test_a_client_order_id_pionex_would_reject_never_leaves_the_process(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, {NEW_ORDER_PATH: httpx.Response(200, json=ACK)}, recorded)

    with pytest.raises(PionexApiError, match="letters, numbers and hyphens"):
        await client.place_market_buy(
            symbol="BTC_USDT",
            client_order_id="has spaces and_underscores",
            quote_amount=Decimal("100"),
        )

    assert [r for r in recorded if r.url.path == NEW_ORDER_PATH] == []


async def test_fills_are_reached_through_the_exchange_order_id(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """Two hops: our id resolves to Pionex's, and only Pionex's id reaches the
    fills."""
    order = {"result": True, "data": {"orderId": "1234567890", "status": "CLOSED"}}
    client = _client(
        signer,
        {
            ORDER_BY_CLIENT_ORDER_ID_PATH: httpx.Response(200, json=order),
            FILLS_BY_ORDER_ID_PATH: httpx.Response(200, json=FILLS),
        },
        recorded,
    )

    order_id = await client.order_id_for(CLIENT_ORDER_ID)
    fills = await client.fills_for_order(order_id)

    assert recorded[0].url.params["clientOrderId"] == CLIENT_ORDER_ID
    assert recorded[1].url.params["orderId"] == "1234567890"
    assert fills[0].price == Decimal("50010.12345678")
    assert fills[0].size == Decimal("0.00199960")
    assert fills[0].fee_coin == "USDT"
    assert fills[0].timestamp_ms == 1787313600123


async def test_a_successful_lookup_with_nothing_to_report_is_a_definitive_miss(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """Pionex answered. It looked, and there is no such order."""
    client = _client(
        signer,
        {ORDER_BY_CLIENT_ORDER_ID_PATH: httpx.Response(200, json={"result": True})},
        recorded,
    )

    with pytest.raises(PionexOrderNotFound):
        await client.order_id_for(CLIENT_ORDER_ID)


async def test_a_failed_lookup_is_never_read_as_a_missing_order(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """THE asymmetry. ``PionexOrderNotFound`` makes the caller release capital
    on the grounds that no order exists. A 500 is not evidence of that, and
    treating it as such would forget a live position."""
    client = _client(
        signer,
        {ORDER_BY_CLIENT_ORDER_ID_PATH: httpx.Response(500, text="boom")},
        recorded,
    )

    with pytest.raises(PionexApiError) as caught:
        await client.order_id_for(CLIENT_ORDER_ID)

    assert not isinstance(caught.value, PionexOrderNotFound)
    assert caught.value.http_status == 500


async def test_pionexs_real_not_found_envelope_is_read_as_a_missing_order(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """This exact payload was captured from the live account on 2026-08-21 by
    ``scripts/check_pionex_order_lookup.py``. It is reproduced verbatim
    because it is the ONLY signal that lets ``SettleExecution`` conclude an
    order was never placed and release the capital held for it.

    Note the shape: HTTP 200, ``result: false``, and the answer carried in the
    code. Nothing about the status line says anything went wrong.
    """
    payload = {
        "result": False,
        "code": "TRADE_ORDER_NOT_EXIST",
        "message": "order not found",
    }
    client = _client(
        signer,
        {ORDER_BY_CLIENT_ORDER_ID_PATH: httpx.Response(200, json=payload)},
        recorded,
    )

    with pytest.raises(PionexOrderNotFound):
        await client.order_id_for(CLIENT_ORDER_ID)


async def test_a_plausible_but_unobserved_code_is_not_read_as_a_missing_order(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """``ORDER_NOT_FOUND`` reads like the obvious name and Pionex does not use
    it — it was one of three guesses the live probe disproved.

    This test is the guard on that lesson. Anything not observed coming back
    from the API stays out of ``ORDER_NOT_FOUND_CODES``, because the cost of
    a wrong entry is releasing capital behind a position that is really open.
    """
    payload = {"result": False, "code": "ORDER_NOT_FOUND", "message": "not found"}
    client = _client(
        signer,
        {ORDER_BY_CLIENT_ORDER_ID_PATH: httpx.Response(200, json=payload)},
        recorded,
    )

    with pytest.raises(PionexApiError) as caught:
        await client.order_id_for(CLIENT_ORDER_ID)

    assert not isinstance(caught.value, PionexOrderNotFound)


async def test_an_unlisted_rejection_code_is_not(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    payload = {"result": False, "code": "AUTH_FAILED", "message": "bad signature"}
    client = _client(
        signer,
        {ORDER_BY_CLIENT_ORDER_ID_PATH: httpx.Response(200, json=payload)},
        recorded,
    )

    with pytest.raises(PionexApiError) as caught:
        await client.order_id_for(CLIENT_ORDER_ID)

    assert not isinstance(caught.value, PionexOrderNotFound)


async def test_a_numeric_fill_price_is_rejected_rather_than_silently_coerced(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """A JSON number has already lost precision before it reaches us, and this
    one lands in the append-only ledger where it can never be corrected."""
    payload = {
        "result": True,
        "data": {
            "fills": [
                {
                    "id": "F-1",
                    "orderId": "1",
                    "symbol": "BTC_USDT",
                    "side": "BUY",
                    "price": 50010.12345678,
                    "size": "0.002",
                    "fee": "0.05",
                    "feeCoin": "USDT",
                    "timestamp": 1787313600123,
                }
            ]
        },
    }
    client = _client(signer, {FILLS_BY_ORDER_ID_PATH: httpx.Response(200, json=payload)}, recorded)

    with pytest.raises(PionexApiError, match="must be a string amount"):
        await client.fills_for_order("1")


async def test_no_fills_yet_is_an_empty_list_not_an_error(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """An accepted order whose fills have not been published is a normal
    transient state. Reading it as an error would be wrong; reading it as
    'never filled' would be worse."""
    payload = {"result": True, "data": {"fills": []}}
    client = _client(signer, {FILLS_BY_ORDER_ID_PATH: httpx.Response(200, json=payload)}, recorded)

    assert await client.fills_for_order("1") == []


def _order_request(recorded: list[httpx.Request]) -> httpx.Request:
    """The new-order POST, ignoring the symbol-catalog GET that precedes it."""
    orders = [r for r in recorded if r.url.path == NEW_ORDER_PATH]
    assert len(orders) == 1, f"expected exactly one order, got {len(orders)}"
    return orders[0]
