"""The safety events a user can read (subscriber-safety SS.10; spec safety-events).

``safety_events`` holds one row per event the system caused to protect a user's money, or
refused to cause:

* ``kind`` is one of ``STOP_FIRED``, ``STOP_FAILED_CLOSED``, ``STRATEGY_STOPPED_CLOSED``,
  ``MANUAL_CLOSE`` and ``OPENING_REFUSED_LEVERAGE_CAP`` (``ck_safety_events_kind``).
* ``allocation_id`` is NULL for a refused opening: it has no allocation.
* ``detail`` is a JSONB object whose values are all strings.
* The source is ``execution_attempt_id`` (the booked order behind the four events an order
  causes) or ``delivery_id`` (the refused opening), each UNIQUE and exactly one set
  (``ck_safety_events_one_source``). The UNIQUE source is what keeps a re-run from writing a
  second row.
* Rows are written in the same transaction as the change they report and never updated or
  deleted; the application has no code that does either.
* ``ix_safety_events_user_occurred`` serves the panel's read: one user's events, newest
  first.

**Downgrade.** Drops the table. The events are a record of what the system did, kept
nowhere else: a downgrade loses them, so once events are written the plan is fix-forward.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "safety_events"
_KINDS = (
    "STOP_FIRED",
    "STOP_FAILED_CLOSED",
    "STRATEGY_STOPPED_CLOSED",
    "MANUAL_CLOSE",
    "OPENING_REFUSED_LEVERAGE_CAP",
)


def upgrade() -> None:
    quoted = ", ".join(f"'{kind}'" for kind in _KINDS)
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("execution_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_safety_events_user"),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name="fk_safety_events_strategy"
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"], ["reservations.id"], name="fk_safety_events_allocation"
        ),
        sa.ForeignKeyConstraint(
            ["execution_attempt_id"], ["execution_attempts.id"], name="fk_safety_events_attempt"
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"], ["signal_deliveries.id"], name="fk_safety_events_delivery"
        ),
        sa.UniqueConstraint("execution_attempt_id", name="uq_safety_events_attempt"),
        sa.UniqueConstraint("delivery_id", name="uq_safety_events_delivery"),
        sa.CheckConstraint(f"kind IN ({quoted})", name="ck_safety_events_kind"),
        sa.CheckConstraint(
            "(execution_attempt_id IS NULL) <> (delivery_id IS NULL)",
            name="ck_safety_events_one_source",
        ),
    )
    op.create_index(
        "ix_safety_events_user_occurred",
        _TABLE,
        ["user_id", sa.text("occurred_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_safety_events_user_occurred", table_name=_TABLE)
    op.drop_table(_TABLE)
