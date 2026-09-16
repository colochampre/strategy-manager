"""Binance's contract rules, symbol config and position, as an order needs them.

Every payload here is the shape the live account actually returned on
2026-09-15. Two of them disagree with the published documentation, and both
disagreements fail silently if assumed away:

  * ``symbolConfig`` answers a single-symbol query with a one-element LIST,
    not the flat object the docs show. Taking index 0 would read another
    market's leverage -- the exact trap Pionex's leverage endpoint set.
  * the catalogue mixes ``PERPETUAL`` with ``TRADIFI_PERPETUAL`` and dated
    quarterlies, so ``contractType`` has to be checked rather than assumed.
"""

from decimal import Decimal

import pytest

from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.read_client import (
    EXCHANGE_INFO_PATH,
    POSITION_RISK_PATH,
    SYMBOL_CONFIG_PATH,
    BinanceReadOnlyClient,
)

# AAVEUSDT as the venue listed it: step 0.1, market ceiling 9000 against a
# limit ceiling of 78000, minimum notional 5.
AAVE = {
    "symbol": "AAVEUSDT",
    "contractType": "PERPETUAL",
    "status": "TRADING",
    "baseAsset": "AAVE",
    "quoteAsset": "USDT",
    "marginAsset": "USDT",
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.010"},
        {"filterType": "LOT_SIZE", "stepSize": "0.1", "minQty": "0.1", "maxQty": "78000"},
        {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.1", "minQty": "0.1", "maxQty": "9000"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ],
}

TRADIFI = {**AAVE, "symbol": "AAPLUSDT", "contractType": "TRADIFI_PERPETUAL"}
QUARTERLY = {**AAVE, "symbol": "BTCUSDT_251226", "contractType": "CURRENT_QUARTER"}

# The live short: direction lives in the SIGN of positionAmt.
AAVE_SHORT = {
    "symbol": "AAVEUSDT",
    "positionSide": "BOTH",
    "positionAmt": "-0.1",
    "entryPrice": "123.97",
    "markPrice": "124.02593255",
    "notional": "-12.40259325",
    "unRealizedProfit": "-0.00559325",
    "liquidationPrice": "184.08061337",
}
AAVE_FLAT = {**AAVE_SHORT, "positionAmt": "0", "notional": "0", "liquidationPrice": "0"}


class FakeTransport:
    def __init__(self, public: object = None, signed: object = None) -> None:
        self.public = public
        self.signed = signed
        self.calls: list[tuple[str, str, object]] = []

    async def get_public(self, path: str, params: object = None) -> object:
        self.calls.append(("public", path, params))
        return self.public

    async def get_signed(self, path: str, params: object = None) -> object:
        self.calls.append(("signed", path, params))
        return self.signed


def _client(**kwargs: object) -> tuple[BinanceReadOnlyClient, FakeTransport]:
    client = BinanceReadOnlyClient.__new__(BinanceReadOnlyClient)
    transport = FakeTransport(**kwargs)  # type: ignore[arg-type]
    client._transport = transport  # type: ignore[attr-defined]
    return client, transport


# --- the catalogue ----------------------------------------------------------


async def test_the_rules_come_from_the_entry_matching_the_symbol() -> None:
    client, transport = _client(public={"symbols": [TRADIFI, AAVE, QUARTERLY]})

    rules = await client.perp_rules("AAVEUSDT")

    assert rules.symbol == "AAVEUSDT"
    assert rules.base_asset == "AAVE"
    assert transport.calls == [("public", EXCHANGE_INFO_PATH, None)]


async def test_the_market_ceiling_is_the_one_kept_not_the_limit_one() -> None:
    """A market order is capped lower than a limit order on the same symbol,
    and this system only ever sends market orders."""
    client, _ = _client(public={"symbols": [AAVE]})

    rules = await client.perp_rules("AAVEUSDT")

    assert rules.market_max_qty == Decimal("9000")


async def test_step_minimum_notional_and_tick_are_read_from_their_filters() -> None:
    client, _ = _client(public={"symbols": [AAVE]})

    rules = await client.perp_rules("AAVEUSDT")

    assert rules.qty_step == Decimal("0.1")
    assert rules.min_qty == Decimal("0.1")
    assert rules.min_notional == Decimal("5")
    assert rules.tick_size == Decimal("0.010")


async def test_a_symbol_the_catalogue_does_not_list_is_refused() -> None:
    client, _ = _client(public={"symbols": [AAVE]})

    with pytest.raises(BinanceApiError, match="no entry for NOSUCHUSDT"):
        await client.perp_rules("NOSUCHUSDT")


# --- what a contract will and will not accept -------------------------------


async def test_a_size_is_truncated_to_the_step_never_rounded_up() -> None:
    """Rounding up spends capital that was never granted; on a close it asks
    the venue to reduce more than the position holds."""
    client, _ = _client(public={"symbols": [AAVE]})
    rules = await client.perp_rules("AAVEUSDT")

    assert rules.round_qty(Decimal("3.1060")) == Decimal("3.1")
    assert rules.round_qty(Decimal("0.09")) == Decimal("0")


async def test_a_tradable_order_passes_every_check() -> None:
    client, _ = _client(public={"symbols": [AAVE]})
    rules = await client.perp_rules("AAVEUSDT")

    rules.assert_tradable(Decimal("3.1"), Decimal("124.02"))


async def test_a_tradifi_perpetual_is_refused() -> None:
    """191 of the 897 listed contracts carry this type. It is a different
    product, and an unrecognised type must never read as tradable."""
    client, _ = _client(public={"symbols": [TRADIFI]})
    rules = await client.perp_rules("AAPLUSDT")

    with pytest.raises(BinanceApiError, match="TRADIFI_PERPETUAL"):
        rules.assert_tradable(Decimal("1"), Decimal("100"))


async def test_a_dated_quarterly_is_refused() -> None:
    """It shares the catalogue and expires underneath any position in it."""
    client, _ = _client(public={"symbols": [QUARTERLY]})
    rules = await client.perp_rules("BTCUSDT_251226")

    with pytest.raises(BinanceApiError, match="CURRENT_QUARTER"):
        rules.assert_tradable(Decimal("1"), Decimal("100"))


async def test_a_halted_market_is_refused() -> None:
    client, _ = _client(public={"symbols": [{**AAVE, "status": "BREAK"}]})
    rules = await client.perp_rules("AAVEUSDT")

    with pytest.raises(BinanceApiError, match="is BREAK, not TRADING"):
        rules.assert_tradable(Decimal("1"), Decimal("100"))


async def test_a_size_below_the_floor_is_refused() -> None:
    client, _ = _client(public={"symbols": [AAVE]})
    rules = await client.perp_rules("AAVEUSDT")

    with pytest.raises(BinanceApiError, match="at least 0.1 AAVE"):
        rules.assert_tradable(Decimal("0"), Decimal("124"))


async def test_a_size_above_the_market_ceiling_is_refused() -> None:
    client, _ = _client(public={"symbols": [AAVE]})
    rules = await client.perp_rules("AAVEUSDT")

    with pytest.raises(BinanceApiError, match="caps a MARKET order at 9000"):
        rules.assert_tradable(Decimal("9001"), Decimal("124"))


async def test_a_notional_below_the_minimum_is_refused() -> None:
    client, _ = _client(public={"symbols": [AAVE]})
    rules = await client.perp_rules("AAVEUSDT")

    with pytest.raises(BinanceApiError, match="notional of at least 5"):
        rules.assert_tradable(Decimal("0.1"), Decimal("1"))


async def test_a_close_skips_the_notional_check_rather_than_inventing_a_price() -> None:
    """A close is sized from the ledger and carries no price."""
    client, _ = _client(public={"symbols": [AAVE]})
    rules = await client.perp_rules("AAVEUSDT")

    rules.assert_tradable(Decimal("0.1"), price=None)


# --- the account's own settings ---------------------------------------------


async def test_symbol_config_is_read_from_a_list_not_a_flat_object() -> None:
    """The documented example shows an object; the venue answers a one-element
    list. Taking index 0 blindly is how Pionex's leverage read went wrong."""
    client, transport = _client(
        signed=[
            {"symbol": "STXUSDT", "marginType": "ISOLATED", "leverage": 2,
             "isAutoAddMargin": False},
            {"symbol": "AAVEUSDT", "marginType": "ISOLATED", "leverage": 2,
             "isAutoAddMargin": False},
        ]
    )

    config = await client.symbol_config("AAVEUSDT")

    assert config.symbol == "AAVEUSDT"
    assert config.leverage == Decimal("2")
    assert config.margin_type == "ISOLATED"
    assert transport.calls == [("signed", SYMBOL_CONFIG_PATH, {"symbol": "AAVEUSDT"})]


async def test_the_leverage_is_the_one_for_the_symbol_asked_about() -> None:
    client, _ = _client(
        signed=[
            {"symbol": "SFPUSDT", "marginType": "ISOLATED", "leverage": 7,
             "isAutoAddMargin": False},
            {"symbol": "AAVEUSDT", "marginType": "ISOLATED", "leverage": 2,
             "isAutoAddMargin": False},
        ]
    )

    assert await client.leverage_for("AAVEUSDT") == Decimal("2")


async def test_a_symbol_config_with_no_matching_entry_is_refused() -> None:
    client, _ = _client(signed=[{"symbol": "SFPUSDT", "leverage": 2}])

    with pytest.raises(BinanceApiError, match="no entry for AAVEUSDT"):
        await client.symbol_config("AAVEUSDT")


# --- positions --------------------------------------------------------------


async def test_a_short_reads_back_with_a_negative_size() -> None:
    """Binance puts the direction in the sign; Bybit uses a side field.
    Translated here so a position means one thing across venues."""
    client, transport = _client(signed=[AAVE_SHORT])

    position = await client.position_for("AAVEUSDT")

    assert position is not None
    assert position.signed_size == Decimal("-0.1")
    assert position.entry_price == Decimal("123.97")
    assert position.liquidation_price == Decimal("184.08061337")
    assert transport.calls == [("signed", POSITION_RISK_PATH, {"symbol": "AAVEUSDT"})]


async def test_a_flat_symbol_reads_as_no_position() -> None:
    """Binance reports flat as an entry with a zero amount, not as an absent
    one, so 'no position' is a value rather than a missing key."""
    client, _ = _client(signed=[AAVE_FLAT])

    assert await client.position_for("AAVEUSDT") is None


async def test_a_symbol_absent_from_the_response_reads_as_no_position() -> None:
    client, _ = _client(signed=[AAVE_SHORT])

    assert await client.position_for("SFPUSDT") is None
