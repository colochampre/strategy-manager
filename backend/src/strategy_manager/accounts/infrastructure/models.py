"""SQLAlchemy ORM models owned by ``accounts``. Mirror migrations
``0003_strategies_pools`` and ``0009_pool_balance_snapshots``.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Numeric,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.shared.db import Base


class CapitalPoolRow(Base):
    """Mirrors the ``capital_pools`` table — the single source of truth for
    which pools exist. Composite primary key: no surrogate id."""

    __tablename__ = "capital_pools"

    venue: Mapped[str] = mapped_column(Text, primary_key=True)
    settlement_currency: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    min_order_size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PoolBalanceSnapshotRow(Base):
    """Mirrors ``pool_balance_snapshots``: the last balance the exchange
    reported for a pool. One row per pool, overwritten on every sync.

    ``observed_at`` is the exchange's reading time, not the write time, so a
    reader can tell a fresh figure from a stale one even when the row was
    just rewritten.
    """

    __tablename__ = "pool_balance_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["venue", "settlement_currency"],
            ["capital_pools.venue", "capital_pools.settlement_currency"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "available >= 0", name="ck_pool_balance_snapshots_available_non_negative"
        ),
    )

    venue: Mapped[str] = mapped_column(Text, primary_key=True)
    settlement_currency: Mapped[str] = mapped_column(Text, primary_key=True)
    available: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
