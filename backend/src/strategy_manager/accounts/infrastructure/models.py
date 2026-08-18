"""SQLAlchemy ORM model owned by ``accounts``. Mirrors migration
``0003_strategies_pools``.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, Text, text
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
