"""``KNOWN_FUTURES_POOLS``: which pool a saved key enables (unit 6d, decision 21).

The Bybit entry is the one that matters most. The docs label its pool
"linear/USDT"; the ``Venue`` enum has no such member, and the row production
holds is ``bybit/usdt-m/USDT``. A second Bybit USDT pool (say ``spot/USDT``)
would let the same unified balance be reserved twice (CLAUDE.md rule 5).
"""

from decimal import Decimal

import pytest

from strategy_manager.accounts.domain.known_pools import (
    KNOWN_FUTURES_POOLS,
    KnownPool,
    known_pool_for,
)
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue


def test_bybit_maps_to_usdt_m_usdt() -> None:
    pool = KNOWN_FUTURES_POOLS[Exchange.BYBIT]

    assert (pool.venue, pool.settlement_currency) == (Venue.USDT_M, Currency.USDT)


def test_binance_maps_to_usdt_m_usdt() -> None:
    pool = KNOWN_FUTURES_POOLS[Exchange.BINANCE]

    assert (pool.venue, pool.settlement_currency) == (Venue.USDT_M, Currency.USDT)


def test_the_constant_names_exactly_the_two_exchanges_that_can_execute() -> None:
    """Pionex is outside it: no futures order placement, and its script never
    goes through ``SaveCredential``."""
    assert set(KNOWN_FUTURES_POOLS) == {Exchange.BYBIT, Exchange.BINANCE}


def test_every_known_pool_is_a_futures_pool_never_spot() -> None:
    """One USDT balance stands behind Bybit's spot and linear products, so a
    spot pool beside the usdt-m one could reserve the same money twice."""
    venues = {exchange: pool.venue for exchange, pool in KNOWN_FUTURES_POOLS.items()}

    assert Venue.SPOT not in venues.values()
    assert Venue.COIN_M not in venues.values()


def test_each_exchange_has_exactly_one_pool_and_it_is_immutable() -> None:
    with pytest.raises(TypeError):
        KNOWN_FUTURES_POOLS[Exchange.PIONEX] = KnownPool(  # type: ignore[index]
            Venue.SPOT, Currency.USDT, Decimal("10")
        )


@pytest.mark.parametrize("exchange", [Exchange.BYBIT, Exchange.BINANCE])
def test_default_min_order_size_matches_the_seeded_usdt_m_row(exchange: Exchange) -> None:
    """Migration 0003 seeded ``usdt-m/USDT`` at 5; a row inserted from scratch
    starts at the same figure instead of a second, competing number."""
    assert KNOWN_FUTURES_POOLS[exchange].default_min_order_size == Decimal("5")


def test_known_pool_for_reads_by_plain_string() -> None:
    """The request path hands over a string, not an ``Exchange``."""
    assert known_pool_for("bybit") is KNOWN_FUTURES_POOLS[Exchange.BYBIT]


@pytest.mark.parametrize("exchange", ["pionex", "kraken", ""])
def test_an_exchange_without_a_known_pool_raises_no_fallback(exchange: str) -> None:
    with pytest.raises(InvariantViolation):
        known_pool_for(exchange)
