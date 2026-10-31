"""Builders for the guard's own elements, shared by the open-positions tests.

The ids are fresh on every call: a case is told apart by what it holds, never
by a fixed id. Symbols are spelled the way the ledger writes them (``.P`` for a
TradingView perpetual); a test that crosses a module boundary spells the same
market differently on each side (design section L, "Symbols").
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.domain.fill import REHEARSAL_ORDER_ID_PREFIX
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)
from strategy_manager.performance.application.ports import PositionFacts, SubmittedOrder
from strategy_manager.performance.domain.open_position import FillAggregate, PoolLabel
from strategy_manager.shared.domain.mode import Mode
from tests.owner import OWNER_ID

POOL = PoolLabel("bybit", "usdt-m", "USDT")
T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


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
        user_id=OWNER_ID,
        mode=Mode.LIVE if live else Mode.SIMULATION,
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
        mode=Mode.SIMULATION if rehearsal else Mode.LIVE,
        strategy_name=name,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        symbol=symbol,
        exchange_order_id=order_id,
    )


def fill_aggregate(
    allocation_id: UUID,
    strategy_id: UUID,
    *,
    side: str = "BUY",
    quantity: str = "1",
    price: str = "10",
    symbol: str = "STXUSDT.P",
    fee: str = "0",
    fee_currency: str = "USDT",
    pool: PoolLabel = POOL,
    at: datetime = T0,
    fill_count: int = 1,
) -> FillAggregate:
    qty = Decimal(quantity)
    return FillAggregate(
        allocation_id=allocation_id,
        strategy_id=strategy_id,
        exchange=pool.exchange,
        venue=pool.venue,
        settlement_currency=pool.settlement_currency,
        symbol=symbol,
        side=side,
        fee_currency=fee_currency,
        quantity=qty,
        notional=qty * Decimal(price),
        fee=Decimal(fee),
        first_filled_at=at,
        fill_count=fill_count,
    )


def position_facts(
    allocation_id: UUID,
    strategy_id: UUID,
    groups: tuple[FillAggregate, ...],
    *,
    name: str = "Alpha",
    archived: bool = False,
    margin: str = "20",
    status: str = "FILLED",
    leverage: str | None = "3",
    reservation_pool: PoolLabel = POOL,
) -> PositionFacts:
    return PositionFacts(
        allocation_id=allocation_id,
        strategy_id=strategy_id,
        strategy_name=name,
        strategy_archived=archived,
        margin_granted=Decimal(margin),
        reservation_status=status,
        leverage=None if leverage is None else Decimal(leverage),
        reservation_pool=reservation_pool,
        groups=groups,
    )


def submitted_order(
    attempt_id: UUID,
    *,
    opening: bool = True,
    symbol: str = "STXUSDT.P",
    order_id: str | None = "ORDER-1",
    created_at: datetime = T0,
    strategy_id: UUID | None = None,
    name: str | None = "Beta",
    archived: bool | None = False,
    pool: PoolLabel = POOL,
    reservation_pool: PoolLabel | None = POOL,
) -> SubmittedOrder:
    return SubmittedOrder(
        attempt_id=attempt_id,
        opening=opening,
        pool=pool,
        symbol=symbol,
        exchange_order_id=order_id,
        created_at=created_at,
        strategy_id=strategy_id,
        strategy_name=name,
        strategy_archived=archived,
        reservation_pool=reservation_pool,
    )
