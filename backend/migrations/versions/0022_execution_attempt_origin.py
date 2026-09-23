"""``execution_attempts.origin`` -- SYSTEM or VENUE (design.md § 2;
spec: trade-execution § Execution Attempt Origin).

Until now every attempt was submitted by THIS system -- ``PlaceOrder`` or
``ClosePosition``, both of which build the order and send it to
``ExchangePort``. Reconciliation's booking slice (this change) adds a second
kind: an attempt ``ApproveBooking`` constructs directly in status FILLED,
recording a close the VENUE reports that this system never submitted. The
two kinds must stay distinguishable in the row itself -- ``origin`` is the
queryable predicate, and it also answers a second question for free
(design.md § 8): a VENUE row's ``usd_rate`` is a booking-time rate, not a
fill-time rate.

``ADD COLUMN ... DEFAULT 'SYSTEM'`` backfills every existing row correct by
construction: every pre-0022 attempt was built by ``PlaceOrder`` or
``ClosePosition``, both of which submit to a venue. The DEFAULT stays on the
column permanently -- it is what lets this be one statement rather than an
ADD COLUMN nullable, a backfill UPDATE, and an ALTER COLUMN SET NOT NULL.
The Python ``ExecutionAttempt.origin`` field carries no default of its own;
mypy therefore forces every constructor to name it, which is the discipline
the DB default cannot provide.

``downgrade()`` REFUSES while any VENUE-origin row exists, naming the count
and the ids (0012/0021 precedent) -- and, UNLIKE 0021's
``force_failed_close_drop``, offers **no force flag at all**. 0021's escape
deletes FAILED closing attempts, which recorded no fills and left nothing
behind to lose. A VENUE attempt is the opposite: it always has ledger rows
behind it (it is constructed already FILLED), and the append-only ledger
trigger itself forbids deleting that history. No flag should offer to
discard what the database already refuses to let go.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "execution_attempts"
_COLUMN = "origin"
_CHECK = "ck_execution_attempts_origin"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.Text(), nullable=False, server_default="SYSTEM"),
    )
    op.create_check_constraint(_CHECK, _TABLE, f"{_COLUMN} IN ('SYSTEM', 'VENUE')")


def downgrade() -> None:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT id FROM {_TABLE} WHERE {_COLUMN} = 'VENUE'"  # noqa: S608
            )
        )
        .all()
    )
    if rows:
        ids = ", ".join(str(row[0]) for row in rows)
        raise RuntimeError(
            f"{len(rows)} execution_attempts row(s) ({ids}) record a VENUE-origin "
            "attempt, which the pre-0022 shape cannot represent. A VENUE attempt "
            "is constructed already FILLED and always has ledger rows behind it, "
            "and the append-only ledger trigger itself forbids deleting that "
            "history -- so, unlike 0021's force_failed_close_drop, this downgrade "
            "offers no force flag to discard rows and make itself succeed."
        )

    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, _COLUMN)
