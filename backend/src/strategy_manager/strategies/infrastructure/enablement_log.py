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

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from strategy_manager.shared.db import Base


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
