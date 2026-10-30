"""``TradeCapability``: what is known about a user's active key on an exchange
before a live opening goes through (decisions 18 and 20; design.md § 4a).

Asked twice for one opening: on the signal path, ahead of the guard and the
balance refresh, and again in the pool's lock, where a key deleted or replaced in
between is seen. Both refuse with the same reason, so it is stated once, here.
"""

from enum import Enum


class TradeCapability(Enum):
    """TRADE_CAPABLE: the active key can place orders. READ_ONLY: an active key
    exists but cannot trade. NO_KEY: the exchange has no active key at all, never
    keyed or deleted (decision 22)."""

    TRADE_CAPABLE = "TRADE_CAPABLE"
    READ_ONLY = "READ_ONLY"
    NO_KEY = "NO_KEY"


def key_refusal(capability: TradeCapability, exchange: str) -> tuple[str, str]:
    """The reason code of a live opening refused over its key, and the words that
    say what to fix. The two problems have different fixes, so they carry
    different codes; both name the exchange and where to fix it."""
    if capability is TradeCapability.NO_KEY:
        return "EXCHANGE_HAS_NO_KEY", f"{exchange} has no active key; store one (Settings)"
    return (
        "EXCHANGE_KEY_READ_ONLY",
        f"the active {exchange} key cannot trade; store a key that can trade futures (Settings)",
    )
