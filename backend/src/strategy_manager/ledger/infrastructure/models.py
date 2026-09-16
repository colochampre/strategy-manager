"""SQLAlchemy ORM model owned by ``ledger``. Mirrors migration
``0005_ledger_execution``'s ``ledger_entries`` table. The append-only
enforcement itself (both triggers) is raw SQL created by the migration, not
modelled here — SQLAlchemy metadata has no notion of a trigger.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.shared.db import Base


class LedgerEntryRow(Base):
    """Mirrors the ``ledger_entries`` table created by migration ``0005``."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        # Fill ids are only unique WITHIN an exchange: nothing stops Binance
        # and Bybit from issuing the same one, and keyed by venue alone the
        # second exchange's fill would be silently rejected as a duplicate of
        # the first's.
        UniqueConstraint(
            "exchange",
            "venue",
            "exchange_fill_id",
            name="ux_ledger_exchange_fill",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    strategy_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False
    )
    allocation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reservations.id"), nullable=False
    )
    execution_attempt_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("execution_attempts.id"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    settlement_currency: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False, server_default="0")
    fee_currency: Mapped[str] = mapped_column(Text, nullable=False)
    notional: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    exchange_order_id: Mapped[str] = mapped_column(Text, nullable=False)
    exchange_fill_id: Mapped[str] = mapped_column(Text, nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usd_rate_at_fill: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
