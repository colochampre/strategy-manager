"""SQLAlchemy ORM model owned by ``safety``. Mirrors the ``safety_events`` table created by
migration ``0044`` (subscriber-safety SS.10)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from strategy_manager.allocation.infrastructure.models import ReservationRow  # noqa: F401
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow  # noqa: F401
from strategy_manager.identity.infrastructure.models import UserRow  # noqa: F401
from strategy_manager.shared.db import Base
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow  # noqa: F401
from strategy_manager.strategies.infrastructure.models import StrategyRow  # noqa: F401


class SafetyEventRow(Base):
    __tablename__ = "safety_events"
    __table_args__ = (
        UniqueConstraint("execution_attempt_id", name="uq_safety_events_attempt"),
        UniqueConstraint("delivery_id", name="uq_safety_events_delivery"),
        CheckConstraint(
            "kind IN ('STOP_FIRED', 'STOP_FAILED_CLOSED', 'STRATEGY_STOPPED_CLOSED', "
            "'MANUAL_CLOSE', 'OPENING_REFUSED_LEVERAGE_CAP')",
            name="ck_safety_events_kind",
        ),
        CheckConstraint(
            "(execution_attempt_id IS NULL) <> (delivery_id IS NULL)",
            name="ck_safety_events_one_source",
        ),
        Index("ix_safety_events_user_occurred", "user_id", text("occurred_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", name="fk_safety_events_user"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("strategies.id", name="fk_safety_events_strategy"),
        nullable=False,
    )
    allocation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("reservations.id", name="fk_safety_events_allocation"),
        nullable=True,
    )
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    execution_attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("execution_attempts.id", name="fk_safety_events_attempt"),
        nullable=True,
    )
    delivery_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("signal_deliveries.id", name="fk_safety_events_delivery"),
        nullable=True,
    )
