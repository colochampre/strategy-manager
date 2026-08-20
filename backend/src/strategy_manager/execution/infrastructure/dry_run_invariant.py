"""Startup invariant: ``DRY_RUN=false`` requires a real exchange adapter.

Specified by ``trade-execution § DRY_RUN Safety`` — "the composition root MUST
fail startup if ``dry_run=false`` is configured while no real (non-fake)
``ExchangePort`` adapter is registered".

The configuration this catches is the one that reads as intentional and is
not. Turning ``DRY_RUN`` off is a deliberate act that means "trade for real",
so the operator who does it believes real orders are going out. With only a
fake adapter registered, every signal instead reports a perfect fill at a
fixed price against no exchange at all: a strategy that looks live, looks
profitable, and has never placed an order. Refusing to start is the only
outcome that tells the truth.
"""

from strategy_manager.execution.application.ports import ExchangePort
from strategy_manager.shared.domain.errors import InvariantViolation


def assert_dry_run_safe(*, dry_run: bool, exchange: ExchangePort) -> None:
    if dry_run or exchange.is_live:
        return

    raise InvariantViolation(
        f"DRY_RUN is false but the registered ExchangePort adapter "
        f"({type(exchange).__name__}) is not live. Refusing to start: this "
        "configuration reports fabricated fills while appearing to trade. "
        "Set DRY_RUN=true, or register a live exchange adapter."
    )
