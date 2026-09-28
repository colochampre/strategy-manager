"""SQLAlchemy adapter for ``EnablementLogPort`` and the ORM row it writes
(design.md § 9 "Enablement event log and uptime"; spec: strategy-lifecycle
§ "Enable/Disable Event Log"; tasks.md 2d.6).

Every event this adapter writes is OBSERVED. BASELINE rows are written
exclusively, once, by migration 0024 itself, at deploy time, for strategies
that were already enabled then — no application code writes a BASELINE row,
today or ever.

Following ``ReconciliationDiscrepancyRow``'s own convention: the migration
is the schema's source of truth for every table-level constraint (the FK
into ``strategies``, the ``origin`` CHECK, the append-only trigger, the
index). This model maps column shape only, so there is exactly one place
those rules can drift from what the database actually enforces.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Text, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from strategy_manager.shared.db import Base
from strategy_manager.strategies.domain.enablement import EnablementEvent, EnablementOrigin


class StrategyEnablementEventRow(Base):
    """Mirrors the ``strategy_enablement_events`` table created by migration
    ``0024``."""

    __tablename__ = "strategy_enablement_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    strategy_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)


class SqlAlchemyEnablementLog:
    """Implements ``EnablementLogPort`` against
    ``strategy_enablement_events``. Every event it writes carries
    ``origin='OBSERVED'`` — see the module docstring for why that is not a
    caller-supplied value."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, strategy_id: UUID, enabled: bool, occurred_at: datetime) -> None:
        self._session.add(
            StrategyEnablementEventRow(
                id=uuid4(),
                strategy_id=strategy_id,
                enabled=enabled,
                occurred_at=occurred_at,
                origin="OBSERVED",
            )
        )
        await self._session.flush()

    async def list_for(self, strategy_id: UUID) -> list[EnablementEvent]:
        """Every event for one strategy, ordered by ``occurred_at`` --
        backs ``GET /strategies/{id}/events`` and a single strategy's
        ``uptime`` on the detail view."""
        result = await self._session.execute(
            select(StrategyEnablementEventRow)
            .where(StrategyEnablementEventRow.strategy_id == strategy_id)
            .order_by(StrategyEnablementEventRow.occurred_at)
        )
        return [_to_domain(row) for row in result.scalars().all()]

    async def list_for_many(
        self, strategy_ids: Sequence[UUID]
    ) -> dict[UUID, list[EnablementEvent]]:
        """Every event for every id in ``strategy_ids``, grouped -- ONE
        query backs ``uptime`` for the WHOLE ``GET /strategies`` list
        (design.md § 14: "``list_all(include_archived)`` + one events
        query -> ``uptime()``"), rather than one query per strategy."""
        grouped: dict[UUID, list[EnablementEvent]] = {sid: [] for sid in strategy_ids}
        if not strategy_ids:
            return grouped

        result = await self._session.execute(
            select(StrategyEnablementEventRow)
            .where(StrategyEnablementEventRow.strategy_id.in_(strategy_ids))
            .order_by(StrategyEnablementEventRow.occurred_at)
        )
        for row in result.scalars().all():
            grouped[row.strategy_id].append(_to_domain(row))
        return grouped


def _to_domain(row: StrategyEnablementEventRow) -> EnablementEvent:
    return EnablementEvent(
        strategy_id=row.strategy_id,
        enabled=row.enabled,
        occurred_at=row.occurred_at,
        origin=EnablementOrigin(row.origin),
    )
