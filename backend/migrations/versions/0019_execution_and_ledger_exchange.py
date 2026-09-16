"""Carry the exchange onto the execution attempt and the ledger row.

``0018`` made the exchange part of a pool's identity. These two tables record
what happened AGAINST a pool, and without the column a fill on Binance and a
fill on Bybit are indistinguishable once written: the venue says ``usdt-m``
for both.

The unique index moves with it. Fill ids are only unique WITHIN an exchange --
nothing stops Binance and Bybit from issuing the same one -- so keyed by
``(venue, exchange_fill_id)`` the second exchange's fill would be rejected as
a duplicate of the first's, and that fill would never reach the ledger.

``ledger_entries`` carries the append-only triggers from ``0005``, and the
backfill is an UPDATE: it would fire the very guard that exists to stop rows
being rewritten. The triggers are therefore disabled for exactly the length of
that statement and re-enabled immediately, inside the same transaction -- so a
failure anywhere in this migration rolls back with the guard intact. This is
the one write to that table that is not a new fill, and it is adding a fact
about rows rather than changing what they say.

Backfill follows the same mapping as ``0017`` and ``0018``: usdt-m rows are
Bybit's, spot and coin-m rows are the Pionex era's.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_KNOWN_EXCHANGES = "exchange IN ('pionex','bybit','binance')"
_BACKFILL = (
    "UPDATE {table} SET exchange = "
    "CASE WHEN venue = 'usdt-m' THEN 'bybit' ELSE 'pionex' END"
)
_FILL_INDEX = "ux_ledger_exchange_fill"


def upgrade() -> None:
    op.add_column("execution_attempts", sa.Column("exchange", sa.Text(), nullable=True))
    op.execute(_BACKFILL.format(table="execution_attempts"))
    op.alter_column("execution_attempts", "exchange", nullable=False)
    op.create_check_constraint(
        "ck_execution_attempts_exchange", "execution_attempts", _KNOWN_EXCHANGES
    )

    op.add_column("ledger_entries", sa.Column("exchange", sa.Text(), nullable=True))
    op.execute("ALTER TABLE ledger_entries DISABLE TRIGGER USER")
    op.execute(_BACKFILL.format(table="ledger_entries"))
    op.execute("ALTER TABLE ledger_entries ENABLE TRIGGER USER")
    op.alter_column("ledger_entries", "exchange", nullable=False)
    op.create_check_constraint(
        "ck_ledger_entries_exchange", "ledger_entries", _KNOWN_EXCHANGES
    )

    op.drop_constraint(_FILL_INDEX, "ledger_entries", type_="unique")
    op.create_unique_constraint(
        _FILL_INDEX, "ledger_entries", ["exchange", "venue", "exchange_fill_id"]
    )


def downgrade() -> None:
    op.drop_constraint(_FILL_INDEX, "ledger_entries", type_="unique")
    op.create_unique_constraint(
        _FILL_INDEX, "ledger_entries", ["venue", "exchange_fill_id"]
    )

    op.drop_constraint("ck_ledger_entries_exchange", "ledger_entries")
    op.drop_column("ledger_entries", "exchange")

    op.drop_constraint("ck_execution_attempts_exchange", "execution_attempts")
    op.drop_column("execution_attempts", "exchange")
