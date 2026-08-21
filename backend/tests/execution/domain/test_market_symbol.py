"""``base_currency_of`` — splitting a market symbol into what it trades.

Sizing a close needs the base half of the market, because that is the currency
being sold and because a fee charged in it reduces what there is to sell.
"""

import pytest

from strategy_manager.execution.domain.market_symbol import base_currency_of
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


@pytest.mark.parametrize("symbol", ["BTCUSDT", "BTC", "_USDT", "BTC_", ""])
def test_a_symbol_without_a_usable_split_is_refused(symbol: str) -> None:
    """Venues that write BTCUSDT with no separator cannot be split without a
    currency registry. Refusing is correct: guessing a boundary would size a
    close in a currency nobody chose."""
    with pytest.raises(InvariantViolation, match="BASE_QUOTE"):
        base_currency_of(symbol, "USDT")
