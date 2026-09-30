"""``KNOWN_FUTURES_POOLS``: the one place naming which pool a saved key enables
(owner decision 21).

Saving a Bybit or Binance key enables that exchange's single futures pool. The
pool's identity, ``(exchange, venue, settlement_currency)``, and the
``min_order_size`` a row created from scratch starts with both come from here
and nowhere else: never from a request body, so the panel cannot name a pool.

**The Bybit pool is venue ``usdt-m``.** The docs call it "linear/USDT"; that is a
label for the same pool, not a second one. ``Venue`` has only ``spot``,
``usdt-m`` and ``coin-m``, and production holds ``bybit/usdt-m/USDT`` (migration
0017) and ``binance/usdt-m/USDT`` (0018). Bybit's Unified Trading Account has ONE
USDT balance behind spot and linear perpetuals together (CLAUDE.md rule 5), so a
second Bybit USDT pool would let the same money be reserved twice. The mapping
holds one pool per exchange, structurally: a second entry for an exchange is a
duplicate key.

Pionex is deliberately absent. It offers no futures order placement over the
API, and its script does not go through ``SaveCredential``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue


@dataclass(frozen=True, slots=True)
class KnownPool:
    """A pool's identity below its exchange, and what a new row starts with.

    ``default_min_order_size`` is used ONLY when the row does not exist. An
    existing row keeps whatever ``min_order_size`` it was configured with.
    """

    venue: Venue
    settlement_currency: Currency
    default_min_order_size: Decimal


KNOWN_FUTURES_POOLS: Mapping[Exchange, KnownPool] = MappingProxyType(
    {
        Exchange.BYBIT: KnownPool(Venue.USDT_M, Currency.USDT, Decimal("5")),
        Exchange.BINANCE: KnownPool(Venue.USDT_M, Currency.USDT, Decimal("5")),
    }
)


def known_pool_for(exchange: str) -> KnownPool:
    """The pool a key for ``exchange`` enables. An exchange with none raises;
    there is no fallback pool."""
    try:
        return KNOWN_FUTURES_POOLS[Exchange(exchange)]
    except (KeyError, ValueError):
        raise InvariantViolation(f"no futures pool is known for exchange '{exchange}'") from None
