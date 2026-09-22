"""SQLAlchemy implementation of ``ExecutionAttemptRepositoryPort`` against
the ``execution_attempts`` table (migrations ``0005``, ``0011``, ``0012``).
"""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.market_symbol import market_spellings
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.shared.domain.errors import InvariantViolation


def _to_domain(row: ExecutionAttemptRow) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=row.id,
        reservation_id=row.reservation_id,
        closes_allocation_id=row.closes_allocation_id,
        exchange=row.exchange,
        venue=row.venue,
        settlement_currency=row.settlement_currency,
        symbol=row.symbol,
        side=OrderSide(row.side),
        quantity=row.quantity,
        quote_amount=row.quote_amount,
        leverage=row.leverage,
        status=ExecutionStatus(row.status),
        client_order_id=row.client_order_id,
        exchange_order_id=row.exchange_order_id,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyExecutionAttemptRepository:
    """Implements ``execution.application.ports.ExecutionAttemptRepositoryPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, attempt: ExecutionAttempt) -> None:
        self._session.add(
            ExecutionAttemptRow(
                id=attempt.id,
                reservation_id=attempt.reservation_id,
                closes_allocation_id=attempt.closes_allocation_id,
                exchange=attempt.exchange,
                venue=attempt.venue,
                settlement_currency=attempt.settlement_currency,
                symbol=attempt.symbol,
                side=attempt.side.value,
                quantity=attempt.quantity,
                quote_amount=attempt.quote_amount,
                leverage=attempt.leverage,
                status=attempt.status.value,
                client_order_id=attempt.client_order_id,
                exchange_order_id=attempt.exchange_order_id,
                error=attempt.error,
            )
        )
        await self._session.flush()

    async def get(self, attempt_id: UUID) -> ExecutionAttempt:
        row = (
            await self._session.execute(
                select(ExecutionAttemptRow).where(ExecutionAttemptRow.id == attempt_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise InvariantViolation(f"no execution attempt {attempt_id}")

        return _to_domain(row)

    async def mark_placed(self, attempt_id: UUID, exchange_order_id: str) -> None:
        """Records the exchange's id for an already-SUBMITTED attempt.

        Bookkeeping, not a precondition: settlement finds the order by the
        client order id, so losing this write to a crash costs traceability
        and nothing else.
        """
        await self._session.execute(
            update(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.id == attempt_id)
            .values(exchange_order_id=exchange_order_id)
        )

    async def mark_filled(self, attempt_id: UUID, exchange_order_id: str) -> None:
        await self._session.execute(
            update(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.id == attempt_id)
            .values(status=ExecutionStatus.FILLED.value, exchange_order_id=exchange_order_id)
        )

    async def mark_failed(self, attempt_id: UUID, error: str) -> None:
        await self._session.execute(
            update(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.id == attempt_id)
            .values(status=ExecutionStatus.FAILED.value, error=error)
        )

    async def submitted_for_strategy_symbol(
        self,
        exchange: str,
        venue: str,
        settlement_currency: str,
        strategy_id: UUID,
        symbol: str,
    ) -> bool:
        """Implements ``signals.infrastructure.in_flight_work``'s half (a) of
        the "In flight vs orphan" check (design.md § "the query"): whether
        the strategy has a SUBMITTED execution attempt -- opening or closing
        -- on this market within this pool, merged across every spelling it
        wears (``market_spellings``).

        Attempts carry no ``strategy_id`` of their own, so the join reaches
        it through whichever reservation the attempt is tied to --
        ``reservation_id`` for an opening attempt, ``closes_allocation_id``
        for a closing one (a closing attempt's ``closes_allocation_id`` IS
        the reservation that originally opened the position). Exactly one of
        the two is set (``ck_execution_attempts_one_origin``, migration
        ``0012``), so ``COALESCE`` picks whichever it is.
        """
        spellings = list(market_spellings(symbol))
        origin = func.coalesce(
            ExecutionAttemptRow.reservation_id, ExecutionAttemptRow.closes_allocation_id
        )
        result = await self._session.execute(
            select(ExecutionAttemptRow.id)
            .join(ReservationRow, ReservationRow.id == origin)
            .where(
                ExecutionAttemptRow.exchange == exchange,
                ExecutionAttemptRow.venue == venue,
                ExecutionAttemptRow.settlement_currency == settlement_currency,
                ExecutionAttemptRow.status == ExecutionStatus.SUBMITTED.value,
                ReservationRow.strategy_id == strategy_id,
                func.upper(ExecutionAttemptRow.symbol).in_(spellings),
            )
            .limit(1)
        )
        return result.first() is not None

    async def latest_close_for(self, allocation_id: UUID) -> ExecutionAttempt | None:
        """The most recent closing execution attempt for ``allocation_id``,
        in ANY status, or ``None`` if it has never been closed -- what the
        S5 continuation's idempotent release half reads before re-submitting
        a close (design.md § S5, "Idempotent release half"): a non-FAILED
        row here means the close already happened or is in flight, so only
        the seed needs enqueuing again, never a second close order.

        Ordered by ``created_at`` for when there is more than one to choose
        from. Today ``closes_allocation_id`` is UNIQUE system-wide (at most
        one row can ever match), a constraint migration ``0021`` (S6) relaxes
        to SUBMITTED-only -- the ordering is here for that future, not
        because it decides anything yet.
        """
        row = (
            await self._session.execute(
                select(ExecutionAttemptRow)
                .where(ExecutionAttemptRow.closes_allocation_id == allocation_id)
                .order_by(ExecutionAttemptRow.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row is not None else None
