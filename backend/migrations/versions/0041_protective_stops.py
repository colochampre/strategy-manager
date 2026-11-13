"""The protective stop of each opening (subscriber-safety D1; tasks.md SS.5).

``protective_stops`` holds one row per opening execution attempt, written in the
transaction that writes the attempt and BEFORE the order is sent, so a crash leaves a
trace of a stop that may exist at the venue:

* ``execution_attempt_id`` is UNIQUE: an opening has at most one stop.
* ``allocation_id`` is the reservation that funded the opening, the id its fills carry in
  the ledger; the stop watcher (SS.7) reads a live allocation's stops by it.
* ``stop_loss_pct`` is the level the stop was placed at (``NUMERIC(4, 2)``, 1 to 50, the
  range of ``strategies.stop_loss_pct``), carried from the policy the leverage cap was
  checked against. ``trigger_price`` is where it rests, ``NULL`` when no price was worked
  out (a simulated opening). ``venue_stop_id`` is the id the venue gave it, ``NULL`` until
  it is found resting.
* ``status`` is ``PENDING`` (sent with the opening, not yet found resting), ``RESTING``,
  ``FAILED`` (not found: the position is closed at once), ``GONE`` (the position closed by
  other means), ``VOID`` (the opening ended without fills) or ``SIMULATED`` (a simulated
  opening, which places no stop). SS.7 adds ``FIRED`` with its own migration.

**Downgrade.** Drops the table with its constraints and indexes. A stop that rests at the
venue keeps resting and is no longer tracked here, so once stops are placed the plan is
fix-forward.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "protective_stops"


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
        sa.Column("execution_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("position_side", sa.Text(), nullable=False),
        sa.Column("stop_loss_pct", sa.Numeric(4, 2), nullable=False),
        sa.Column("trigger_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("venue_stop_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_protective_stops_user"),
        sa.ForeignKeyConstraint(
            ["execution_attempt_id"], ["execution_attempts.id"], name="fk_protective_stops_attempt"
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"], ["reservations.id"], name="fk_protective_stops_allocation"
        ),
        sa.UniqueConstraint("execution_attempt_id", name="uq_protective_stops_attempt"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RESTING', 'FAILED', 'GONE', 'VOID', 'SIMULATED')",
            name="ck_protective_stops_status",
        ),
        sa.CheckConstraint(
            "position_side IN ('LONG', 'SHORT')", name="ck_protective_stops_position_side"
        ),
        sa.CheckConstraint(
            "stop_loss_pct BETWEEN 1 AND 50", name="ck_protective_stops_stop_loss_pct_range"
        ),
        sa.CheckConstraint(
            "trigger_price IS NULL OR trigger_price > 0",
            name="ck_protective_stops_trigger_price_positive",
        ),
    )
    op.create_index("ix_protective_stops_user_id", _TABLE, ["user_id"])
    op.create_index("ix_protective_stops_allocation_id", _TABLE, ["allocation_id"])


def downgrade() -> None:
    op.drop_index("ix_protective_stops_allocation_id", table_name=_TABLE)
    op.drop_index("ix_protective_stops_user_id", table_name=_TABLE)
    op.drop_table(_TABLE)
