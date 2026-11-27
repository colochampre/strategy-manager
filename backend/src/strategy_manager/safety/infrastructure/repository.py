"""SQLAlchemy adapters for the safety events (subscriber-safety SS.10): the writer every
site that causes an event uses, and the reader behind the panel's list."""

from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.safety.application.read_safety_events import SafetyEventView
from strategy_manager.safety.infrastructure.models import SafetyEventRow
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.safety_event import NewSafetyEvent, SafetyEventKind
from strategy_manager.strategies.infrastructure.models import StrategyRow


class SqlAlchemySafetyEventWriter:
    """Implements ``SafetyEventWriterPort``: stages the row on the caller's session and
    never commits, so it rides the commit of the change it reports.

    ``ON CONFLICT DO NOTHING`` is what makes a re-run harmless: the source of an event (the
    attempt or the delivery) is UNIQUE, so a second event from the same source is dropped by
    the database and neither raises nor writes. A CHECK failure (a kind or a source the
    schema does not know) still raises."""

    def __init__(self, session: AsyncSession, clock: ClockPort) -> None:
        self._session = session
        self._clock = clock

    async def record(self, event: NewSafetyEvent) -> None:
        await self._session.execute(
            insert(SafetyEventRow)
            .values(
                user_id=event.user_id,
                kind=event.kind.value,
                strategy_id=event.strategy_id,
                allocation_id=event.allocation_id,
                exchange=event.exchange,
                venue=event.venue,
                symbol=event.symbol,
                occurred_at=self._clock.now(),
                detail=dict(event.detail),
                execution_attempt_id=event.execution_attempt_id,
                delivery_id=event.delivery_id,
            )
            .on_conflict_do_nothing()
        )


class SqlAlchemySafetyEventReader:
    """Implements ``SafetyEventReaderPort``: one user's events, newest first."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def newest_of(self, user_id: UUID, limit: int) -> list[SafetyEventView]:
        rows = await self._session.execute(
            select(SafetyEventRow, StrategyRow.name)
            .join(StrategyRow, StrategyRow.id == SafetyEventRow.strategy_id)
            .where(SafetyEventRow.user_id == user_id)
            .order_by(SafetyEventRow.occurred_at.desc(), SafetyEventRow.id.desc())
            .limit(limit)
        )
        return _views(rows.all())

    async def of_kinds(
        self, user_id: UUID, kinds: Collection[SafetyEventKind]
    ) -> list[SafetyEventView]:
        rows = await self._session.execute(
            select(SafetyEventRow, StrategyRow.name)
            .join(StrategyRow, StrategyRow.id == SafetyEventRow.strategy_id)
            .where(
                SafetyEventRow.user_id == user_id,
                SafetyEventRow.kind.in_([kind.value for kind in kinds]),
            )
            .order_by(SafetyEventRow.occurred_at.desc(), SafetyEventRow.id.desc())
        )
        return _views(rows.all())


def _views(rows: Sequence[Row[tuple[SafetyEventRow, str]]]) -> list[SafetyEventView]:
    return [
        SafetyEventView(
            id=row.id,
            kind=SafetyEventKind(row.kind),
            strategy_id=row.strategy_id,
            strategy_name=name,
            allocation_id=row.allocation_id,
            exchange=row.exchange,
            venue=row.venue,
            symbol=row.symbol,
            occurred_at=row.occurred_at,
            detail={key: str(value) for key, value in row.detail.items()},
        )
        for row, name in rows
    ]
