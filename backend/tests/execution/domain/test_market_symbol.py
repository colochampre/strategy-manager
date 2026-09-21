"""``base_currency_of`` — splitting a market symbol into what it trades.

Sizing a close needs the base half of the market, because that is the currency
being sold and because a fee charged in it reduces what there is to sell.
"""

import pytest

from strategy_manager.execution.domain.market_symbol import (
    base_currency_of,
    market_spellings,
)
from strategy_manager.shared.domain.errors import InvariantViolation


def test_the_base_is_the_half_before_the_separator() -> None:
    assert base_currency_of("BTC_USDT", "USDT") == "BTC"
    assert base_currency_of("ETH_USDT", "USDT") == "ETH"


def test_the_comparison_is_case_insensitive_on_both_sides() -> None:
    """The settlement currency comes from a pool config and the symbol from a
    TradingView alert. Neither is guaranteed to be normalised, and a case
    mismatch here would refuse a perfectly valid close."""
    assert base_currency_of("btc_usdt", "USDT") == "BTC"
    assert base_currency_of("BTC_USDT", "usdt") == "BTC"


def test_a_symbol_quoted_in_another_currency_is_refused() -> None:
    """A strategy in a USDT pool signalling a BTC-quoted market is
    misconfigured. Caught here it is one clear error; uncaught it becomes an
    order sized in the wrong currency."""
    with pytest.raises(InvariantViolation, match="cannot fund"):
        base_currency_of("ETH_BTC", "USDT")


@pytest.mark.parametrize("symbol", ["_USDT", "BTC_"])
def test_a_malformed_separated_symbol_is_refused(symbol: str) -> None:
    """A separator with nothing on one side of it is not a market."""
    with pytest.raises(InvariantViolation, match="BASE_QUOTE"):
        base_currency_of(symbol, "USDT")


@pytest.mark.parametrize("symbol", ["BTC", "", "USDT"])
def test_a_concatenated_symbol_that_is_not_quoted_here_is_refused(
    symbol: str,
) -> None:
    """Without a separator the settlement currency is the only boundary. A
    symbol that does not end in it cannot be resolved, and guessing one would
    size a close in a currency nobody chose. ``USDT`` alone is refused too:
    stripping the quote leaves no base at all."""
    with pytest.raises(InvariantViolation):
        base_currency_of(symbol, "USDT")


def test_a_concatenated_symbol_resolves_against_the_settlement_currency() -> None:
    """This used to be refused, on the grounds that BTCUSDT cannot be split
    without a currency registry. It does not need one: the caller already
    supplies the quote, and SOLUSDT minus a known USDT is SOL.

    Bybit writes every symbol this way, so the old refusal would have made
    every close on that venue impossible."""
    assert base_currency_of("BTCUSDT", "USDT") == "BTC"
    assert base_currency_of("SOLUSDT", "USDT") == "SOL"
    assert base_currency_of("1INCHUSDT", "USDT") == "1INCH"


def test_tradingviews_perpetual_suffix_is_not_part_of_the_symbol() -> None:
    """A TradingView alert charted on Bybit sends SOLUSDT.P. The .P is a
    contract marker, and reading it as part of the currency would leave the
    symbol quoted in nothing the pool holds."""
    assert base_currency_of("SOLUSDT.P", "USDT") == "SOL"
    assert base_currency_of("solusdt.p", "usdt") == "SOL"


def test_a_base_whose_name_ends_in_the_quote_still_resolves() -> None:
    """Only ONE suffix is removed, so a boundary that appears twice does not
    eat the base."""
    assert base_currency_of("XUSDTUSDT", "USDT") == "XUSDT"


def test_a_perpetual_symbol_splits_on_the_market_not_the_contract_marker() -> None:
    """``BTC_USDT_PERP`` trades BTC settled in USDT. Splitting on the first
    separator alone reads the quote as ``USDT_PERP``, which matches no
    settlement currency, so every futures close would be refused as a
    misconfigured strategy."""
    assert base_currency_of("BTC_USDT_PERP", "USDT") == "BTC"
    assert base_currency_of("eth_usdt_perp", "usdt") == "ETH"


def test_a_perpetual_still_has_its_quote_half_checked() -> None:
    """Stripping the contract marker must not also strip the check that the
    market is one the pool can actually fund (CLAUDE.md rule 5)."""
    with pytest.raises(InvariantViolation, match="cannot fund"):
        base_currency_of("ADA_BTC_PERP", "USDT")


def test_a_coin_margined_perpetual_resolves_against_its_own_settlement() -> None:
    """The catalogue lists 43 non-USDT-settled perpetuals. ``ADA_BTC_PERP``
    is funded by the BTC pool, not the USDT one."""
    assert base_currency_of("ADA_BTC_PERP", "BTC") == "ADA"


def test_market_spellings_returns_every_shape_the_same_market_can_wear() -> None:
    """The three spellings a Bybit perpetual is known by: the venue's bare
    name, TradingView's alert spelling, and Pionex's. A query that only
    accepts the one it was called with misses a holding recorded under
    another (bug/reconciliation-symbol-spelling-mismatch)."""
    assert market_spellings("STXUSDT") == frozenset(
        {"STXUSDT", "STXUSDT.P", "STXUSDT_PERP"}
    )


def test_market_spellings_is_the_same_set_regardless_of_which_spelling_is_asked() -> None:
    """Whichever spelling a caller happens to hold, the returned set must be
    identical -- otherwise a query built from one spelling would not find a
    row recorded under another."""
    assert market_spellings("STXUSDT.P") == market_spellings("STXUSDT_PERP")
    assert market_spellings("stxusdt") == market_spellings("STXUSDT")
