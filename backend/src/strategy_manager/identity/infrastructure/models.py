"""ORM row for ``users`` (migration ``0029``; multi-user design AD1).

The constraints are declared here as well as in the migration, by the same
names, because the integration tests build their schema with ``create_all`` and
``SqlAlchemyUserRepository`` relies on the e-mail's unique index for its
``ON CONFLICT``. The migration remains the schema's source of truth.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from strategy_manager.shared.db import Base


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="ux_users_email"),
        CheckConstraint(
            "email = lower(email) AND email !~ '[[:space:]]'", name="ck_users_email_normalized"
        ),
        CheckConstraint("mode IN ('LIVE', 'SIMULATION')", name="ck_users_mode"),
        CheckConstraint(
            "display_name = btrim(display_name) AND char_length(display_name) BETWEEN 3 AND 30 "
            "AND position('@' in display_name) = 0",
            name="ck_users_display_name_shape",
        ),
        Index("ux_users_display_name_lower", text("lower(display_name)"), unique=True),
        CheckConstraint(
            "deleted_at IS NULL OR (display_name IS NULL "
            "AND email = 'deleted-' || id::text || '@invalid' "
            "AND first_name IS NULL AND last_name IS NULL AND cuit IS NULL)",
            name="ck_users_deleted_names_nobody",
        ),
        CheckConstraint(
            "(first_name IS NOT NULL AND last_name IS NOT NULL AND cuit IS NOT NULL "
            "AND country IS NOT NULL AND adult_declared_at IS NOT NULL "
            "AND truthful_declared_at IS NOT NULL) OR (first_name IS NULL AND last_name IS NULL "
            "AND cuit IS NULL AND country IS NULL AND adult_declared_at IS NULL "
            "AND truthful_declared_at IS NULL)",
            name="ck_users_profile_whole",
        ),
        CheckConstraint("cuit ~ '^[0-9]{11}$'", name="ck_users_cuit_shape"),
        CheckConstraint("country = 'AR'", name="ck_users_country_served"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Added by migration 0035. A new user starts in simulation (decision 6).
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="SIMULATION")
    # Added by migration 0036. None until the user chooses one (decision 27).
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Added by migration 0045. Set when the user deleted their account, which
    # anonymises the row instead of removing it (account-deletion S3).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Added by migration 0046: the identity given at sign-up (public-site LS3),
    # whole or absent, and erased with the account until LQ6 says otherwise.
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    cuit: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    adult_declared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    truthful_declared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Added by migration 0047: when the admin suspended the account (public-site
    # LS9). The date alone; None while the account is not suspended.
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LegalAcceptanceRow(Base):
    """One acceptance of the terms and the privacy policy (migration 0046, LS3).

    Append-only: the migration's triggers refuse UPDATE, DELETE and TRUNCATE. The
    ORM-built test schema has no trigger, so ``tests/migrations`` proves that rule.
    """

    __tablename__ = "legal_acceptances"
    __table_args__ = (Index("ix_legal_acceptances_user_accepted", "user_id", "accepted_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_legal_acceptances_user"),
        nullable=False,
    )
    terms_version: Mapped[str] = mapped_column(Text, nullable=False)
    privacy_version: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
