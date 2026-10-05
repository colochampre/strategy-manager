"""``/performance``: what the ledger says about one pool and one strategy
(design.md sections 11 and 14).

Four read-only routes:

- ``GET /performance/pools/{exchange}/{venue}/{ccy}``: one pool's report.
- ``GET /performance/strategies/{id}``: one strategy's report inside its pool,
  plus ``by_pair``.
- ``GET /performance/strategies/{id}/trades/{allocation_id}/fills``: the individual
  fills of one operation, oldest first, capped at 200. An unknown id, another
  strategy's operation and an allocation with no fill are one 404.
- ``GET /performance/strategies/{id}/trades``: its closed operations, newest
  first, in keyset pages. Each row carries its prices, size and fees; rehearsal
  (dry-run) operations are listed only for ``include_rehearsal=true`` and each row
  says whether it is one.

**Rule 7 (no cross-pool total) and decision 1 (one strategy per pool).** Every
body is one pool in its own settlement currency. There is no route, field or
type here that combines two pools, including two on one exchange.

**A strategy binds to its OWN pool.** The strategy routes take no pool. They
load the strategy first (404 if it does not exist; an archived strategy is
found, since archiving hides a strategy and does not erase its history) and read
through ``PoolKey(strategy's exchange, venue, settlement currency)``. This is
the router's job and cannot be left to the reads: a read given the wrong pool
returns an empty result, not an error, because the ledger cannot tell "no
trades" from "not this pool's strategy".

**The wire** (``shared.infrastructure.wire``): money, quantities, prices and
ratios are JSON strings in plain notation, prices to 18 places and ratios to 10;
instants are UTC. A row's four figures (``base_currency``, ``entry_price``,
``exit_price``, ``size``) are null together when they cannot be derived, never
zero, and ``other_fees`` lists each fee that is not in the settlement currency in
its own currency, never converted. The one field that is
a Python keyword on the wire, ``return``, is a serialization alias.

**What a refused read looks like.** A read that finds its data inconsistent (a
row of another pool, an allocation split over two strategies, a non-positive
capital) raises ``InvariantViolation``. It is answered with a fixed 500 that
echoes nothing, and ONE ``ERROR`` is logged with the reason: without it the only
trace would be a status code. ``ERROR`` and not ``WARNING`` because this is a
fault in stored data, not a steady-state exclusion (those are counted in the
body instead), and it fires per request only while the fault exists.

Authentication is attached to the ROUTER (see ``strategies/infrastructure/
router.py`` for why it is structural).
"""

