"""``PoolKey`` VO: identifies a capital pool by
``(exchange, venue, settlement_currency)`` (design.md's component inventory
§ allocation/domain/pool_key.py).
"""

from dataclasses import dataclass

from strategy_manager.shared.domain.money import Currency, Exchange, Venue


@dataclass(frozen=True, slots=True)
class PoolKey:
    """A pool's identity (spec: capital-allocation § Purpose).

    ``exchange`` is part of it because two exchanges both have a ``usdt-m``
    venue holding USDT, and they are different money. Keyed by the pair alone,
    a Binance futures pool and a Bybit futures pool were one pool: one row,
    one advisory lock, one balance, and a ledger that could not say where a
    fill happened.
    """

    exchange: Exchange
    venue: Venue
    settlement_currency: Currency
