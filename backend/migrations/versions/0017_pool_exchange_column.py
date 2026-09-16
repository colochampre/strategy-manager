"""Record which exchange a pool's money sits on.

A venue says which wallet and which product -- spot, USDⓈ-M, COIN-M -- and
two exchanges both have a ``usdt-m`` one. Until now the system had no way to
say which: a Binance USDT futures pool and a Bybit USDT futures pool would be
the same row, the same advisory lock, the same balance snapshot, and a ledger
that could not say where a fill happened.

This is the EXPAND half of the change. It adds the column and its constraint
only; the primary key and every foreign key still run on
``(venue, settlement_currency)``, so nothing about identity moves yet and the
system keeps working exactly as before. The key switch that finally lets two
exchanges share a venue is a separate migration, once every writer is known to
populate this column.

Backfill follows the pools as they were actually configured: ``usdt-m`` is
Bybit's -- the only venue this system has ever placed a live order on -- and
``spot`` and ``coin-m`` are the Pionex-era pools, all three disabled.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLES = ("capital_pools", "pool_balance_snapshots")

# Every value the system may name. A pool on an exchange nothing can sign for
# is a pool whose orders have no key.
_KNOWN_EXCHANGES = "exchange IN ('pionex','bybit','binance')"

# usdt-m was Bybit's; spot and coin-m were configured in the Pionex era.
_BACKFILL = (
    "UPDATE {table} SET exchange = "
    "CASE WHEN venue = 'usdt-m' THEN 'bybit' ELSE 'pionex' END"
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("exchange", sa.Text(), nullable=True))
        op.execute(_BACKFILL.format(table=table))
        op.alter_column(table, "exchange", nullable=False)
        op.create_check_constraint(f"ck_{table}_exchange", table, _KNOWN_EXCHANGES)


def downgrade() -> None:
    for table in _TABLES:
        op.drop_constraint(f"ck_{table}_exchange", table)
        op.drop_column(table, "exchange")
