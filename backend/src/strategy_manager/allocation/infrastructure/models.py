"""SQLAlchemy ORM model owned by ``allocation``. Mirrors migration
``0004_reservations`` as later migrations left it (``0030``: its owner and pool).
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.shared.db import Base
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow  # noqa: F401


class ReservationRow(Base):
    """Mirrors the ``reservations`` table created by migration ``0004``.

    A reservation belongs to a user and holds capital in that user's pool
    (migration ``0030``, multi-user design AD2): ``user_id`` names the owner and
    ``pool_id`` the pool, and their FK is ``(pool_id, user_id)``, so the database
    refuses one user's reservation in another user's pool. The market columns
    stay as data."""

    __tablename__ = "reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["pool_id", "user_id"],
            ["capital_pools.id", "capital_pools.user_id"],
            name="fk_reservations_capital_pool",
        ),
        ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_reservations_user"),
        CheckConstraint("mode IN ('LIVE', 'SIMULATION')", name="ck_reservations_mode"),
        Index("ix_reservations_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pool_id: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False
    )
    signal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("signals.id"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
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
    # Added by migration 0008. Both stay NULL while the reservation still holds
    # capital; a CHECK constraint enforces that pairing at the database level.
    terminal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Added by migration 0026: the capital of this reservation's own pool
    # (its settlement currency) as read inside the allocation lock. NULL on
    # every row written before that migration -- it cannot be backfilled. A
    # CHECK there enforces NULL-or-positive; nothing sums it across pools.
    pool_total_at_open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    # Added by migration 0032: the delivery (one signal reaching one subscription)
    # this reservation serves. It is the reservation's uniqueness now: two
    # subscribers each hold a reservation for one signal, so ``signal_id`` is not
    # unique, and one delivery is served by one reservation.
    delivery_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("signal_deliveries.id", name="fk_reservations_delivery"),
        nullable=False,
        unique=True,
    )
    # Added by migration 0035: the mode this reservation opened in. NO server
    # default, so a writer that forgets it fails loudly.
    mode: Mapped[str] = mapped_column(Text, nullable=False)
