"""SQLAlchemy ORM model owned by ``strategies``. Mirrors migration
``0003_strategies_pools``, extended by ``0007_allocation_percent``,
``0024_strategy_lifecycle`` and ``0030_ownership``.

``id`` has NO ``gen_random_uuid()`` server default: it MUST be supplied
explicitly by the caller as the strategy's ``signal_type`` UUID (design.md
§ "strategy_id derives from signal_type" — HARD CONSTRAINT ON SLICE 3).

**A strategy names a market, not a pool** (multi-user design AD3). ``0030``
dropped the composite FK into ``capital_pools``, because pools now belong to
users and the market triple stopped being their key. ``ck_strategies_venue``
keeps the venue to the ones a pool can have, and ``RegisterStrategy`` still
checks that the pool exists.

``author_id`` references ``users``, so ``identity``'s ``UserRow`` must be on the
same ``Base.metadata`` wherever a schema is built from it (``tests/pg_schema.py``
registers it for the integration tests). The constraints carry 0030's names.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY as PGARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.shared.db import Base


class StrategyRow(Base):
    """Mirrors the ``strategies`` table created by migration ``0003``,
    extended with ``author_id`` by migration ``0030`` and with the secret hash,
    the visibility and the per-author name by ``0033``, which also dropped
    ``allocation_percent``, with the secret's last four by ``0034``, and with the
    author's description by ``0037``, and with the link's token by ``0038``."""

    __tablename__ = "strategies"
    __table_args__ = (
        CheckConstraint("venue IN ('spot', 'usdt-m', 'coin-m')", name="ck_strategies_venue"),
        CheckConstraint(
            "visibility IN ('PUBLIC', 'LINK', 'PRIVATE')", name="ck_strategies_visibility"
        ),
        CheckConstraint(
            "(visibility = 'LINK') = (share_token IS NOT NULL)",
            name="ck_strategies_share_token_iff_link",
        ),
        CheckConstraint(
            "share_token IS NULL OR share_token ~ '^[A-Za-z0-9_-]{43}$'",
            name="ck_strategies_share_token_shape",
        ),
        Index("ux_strategies_share_token", "share_token", unique=True),
        CheckConstraint(
            "char_length(webhook_secret_last4) = 4",
            name="ck_strategies_webhook_secret_last4_length",
        ),
        CheckConstraint(
            "description IS NULL OR (description = btrim(description, E' \\t\\r\\n') "
            "AND char_length(description) BETWEEN 1 AND 2000)",
            name="ck_strategies_description_shape",
        ),
        CheckConstraint(
            "stop_loss_pct BETWEEN 1 AND 50", name="ck_strategies_stop_loss_pct_range"
        ),
        UniqueConstraint("author_id", "name", name="ux_strategies_author_name"),
        Index("ix_strategies_author_id", "author_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    settlement_currency: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_strategies_author"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    fill_mode: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 hex of the strategy's webhook secret (migration 0033). The domain
    # ``Strategy`` never carries it: only the repository's insert and replace touch it.
    webhook_secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # The secret's last four characters (migration 0034), for the panel's mask. Like the
    # hash it is read only by the repository's own query, never by ``_to_domain``.
    webhook_secret_last4: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PRIVATE'")
    )
    # Migration ``0038`` (decision 41): the link's token, set exactly while the
    # strategy is LINK. Stored readable, so the author's aside can always show it.
    share_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Migration ``0037`` (decision 38): what the author writes about how the strategy
    # trades and the configuration they recommend. Optional, trimmed, 1 to 2,000 chars.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Migration ``0040`` (subscriber-safety D5): where its positions are stopped, as a
    # percentage of price from the entry. Existing strategies got 10 (D6).
    stop_loss_pct: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, server_default=text("10")
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
