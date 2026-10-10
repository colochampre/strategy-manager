"""What a share of a pool's TOTAL balance asks for, and whether that is enough to
trade (design.md, unit 12f addendum, sections C2 and C3; spec: admin-api "The Share
Preview Route Serves The Amount A Share Asks For").

The amount is NOT a second implementation of the engine's sizing. It is
``requested_from_percent``, the very function the worker sizes a request with, so
the figure the panel shows and the request the allocation makes cannot drift apart.
``below_pool_minimum`` is the comparison ``decide()`` makes first (rule 1: a
request below ``min_order_size`` is skipped), strictly below, so an amount equal to
the minimum is NOT flagged.

No framework imports, no I/O, no clock: pure ``Decimal`` arithmetic.
"""

from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.allocation.domain.percent import requested_from_percent


@dataclass(frozen=True, slots=True)
class ShareAmount:
    """One share and what it asks for. ``share`` is a percentage (``33.5`` is
    33.5%), ``amount`` is in the pool's settlement currency."""

    share: Decimal
    amount: Decimal
    below_pool_minimum: bool


def share_amount(total: Decimal, share: Decimal, minimum: Decimal) -> ShareAmount:
    """``share`` percent of ``total``, cut down to 18 places, and whether it is
    below ``minimum``. ``total`` is the pool's TOTAL, never what is free."""

    amount = requested_from_percent(total, share)
    return ShareAmount(share=share, amount=amount, below_pool_minimum=amount < minimum)


def step_amounts(total: Decimal, minimum: Decimal) -> tuple[ShareAmount, ...]:
    """The hundred whole shares, 1 to 100, each exactly ``share_amount``."""

    return tuple(share_amount(total, Decimal(n), minimum) for n in range(1, 101))
