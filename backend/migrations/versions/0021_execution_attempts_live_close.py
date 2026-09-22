"""``execution_attempts.closes_allocation_id`` stops being UNIQUE system-wide.

Migration ``0012`` made a closing attempt UNIQUE per allocation, unconditionally
-- one closing order per position, forever. That was the right idempotency
rule for "a close is in flight", and the wrong one for "a close is DONE":
spec: trade-execution § Retryable Close, Single In-Flight Attempt requires a
FAILED, FILLED or ABORTED_EXPIRED attempt to never block a LATER close on the
same allocation -- a rejected close must be retryable, and a partial fill
must leave a residual that can still be closed. The unconditional UNIQUE made
both impossible: a retry after a definitive rejection hit the same
constraint the rejection itself never violated, so the position was stuck
closable exactly once.

The fix is a PARTIAL unique index scoped to ``status = 'SUBMITTED'`` only
(owner decision, this unit -- not ``status <> 'FAILED'``, which would have
left a FILLED close's residual permanently unclosable): at most one LIVE
close may be in flight per allocation at a time, and however many FAILED or
FILLED rows accumulate on that allocation afterward, none of them counts
against it. A plain index replaces the lookup the dropped UNIQUE used to
provide as a side effect -- ``latest_close_for`` and
``submitted_closing_allocations`` both filter on this column, and it was
otherwise the table's only index on it.

``downgrade()`` follows ``0012``'s own precedent: refuse to silently discard
trading history. The pre-0021 shape allows at most ONE closing attempt per
allocation ever, so downgrading while any allocation holds MORE than one
raises, naming the count and the allocation ids. Pass
``-x force_failed_close_drop=1`` to delete only the FAILED closing attempts
on those allocations first -- after which, per the spec's own single-live-
attempt invariant, at most one non-FAILED row can remain per allocation and
the unconditional UNIQUE becomes satisfiable again.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "execution_attempts"
_COLUMN = "closes_allocation_id"
_UNIQUE = "uq_execution_attempts_closes_allocation"
_LIVE_CLOSE_INDEX = "ux_execution_attempts_live_close"
_ALLOCATION_INDEX = "ix_execution_attempts_closes_allocation"


def upgrade() -> None:
    op.drop_constraint(_UNIQUE, _TABLE, type_="unique")
    op.create_index(
        _LIVE_CLOSE_INDEX,
        _TABLE,
        [_COLUMN],
        unique=True,
        postgresql_where=sa.text(f"{_COLUMN} IS NOT NULL AND status = 'SUBMITTED'"),
    )
    op.create_index(_ALLOCATION_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    forced = context.get_x_argument(as_dictionary=True).get("force_failed_close_drop")
    if forced:
        bind.execute(
            sa.text(
                f"DELETE FROM {_TABLE} WHERE status = 'FAILED' "  # noqa: S608
                f"AND {_COLUMN} IN ("
                f"SELECT {_COLUMN} FROM {_TABLE} WHERE {_COLUMN} IS NOT NULL "
                f"GROUP BY {_COLUMN} HAVING count(*) > 1)"
            )
        )

    rows = bind.execute(
        sa.text(
            f"SELECT {_COLUMN}, count(*) FROM {_TABLE} "  # noqa: S608
            f"WHERE {_COLUMN} IS NOT NULL GROUP BY {_COLUMN} HAVING count(*) > 1"
        )
    ).all()
    if rows:
        allocation_ids = ", ".join(str(row[0]) for row in rows)
        total = sum(row[1] for row in rows)
        raise RuntimeError(
            f"{total} execution_attempts row(s) across {len(rows)} allocation(s) "
            f"({allocation_ids}) record more than one closing attempt, which the "
            "pre-0021 unconditional UNIQUE cannot represent. Downgrading would "
            "delete real trading history. Re-run with "
            "-x force_failed_close_drop=1 to discard the FAILED closing "
            "attempts on those allocations first."
        )

    op.drop_index(_ALLOCATION_INDEX, table_name=_TABLE)
    op.drop_index(_LIVE_CLOSE_INDEX, table_name=_TABLE)
    op.create_unique_constraint(_UNIQUE, _TABLE, [_COLUMN])
