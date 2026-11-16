"""How one venue fill becomes one ledger row (CLAUDE.md rules 6 and 7).

One function, so the fills ``SettleExecution`` books for an order this system placed and the
fills ``WatchProtectiveStops`` books for a stop that fired at the venue take exactly the
same shape: the attempt's allocation, one row per fill rather than an average, and the USD
rate resolved once per settlement and never backfilled.
"""

from decimal import Decimal
from uuid import UUID

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
from strategy_manager.execution.domain.fill import Fill


def fill_record_of(
    user_id: UUID,
    attempt: ExecutionAttempt,
    strategy_id: UUID,
    usd_rate: Decimal,
    fill: Fill,
) -> FillRecord:
    """The ledger row for ``fill`` under ``attempt``'s allocation.

    A market order can come back as several fills at different prices, and each one is
    recorded so the ledger stays a faithful account of what happened rather than an average
    that cannot be reconciled against the exchange. ``usd_rate`` is resolved once for the
    whole settlement and passed in: every fill of one order settles at one instant, and rule
    7 wants the rate at fill time, not a different rate per row."""
    return FillRecord(
        user_id=user_id,
        strategy_id=strategy_id,
        allocation_id=attempt.allocation_id,
        execution_attempt_id=attempt.id,
        exchange=attempt.exchange,
        venue=attempt.venue,
        settlement_currency=attempt.settlement_currency,
        symbol=attempt.symbol,
        side=attempt.side.value,
        quantity=fill.quantity,
        price=fill.price,
        fee=fill.fee,
        fee_currency=fill.fee_currency,
        notional=fill.quantity * fill.price,
        exchange_order_id=fill.exchange_order_id,
        exchange_fill_id=fill.exchange_fill_id,
        filled_at=fill.filled_at,
        usd_rate_at_fill=usd_rate,
    )
