from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.futures_read_client import (
    LEVERAGE_PATH,
    MARGIN_MODE_PATH,
    POSITION_MODE_PATH,
    POSITIONS_PATH,
    RISK_TABLE_PATH,
    SYMBOLS_PATH,
    PionexFuturesReadClient,
)
from strategy_manager.shared.infrastructure.pionex.read_client import (
    FUTURES_BALANCES_PATH,
)
from strategy_manager.shared.infrastructure.pionex.signer import (
    KEY_HEADER,
    SIGNATURE_HEADER,
    PionexSigner,
)


def _envelope(data: dict[str, Any]) -> dict[str, Any]:
    return {"result": True, "timestamp": 1787313600000, "data": data}


def _contract(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "symbol": "BTC_USDT_PERP",
        "name": "BTC/USDT Perpetual",
        "type": "PERP",
        "baseCurrency": "BTC",
        "quoteCurrency": "USDT",
        "basePrecision": 3,
        "quotePrecision": 1,
        "minNotional": "5",
        "baseStep": "0.001",
        "quoteStep": "0.1",
        "minSizeLimit": "0.001",
        "maxSizeLimit": "100",
        "minSizeMarket": "0.001",
        "maxSizeMarket": "50",
        "maxOrderNum": 200,
        "status": "TRADING",
        "liquidationFeeRate": "0.005",
    }
    return {**entry, **overrides}


# The venue answers a single-symbol leverage query with a LIST, not the flat
# object the published reference describes.
LEVERAGES: dict[str, Any] = {
    "leverages": [
        {"symbol": "ETH_USDT_PERP", "leverage": "3"},
        {"symbol": "BTC_USDT_PERP", "leverage": "20"},
    ]
}

POSITION: dict[str, Any] = {
    "positionId": 90210,
    "symbol": "BTC_USDT_PERP",
    "positionSide": "LONG",
    "isolatedMode": "CROSS",
    "netSize": "0.015",
    "avgPrice": "64250.5",
    "leverage": "10",
    "unrealizedPnL": "-3.25",
    "markPrice": "64034.1",
    "liquidationPrice": "58200.0",
}


def _client(
    signer: PionexSigner,
    responses: dict[str, httpx.Response],
    recorded: list[httpx.Request],
) -> PionexFuturesReadClient:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return responses[request.url.path]

    http = httpx.AsyncClient(
        base_url="https://api.pionex.com",
        transport=httpx.MockTransport(handler),
    )
    return PionexFuturesReadClient(http, signer)


@pytest.fixture
def recorded() -> list[httpx.Request]:
    return []


