"""The Binance futures trade client: the class that can move money.

Driven through ``httpx.MockTransport`` rather than a stubbed transport object,
because the thing most worth asserting here is the BYTES that leave: a signed
POST whose body is not exactly the string that was signed is rejected by the
venue with an error that says nothing about why.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

from strategy_manager.shared.infrastructure.binance.errors import (
    BinanceApiError,
    BinanceOrderNotFound,
)
from strategy_manager.shared.infrastructure.binance.read_client import (
    EXCHANGE_INFO_PATH,
)
from strategy_manager.shared.infrastructure.binance.signer import (
    BinanceCredentials,
    BinanceSigner,
    signature_for,
)
from strategy_manager.shared.infrastructure.binance.trade_client import (
    AMBIGUOUS_CODES,
    ORDER_PATH,
    POSITION_MODE_PATH,
    USER_TRADES_PATH,
    BinanceTradeClient,
)
from tests.shared.infrastructure.binance.test_futures_rules import AAVE

API_SECRET = "test-secret"
CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
SYMBOL = "AAVEUSDT"
QTY = Decimal("0.5")

# Any fixed instant works; what matters is that the signer reads the injected
# clock, so the signed body is reproducible instead of wall-clock noise.
FROZEN_NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)

ORDER_ACK = {
    "orderId": 778899,
    "clientOrderId": CLIENT_ORDER_ID,
    "symbol": SYMBOL,
    "status": "NEW",
    "origQty": "0.5",
    "executedQty": "0",
    "avgPrice": "0.00000",
    "side": "BUY",
    "reduceOnly": False,
}

# One leg of a real USDⓈ-M fill: the fee is charged in USDT, never in the base
# asset, so the base quantity a close is sized from equals the open exactly.
TRADE = {
    "id": 5150,
    "orderId": 778899,
    "symbol": SYMBOL,
    "side": "BUY",
    "price": "123.97",
    "qty": "0.5",
    "quoteQty": "61.985",
    "realizedPnl": "0",
    "commission": "0.03409175",
    "commissionAsset": "USDT",
    "time": 1789560000000,
    "buyer": True,
    "maker": False,
    "positionSide": "BOTH",
    "marginAsset": "USDT",
}


class FrozenClock:
    """Implements ``ClockPort`` with a fixed instant."""

    def now(self) -> datetime:
        return FROZEN_NOW


def _signer() -> BinanceSigner:
    return BinanceSigner(
        BinanceCredentials(api_key="key-abcd", api_secret=API_SECRET),
        FrozenClock(),
        recv_window_ms=5000,
    )


def _client(
    recorded: list[httpx.Request],
    *,
    hedge_mode: bool = False,
    order_response: dict[str, Any] | None = None,
    overrides: dict[tuple[str, str], httpx.Response] | None = None,
) -> BinanceTradeClient:
    responses: dict[tuple[str, str], httpx.Response] = {
        ("GET", POSITION_MODE_PATH): httpx.Response(
            200, json={"dualSidePosition": hedge_mode}
        ),
        ("POST", ORDER_PATH): httpx.Response(
            200, json=ORDER_ACK if order_response is None else order_response
        ),
        ("GET", EXCHANGE_INFO_PATH): httpx.Response(200, json={"symbols": [AAVE]}),
        ("GET", USER_TRADES_PATH): httpx.Response(200, json=[TRADE]),
    }
    responses.update(overrides or {})

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return responses[(request.method, request.url.path)]

    http = httpx.AsyncClient(
        base_url="https://fapi.binance.com",
        transport=httpx.MockTransport(handler),
    )
    return BinanceTradeClient(http, _signer())


def _sent_body(recorded: list[httpx.Request]) -> str:
    posted = [r for r in recorded if r.method == "POST"]
    assert len(posted) == 1
    return posted[0].content.decode()


def _sent_order(recorded: list[httpx.Request]) -> dict[str, str]:
    return dict(parse_qsl(_sent_body(recorded)))


async def _place(
    client: BinanceTradeClient,
    *,
    side: str = "BUY",
    qty: Decimal = QTY,
    reduce_only: bool = False,
    client_order_id: str = CLIENT_ORDER_ID,
) -> None:
    await client.place_market_order(
        symbol=SYMBOL,
        client_order_id=client_order_id,
        side=side,
        qty=qty,
        reduce_only=reduce_only,
    )


@pytest.fixture
def recorded() -> list[httpx.Request]:
    return []


# --- what actually leaves ----------------------------------------------------


async def test_an_order_is_sent_as_the_exact_form_encoded_body_that_was_signed(
    recorded: list[httpx.Request],
) -> None:
    """The whole point of the POST path: the signature covers one string and
    that same string goes out, parameter order included."""
    client = _client(recorded)

    await _place(client)

    body = _sent_body(recorded)
    signed, _, signature = body.rpartition("&signature=")
    assert signed == (
        f"symbol={SYMBOL}&side=BUY&type=MARKET&quantity=0.5"
        f"&newClientOrderId={CLIENT_ORDER_ID}&reduceOnly=false"
        f"&recvWindow=5000&timestamp={int(FROZEN_NOW.timestamp() * 1000)}"
    )
    assert signature == signature_for(API_SECRET, signed)


async def test_the_order_parameters_travel_in_the_body_and_not_in_the_url(
    recorded: list[httpx.Request],
) -> None:
    client = _client(recorded)

    await _place(client)

    posted = [r for r in recorded if r.method == "POST"][0]
    assert posted.url.query == b""
    assert posted.headers["content-type"] == "application/x-www-form-urlencoded"


async def test_an_order_returns_the_numeric_exchange_id(
    recorded: list[httpx.Request],
) -> None:
    client = _client(recorded)

    ack = await client.place_market_order(
        symbol=SYMBOL,
        client_order_id=CLIENT_ORDER_ID,
        side="BUY",
        qty=QTY,
        reduce_only=False,
    )

    assert ack.order_id == 778899
    assert ack.client_order_id == CLIENT_ORDER_ID


async def test_a_close_carries_reduce_only(recorded: list[httpx.Request]) -> None:
    client = _client(recorded)

    await _place(client, side="SELL", reduce_only=True)

    assert _sent_order(recorded)["reduceOnly"] == "true"


async def test_an_open_says_reduce_only_is_false_rather_than_omitting_it(
    recorded: list[httpx.Request],
) -> None:
    """Sent on both sides so the wire says which one this is, instead of
    leaving it to a default that only holds in one-way mode."""
    client = _client(recorded)

    await _place(client)

    assert _sent_order(recorded)["reduceOnly"] == "false"


async def test_position_side_is_never_sent(recorded: list[httpx.Request]) -> None:
    """Omitting it is what pins one-way mode: Binance defaults it to BOTH
    there and requires it only when the account is hedged, which this client
    refuses outright."""
    client = _client(recorded)

    await _place(client)

    assert "positionSide" not in _sent_order(recorded)


async def test_a_quantity_is_never_sent_in_scientific_notation(
    recorded: list[httpx.Request],
) -> None:
    """A futures size is always a quotient, so an exponent is not an edge case
    here -- it is the normal output of the sizing rule."""
    client = _client(recorded)

    await _place(client, qty=Decimal("1E-8"))

    assert _sent_order(recorded)["quantity"] == "0.00000001"


async def test_a_quantity_of_zero_never_reaches_the_venue(
    recorded: list[httpx.Request],
) -> None:
    client = _client(recorded)

    with pytest.raises(BinanceApiError, match="qty must be positive"):
        await _place(client, qty=Decimal("0"))

    assert recorded == []


# --- the client order id is the only handle ----------------------------------


async def test_a_client_order_id_over_the_length_limit_is_refused_before_any_call(
    recorded: list[httpx.Request],
) -> None:
    """A UUID4 is exactly 36 characters, so a prefix is what breaks this."""
    client = _client(recorded)

    with pytest.raises(BinanceApiError, match="1-36 characters"):
        await _place(client, client_order_id=f"open-{CLIENT_ORDER_ID}")

    assert recorded == []


async def test_a_client_order_id_outside_the_documented_charset_is_refused(
    recorded: list[httpx.Request],
) -> None:
    client = _client(recorded)

    with pytest.raises(BinanceApiError, match="letters, numbers"):
        await _place(client, client_order_id="not a valid id!")

    assert recorded == []


async def test_a_mismatched_client_order_id_echo_is_refused(
    recorded: list[httpx.Request],
) -> None:
    """If the echoed id is not ours, the handle this system uses to recover
    the order names an order Binance did not create."""
    client = _client(
        recorded,
        order_response={**ORDER_ACK, "clientOrderId": "somebody-elses-id"},
    )

    with pytest.raises(BinanceApiError, match="cannot be tracked by our own id"):
        await _place(client)


async def test_an_order_with_no_id_is_refused(recorded: list[httpx.Request]) -> None:
    client = _client(recorded, order_response={"status": "NEW", "symbol": SYMBOL})

    with pytest.raises(BinanceApiError, match="no orderId"):
        await _place(client)


# --- the account must be in one-way mode -------------------------------------


async def test_a_hedged_account_is_refused_before_any_order_is_sent(
    recorded: list[httpx.Request],
) -> None:
    """In hedge mode a symbol holds a long AND a short, reduceOnly cannot be
    sent at all, and every close could open a fresh position on the other
    side."""
    client = _client(recorded, hedge_mode=True)

    with pytest.raises(BinanceApiError, match="hedge mode"):
        await _place(client)

    assert [r for r in recorded if r.method == "POST"] == []


async def test_the_position_mode_is_read_once_per_client(
    recorded: list[httpx.Request],
) -> None:
    """It is an account-wide setting and the client is built per job, so
    re-reading it would add a round trip to the hot path for a number that
    cannot change inside one job."""
    client = _client(recorded)

    for _ in range(2):
        await _place(client)

    mode_reads = [r for r in recorded if r.url.path == POSITION_MODE_PATH]
    assert len(mode_reads) == 1


async def test_an_unreadable_position_mode_stops_the_order(
    recorded: list[httpx.Request],
) -> None:
    """An unknown mode is not a one-way mode."""
    client = _client(
        recorded,
        overrides={
            ("GET", POSITION_MODE_PATH): httpx.Response(200, json={"dual": "no"})
        },
    )

    with pytest.raises(BinanceApiError, match="dualSidePosition"):
        await _place(client)

    assert [r for r in recorded if r.method == "POST"] == []


# --- the lookup hop ----------------------------------------------------------


async def test_the_lookup_is_scoped_to_the_symbol_and_keyed_by_our_own_id(
    recorded: list[httpx.Request],
) -> None:
    """``symbol`` is mandatory on this endpoint: the id alone cannot find an
    order."""
    client = _client(
        recorded,
        overrides={
            ("GET", ORDER_PATH): httpx.Response(
                200, json={"orderId": 778899, "clientOrderId": CLIENT_ORDER_ID}
            )
        },
    )

    order_id = await client.order_id_for(CLIENT_ORDER_ID, SYMBOL)

    assert order_id == 778899
    assert recorded[0].url.params["symbol"] == SYMBOL
    assert recorded[0].url.params["origClientOrderId"] == CLIENT_ORDER_ID


async def test_the_not_found_code_becomes_order_not_found(
    recorded: list[httpx.Request],
) -> None:
    """-2013 is Binance saying it looked and there is no such order."""
    client = _client(
        recorded,
        overrides={
            ("GET", ORDER_PATH): httpx.Response(
                400, json={"code": -2013, "msg": "Order does not exist."}
            )
        },
    )

    with pytest.raises(BinanceOrderNotFound):
        await client.order_id_for(CLIENT_ORDER_ID, SYMBOL)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (-1001, "Internal error; unable to process your request."),
        (-1007, "Send status unknown; execution status unknown."),
    ],
)
async def test_an_ambiguous_failure_is_never_read_as_no_such_order(
    recorded: list[httpx.Request], code: int, message: str
) -> None:
    """The asymmetry that protects a live position: a failed lookup read as
    "no such order" releases the capital behind a real trade. The code
    survives so the adapter can tell the two apart."""
    client = _client(
        recorded,
        overrides={
            ("GET", ORDER_PATH): httpx.Response(500, json={"code": code, "msg": message})
        },
    )

    with pytest.raises(BinanceApiError) as caught:
        await client.order_id_for(CLIENT_ORDER_ID, SYMBOL)

    assert caught.value.code == str(code)
    assert str(code) in AMBIGUOUS_CODES


async def test_a_definitive_rejection_keeps_its_code_and_stays_an_api_error(
    recorded: list[httpx.Request],
) -> None:
    """-2015 is one code for three causes, and the trade key is IP-restricted:
    moving the worker to another host answers with exactly this while the
    read-only key keeps working."""
    client = _client(
        recorded,
        overrides={
            ("GET", ORDER_PATH): httpx.Response(
                401,
                json={
                    "code": -2015,
                    "msg": "Invalid API-key, IP, or permissions for action.",
                },
            )
        },
    )

    with pytest.raises(BinanceApiError) as caught:
        await client.assert_order_placed(CLIENT_ORDER_ID, SYMBOL)

    assert caught.value.code == "-2015"
    assert str(caught.value.code) not in AMBIGUOUS_CODES


# --- fills -------------------------------------------------------------------


async def test_fills_are_read_by_symbol_and_numeric_exchange_order_id(
    recorded: list[httpx.Request],
) -> None:
    """userTrades does not accept our own id, which is why settlement takes
    two hops on this venue and one on Bybit."""
    client = _client(recorded)

    await client.fills_for(symbol=SYMBOL, order_id=778899)

    assert recorded[0].url.path == USER_TRADES_PATH
    assert recorded[0].url.params["symbol"] == SYMBOL
    assert recorded[0].url.params["orderId"] == "778899"


async def test_a_fill_parses_its_price_size_and_commission_exactly(
    recorded: list[httpx.Request],
) -> None:
    client = _client(recorded)

    fill = (await client.fills_for(symbol=SYMBOL, order_id=778899))[0]

    assert fill.trade_id == 5150
    assert fill.order_id == 778899
    assert fill.price == Decimal("123.97")
    assert fill.qty == Decimal("0.5")
    assert fill.commission == Decimal("0.03409175")
    assert fill.commission_asset == "USDT"
    assert fill.trade_time_ms == 1789560000000


async def test_a_commission_read_as_a_json_number_is_refused(
    recorded: list[httpx.Request],
) -> None:
    """A JSON number has already lost precision before it reaches this
    process, and a fee lands in the append-only ledger."""
    client = _client(
        recorded,
        overrides={
            ("GET", USER_TRADES_PATH): httpx.Response(
                200, json=[{**TRADE, "commission": 0.03409175}]
            )
        },
    )

    with pytest.raises(BinanceApiError, match="commission"):
        await client.fills_for(symbol=SYMBOL, order_id=778899)


async def test_a_missing_commission_is_refused_rather_than_read_as_free(
    recorded: list[httpx.Request],
) -> None:
    client = _client(
        recorded,
        overrides={
            ("GET", USER_TRADES_PATH): httpx.Response(
                200, json=[{**TRADE, "commission": ""}]
            )
        },
    )

    with pytest.raises(BinanceApiError, match="commission"):
        await client.fills_for(symbol=SYMBOL, order_id=778899)


async def test_no_fills_yet_is_an_empty_list_not_an_error(
    recorded: list[httpx.Request],
) -> None:
    """Accepted but unpublished is a legitimate transient state; the settle
    job asks again rather than concluding the order did not fill."""
    client = _client(
        recorded,
        overrides={("GET", USER_TRADES_PATH): httpx.Response(200, json=[])},
    )

    assert await client.fills_for(symbol=SYMBOL, order_id=778899) == []


# --- the contract catalogue --------------------------------------------------


async def test_the_catalogue_is_downloaded_once_per_client(
    recorded: list[httpx.Request],
) -> None:
    """Binance offers no per-symbol variant of exchangeInfo: every question
    about one market downloads all of them."""
    client = _client(recorded)

    await client.perp_rules(SYMBOL)
    await client.perp_rules(SYMBOL)

    catalogue_reads = [r for r in recorded if r.url.path == EXCHANGE_INFO_PATH]
    assert len(catalogue_reads) == 1


async def test_a_symbol_the_catalogue_does_not_list_is_refused(
    recorded: list[httpx.Request],
) -> None:
    client = _client(recorded)

    with pytest.raises(BinanceApiError, match="does not list 'NOSUCHUSDT'"):
        await client.perp_rules("NOSUCHUSDT")


async def test_a_broken_entry_for_another_market_does_not_refuse_this_one(
    recorded: list[httpx.Request],
) -> None:
    """Entries are parsed on demand: one unrelated market whose shape changed
    must not stop every order on the venue."""
    client = _client(
        recorded,
        overrides={
            ("GET", EXCHANGE_INFO_PATH): httpx.Response(
                200, json={"symbols": [{"symbol": "BROKENUSDT"}, AAVE]}
            )
        },
    )

    assert (await client.perp_rules(SYMBOL)).symbol == SYMBOL
