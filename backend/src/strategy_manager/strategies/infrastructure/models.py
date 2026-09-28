"""SQLAlchemy ORM model owned by ``strategies``. Mirrors migration
``0003_strategies_pools``, extended by ``0007_allocation_percent`` and
``0024_strategy_lifecycle``.

``id`` has NO ``gen_random_uuid()`` server default: it MUST be supplied
explicitly by the caller as the strategy's ``signal_type`` UUID (design.md
§ "strategy_id derives from signal_type" — HARD CONSTRAINT ON SLICE 3).

``strategies`` has a composite FK into ``capital_pools``, so both models share
the one declarative registry in ``shared.db.Base``.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKeyConstraint, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ARRAY as PGARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.shared.db import Base


class StrategyRow(Base):
    """Mirrors the ``strategies`` table created by migration ``0003``,
    extended with ``allocation_percent`` by migration ``0007``."""

    __tablename__ = "strategies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["exchange", "venue", "settlement_currency"],
            [
                "capital_pools.exchange",
                "capital_pools.venue",
                "capital_pools.settlement_currency",
            ],
            name="fk_strategies_capital_pool",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    settlement_currency: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    fill_mode: Mapped[str] = mapped_column(Text, nullable=False)
    allocation_percent: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, server_default=text("100")
    )
    # ``ck_strategies_allowed_pairs_no_null`` (migration 0024): entries are
    # market_key()-normalized symbols this strategy may OPEN on.
    allowed_pairs: Mapped[list[str]] = mapped_column(
        PGARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    # ``ck_strategies_archived_requires_disabled`` (migration 0024): never
    # cleared once set -- archive is terminal.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