async def test_the_catalogue_is_read_from_the_spot_common_path_with_type_perp(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The futures contract table is NOT under /uapi/v1/. Assuming symmetry
    with the account endpoints sends every catalogue read to a 404."""
    responses = {
        SYMBOLS_PATH: httpx.Response(200, json=_envelope({"symbols": [_contract()]}))
    }
    client = _client(signer, responses, recorded)

    await client.perp_contracts()

    request = recorded[0]
    assert request.url.path == SYMBOLS_PATH
    assert request.url.path != FUTURES_BALANCES_PATH
    assert not request.url.path.startswith("/uapi/")
    assert request.url.params["type"] == "PERP"


async def test_contract_rules_are_parsed_as_exact_decimals(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    responses = {
        SYMBOLS_PATH: httpx.Response(200, json=_envelope({"symbols": [_contract()]}))
    }
    client = _client(signer, responses, recorded)

    contracts = await client.perp_contracts()

    assert contracts[0].symbol == "BTC_USDT_PERP"
    assert contracts[0].base_precision == 3
    assert contracts[0].min_notional == Decimal("5")
    assert contracts[0].base_step == Decimal("0.001")
    assert contracts[0].min_size_market == Decimal("0.001")
    assert contracts[0].is_usdt_margined
    assert contracts[0].is_trading


async def test_a_non_usdt_quote_currency_is_reported_as_not_usdt_margined(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """This is the COIN-M open risk in one assertion: whatever the account
    turns out to list, the client must not flatten a coin-margined contract
    into the USDT pool. Pools cannot fund each other (CLAUDE.md rule 5)."""
    coin_m = _contract(symbol="BTC_USD_PERP", quoteCurrency="USD")
    responses = {
        SYMBOLS_PATH: httpx.Response(
            200, json=_envelope({"symbols": [_contract(), coin_m]})
        )
    }
    client = _client(signer, responses, recorded)

    contracts = await client.perp_contracts()

    assert [c.is_usdt_margined for c in contracts] == [True, False]


async def test_leverage_tiers_are_read_for_the_requested_symbol(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    payload = _envelope(
        {
            "symbols": [
                {"symbol": "ETH_USDT_PERP", "rows": []},
                {
                    "symbol": "BTC_USDT_PERP",
                    "rows": [
                        {
                            "rowNum": 1,
                            "notionalLimit": "50000",
                            "maxLeverage": "50",
                            "maintMarginRatio": "0.004",
                            "quickDeduction": "0",
                        }
                    ],
                },
            ]
        }
    )
    client = _client(signer, {RISK_TABLE_PATH: httpx.Response(200, json=payload)}, recorded)

    tiers = await client.leverage_tiers("BTC_USDT_PERP")

    assert [tier.max_leverage for tier in tiers] == [Decimal("50")]
    assert tiers[0].notional_limit == Decimal("50000")


async def test_leverage_tiers_for_an_unlisted_symbol_fail_loudly(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """Returning an empty tier list would read as "no leverage limit"."""
    payload = _envelope({"symbols": [{"symbol": "ETH_USDT_PERP", "rows": []}]})
    client = _client(signer, {RISK_TABLE_PATH: httpx.Response(200, json=payload)}, recorded)

    with pytest.raises(PionexApiError, match="no rows for"):
        await client.leverage_tiers("BTC_USDT_PERP")


async def test_positions_are_read_from_the_uapi_path_and_keep_side_and_size(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """Both ``position_side`` and the signed ``net_size`` are kept. Deriving
    one from the other is how a REVERSE ends up doubling a long."""
    payload = _envelope({"positions": [POSITION]})
    client = _client(signer, {POSITIONS_PATH: httpx.Response(200, json=payload)}, recorded)

    positions = await client.positions()

    assert recorded[0].url.path == POSITIONS_PATH
    assert positions[0].position_side == "LONG"
    assert positions[0].net_size == Decimal("0.015")
    assert positions[0].leverage == Decimal("10")
    assert positions[0].unrealized_pnl == Decimal("-3.25")


async def test_an_unreported_pnl_stays_none_rather_than_becoming_zero(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    entry = {**POSITION}
    del entry["unrealizedPnL"]
    payload = _envelope({"positions": [entry]})
    client = _client(signer, {POSITIONS_PATH: httpx.Response(200, json=payload)}, recorded)

    positions = await client.positions()

    assert positions[0].unrealized_pnl is None


async def test_the_account_reads_are_signed_and_hit_the_uapi_base_path(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    responses = {
        LEVERAGE_PATH: httpx.Response(200, json=_envelope(LEVERAGES)),
        MARGIN_MODE_PATH: httpx.Response(
            200, json=_envelope({"symbol": "BTC_USDT_PERP", "isolatedMode": "CROSS"})
        ),
        POSITION_MODE_PATH: httpx.Response(
            200, json=_envelope({"positionMode": "BUYSELL"})
        ),
    }
    client = _client(signer, responses, recorded)

    assert await client.leverage_for("BTC_USDT_PERP") == Decimal("20")
    assert await client.margin_mode_for("BTC_USDT_PERP") == "CROSS"
    assert await client.position_mode() == "BUYSELL"

    for request in recorded:
        assert request.method == "GET"
        assert request.url.path.startswith("/uapi/v1/")
        assert request.headers[KEY_HEADER] == "test-key-abcd"
        assert len(request.headers[SIGNATURE_HEADER]) == 64


async def test_the_transmitted_query_is_byte_identical_to_the_signed_one(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The symbol travels as a query parameter, and Pionex signs values raw.
    If httpx re-encodes it, every futures account read fails authentication."""
    payload = _envelope(LEVERAGES)
    client = _client(signer, {LEVERAGE_PATH: httpx.Response(200, json=payload)}, recorded)

    signed = signer.sign("GET", LEVERAGE_PATH, {"symbol": "BTC_USDT_PERP"})
    await client.leverage_for("BTC_USDT_PERP")

    sent = recorded[0].url
    assert f"{sent.path}?{sent.query.decode()}" == signed.path_with_query


async def test_a_numeric_amount_is_rejected_rather_than_silently_coerced(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    payload = _envelope({"symbols": [_contract(minNotional=5.0)]})
    client = _client(signer, {SYMBOLS_PATH: httpx.Response(200, json=payload)}, recorded)

    with pytest.raises(PionexApiError, match="must be a string amount"):
        await client.perp_contracts()


async def test_a_boolean_precision_is_rejected_rather_than_read_as_one(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """``bool`` is an ``int`` subclass, so ``True`` would pass an isinstance
    check and quietly become a precision of 1 decimal place."""
    payload = _envelope({"symbols": [_contract(basePrecision=True)]})
    client = _client(signer, {SYMBOLS_PATH: httpx.Response(200, json=payload)}, recorded)

    with pytest.raises(PionexApiError, match="must be an integer"):
        await client.perp_contracts()


async def test_an_unexpected_payload_shape_names_what_actually_arrived(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """This client's job is finding where the docs and the venue disagree, so
    a shape mismatch has to say what it got, not only what it wanted."""
    payload = _envelope({"contracts": []})
    client = _client(signer, {SYMBOLS_PATH: httpx.Response(200, json=payload)}, recorded)

    with pytest.raises(PionexApiError, match=r"payload keys were \['contracts'\]"):
        await client.perp_contracts()


async def test_a_rejected_result_becomes_a_pionex_api_error(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    payload = {"result": False, "code": "AUTH_UNAVAILABLE", "message": "no permission"}
    client = _client(signer, {POSITIONS_PATH: httpx.Response(200, json=payload)}, recorded)

    with pytest.raises(PionexApiError, match="no permission") as caught:
        await client.positions()

    assert caught.value.code == "AUTH_UNAVAILABLE"


def test_the_client_exposes_no_writing_method() -> None:
    """The read-only guarantee is structural, and this probe runs against a
    live account with real money in it. This test is the tripwire that fires
    the day someone adds leverage setting or order submission here."""
    forbidden = ("order", "submit", "cancel", "close", "buy", "sell", "transfer",
                 "withdraw", "post", "delete", "put", "set")
    public = [name for name in dir(PionexFuturesReadClient) if not name.startswith("_")]

    assert [name for name in public if any(word in name.lower() for word in forbidden)] == []


async def test_leverage_is_matched_by_symbol_not_taken_positionally(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The venue answers a single-symbol query with a list. Reading entry
    zero would report ETH's leverage as BTC's, and leverage is the multiplier
    on every sizing decision that follows."""
    payload = _envelope(LEVERAGES)
    client = _client(signer, {LEVERAGE_PATH: httpx.Response(200, json=payload)}, recorded)

    assert LEVERAGES["leverages"][0]["symbol"] != "BTC_USDT_PERP"
    assert await client.leverage_for("BTC_USDT_PERP") == Decimal("20")


async def test_leverage_for_a_symbol_the_venue_omits_fails_loudly(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    payload = _envelope({"leverages": []})
    client = _client(signer, {LEVERAGE_PATH: httpx.Response(200, json=payload)}, recorded)

    with pytest.raises(PionexApiError, match="no leverage is reported"):
        await client.leverage_for("BTC_USDT_PERP")


async def test_the_documented_contract_type_field_is_not_the_live_one(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The reference documents ``contractType: PERPETUAL``; the venue sends
    ``type: PERP`` and no ``contractType`` at all. Reading the documented
    name yields None for every one of the 603 listed markets."""
    entry = _contract()
    assert "contractType" not in entry

    responses = {SYMBOLS_PATH: httpx.Response(200, json=_envelope({"symbols": [entry]}))}
    client = _client(signer, responses, recorded)

    contracts = await client.perp_contracts()

    assert contracts[0].contract_type == "PERP"
