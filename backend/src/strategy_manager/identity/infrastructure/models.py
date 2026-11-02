"""ORM row for ``users`` (migration ``0029``; multi-user design AD1).

The constraints are declared here as well as in the migration, by the same
names, because the integration tests build their schema with ``create_all`` and
``SqlAlchemyUserRepository`` relies on the e-mail's unique index for its
``ON CONFLICT``. The migration remains the schema's source of truth.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Text, UniqueConstraint, func, text
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
