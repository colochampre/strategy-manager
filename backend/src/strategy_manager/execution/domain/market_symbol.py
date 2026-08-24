"""Splitting a market symbol into the two currencies it trades.

A market has a base and a quote: ``BTC_USDT`` buys and sells BTC, priced and
paid for in USDT. Sizing a close needs the base half, because a close sells
what the open actually acquired — and because a fee charged in the base
currency reduces that holding, while a fee charged in anything else does not.

The ``BASE_QUOTE`` shape is Pionex's, and it is not universal: other venues
write ``BTCUSDT`` with no separator, which cannot be split without a currency
registry. This lives in the domain anyway, because "a market has a base and a
quote" is the concept the close-sizing rule depends on, not a transport
detail. The day a venue with a different convention is added, the split becomes
a per-venue concern and this function is where that will be obvious.

**Perpetual markets carry a third part.** Pionex names them
``BASE_QUOTE_PERP`` -- ``BTC_USDT_PERP``. Splitting that on the first
separator alone reads the quote half as ``USDT_PERP``, which matches no
settlement currency, so every futures close would be refused as a
misconfigured strategy. The contract marker is stripped before the split
rather than after, because it qualifies the market, not the currency.

The quote half is checked against the pool's settlement currency rather than
discarded. A strategy configured in a USDT pool that signals a BTC-quoted
market is misconfigured in a way that would otherwise surface as an
inexplicably wrong order size, and it is cheap to refuse here instead.
"""

from strategy_manager.shared.domain.errors import InvariantViolation

SEPARATOR = "_"
PERPETUAL_SUFFIX = "_PERP"


def is_perpetual(symbol: str) -> bool:
    """Whether this symbol names a perpetual futures market."""
    return symbol.upper().endswith(PERPETUAL_SUFFIX)


def base_currency_of(symbol: str, settlement_currency: str) -> str:
    """Returns the base currency of ``symbol``, asserting its quote half is
    the pool's settlement currency.

    Accepts spot (``BTC_USDT``) and perpetual (``BTC_USDT_PERP``) symbols
    alike: both trade BTC settled in USDT, and a close is sized in the base
    currency on either.
    """

    market = symbol[: -len(PERPETUAL_SUFFIX)] if is_perpetual(symbol) else symbol

    base, separator, quote = market.partition(SEPARATOR)
    if not separator or not base or not quote:
        raise InvariantViolation(
            f"market symbol {symbol!r} is not in BASE{SEPARATOR}QUOTE form, so "
            "its base currency cannot be determined"
        )

    if quote.upper() != settlement_currency.upper():
        raise InvariantViolation(
            f"market symbol {symbol!r} is quoted in {quote!r} but the pool "
            f"settles in {settlement_currency!r}; the strategy is trading a "
            "market its capital pool cannot fund"
        )

    return base.upper()
