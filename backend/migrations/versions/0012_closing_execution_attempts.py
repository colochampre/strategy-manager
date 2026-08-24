"""``execution_attempts`` can belong to a close as well as to an open.

Until now every attempt was reservation-bound: ``reservation_id`` was NOT NULL
and UNIQUE, one attempt per reservation. That shape could not express a close
at all, and closes were consequently broken in every timing window -- reusing
the opening reservation hit the UNIQUE constraint inside the reservation's TTL
and hit the expiry re-check outside it, so no close ever reached the exchange.

A close is a different animal. It consumes no capital, takes no advisory lock,
and holds no reservation: once the opening order FILLED, its reservation
stopped counting toward pool availability (only PENDING and SUBMITTED do) and
the spend became visible in the exchange balance instead. Closing simply
returns the money the same way.

So an attempt now names exactly one of two things, enforced by
``ck_execution_attempts_one_origin``:

- ``reservation_id``       -- an opening order, against capital it reserved
- ``closes_allocation_id`` -- a closing order, against a position that
                              reservation opened

Both stay UNIQUE, and both uniqueness rules are the idempotency rule for their
side: one opening order per reservation, one closing order per position.
PostgreSQL permits many NULLs in a UNIQUE column, so making ``reservation_id``
nullable does not weaken the guarantee that already protected opens.

Existing rows are all opens and satisfy the new constraint unchanged.

``downgrade()`` refuses while any closing attempt exists rather than deleting
trading history to fit an older shape. Pass ``-x force_close_attempt_drop=1``
to discard those rows anyway.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "execution_attempts"
_COLUMN = "closes_allocation_id"
_CHECK = "ck_execution_attempts_one_origin"
_UNIQUE = "uq_execution_attempts_closes_allocation"
_FK = "fk_execution_attempts_closes_allocation"

# Sizing a close aggregates one allocation's ledger rows. ledger_entries is
# append-only and therefore only ever grows, and its existing indexes are on
# (strategy_id, filled_at) and (venue, settlement_currency, filled_at) —
# neither helps this lookup, which would degrade into a full scan on the one
# table that can never be pruned.
_LEDGER_INDEX = "ix_ledger_allocation"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(_FK, _TABLE, "reservations", [_COLUMN], ["id"])
    op.create_unique_constraint(_UNIQUE, _TABLE, [_COLUMN])
    op.alter_column(
        _TABLE,
        "reservation_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_check_constraint(
        _CHECK,
        _TABLE,
        "(reservation_id IS NOT NULL) <> (closes_allocation_id IS NOT NULL)",
    )
    op.create_index(_LEDGER_INDEX, "ledger_entries", ["allocation_id"])


def downgrade() -> None:
    forced = context.get_x_argument(as_dictionary=True).get("force_close_attempt_drop")
    if not forced:
        remaining = (
            op.get_bind()
            .execute(
                sa.text(
                    f"SELECT count(*) FROM {_TABLE} WHERE {_COLUMN} IS NOT NULL"  # noqa: S608
                )
            )
            .scalar_one()
        )
        if remaining:
            raise RuntimeError(
                f"{remaining} execution_attempts row(s) record a closing order, "
                "which the pre-0012 shape cannot represent. Downgrading would "
                "delete real trading history. Re-run with "
                "-x force_close_attempt_drop=1 to discard those rows instead."
            )

    op.drop_index(_LEDGER_INDEX, table_name="ledger_entries")
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.execute(sa.text(f"DELETE FROM {_TABLE} WHERE {_COLUMN} IS NOT NULL"))  # noqa: S608
    op.alter_column(
        _TABLE,
        "reservation_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_constraint(_UNIQUE, _TABLE, type_="unique")
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, _COLUMN)
