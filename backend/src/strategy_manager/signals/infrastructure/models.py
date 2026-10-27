"""SQLAlchemy ORM model owned by ``signals``. Mirrors migration
``0002_signals``, extended by ``0025_signal_outcomes`` (decision 25)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.identity.infrastructure.models import UserRow  # noqa: F401
from strategy_manager.shared.db import Base
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow  # noqa: F401


class SignalRow(Base):
    """Mirrors the ``signals`` table created by migration ``0002_signals``."""

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("strategy_id", "idempotency_key", name="ux_signals_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    strategy_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="ACCEPTED")
    job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    contracts: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    position_size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    # ``0025_signal_outcomes`` (decision 25): the stable reason code from the
    # addendum's § B table. ``ck_signals_rejected_requires_outcome_reason``
    # requires this whenever ``status = 'REJECTED'``.
    outcome_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The human-readable message already logged for that branch.
    outcome_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ``ck_signals_terminal_requires_decided_at`` requires this whenever
    # ``status`` is ``PROCESSED`` or ``REJECTED``.
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignalDeliveryRow(Base):
    """Mirrors the ``signal_deliveries`` table created by migration ``0032``: one
    signal reaching one subscription, with the outcome that subscription's user
    got from it (multi-user design AD5).

    The outcome columns repeat the signal's own (``SignalRow``) and the status
    CHECK allows the same values as ``ck_signals_status``. Nothing writes this
    table yet: the outcome writers move to it in C.7."""

    __tablename__ = "signal_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "signal_id", "subscription_id", name="ux_signal_deliveries_signal_subscription"
        ),
        CheckConstraint(
            "status IN ('ACCEPTED','PROCESSING','PROCESSED','REJECTED')",
            name="ck_signal_deliveries_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    signal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("signals.id", name="fk_signal_deliveries_signal"),
        nullable=False,
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subscriptions.id", name="fk_signal_deliveries_subscription"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_signal_deliveries_user"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="ACCEPTED")
    outcome_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
