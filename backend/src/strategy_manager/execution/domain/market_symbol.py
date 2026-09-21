"""Splitting a market symbol into the two currencies it trades.

A market has a base and a quote: ``BTC_USDT`` buys and sells BTC, priced and
paid for in USDT. Sizing a close needs the base half, because a close sells
what the open actually acquired — and because a fee charged in the base
currency reduces that holding, while a fee charged in anything else does not.

**Three shapes reach this function, and they are not cosmetic variants.**

``BTC_USDT``       Pionex spot. Separated, so the split is a partition.
``BTC_USDT_PERP``  Pionex perpetual. Same, once the contract marker is off.
``SOLUSDT.P``      What TradingView sends for a Bybit perpetual, and what
                   Bybit itself calls ``SOLUSDT``. Concatenated: there is no
                   separator to split on at all.

The concatenated form is why this file used to say a currency registry would
be needed. It is not, because the caller already supplies the one fact that
resolves it: the pool's settlement currency IS the quote. ``SOLUSDT`` minus a
known ``USDT`` suffix is ``SOL``, unambiguously — a base whose own name ends
in the quote still comes out right, since only one suffix is removed.

That the settlement currency is REQUIRED rather than optional is the point.
Guessing where the boundary falls in ``SOLUSDT`` is not possible; being told
the quote makes it arithmetic.

**Contract markers are stripped before the split, never after.** They qualify
the market, not the currency. ``.P`` is TradingView's perpetual suffix and
``_PERP`` is Pionex's; both name the same thing and neither is part of a
currency.

The quote half is checked against the pool's settlement currency rather than
discarded. A strategy configured in a USDT pool that signals a BTC-quoted
market is misconfigured in a way that would otherwise surface as an
inexplicably wrong order size, and it is cheap to refuse here instead.
"""

from strategy_manager.shared.domain.errors import InvariantViolation

SEPARATOR = "_"

# Contract markers, longest first so a symbol carrying one is not left with a
# fragment of the other.
CONTRACT_MARKERS = ("_PERP", ".P")


def strip_contract_marker(symbol: str) -> str:
    """Removes the perpetual marker, leaving the market itself.

    This is also what a venue is asked about: Bybit lists ``SOLUSDT``, while
    the alert that referenced it says ``SOLUSDT.P``. Sending the marker to the
    venue produces "no such symbol" for a market that plainly exists.
    """
    upper = symbol.upper()
    for marker in CONTRACT_MARKERS:
        if upper.endswith(marker):
            return symbol[: -len(marker)]
    return symbol


def is_perpetual(symbol: str) -> bool:
    """Whether this symbol names a perpetual futures market."""
    return strip_contract_marker(symbol) != symbol


def market_spellings(symbol: str) -> frozenset[str]:
    """Every spelling this market can wear, upper-cased: the venue's bare
    name plus one candidate per known contract marker (``STXUSDT``,
    ``STXUSDT.P``, ``STXUSDT_PERP``).

    Built from ``CONTRACT_MARKERS`` rather than hardcoded, so a marker added
    there reaches every caller of this function too — the same reasoning
    ``reconciliation.application.market_key`` gives for reusing
    ``strip_contract_marker`` instead of re-implementing it. A query that
    filters ledger rows by only the one spelling it was called with misses a
    holding recorded under another, which is exactly the mismatch that made
    reconciliation misfire before it was fixed.

    The result is the SAME set no matter which of a market's spellings is
    passed in, because every candidate is rebuilt from the bare form.
    """
    bare = strip_contract_marker(symbol).upper()
    return frozenset({bare, *(f"{bare}{marker}" for marker in CONTRACT_MARKERS)})


def base_currency_of(symbol: str, settlement_currency: str) -> str:
    """Returns the base currency of ``symbol``, asserting its quote half is
    the pool's settlement currency.

    Accepts every shape listed in this module's docstring.
    """
    market = strip_contract_marker(symbol).upper()
    quote = settlement_currency.upper()

    base, separator, tail = market.partition(SEPARATOR)
    if separator:
        return _split(symbol, base, tail, quote)

    # Concatenated. The settlement currency is the only boundary available,
    # and it is enough.
    if not market.endswith(quote) or market == quote:
        raise InvariantViolation(
            f"market symbol {symbol!r} is not quoted in {settlement_currency!r} "
            "and carries no separator, so its base currency cannot be "
            "determined; the strategy is trading a market its capital pool "
            "cannot fund"
        )
    return _non_empty(symbol, market[: -len(quote)])


def _split(symbol: str, base: str, quote: str, settlement: str) -> str:
    if not base or not quote:
        raise InvariantViolation(
            f"market symbol {symbol!r} is not in BASE{SEPARATOR}QUOTE form, so "
            "its base currency cannot be determined"
        )
    if quote != settlement:
        raise InvariantViolation(
            f"market symbol {symbol!r} is quoted in {quote!r} but the pool "
            f"settles in {settlement!r}; the strategy is trading a market its "
            "capital pool cannot fund"
        )
    return base


def _non_empty(symbol: str, base: str) -> str:
    if not base:
        raise InvariantViolation(
            f"market symbol {symbol!r} has no base currency once its quote is "
            "removed"
        )
    return base
