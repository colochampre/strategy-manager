"""``PoolKey`` VO: identifies a capital pool by ``(venue, settlement_currency)``
(design.md's component inventory § allocation/domain/pool_key.py).
"""

from dataclasses import dataclass

from strategy_manager.shared.domain.money import Currency, Venue


@dataclass(frozen=True, slots=True)
class PoolKey:
    """A pool's identity. Every pool is keyed by this pair (spec:
    capital-allocation § Purpose)."""

    venue: Venue
    settlement_currency: Currency
