"""reservations.terminal_at + release_reason, and the sweeper's index
(design.md § Transaction Boundaries, TXN-C; tasks.md 6.3).

Numbered ``0008``, not ``0006``. Slice 6's *code* depends only on slice 4, but
the Alembic revision chain is linear and shared: numbering this ``0006`` off
``0004`` would leave ``0006`` and ``0007`` descending from a common ancestor —
two heads and a forced merge revision. ``0006`` is intentionally never used.

``ix_reservations_sweepable`` is partial. The sweep only ever looks at rows
that still hold capital, and those are the small minority in a healthy system;
indexing the terminal rows too would grow the index without bound as history
accumulates, for a query that never reads them.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_SWEEP_INDEX = "ix_reservations_sweepable"
_REASON_CHECK = "ck_reservations_release_reason"
_TERMINAL_CHECK = "ck_reservations_terminal_at_with_status"

_ACTIVE_STATUSES = "('PENDING', 'SUBMITTED')"
_TERMINAL_STATUSES = "('FILLED', 'RELEASED', 'EXPIRED')"


def upgrade() -> None:
    op.add_column(
        "reservations",
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("reservations", sa.Column("release_reason", sa.Text(), nullable=True))

    op.create_check_constraint(
        _REASON_CHECK,
        "reservations",
        "release_reason IS NULL OR release_reason IN "
        "('EXPIRED_BY_SWEEPER', 'PRE_SUBMIT_EXPIRY', 'EXCHANGE_ERROR')",
    )
    # A row that still holds capital has not ended, so it must carry no
    # terminal timestamp. Enforced here rather than in the repository because
    # every path that terminates a reservation must obey it, including the
    # set-based sweep UPDATE that never loads an aggregate.
    op.create_check_constraint(
        _TERMINAL_CHECK,
        "reservations",
        f"(status IN {_ACTIVE_STATUSES} AND terminal_at IS NULL) "
        f"OR status IN {_TERMINAL_STATUSES}",
    )

    op.create_index(
        _SWEEP_INDEX,
        "reservations",
        ["expires_at"],
        postgresql_where=sa.text(f"status IN {_ACTIVE_STATUSES}"),
    )


def downgrade() -> None:
    op.drop_index(_SWEEP_INDEX, table_name="reservations")
    op.drop_constraint(_TERMINAL_CHECK, "reservations", type_="check")
    op.drop_constraint(_REASON_CHECK, "reservations", type_="check")
    op.drop_column("reservations", "release_reason")
    op.drop_column("reservations", "terminal_at")
