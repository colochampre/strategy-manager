"""Which adapter actually trades a given venue.

This module exists because of a bug that was invisible for weeks. ``venue``
travelled faithfully from ``capital_pools`` through the reservation, the
execution attempt and the ledger row -- and was never once consulted when the
order was sent. A strategy on a ``usdt-m`` pool had its size computed from the
futures wallet, because the balance reader DID map venues onto wallets, and
then had that order placed on spot. Two different pools of money, one order,
nothing raised, and a ledger row claiming a trade happened somewhere it did
not.

The fix is not a check. It is making the selection exist at all: one place
that maps a venue to the adapter that serves it, so "which venue is this?" has
exactly one answer and every use case asks the same question.

A venue nothing serves raises here rather than falling back to any adapter.
There is no sensible default: the whole failure being prevented is an order
reaching the wrong wallet, and a fallback is precisely that.
"""

from collections.abc import Iterable, Mapping

from strategy_manager.execution.application.ports import ExchangeError, ExchangePort


class VenueExchangeRegistry:
    """Implements ``ExchangeRegistryPort`` over a fixed set of adapters."""

    def __init__(self, adapters: Iterable[ExchangePort]) -> None:
        by_venue: dict[str, ExchangePort] = {}
        for adapter in adapters:
            for venue in adapter.venues:
                existing = by_venue.get(venue)
                if existing is not None:
                    # Two adapters claiming one venue means the selection is
                    # ambiguous, and an ambiguous selection is the bug this
                    # class exists to prevent. Refuse at construction, which
                    # is startup, rather than picking one silently.
                    raise ExchangeError(
                        f"venue {venue!r} is claimed by both "
                        f"{type(existing).__name__} and {type(adapter).__name__}; "
                        "exactly one adapter must serve each venue"
                    )
                by_venue[venue] = adapter
        self._by_venue = by_venue

    @property
    def venues(self) -> frozenset[str]:
        """Every venue this registry can trade, for the startup warning and
        the per-signal refusal."""
        return frozenset(self._by_venue)

    @property
    def is_live(self) -> bool:
        """True only if EVERY registered adapter is live.

        The ``DRY_RUN`` invariant asks "can this configuration reach a real
        exchange?", and one live adapter among fakes answers yes. Anything
        weaker would let a live futures adapter ride along in a run the
        operator believes is dry.
        """
        return all(adapter.is_live for adapter in self._by_venue.values())

    @property
    def adapters(self) -> Mapping[str, ExchangePort]:
        """Read-only view, for composition and for tests that assert wiring."""
        return dict(self._by_venue)

    def for_venue(self, venue: str) -> ExchangePort:
        adapter = self._by_venue.get(venue)
        if adapter is None:
            raise ExchangeError(
                f"no exchange adapter serves venue {venue!r}; registered venues "
                f"are {', '.join(sorted(self._by_venue)) or 'none'}"
            )
        return adapter
