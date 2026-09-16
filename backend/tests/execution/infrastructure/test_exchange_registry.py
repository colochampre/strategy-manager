"""Pool-to-adapter selection.

This is the class that closes the gap behind the worst bug this system has
had: ``venue`` reached the reservation, the attempt and the ledger row and
never once selected an adapter, so a usdt-m strategy was sized against the
futures wallet and executed on spot.

The key is ``(exchange, venue)``. A venue alone stopped identifying an adapter
the moment two exchanges offered the same one, and routing by venue would send
a Binance pool's order to whichever adapter claimed ``usdt-m`` first.
"""

import pytest

from strategy_manager.execution.application.ports import ExchangeError
from strategy_manager.execution.infrastructure.exchange_registry import (
    VenueExchangeRegistry,
)


class StubAdapter:
    def __init__(
        self, exchange: str, venues: set[str], *, is_live: bool = True
    ) -> None:
        self.exchange = exchange
        self.venues = frozenset(venues)
        self.is_live = is_live


def test_each_pool_selects_the_adapter_that_declares_it() -> None:
    spot = StubAdapter("pionex", {"spot"})
    futures = StubAdapter("bybit", {"usdt-m"})
    registry = VenueExchangeRegistry([spot, futures])  # type: ignore[list-item]

    assert registry.for_pool("pionex", "spot") is spot
    assert registry.for_pool("bybit", "usdt-m") is futures


def test_one_venue_on_two_exchanges_selects_two_different_adapters() -> None:
    """THE reason the exchange joins the key: both adapters trade usdt-m, and
    a pool's money exists on exactly one of them."""
    bybit = StubAdapter("bybit", {"usdt-m"})
    binance = StubAdapter("binance", {"usdt-m"})
    registry = VenueExchangeRegistry([bybit, binance])  # type: ignore[list-item]

    assert registry.for_pool("bybit", "usdt-m") is bybit
    assert registry.for_pool("binance", "usdt-m") is binance


def test_an_unserved_pool_raises_rather_than_falling_back() -> None:
    """There is no sensible default. The failure being prevented is an order
    reaching the wrong wallet, and a fallback is exactly that."""
    registry = VenueExchangeRegistry([StubAdapter("bybit", {"usdt-m"})])  # type: ignore[list-item]

    with pytest.raises(ExchangeError, match="no exchange adapter serves pool"):
        registry.for_pool("binance", "usdt-m")


def test_the_refusal_names_what_is_registered() -> None:
    """The operator's two remedies -- disable the pool, or register an adapter
    -- both need to know which pools are actually served."""
    registry = VenueExchangeRegistry([StubAdapter("pionex", {"spot"})])  # type: ignore[list-item]

    with pytest.raises(ExchangeError, match="registered pools are pionex/spot"):
        registry.for_pool("bybit", "usdt-m")


def test_two_adapters_claiming_one_pool_is_refused_at_construction() -> None:
    """An ambiguous selection is the bug this class exists to prevent, so it
    fails at startup rather than picking one silently."""
    with pytest.raises(ExchangeError, match="claimed by both"):
        VenueExchangeRegistry(  # type: ignore[list-item]
            [StubAdapter("bybit", {"usdt-m"}), StubAdapter("bybit", {"usdt-m", "spot"})]
        )


def test_two_adapters_sharing_a_venue_on_different_exchanges_is_fine() -> None:
    registry = VenueExchangeRegistry(  # type: ignore[list-item]
        [StubAdapter("bybit", {"usdt-m"}), StubAdapter("binance", {"usdt-m"})]
    )

    assert registry.pools == frozenset({("bybit", "usdt-m"), ("binance", "usdt-m")})


def test_the_registry_reports_the_union_of_every_adapters_pools() -> None:
    registry = VenueExchangeRegistry(  # type: ignore[list-item]
        [StubAdapter("pionex", {"spot"}), StubAdapter("bybit", {"usdt-m"})]
    )

    assert registry.pools == frozenset({("pionex", "spot"), ("bybit", "usdt-m")})


def test_it_is_live_only_when_every_adapter_is() -> None:
    """The DRY_RUN invariant asks whether this configuration can reach a real
    exchange. One live adapter among fakes already answers yes."""
    all_live = VenueExchangeRegistry(  # type: ignore[list-item]
        [StubAdapter("pionex", {"spot"}), StubAdapter("bybit", {"usdt-m"})]
    )
    mixed = VenueExchangeRegistry(  # type: ignore[list-item]
        [StubAdapter("pionex", {"spot"}), StubAdapter("bybit", {"usdt-m"}, is_live=False)]
    )

    assert all_live.is_live is True
    assert mixed.is_live is False


def test_an_empty_registry_serves_nothing_and_says_so() -> None:
    registry = VenueExchangeRegistry([])

    assert registry.pools == frozenset()
    with pytest.raises(ExchangeError, match="registered pools are none"):
        registry.for_pool("bybit", "usdt-m")
