"""The one canonical key a reconciliation scan compares a market under.

The two sides of a scan spell one market differently. The ledger records the
SIGNAL's symbol, in TradingView's form (``STXUSDT.P``); the venue reports its
own name for the same market (``STXUSDT``). Compared as raw strings they never
match, and every open position becomes two false discrepancies: a venue
position with no allocation, and a ledger allocation on a flat venue.

The key is the market with its contract marker removed, upper-cased. Which
markers exist is ``execution.domain.market_symbol``'s knowledge, not this
module's: it is reused rather than copied so a marker added there reaches
reconciliation too.
"""

from strategy_manager.execution.domain.market_symbol import strip_contract_marker


def market_key(symbol: str) -> str:
    """``STXUSDT.P``, ``STXUSDT`` and ``stxusdt`` all map to ``STXUSDT``."""
    return strip_contract_marker(symbol).upper()
