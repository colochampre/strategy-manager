"""ORM row for ``users`` (migration ``0029``; multi-user design AD1).

The constraints are declared here as well as in the migration, by the same
names, because the integration tests build their schema with ``create_all`` and
``SqlAlchemyUserRepository`` relies on the e-mail's unique index for its
``ON CONFLICT``. The migration remains the schema's source of truth.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Text, UniqueConstraint, func
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
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
