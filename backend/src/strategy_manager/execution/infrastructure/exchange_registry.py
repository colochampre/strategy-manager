"""Which adapter actually trades a given pool.

This module exists because of a bug that was invisible for weeks. ``venue``
travelled faithfully from ``capital_pools`` through the reservation, the
execution attempt and the ledger row -- and was never once consulted when the
order was sent. A strategy on a ``usdt-m`` pool had its size computed from the
futures wallet, because the balance reader DID map venues onto wallets, and
then had that order placed on spot. Two different pools of money, one order,
nothing raised, and a ledger row claiming a trade happened somewhere it did
not.

The fix is not a check. It is making the selection exist at all: one place
that maps a pool to the adapter that serves it, so "which pool is this?" has
exactly one answer and every use case asks the same question.

The key is ``(exchange, venue)``, not the venue alone. Once Binance and Bybit
both offer ``usdt-m``, a venue selects nothing: a Binance pool's order routed
by venue would reach whichever adapter claimed it first, against an account
that does not hold that pool's money.

A pool nothing serves raises here rather than falling back to any adapter.
There is no sensible default: the whole failure being prevented is an order
reaching the wrong wallet, and a fallback is precisely that.
"""

from collections.abc import Iterable, Mapping

from strategy_manager.execution.application.ports import ExchangeError, ExchangePort

PoolRoute = tuple[str, str]
"""``(exchange, venue)`` — what selects an adapter."""


class VenueExchangeRegistry:
    """Implements ``ExchangeRegistryPort`` over a fixed set of adapters."""

    def __init__(self, adapters: Iterable[ExchangePort]) -> None:
        by_pool: dict[PoolRoute, ExchangePort] = {}
        for adapter in adapters:
            for venue in adapter.venues:
                route = (adapter.exchange, venue)
                existing = by_pool.get(route)
                if existing is not None:
                    # Two adapters claiming one pool means the selection is
                    # ambiguous, and an ambiguous selection is the bug this
                    # class exists to prevent. Refuse at construction, which
                    # is startup, rather than picking one silently.
                    raise ExchangeError(
                        f"pool {route[0]}/{route[1]} is claimed by both "
                        f"{type(existing).__name__} and {type(adapter).__name__}; "
                        "exactly one adapter must serve each pool"
                    )
                by_pool[route] = adapter
        self._by_pool = by_pool

    @property
    def pools(self) -> frozenset[PoolRoute]:
        """Every ``(exchange, venue)`` this registry can trade, for the startup
        warning and the per-signal refusal."""
        return frozenset(self._by_pool)

    @property
    def is_live(self) -> bool:
        """True only if EVERY registered adapter is live.

        The ``DRY_RUN`` invariant asks "can this configuration reach a real
        exchange?", and one live adapter among fakes answers yes. Anything
        weaker would let a live futures adapter ride along in a run the
        operator believes is dry.
        """
        return all(adapter.is_live for adapter in self._by_pool.values())

    @property
    def adapters(self) -> Mapping[PoolRoute, ExchangePort]:
        """Read-only view, for composition and for tests that assert wiring."""
        return dict(self._by_pool)

    def for_pool(self, exchange: str, venue: str) -> ExchangePort:
        adapter = self._by_pool.get((exchange, venue))
        if adapter is None:
            served = ", ".join(f"{e}/{v}" for e, v in sorted(self._by_pool))
            raise ExchangeError(
                f"no exchange adapter serves pool {exchange}/{venue}; registered "
                f"pools are {served or 'none'}"
            )
        return adapter