import logging
from collections.abc import Awaitable
from datetime import date as calendar_date
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.ports import (
    AllocationFillsSourcePort,
    OperationFillsSourcePort,
    RehearsalPricingSourcePort,
)
from strategy_manager.performance.application.read_operation_fills import (
    ReadOperationFills,
    UnknownOperation,
)
from strategy_manager.performance.application.read_pool_performance import ReadPoolPerformance
from strategy_manager.performance.application.read_strategy_performance import (
    ReadStrategyPerformance,
    StrategyPerformance,
)
from strategy_manager.performance.application.read_strategy_trades import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    InvalidPageRequest,
    ReadStrategyTrades,
    TradeCursor,
    TradeItem,
    TradesPage,
)
from strategy_manager.performance.domain.by_pair import PairStats
from strategy_manager.performance.domain.curve import PoolPerformance
from strategy_manager.performance.infrastructure.allocation_fills_source import (
    SqlAlchemyAllocationFillsSource,
)
from strategy_manager.performance.infrastructure.operation_fills_source import (
    SqlAlchemyOperationFillsSource,
)
from strategy_manager.performance.infrastructure.pool_lookup import SqlAlchemyPoolLookup
from strategy_manager.performance.infrastructure.rehearsal_pricing_source import (
    SqlAlchemyRehearsalPricingSource,
)
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.db import get_session
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.wire import Instant, Money, Price, Ratio
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/performance",
    tags=["performance"],
    dependencies=[Depends(require_admin_token)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

INTEGRITY_FAULT_DETAIL = "performance data failed an integrity check"


def get_clock() -> ClockPort:
    return SystemClock()


def get_fills_source(session: SessionDep) -> AllocationFillsSourcePort:
    return SqlAlchemyAllocationFillsSource(session)


def get_pricing_source(session: SessionDep) -> RehearsalPricingSourcePort:
    return SqlAlchemyRehearsalPricingSource(session)


def get_operation_fills_source(session: SessionDep) -> OperationFillsSourcePort:
    return SqlAlchemyOperationFillsSource(session)


ClockDep = Annotated[ClockPort, Depends(get_clock)]
FillsDep = Annotated[AllocationFillsSourcePort, Depends(get_fills_source)]
PricingDep = Annotated[RehearsalPricingSourcePort, Depends(get_pricing_source)]
OperationFillsDep = Annotated[OperationFillsSourcePort, Depends(get_operation_fills_source)]

async def _guarded[T](read: Awaitable[T]) -> T:
    """Runs a read, turning a refused one into a logged 500 (module docstring).
    ``InvalidPageRequest`` is not caught here: it is the caller's input."""
    try:
        return await read
    except InvariantViolation as exc:
        logger.error("performance read refused: %s", exc)
        raise HTTPException(status_code=500, detail=INTEGRITY_FAULT_DETAIL) from exc


# --- bodies ----------------------------------------------------------------------------


class PoolBody(BaseModel):
    exchange: str
    venue: str
    settlement_currency: str


class ExcludedBody(BaseModel):
    """What the figures leave out, so that nothing is hidden (decision 17)."""

    open_trade_count: int
    rehearsal_fill_count: int
    no_capital_at_open: int
    unconverted_fee: int
    unresolved_allocation_count: int


class RangeBody(BaseModel):
    """PnL and compounded return over one window ending now. ``return`` is never
    null: a window with no trades returns zero."""

    range: str
    pnl: Money
    value: Ratio = Field(serialization_alias="return")
    trade_count: int


class CurvePointBody(BaseModel):
    date: calendar_date
    daily_return: Ratio
    index: Ratio
    drawdown: Ratio


class MonthBody(BaseModel):
    year: int
    month: int
    value: Ratio = Field(serialization_alias="return")


class PerformanceBody(BaseModel):
    pool: PoolBody
    currency: str
    day_boundary: Literal["UTC"] = "UTC"
    trade_count: int
    total_pnl: Money
    max_drawdown: Ratio
    excluded: ExcludedBody
    ranges: list[RangeBody]
    curve: list[CurvePointBody]
    monthly: list[MonthBody]

    @classmethod
    def of(cls, report: PoolPerformance) -> "PerformanceBody":
        pool = report.pool
        return cls(
            pool=PoolBody(
                exchange=pool.exchange.value,
                venue=pool.venue.value,
                settlement_currency=pool.settlement_currency.value,
            ),
            currency=pool.settlement_currency.value,
            trade_count=report.closed_trade_count,
            total_pnl=report.total_pnl,
            max_drawdown=report.max_drawdown,
            excluded=ExcludedBody(
                open_trade_count=report.exclusions.open_trade_count,
                rehearsal_fill_count=report.exclusions.rehearsal_fill_count,
                no_capital_at_open=report.exclusions.no_capital_at_open,
                unconverted_fee=report.exclusions.unconverted_fee,
                unresolved_allocation_count=report.exclusions.unresolved_allocation_count,
            ),
            ranges=[
                RangeBody(
                    range=summary.range.value,
                    pnl=summary.pnl,
                    value=summary.value,
                    trade_count=summary.trade_count,
                )
                for summary in report.ranges
            ],
            curve=[
                CurvePointBody(
                    date=point.day,
                    daily_return=point.daily_return,
                    index=point.index,
                    drawdown=point.drawdown,
                )
                for point in report.curve
            ],
            monthly=[
                MonthBody(year=month.year, month=month.month, value=month.value)
                for month in report.monthly
            ],
        )


class PairBody(BaseModel):
    """``return`` is null when none of the pair's trades has a capital at open."""

    pair: str
    trades: int
    pnl: Money
    value: Ratio | None = Field(serialization_alias="return")

    @classmethod
    def of(cls, stats: PairStats) -> "PairBody":
        return cls(pair=stats.pair, trades=stats.trade_count, pnl=stats.pnl, value=stats.value)


class StrategyPerformanceBody(PerformanceBody):
    strategy_id: UUID
    by_pair: list[PairBody]

    @classmethod
    def from_strategy(cls, result: StrategyPerformance) -> "StrategyPerformanceBody":
        base = PerformanceBody.of(result.performance)
        return cls(
            **base.model_dump(),
            strategy_id=result.strategy_id,
            by_pair=[PairBody.of(stats) for stats in result.by_pair],
        )


class FeeBody(BaseModel):
    """A fee in the currency it was charged in. Never converted."""

    currency: str
    amount: Money


class TradeBody(BaseModel):
    allocation_id: UUID
    pair: str
    direction: Literal["LONG", "SHORT"]
    opened_at: Instant
    closed_at: Instant
    rehearsal: bool
    rehearsal_fill_price: Literal["FIXED_ONE", "ALERT", "UNDETERMINED"] | None
    base_currency: str | None
    entry_price: Price | None
    exit_price: Price | None
    size: Money | None
    fees: Money
    other_fees: list[FeeBody]
    pnl: Money
    capital_at_open: Money | None
    value: Ratio | None = Field(serialization_alias="return")
    fees_complete: bool

    @classmethod
    def of(cls, item: TradeItem) -> "TradeBody":
        trade = item.trade
        figures = item.figures
        return cls(
            allocation_id=trade.allocation_id,
            pair=trade.pair,
            direction=trade.direction.value,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
            rehearsal=item.rehearsal,
            rehearsal_fill_price=None if item.pricing is None else item.pricing.value,
            base_currency=None if figures is None else figures.base_currency,
            entry_price=None if figures is None else figures.entry_price,
            exit_price=None if figures is None else figures.exit_price,
            size=None if figures is None else figures.size,
            fees=item.fees.fees,
            other_fees=[
                FeeBody(currency=fee.currency, amount=fee.amount) for fee in item.fees.other_fees
            ],
            pnl=trade.pnl,
            capital_at_open=trade.pool_total_at_open,
            value=item.value,
            fees_complete=trade.fees_complete,
        )


class CursorBody(BaseModel):
    """The two query parameters that resume after the last trade served."""

    before_closed_at: Instant
    before_allocation_id: UUID


class TradesBody(BaseModel):
    """``next_cursor`` is null on the last page."""

    trades: list[TradeBody]
    next_cursor: CursorBody | None

    @classmethod
    def of(cls, page: TradesPage) -> "TradesBody":
        cursor = page.next_cursor
        return cls(
            trades=[TradeBody.of(item) for item in page.trades],
            next_cursor=(
                None
                if cursor is None
                else CursorBody(
                    before_closed_at=cursor.closed_at, before_allocation_id=cursor.allocation_id
                )
            ),
        )


class FillBody(BaseModel):
    """One fill, as stored: nothing averaged, rounded or converted. ``fee`` is in
    ``fee_currency``, which travels with it."""

    filled_at: Instant
    side: Literal["BUY", "SELL"]
    price: Money
    quantity: Money
    fee: Money
    fee_currency: str
    rehearsal: bool


class OperationFillsBody(BaseModel):
    """``allocation_id`` is the id asked for; ``fills`` is never empty."""

    allocation_id: UUID
    fills: list[FillBody]
    truncated: bool


# --- routes ----------------------------------------------------------------------------


async def _strategy_pool(session: AsyncSession, strategy_id: UUID) -> PoolKey:
    """The pool the strategy lives in, from the strategy row itself; 404 if there
    is no such strategy. Archived strategies are found."""
    strategy = await SqlAlchemyStrategyRepository(session).get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="no such strategy")
    policy = strategy.policy
    return PoolKey(policy.exchange, policy.venue, policy.settlement_currency)


