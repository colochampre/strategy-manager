"""SQLAlchemy ORM models owned by ``accounts``. Mirror migrations
``0003_strategies_pools``, ``0009_pool_balance_snapshots``,
``0010_exchange_credentials``, ``0027_credential_snapshot`` and, for the two
pool tables, ``0030_ownership``.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.shared.db import Base


class CapitalPoolRow(Base):
    """Mirrors the ``capital_pools`` table — the single source of truth for
    which pools exist.

    A pool belongs to a user (migration ``0030``, multi-user design AD2), so the
    market ``(exchange, venue, settlement_currency)`` is no longer a key: two
    users may each hold a pool on the same market. The key is the identity
    ``id``, ``ux_capital_pools_user_market`` keeps one pool per user and market,
    and ``ux_capital_pools_id_user`` is what every row held against a pool
    references, so such a row and its pool always share a user.
    """

    __tablename__ = "capital_pools"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "exchange",
            "venue",
            "settlement_currency",
            name="ux_capital_pools_user_market",
        ),
        UniqueConstraint("id", "user_id", name="ux_capital_pools_id_user"),
        Index("ix_capital_pools_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_capital_pools_user"),
        nullable=False,
    )
    # Part of the market: two exchanges both have a usdt-m venue holding USDT,
    # and they are different money.
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    settlement_currency: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
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
        # ``(pool_id, user_id)``, never ``pool_id`` alone (migration ``0030``):
        # the database refuses one user's snapshot on another user's pool.
        ForeignKeyConstraint(
            ["pool_id", "user_id"],
            ["capital_pools.id", "capital_pools.user_id"],
            name="fk_pool_balance_snapshots_capital_pool",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_pool_balance_snapshots_user"
        ),
        Index("ix_pool_balance_snapshots_user_id", "user_id"),
        CheckConstraint("available >= 0", name="ck_pool_balance_snapshots_available_non_negative"),
        CheckConstraint(
            "total >= available", name="ck_pool_balance_snapshots_total_covers_available"
        ),
    )

    pool_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # The pool's market, kept as data (0030): the key is ``pool_id``.
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    settlement_currency: Mapped[str] = mapped_column(Text, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    available: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExchangeCredentialRow(Base):
    """Mirrors ``exchange_credentials``. Every secret column is ciphertext;
    ``api_key_last4`` is the only readable value in the table, and the only
    one a client may ever be shown (CLAUDE.md rule 8)."""

    __tablename__ = "exchange_credentials"
    __table_args__ = (
        # There is deliberately no UNIQUE on (exchange, label). It existed
        # until migration ``0013`` and made rotation impossible: superseded
        # rows keep their label, so storing a new key under the same one
        # collided with the history the design exists to preserve. The partial
        # index below is the real invariant.
        CheckConstraint(
            "char_length(api_key_last4) = 4",
            name="ck_exchange_credentials_last4_length",
        ),
        # The record of how each fact was established (migration 0027, design
        # addendum section B). Spelled here exactly as the migration spells
        # them: the integration tests build their schema from these.
        CheckConstraint(
            "trade_capability_source IN ('VERIFIED', 'OWNER_CONFIRMED', 'UNRECORDED') "
            "AND withdraw_check IN ('VERIFIED', 'OWNER_CONFIRMED', 'UNRECORDED')",
            name="ck_exchange_credentials_sources_known",
        ),
        CheckConstraint(
            "(trade_capability_source = 'OWNER_CONFIRMED') = (trade_confirmed_at IS NOT NULL) "
            "AND (withdraw_check = 'OWNER_CONFIRMED') = (withdraw_confirmed_at IS NOT NULL)",
            name="ck_exchange_credentials_confirmation_has_timestamp",
        ),
        CheckConstraint(
            "trade_capability_source <> 'OWNER_CONFIRMED' OR trade_capable",
            name="ck_exchange_credentials_confirmed_trade_is_capable",
        ),
        CheckConstraint(
            "(trade_capability_source = 'UNRECORDED') = (withdraw_check = 'UNRECORDED') "
            "AND (validated_at IS NULL) = (withdraw_check = 'UNRECORDED')",
            name="ck_exchange_credentials_recorded_or_legacy",
        ),
        CheckConstraint(
            "exchange <> 'binance' OR "
            "(trade_capability_source <> 'VERIFIED' AND withdraw_check <> 'VERIFIED')",
            name="ck_exchange_credentials_binance_not_verified",
        ),
        CheckConstraint(
            "exchange <> 'bybit' OR "
            "(trade_capability_source <> 'OWNER_CONFIRMED' "
            "AND withdraw_check <> 'OWNER_CONFIRMED')",
            name="ck_exchange_credentials_bybit_not_owner_confirmed",
        ),
        Index(
            "ux_exchange_credentials_one_active_per_exchange",
            "exchange",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_key_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_key_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_secret_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_key_last4: Mapped[str] = mapped_column(Text, nullable=False)
    # How each fact about the key was established. None of these has a
    # server default: 0027 adds them with one to backfill old rows, then drops
    # it, so a writer that forgets to state a fact fails instead of guessing.
    trade_capable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trade_capability_source: Mapped[str] = mapped_column(Text, nullable=False)
    trade_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdraw_check: Mapped[str] = mapped_column(Text, nullable=False)
    withdraw_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NULL means unknown, never "no".
    internal_transfer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
