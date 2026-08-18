"""Pure function deriving the requested allocation amount from a strategy's
configured percentage applied to the pool BALANCE — the owner's explicit
decision 2026-08-18, superseding an earlier "percentage of availability"
draft (design.md § "Order size never comes from the alert"; tasks.md 7.3/7.4).

No framework imports, no I/O, no clock — pure ``Decimal`` arithmetic, per the
layering rule that ``domain`` never depends on FastAPI, SQLAlchemy or httpx.
``decide()`` (``allocation/domain/decision.py``) is unchanged: this function
only caps the *ask*; the advisory lock and ``decide()`` still govern the
*grant*.
"""

from decimal import ROUND_DOWN, Decimal

# Matches the numeric(38,18) scale used for money-bearing columns elsewhere
# in this schema (design.md § SQL Schema and Migration Map).
_QUANTUM = Decimal("0.000000000000000001")


def requested_from_percent(balance: Decimal, percent: Decimal) -> Decimal:
    """``requested = balance * percent / 100``, quantized ``ROUND_DOWN`` — the
    engine never rounds up, because rounding up is over-allocation
    (design.md's ``decide()`` invariants). A 100% strategy requests exactly
    the balance.
    """

    return (balance * percent / Decimal("100")).quantize(_QUANTUM, rounding=ROUND_DOWN)