@router.get("/pools/{exchange}/{venue}/{ccy}", response_model=PerformanceBody)
async def pool_performance(
    exchange: str, venue: str, ccy: str, session: SessionDep, fills: FillsDep, clock: ClockDep
) -> PerformanceBody:
    pool = await SqlAlchemyPoolLookup(session).find(exchange, venue, ccy)
    if pool is None:
        raise HTTPException(status_code=404, detail="no such pool")
    report = await _guarded(ReadPoolPerformance(fills, clock).read(pool))
    return PerformanceBody.of(report)


@router.get("/strategies/{strategy_id}", response_model=StrategyPerformanceBody)
async def strategy_performance(
    strategy_id: UUID, session: SessionDep, fills: FillsDep, clock: ClockDep
) -> StrategyPerformanceBody:
    pool = await _strategy_pool(session, strategy_id)
    result = await _guarded(ReadStrategyPerformance(fills, clock).read(strategy_id, pool))
    return StrategyPerformanceBody.from_strategy(result)


@router.get("/strategies/{strategy_id}/trades", response_model=TradesBody)
async def strategy_trades(
    strategy_id: UUID,
    session: SessionDep,
    fills: FillsDep,
    pricing: PricingDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    before_closed_at: datetime | None = None,
    before_allocation_id: UUID | None = None,
    include_rehearsal: bool = False,
) -> TradesBody:
    if (before_closed_at is None) != (before_allocation_id is None):
        missing = "before_allocation_id" if before_allocation_id is None else "before_closed_at"
        raise HTTPException(
            status_code=422,
            detail=(
                "a cursor is both before_closed_at and before_allocation_id; "
                f"{missing} is missing"
            ),
        )
    pool = await _strategy_pool(session, strategy_id)
    try:
        before = (
            None
            if before_closed_at is None or before_allocation_id is None
            else TradeCursor(before_closed_at, before_allocation_id)
        )
        page = await _guarded(
            ReadStrategyTrades(fills, pricing).read(
                strategy_id, pool, limit=limit, before=before, include_rehearsal=include_rehearsal
            )
        )
    except InvalidPageRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TradesBody.of(page)


@router.get(
    "/strategies/{strategy_id}/trades/{allocation_id}/fills", response_model=OperationFillsBody
)
async def operation_fills(
    strategy_id: UUID, allocation_id: UUID, session: SessionDep, source: OperationFillsDep
) -> OperationFillsBody:
    pool = await _strategy_pool(session, strategy_id)
    try:
        result = await _guarded(ReadOperationFills(source).read(strategy_id, pool, allocation_id))
    except UnknownOperation as exc:
        # One answer for an id that does not exist, another strategy's operation and
        # an allocation that never had a fill: it must not say which one it was.
        raise HTTPException(status_code=404, detail="no such operation") from exc
    return OperationFillsBody(
        allocation_id=result.allocation_id,
        fills=[
            FillBody(
                filled_at=fill.filled_at,
                side=cast(Literal["BUY", "SELL"], fill.side),  # pydantic refuses any other value
                price=fill.price,
                quantity=fill.quantity,
                fee=fill.fee,
                fee_currency=fill.fee_currency,
                rehearsal=fill.rehearsal,
            )
            for fill in result.fills
        ],
        truncated=result.truncated,
    )
