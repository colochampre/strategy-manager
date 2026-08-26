"""The Bybit read client, and the envelope every call comes wrapped in."""

from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.read_client import (
    ACCOUNT_INFO_PATH,
    INSTRUMENTS_PATH,
    POSITIONS_PATH,
    WALLET_BALANCE_PATH,
    BybitReadOnlyClient,
)
from strategy_manager.shared.infrastructure.bybit.signer import (
    KEY_HEADER,
    SIGNATURE_HEADER,
    BybitSigner,
)

# BTCUSDT exactly as the live account reported it on 2026-08-26.
BTC_PERP: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "contractType": "LinearPerpetual",
    "status": "Trading",
    "baseCoin": "BTC",
    "quoteCoin": "USDT",
    "settleCoin": "USDT",
    "lotSizeFilter": {
        "qtyStep": "0.001",
        "minOrderQty": "0.001",
        "maxOrderQty": "1500.000",
        "minNotionalValue": "5",
    },
    "priceFilter": {"tickSize": "0.10"},
    "leverageFilter": {"minLeverage": "1", "maxLeverage": "150.00", "leverageStep": "0.01"},
}

# A DATED future. It shares the 'linear' category and expires underneath any
# position held in it, which is why contractType is read rather than assumed.
BTC_DATED: dict[str, Any] = {
    **BTC_PERP,
    "symbol": "BTCUSDT-25DEC26",
    "contractType": "LinearFutures",
}

POSITION: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "side": "Buy",
    "size": "0.015",
    "avgPrice": "78061.90",
    "leverage": "10",
    "positionIdx": 0,
    "unrealisedPnl": "-3.25",
    "liqPrice": "71000.00",
}


def _envelope(result: Any) -> dict[str, Any]:
    return {"retCode": 0, "retMsg": "OK", "result": result, "time": 1787762883000}


def _client(
    signer: BybitSigner,
    responses: dict[str, httpx.Response],
    recorded: list[httpx.Request],
) -> BybitReadOnlyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return responses[request.url.path]

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com",
        transport=httpx.MockTransport(handler),
    )
    return BybitReadOnlyClient(http, signer)


@pytest.fixture
def recorded() -> list[httpx.Request]:
    return []


