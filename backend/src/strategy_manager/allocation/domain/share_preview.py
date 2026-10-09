"""STUB (12f.9.9, RED commit): answers a zero amount for every share."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ShareAmount:
    share: Decimal
    amount: Decimal
    below_pool_minimum: bool


def share_amount(total: Decimal, share: Decimal, minimum: Decimal) -> ShareAmount:
    return ShareAmount(share=share, amount=Decimal(0), below_pool_minimum=False)


def step_amounts(total: Decimal, minimum: Decimal) -> tuple[ShareAmount, ...]:
    return tuple(share_amount(total, Decimal(n), minimum) for n in range(1, 101))
