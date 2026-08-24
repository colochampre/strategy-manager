"""Venue-to-adapter selection.

This is the class that closes the gap behind the worst bug this system has
had: ``venue`` reached the reservation, the attempt and the ledger row and
never once selected an adapter, so a usdt-m strategy was sized against the
futures wallet and executed on spot.
"""

import pytest

from strategy_manager.execution.application.ports import ExchangeError
from strategy_manager.execution.infrastructure.exchange_registry import (
    VenueExchangeRegistry,
)


class StubAdapter:
    def __init__(self, venues: set[str], *, is_live: bool = True) -> None:
        self.venues = frozenset(venues)
        self.is_live = is_live


def test_each_venue_selects_the_adapter_that_declares_it() -> None:
    spot = StubAdapter({"spot"})
    futures = StubAdapter({"usdt-m"})
    registry = VenueExchangeRegistry([spot, futures])  # type: ignore[list-item]

    assert registry.for_venue("spot") is spot
    assert registry.for_venue("usdt-m") is futures


def test_an_unserved_venue_raises_rather_than_falling_back() -> None:
    """There is no sensible default. The failure being prevented is an order
    reaching the wrong wallet, and a fallback is exactly that."""
    registry = VenueExchangeRegistry([StubAdapter({"spot"})])  # type: ignore[list-item]

    with pytest.raises(ExchangeError, match="no exchange adapter serves venue"):
        registry.for_venue("coin-m")


def test_the_refusal_names_what_is_registered() -> None:
    """The operator's two remedies -- disable the pool, or register an adapter
    -- both need to know which venues are actually served."""
    registry = VenueExchangeRegistry([StubAdapter({"spot"})])  # type: ignore[list-item]

    with pytest.raises(ExchangeError, match="registered venues are spot"):
        registry.for_venue("usdt-m")


def test_two_adapters_claiming_one_venue_is_refused_at_construction() -> None:
    """An ambiguous selection is the bug this class exists to prevent, so it
    fails at startup rather than picking one silently."""
    with pytest.raises(ExchangeError, match="claimed by both"):
        VenueExchangeRegistry(  # type: ignore[list-item]
            [StubAdapter({"spot"}), StubAdapter({"spot", "usdt-m"})]
        )


def test_the_registry_reports_the_union_of_every_adapters_venues() -> None:
    registry = VenueExchangeRegistry(  # type: ignore[list-item]
        [StubAdapter({"spot"}), StubAdapter({"usdt-m"})]
    )

    assert registry.venues == frozenset({"spot", "usdt-m"})


def test_it_is_live_only_when_every_adapter_is() -> None:
    """The DRY_RUN invariant asks whether this configuration can reach a real
    exchange. One live adapter among fakes already answers yes."""
    all_live = VenueExchangeRegistry(  # type: ignore[list-item]
        [StubAdapter({"spot"}), StubAdapter({"usdt-m"})]
    )
    mixed = VenueExchangeRegistry(  # type: ignore[list-item]
        [StubAdapter({"spot"}), StubAdapter({"usdt-m"}, is_live=False)]
    )

    assert all_live.is_live is True
    assert mixed.is_live is False


def test_an_empty_registry_serves_nothing_and_says_so() -> None:
    registry = VenueExchangeRegistry([])

    assert registry.venues == frozenset()
    with pytest.raises(ExchangeError, match="registered venues are none"):
        registry.for_venue("spot")
