"""The seats an author's wider stop lowered (panel-redesign RD.9a).

When an author widens a strategy's stop so that its leverage cap falls below a seat's
leverage, the seat is lowered to the new cap in the same transaction as the stop, and
its owner is told. ``leverage_lowered_events`` holds one row per lowered seat, which is
that notice:

* ``user_id`` is the seat's owner, the only one who reads the row.
* ``old_leverage`` and ``new_leverage`` are both in 1..20 and the leverage goes down
  (``ck_leverage_lowered_events_lowered``).
* ``strategy_id`` and ``subscription_id`` cascade: the strategy's deletion takes its
  seats with it (``fk_subscriptions_strategy``), and so its events.
* ``ix_leverage_lowered_events_user_occurred`` serves the panel's read: one user's events,
  newest first.

Rows are written in the same transaction as the stop and never updated. Nothing is
backfilled: no seat has been lowered yet.

**Downgrade.** Drops the table. The notices are kept nowhere else, so once rows exist the
plan is fix-forward.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "leverage_lowered_events"
_INDEX = "ix_leverage_lowered_events_user_occurred"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("old_leverage", sa.Integer(), nullable=False),
        sa.Column("new_leverage", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_leverage_lowered_events_user"),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name="fk_leverage_lowered_events_strategy",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name="fk_leverage_lowered_events_subscription",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "old_leverage BETWEEN 1 AND 20 AND new_leverage BETWEEN 1 AND 20 "
            "AND new_leverage < old_leverage",
            name="ck_leverage_lowered_events_lowered",
        ),
    )
    op.create_index(_INDEX, _TABLE, ["user_id", sa.text("occurred_at DESC")])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
