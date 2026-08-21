"""Which configured pools the registered exchange adapter can actually trade.

``venue`` is carried faithfully from ``capital_pools`` through the
reservation, the execution attempt and the ledger row -- and never once
consulted when the order is sent. ``PionexTradeClient`` speaks ``/api/v1/``,
which is spot. Pionex's futures API is ``/uapi/v1/``: a different base path,
different semantics, a different adapter.

So a strategy on a ``usdt-m`` pool has its size computed from the futures
wallet, because ``PionexBalanceReader`` does map venues onto wallets, and then
has that order placed on spot. Two different pools of money, one order, and
nothing raised. The ledger would record ``venue = 'usdt-m'`` for a trade that
happened on spot, and rule 7's per-pool PnL would be reported against a wallet
that never moved.

**This module reports; it does not refuse.** The refusal belongs to the signal
that would actually be mispriced, in ``ProcessSignalHandler``, where it costs
that one signal and nothing else.

Refusing at startup was the first attempt and it was disproportionate: a
``coin-m`` pool that no strategy trades would have stopped the worker
outright, taking spot trading down with it over a configuration nobody was
using. Prevention that halts the working parts along with the broken one is
not prevention, it is an outage.

What startup owes the operator is the WARNING -- the pools are known there, the
adapter is known there, and finding out at boot beats finding out per signal.
"""

from collections.abc import Sequence

from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.execution.application.ports import ExchangePort


def untradable_pool_venues(
    *, exchange: ExchangePort | type[ExchangePort], pools: Sequence[PoolConfig]
) -> list[str]:
    """Venues among the enabled pools that this adapter cannot trade, sorted.

    Accepts an adapter or an adapter class, for the same reason
    ``assert_dry_run_safe`` does: the live adapter is built per job and does
    not exist yet at startup.
    """
    return sorted(
        {pool.venue.value for pool in pools if pool.venue.value not in exchange.venues}
    )


def describe_untradable(
    *, exchange: ExchangePort | type[ExchangePort], untradable: Sequence[str]
) -> str:
    """The startup warning's text. Names both halves of the mismatch, because
    the operator's two remedies -- disable those pools, or register an adapter
    that serves them -- both need to know which is which."""
    served = ", ".join(sorted(exchange.venues)) or "nothing"
    return (
        f"{_name(exchange)} trades {served}, but enabled capital pools exist on "
        f"{', '.join(untradable)}. Signals for strategies on those venues will "
        "be refused rather than executed against the wrong wallet. Disable "
        "those pools, or register an adapter that serves them."
    )


def _name(exchange: ExchangePort | type[ExchangePort]) -> str:
    return exchange.__name__ if isinstance(exchange, type) else type(exchange).__name__
