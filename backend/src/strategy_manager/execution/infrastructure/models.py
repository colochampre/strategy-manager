"""SQLAlchemy ORM model owned by ``execution``. Mirrors the
``execution_attempts`` table created by migration ``0005_ledger_execution``
and reshaped by ``0011_execution_attempt_quote_amount`` and
``0012_closing_execution_attempts``.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.shared.db import Base


class ExecutionAttemptRow(Base):
    """Mirrors the ``execution_attempts`` table created by migration
    ``0005`` and reshaped by ``0011`` and ``0012``."""

    __tablename__ = "execution_attempts"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Exactly one of these is set, enforced by ``ck_execution_attempts_one_origin``
    # (migration ``0012``). Both are UNIQUE, and each uniqueness rule is the
    # idempotency rule for its side: one opening order per reservation, one
    # closing order per position. PostgreSQL allows many NULLs in a UNIQUE
    # column, so nullability costs neither guarantee.
    reservation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reservations.id"), nullable=True, unique=True
    )
    closes_allocation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reservations.id"), nullable=True, unique=True
    )
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    settlement_currency: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    # Exactly one of these is set, enforced by the CHECK constraint
    # ``ck_execution_attempts_one_size`` (migration ``0011``): ``quantity``
    # is a sell's base size, ``quote_amount`` a buy's quote amount. Whichever
    # is populated is the number that actually went on the wire.
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    quote_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)

    # ``ck_execution_attempts_leverage_positive`` (migration ``0015``):
    # set for a futures order, NULL for a spot one.
    leverage: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    client_order_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    exchange_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