async def test_contract_rules_are_parsed_as_exact_decimals(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    responses = {
        INSTRUMENTS_PATH: httpx.Response(200, json=_envelope({"list": [BTC_PERP]}))
    }
    client = _client(signer, responses, recorded)

    contracts = await client.perp_contracts()

    assert contracts[0].symbol == "BTCUSDT"
    assert contracts[0].qty_step == Decimal("0.001")
    assert contracts[0].min_order_qty == Decimal("0.001")
    assert contracts[0].min_notional == Decimal("5")
    assert contracts[0].max_leverage == Decimal("150.00")
    assert contracts[0].is_perpetual
    assert contracts[0].is_usdt_settled
    assert contracts[0].is_trading


async def test_a_dated_future_is_not_reported_as_a_perpetual(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """Bybit lists 40 dated contracts alongside 800 perpetuals under one
    category. A dated contract traded as a perpetual settles underneath the
    position."""
    responses = {
        INSTRUMENTS_PATH: httpx.Response(
            200, json=_envelope({"list": [BTC_PERP, BTC_DATED]})
        )
    }
    client = _client(signer, responses, recorded)

    contracts = await client.perp_contracts()

    assert [c.is_perpetual for c in contracts] == [True, False]


async def test_a_short_position_reads_back_as_a_negative_size(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """Bybit puts the direction in ``side`` and keeps ``size`` unsigned, where
    Pionex signs ``netSize``. Translating here keeps one meaning of "a
    position" across venues, which is what the close-sizing rule depends on."""
    short = {**POSITION, "side": "Sell"}
    responses = {POSITIONS_PATH: httpx.Response(200, json=_envelope({"list": [short]}))}
    client = _client(signer, responses, recorded)

    positions = await client.positions()

    assert positions[0].size == Decimal("0.015")
    assert positions[0].signed_size == Decimal("-0.015")


async def test_a_long_position_keeps_a_positive_signed_size(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    responses = {
        POSITIONS_PATH: httpx.Response(200, json=_envelope({"list": [POSITION]}))
    }
    client = _client(signer, responses, recorded)

    positions = await client.positions()

    assert positions[0].signed_size == Decimal("0.015")


async def test_a_flat_position_is_parsed_rather_than_rejected(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """Bybit reports a flat position with an empty side and an empty average
    price. That is a legitimate answer, not a malformed one -- and it is how
    leverage is read for a symbol nothing is open on."""
    flat = {**POSITION, "side": "", "size": "0", "avgPrice": "", "liqPrice": ""}
    responses = {POSITIONS_PATH: httpx.Response(200, json=_envelope({"list": [flat]}))}
    client = _client(signer, responses, recorded)

    positions = await client.positions()

    assert positions[0].size == Decimal("0")
    assert positions[0].signed_size == Decimal("0")
    assert positions[0].avg_price == Decimal("0")
    assert positions[0].liq_price is None


async def test_leverage_is_matched_by_symbol_not_taken_positionally(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """A list keyed by nothing is where the wrong market's leverage gets read
    as this one's -- the mistake Pionex made expensive."""
    other = {**POSITION, "symbol": "ETHUSDT", "leverage": "3"}
    responses = {
        POSITIONS_PATH: httpx.Response(200, json=_envelope({"list": [other, POSITION]}))
    }
    client = _client(signer, responses, recorded)

    assert await client.leverage_for("BTCUSDT") == Decimal("10")


async def test_leverage_for_a_symbol_the_venue_omits_fails_loudly(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    responses = {POSITIONS_PATH: httpx.Response(200, json=_envelope({"list": []}))}
    client = _client(signer, responses, recorded)

    with pytest.raises(BybitApiError, match="no leverage"):
        await client.leverage_for("BTCUSDT")


async def test_balances_are_read_from_the_nested_unified_account(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """Bybit nests them one level deeper than Pionex: result.list[0].coin[]."""
    payload = _envelope(
        {
            "list": [
                {
                    "accountType": "UNIFIED",
                    "coin": [
                        {
                            "coin": "USDT",
                            "walletBalance": "500.25",
                            "equity": "500.25",
                            "availableToWithdraw": "500.25",
                        }
                    ],
                }
            ]
        }
    )
    client = _client(signer, {WALLET_BALANCE_PATH: httpx.Response(200, json=payload)}, recorded)

    balances = await client.wallet_balance()

    assert balances[0].coin == "USDT"
    assert balances[0].wallet_balance == Decimal("500.25")


async def test_an_account_with_no_coins_reads_as_empty_not_as_a_failure(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    payload = _envelope({"list": []})
    client = _client(signer, {WALLET_BALANCE_PATH: httpx.Response(200, json=payload)}, recorded)

    assert await client.wallet_balance() == []


async def test_every_account_read_is_signed(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    payload = _envelope({"marginMode": "ISOLATED_MARGIN"})
    client = _client(signer, {ACCOUNT_INFO_PATH: httpx.Response(200, json=payload)}, recorded)

    await client.account_info()

    request = recorded[0]
    assert request.method == "GET"
    assert request.headers[KEY_HEADER] == "test-key-abcd"
    assert len(request.headers[SIGNATURE_HEADER]) == 64


async def test_a_business_failure_arrives_over_http_200(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """Bybit reports rejections with a 200 status and a non-zero retCode.
    Reading the status line alone would treat every rejection as a success."""
    payload = {"retCode": 10004, "retMsg": "error sign!", "result": {}}
    client = _client(signer, {ACCOUNT_INFO_PATH: httpx.Response(200, json=payload)}, recorded)

    with pytest.raises(BybitApiError, match="error sign") as caught:
        await client.account_info()

    assert caught.value.code == "10004"
    assert caught.value.http_status is None


async def test_a_non_200_status_becomes_an_api_error(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, {ACCOUNT_INFO_PATH: httpx.Response(403, text="nope")}, recorded)

    with pytest.raises(BybitApiError) as caught:
        await client.account_info()

    assert caught.value.http_status == 403


async def test_a_numeric_amount_is_rejected_rather_than_silently_coerced(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """A JSON number has already lost precision before it reaches us."""
    broken = {**BTC_PERP, "lotSizeFilter": {**BTC_PERP["lotSizeFilter"], "qtyStep": 0.001}}
    responses = {
        INSTRUMENTS_PATH: httpx.Response(200, json=_envelope({"list": [broken]}))
    }
    client = _client(signer, responses, recorded)

    with pytest.raises(BybitApiError, match="must be a string amount"):
        await client.perp_contracts()


async def test_an_unexpected_payload_shape_names_what_arrived(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    responses = {
        INSTRUMENTS_PATH: httpx.Response(200, json=_envelope({"instruments": []}))
    }
    client = _client(signer, responses, recorded)

    with pytest.raises(BybitApiError, match=r"payload keys were \['instruments'\]"):
        await client.perp_contracts()


def test_the_client_exposes_no_writing_method() -> None:
    """The read-only guarantee is structural. This is the tripwire that fires
    the day someone adds order submission to the balance reader."""
    forbidden = ("order", "submit", "cancel", "close", "buy", "sell", "transfer",
                 "withdraw", "post", "delete", "put", "set", "amend")
    public = [name for name in dir(BybitReadOnlyClient) if not name.startswith("_")]

    assert [name for name in public if any(w in name.lower() for w in forbidden)] == []
