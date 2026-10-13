"""Builders for the guard's own elements, shared by the open-positions tests.

The ids are fresh on every call: a case is told apart by what it holds, never
by a fixed id. Symbols are spelled the way the ledger writes them (``.P`` for a
TradingView perpetual); a test that crosses a module boundary spells the same
market differently on each side (design section L, "Symbols").
"""

from uuid import UUID, uuid4

from strategy_manager.execution.domain.fill import REHEARSAL_ORDER_ID_PREFIX
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)


def open_element(
    *,
    rehearsal: bool,
    live: bool,
    allocation_id: UUID | None = None,
    name: str = "Alpha",
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
    symbol: str = "SOLUSDT.P",
) -> OpenAllocationOrigin:
    return OpenAllocationOrigin(
        allocation_id=allocation_id or uuid4(),
        strategy_name=name,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        symbol=symbol,
        holds_rehearsal_fill=rehearsal,
        holds_live_fill=live,
    )


def in_flight_element(
    *,
    rehearsal: bool,
    attempt_id: UUID | None = None,
    name: str = "Beta",
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
    symbol: str = "ETHUSDT.P",
) -> InFlightAttemptOrigin:
    attempt = attempt_id or uuid4()
    order_id = f"{REHEARSAL_ORDER_ID_PREFIX}{attempt}" if rehearsal else f"ORDER-{attempt}"
    return InFlightAttemptOrigin(
        attempt_id=attempt,
        strategy_name=name,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        symbol=symbol,
        exchange_order_id=order_id,
    )
