"""SQLAlchemy ORM model owned by ``allocation``. Mirrors migration
``0004_reservations``.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.shared.db import Base


class ReservationRow(Base):
    """Mirrors the ``reservations`` table created by migration ``0004``."""

    __tablename__ = "reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["venue", "settlement_currency"],
            ["capital_pools.venue", "capital_pools.settlement_currency"],
            name="fk_reservations_capital_pool",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    strategy_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False
    )
    signal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("signals.id"), nullable=False, unique=True
    )
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    settlement_currency: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
