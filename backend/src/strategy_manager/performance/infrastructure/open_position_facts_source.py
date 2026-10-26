"""``SqlAlchemyOpenPositionFactsSource``: the facts the mode guard's reader does
not carry (design addendum "open positions", section C, steps 3 and 4).

Three statements, each ONE statement however many rows it answers:

* ``submitted_orders``: every ``SUBMITTED`` attempt, with or without an order id.
  The parents are LEFT joins, so an attempt whose reservation or strategy is
  missing is still a row: no attempt is dropped by a missing parent.
* ``position_facts``, 1 of 2: the fills of the asked allocations, grouped by
  allocation, strategy, pool, symbol, side and upper-cased fee currency.
* ``position_facts``, 2 of 2: each reservation's grant, status, strategy, pool
  and the leverage of its OPENING attempt.

**One user's rows** (multi-user design AD8): every statement filters the ledger
entries, reservations and execution attempts on ``user_id``. Strategies stay
global: a strategy's name and archive flag are the same for every user.

**The origin is not decided here.** Nothing in these statements tests the
rehearsal prefix; a position's origin is the guard's two flags and nowhere else.
**Nothing filters the guard's answer.** An allocation these statements know
nothing about is simply absent from the answer, and the caller keeps its row.

The adapter reads other modules' tables, as the neighbouring performance
adapters do; no ORM row crosses into ``application/`` or ``domain/``.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.performance.application.ports import PositionFacts, SubmittedOrder
from strategy_manager.performance.domain.open_position import FillAggregate, PoolLabel
from strategy_manager.strategies.infrastructure.models import StrategyRow

_SUBMITTED = "SUBMITTED"


class SqlAlchemyOpenPositionFactsSource:
    """Implements ``OpenPositionFactsSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def position_facts(
        self, user_id: UUID, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, PositionFacts]:
        if not allocation_ids:
            return {}

        fee_currency = func.upper(LedgerEntryRow.fee_currency)
        fills = await self._session.execute(
            select(
                LedgerEntryRow.allocation_id,
                LedgerEntryRow.strategy_id,
                LedgerEntryRow.exchange,
                LedgerEntryRow.venue,
                LedgerEntryRow.settlement_currency,
                LedgerEntryRow.symbol,
                LedgerEntryRow.side,
                fee_currency,
                func.sum(LedgerEntryRow.quantity),
                func.sum(LedgerEntryRow.notional),
                func.sum(LedgerEntryRow.fee),
                func.min(LedgerEntryRow.filled_at),
                func.count(),
            )
            .where(
                LedgerEntryRow.user_id == user_id,
                LedgerEntryRow.allocation_id.in_(allocation_ids),
            )
            .group_by(
                LedgerEntryRow.allocation_id,
                LedgerEntryRow.strategy_id,
                LedgerEntryRow.exchange,
                LedgerEntryRow.venue,
                LedgerEntryRow.settlement_currency,
                LedgerEntryRow.symbol,
                LedgerEntryRow.side,
                fee_currency,
            )
        )
        groups: dict[UUID, list[FillAggregate]] = defaultdict(list)
        for row in fills.all():
            groups[row[0]].append(
                FillAggregate(
                    allocation_id=row[0],
                    strategy_id=row[1],
                    exchange=row[2],
                    venue=row[3],
                    settlement_currency=row[4],
                    symbol=row[5],
                    side=row[6],
                    fee_currency=row[7],
                    quantity=Decimal(row[8]),
                    notional=Decimal(row[9]),
                    fee=Decimal(row[10]),
                    first_filled_at=row[11],
                    fill_count=int(row[12]),
                )
            )

        # The LEFT join to the attempts is on the OPENING link only: a closing
        # attempt of the same reservation points at it by ``closes_allocation_id``
        # and must not lend its leverage to the position.
        reservations = await self._session.execute(
            select(
                ReservationRow.id,
                ReservationRow.strategy_id,
                StrategyRow.name,
                StrategyRow.archived_at.is_not(None),
                ReservationRow.amount,
                ReservationRow.status,
                ExecutionAttemptRow.leverage,
                ReservationRow.exchange,
                ReservationRow.venue,
                ReservationRow.settlement_currency,
            )
            .join(StrategyRow, StrategyRow.id == ReservationRow.strategy_id)
            .outerjoin(
                ExecutionAttemptRow,
                and_(
                    ExecutionAttemptRow.reservation_id == ReservationRow.id,
                    ExecutionAttemptRow.user_id == user_id,
                ),
            )
            .where(ReservationRow.user_id == user_id, ReservationRow.id.in_(allocation_ids))
        )
        facts: dict[UUID, PositionFacts] = {}
        for row in reservations.all():
            facts[row[0]] = PositionFacts(
                allocation_id=row[0],
                strategy_id=row[1],
                strategy_name=row[2],
                strategy_archived=bool(row[3]),
                margin_granted=Decimal(row[4]),
                reservation_status=row[5],
                leverage=None if row[6] is None else Decimal(row[6]),
                reservation_pool=PoolLabel(row[7], row[8], row[9]),
                groups=tuple(groups.get(row[0], ())),
            )
        return facts

    async def submitted_orders(self, user_id: UUID) -> Sequence[SubmittedOrder]:
        reservation = aliased(ReservationRow)
        result = await self._session.execute(
            select(
                ExecutionAttemptRow.id,
                ExecutionAttemptRow.reservation_id.is_not(None),
                ExecutionAttemptRow.exchange,
                ExecutionAttemptRow.venue,
                ExecutionAttemptRow.settlement_currency,
                ExecutionAttemptRow.symbol,
                ExecutionAttemptRow.exchange_order_id,
                ExecutionAttemptRow.created_at,
                reservation.strategy_id,
                StrategyRow.name,
                StrategyRow.archived_at,
                reservation.exchange,
                reservation.venue,
                reservation.settlement_currency,
            )
            .select_from(ExecutionAttemptRow)
            .outerjoin(
                reservation,
                and_(
                    reservation.id
                    == func.coalesce(
                        ExecutionAttemptRow.reservation_id, ExecutionAttemptRow.closes_allocation_id
                    ),
                    reservation.user_id == user_id,
                ),
            )
            .outerjoin(StrategyRow, StrategyRow.id == reservation.strategy_id)
            .where(ExecutionAttemptRow.user_id == user_id, ExecutionAttemptRow.status == _SUBMITTED)
        )
        orders: list[SubmittedOrder] = []
        for row in result.all():
            has_strategy = row[9] is not None
            orders.append(
                SubmittedOrder(
                    attempt_id=row[0],
                    opening=bool(row[1]),
                    pool=PoolLabel(row[2], row[3], row[4]),
                    symbol=row[5],
                    exchange_order_id=row[6],
                    created_at=row[7],
                    strategy_id=row[8],
                    strategy_name=row[9],
                    # A missing strategy is "unknown", not "not archived".
                    strategy_archived=(row[10] is not None) if has_strategy else None,
                    reservation_pool=(
                        PoolLabel(row[11], row[12], row[13]) if row[11] is not None else None
                    ),
                )
            )
        return orders
