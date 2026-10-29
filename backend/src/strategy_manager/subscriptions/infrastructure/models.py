"""ORM row for ``subscriptions`` (migration ``0031``; multi-user design AD3).

The constraints are declared here as well as in the migration, by the same
names, because the integration tests build their schema with ``create_all``.
The migration remains the schema's source of truth.

**Migration-only:** the trigger ``trg_subscriptions_pool_market`` (a subscription's
pool must trade its strategy's market, ``ck_subscriptions_pool_market``) has no
ORM form, so a ``create_all`` schema does not enforce it. The same goes for the
backfill and for ``strategies.allocation_percent`` becoming nullable.

The referenced tables are imported only to register them on ``Base.metadata``:
``create_all`` cannot resolve a foreign key to a table it has not been shown.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow  # noqa: F401
from strategy_manager.identity.infrastructure.models import UserRow  # noqa: F401
from strategy_manager.shared.db import Base
from strategy_manager.strategies.infrastructure.models import StrategyRow  # noqa: F401


class SubscriptionRow(Base):
    """Mirrors the ``subscriptions`` table created by migration ``0031``: a user's
    place in a strategy, through the user's own pool, at the user's own share.

    ``(pool_id, user_id)`` references ``capital_pools (id, user_id)``, so a
    subscription never sits in another user's pool. A strategy's deletion takes
    its subscriptions with it (``fk_subscriptions_strategy`` cascades)."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["pool_id", "user_id"],
            ["capital_pools.id", "capital_pools.user_id"],
            name="fk_subscriptions_pool",
        ),
        CheckConstraint(
            "allocation_percent > 0 AND allocation_percent <= 100",
            name="ck_subscriptions_allocation_percent_range",
        ),
        CheckConstraint("status IN ('ACTIVE', 'LEAVING', 'ENDED')", name="ck_subscriptions_status"),
        Index(
            "ux_subscriptions_one_live_per_strategy",
            "user_id",
            "strategy_id",
            unique=True,
            postgresql_where=text("status <> 'ENDED'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_subscriptions_user"),
        nullable=False,
        index=True,
    )
    strategy_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("strategies.id", name="fk_subscriptions_strategy", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pool_id: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_percent: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
