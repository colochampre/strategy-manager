"""``reservations.pool_total_at_open`` (design.md section 10; tasks.md PR 6a,
unit 3a).

Each reservation now records the capital of ITS OWN pool -- the pool of its
``(exchange, venue, settlement_currency)`` -- as ``AllocateCapital`` read it
inside the advisory lock, at the moment the reservation was made. The
performance read models use it as the denominator of a trade's return
(``pnl / pool_total_at_open``). It is in that pool's settlement currency and is
never summed across pools (CLAUDE.md rules 5 and 7).

**Why it ships alone and first.** The value cannot be reconstructed afterwards:
the pool balance is a live reading, and no earlier row keeps it. Every
reservation made before this migration is deployed stays NULL forever, and a
trade with a NULL value is excluded from the return curve. So the sooner this
is deployed, the fewer trades are lost to it. Nothing is backfilled and no
default is set: NULL means "not recorded", and a made-up number would be worse.

**The CHECK.** ``pool_total_at_open IS NULL OR pool_total_at_open > 0``. A
reservation exists only when ``decide()`` granted something, and a grant needs
positive availability, which the snapshot's ``total >= available`` CHECK keeps
at or below ``total``. So a real value is always positive; ``AllocateCapital``
also stores NULL, never zero, if a source ever broke that.

**The downgrade refusal.** Dropping the column discards values that no query can
recompute, exactly the 0012/0021/0024/0025 precedent. The downgrade refuses
while any row holds a non-null value and names the count. There is no force
flag: the values are not safe to discard.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_RESERVATIONS = "reservations"
_COLUMN = "pool_total_at_open"
_POSITIVE_CHECK = "ck_reservations_pool_total_at_open_positive"


def upgrade() -> None:
    op.add_column(
        _RESERVATIONS,
        sa.Column(_COLUMN, sa.Numeric(38, 18), nullable=True),
    )
    op.create_check_constraint(
        _POSITIVE_CHECK,
        _RESERVATIONS,
        f"{_COLUMN} IS NULL OR {_COLUMN} > 0",
    )


def downgrade() -> None:
    bind: Connection = op.get_bind()

    recorded_count = bind.execute(
        sa.text(f"SELECT count(*) FROM {_RESERVATIONS} WHERE {_COLUMN} IS NOT NULL")  # noqa: S608
    ).scalar_one()

    if recorded_count > 0:
        raise RuntimeError(
            f"Refusing to downgrade 0026_reservation_pool_total: {recorded_count} "
            f"{_RESERVATIONS} row(s) carry a non-null {_COLUMN}. That is the pool "
            "capital as it stood when each reservation was made; it cannot be "
            "recomputed once dropped (0012/0021/0024/0025 precedent). This downgrade "
            "offers no force flag: the values are not safe to discard."
        )

    op.drop_constraint(_POSITIVE_CHECK, _RESERVATIONS, type_="check")
    op.drop_column(_RESERVATIONS, _COLUMN)
