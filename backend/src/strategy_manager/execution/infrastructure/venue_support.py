"""Which configured pools the registered exchange adapters can actually trade.

``venue`` is carried faithfully from ``capital_pools`` through the
reservation, the execution attempt and the ledger row -- and was never once
consulted when the order was sent. ``PionexTradeClient`` speaks ``/api/v1/``,
which is spot. Pionex's futures API is ``/uapi/v1/``: a different base path,
different semantics, a different adapter.

So a strategy on a ``usdt-m`` pool had its size computed from the futures
wallet, because ``PionexBalanceReader`` does map venues onto wallets, and then
had that order placed on spot. Two different pools of money, one order, and
nothing raised.

The question is now asked per POOL, ``(exchange, venue)``, because a venue on
its own stopped identifying an adapter: Binance and Bybit both offer
``usdt-m``, and a pool's money exists on exactly one of them.

**This module reports; it does not refuse.** The refusal belongs to the signal
that would actually be mispriced, in ``ProcessSignalHandler``, where it costs
that one signal and nothing else.

Refusing at startup was the first attempt and it was disproportionate: a
``coin-m`` pool that no strategy trades would have stopped the worker
outright, taking spot trading down with it over a configuration nobody was
using. Prevention that halts the working parts along with the broken one is
not prevention, it is an outage.

What startup owes the operator is the WARNING -- the pools are known there, the
adapters are known there, and finding out at boot beats finding out per signal.
"""

from collections.abc import Sequence

from strategy_manager.accounts.domain.pool_config import PoolConfig

PoolRoute = tuple[str, str]
"""``(exchange, venue)`` — what selects an adapter."""


def pool_route(pool: PoolConfig) -> PoolRoute:
    return (pool.exchange.value, pool.venue.value)


def unserved_pools(
    *, served: frozenset[PoolRoute], pools: Sequence[PoolConfig]
) -> list[str]:
    """Enabled pools that NO registered adapter trades, as ``exchange/venue``.

    The union across adapters is the honest question once more than one
    exists. Asking it per adapter reports every futures pool as untradable
    merely because the spot adapter does not serve it -- noise that trains an
    operator to ignore the one warning that matters.
    """
    return sorted(
        {
            f"{exchange}/{venue}"
            for exchange, venue in (pool_route(pool) for pool in pools)
            if (exchange, venue) not in served
        }
    )


def describe_unserved(
    *, served: frozenset[PoolRoute], by: str, unserved: Sequence[str]
) -> str:
    """The startup warning's text. Names both halves of the mismatch, because
    the operator's two remedies -- disable those pools, or register an adapter
    that serves them -- both need to know which is which."""
    trades = ", ".join(sorted(f"{exchange}/{venue}" for exchange, venue in served)) or "nothing"
    return (
        f"{by} trades {trades}, but enabled capital pools exist on "
        f"{', '.join(unserved)}. Signals for strategies on those pools will "
        "be refused rather than executed against the wrong wallet. Disable "
        "those pools, or register an adapter that serves them."
    )
