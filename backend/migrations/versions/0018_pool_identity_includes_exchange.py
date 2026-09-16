"""Make the exchange part of a pool's identity.

The CONTRACT half of the change ``0017`` began. ``0017`` recorded which
exchange each pool's money sits on; until now that column was carried but not
keyed, so ``capital_pools`` still allowed exactly one row per
``(venue, settlement_currency)`` and a Binance USDT futures pool could not
exist beside Bybit's.

After this, a pool is ``(exchange, venue, settlement_currency)`` everywhere
that references one: the primary key, the snapshot that mirrors it, and the
two tables that point at a pool and hold money against it -- strategies and
reservations.

``strategies`` and ``reservations`` inherit the exchange of the pool their
venue already named, which is the same backfill ``0017`` applied: usdt-m rows
are Bybit's, spot and coin-m rows are the Pionex era's. Rows cannot be
ambiguous here, because until this migration only one exchange per venue could
exist at all.

The advisory lock changes shape with this: it folds the exchange into its
first key as ``exchange:venue``. Nothing in the schema encodes that -- the
startup collision invariant recomputes it from these rows, so it is verified
against the real keys rather than assumed.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_POOL_COLUMNS = ["exchange", "venue", "settlement_currency"]
_KNOWN_EXCHANGES = "exchange IN ('pionex','bybit','binance')"
_BACKFILL = (
    "UPDATE {table} SET exchange = "
    "CASE WHEN venue = 'usdt-m' THEN 'bybit' ELSE 'pionex' END"
)

# The snapshot FK was created unnamed by 0009, so it carries PostgreSQL's
# generated name rather than one this project chose.
_SNAPSHOT_FK = "pool_balance_snapshots_venue_settlement_currency_fkey"
_SNAPSHOT_FK_NEW = "fk_pool_balance_snapshots_capital_pool"


def upgrade() -> None:
    for table in ("strategies", "reservations"):
        op.add_column(table, sa.Column("exchange", sa.Text(), nullable=True))
        op.execute(_BACKFILL.format(table=table))
        op.alter_column(table, "exchange", nullable=False)
        op.create_check_constraint(f"ck_{table}_exchange", table, _KNOWN_EXCHANGES)

    # Every reference has to go before the key it points at can change.
    op.drop_constraint("fk_strategies_capital_pool", "strategies", type_="foreignkey")
    op.drop_constraint("fk_reservations_capital_pool", "reservations", type_="foreignkey")
    op.drop_constraint(_SNAPSHOT_FK, "pool_balance_snapshots", type_="foreignkey")

    op.drop_constraint("capital_pools_pkey", "capital_pools", type_="primary")
    op.create_primary_key("capital_pools_pkey", "capital_pools", _POOL_COLUMNS)

    op.drop_constraint(
        "pool_balance_snapshots_pkey", "pool_balance_snapshots", type_="primary"
    )
    op.create_primary_key(
        "pool_balance_snapshots_pkey", "pool_balance_snapshots", _POOL_COLUMNS
    )

    op.create_foreign_key(
        "fk_strategies_capital_pool",
        "strategies",
        "capital_pools",
        _POOL_COLUMNS,
        _POOL_COLUMNS,
    )
    op.create_foreign_key(
        "fk_reservations_capital_pool",
        "reservations",
        "capital_pools",
        _POOL_COLUMNS,
        _POOL_COLUMNS,
    )
    op.create_foreign_key(
        _SNAPSHOT_FK_NEW,
        "pool_balance_snapshots",
        "capital_pools",
        _POOL_COLUMNS,
        _POOL_COLUMNS,
        ondelete="CASCADE",
    )


def _assert_one_exchange_per_venue() -> None:
    """The old key cannot represent what the new one allows.

    Once two exchanges hold the same venue and currency, going back to
    ``(venue, settlement_currency)`` would need one of the two pools to stop
    existing -- along with its strategies, reservations and snapshot. Postgres
    does refuse it on its own, with a duplicate-key error that names an index
    rather than the decision the operator has to make. This says it instead.
    """
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT venue, settlement_currency, count(*) AS exchanges "
                "FROM capital_pools GROUP BY venue, settlement_currency "
                "HAVING count(*) > 1 ORDER BY venue, settlement_currency"
            )
        )
        .all()
    )
    if not duplicates:
        return

    listed = ", ".join(
        f"{venue}/{currency} on {count} exchanges"
        for venue, currency, count in duplicates
    )
    raise RuntimeError(
        "cannot downgrade past 0018: the previous key is (venue, settlement_currency), "
        f"and these pools now exist on more than one exchange: {listed}. Delete the "
        "pools of every exchange but one first -- and close or move whatever they "
        "hold, because their strategies, reservations and balance snapshots go with "
        "them."
    )


def downgrade() -> None:
    _assert_one_exchange_per_venue()

    op.drop_constraint(_SNAPSHOT_FK_NEW, "pool_balance_snapshots", type_="foreignkey")
    op.drop_constraint("fk_reservations_capital_pool", "reservations", type_="foreignkey")
    op.drop_constraint("fk_strategies_capital_pool", "strategies", type_="foreignkey")

    op.drop_constraint(
        "pool_balance_snapshots_pkey", "pool_balance_snapshots", type_="primary"
    )
    op.create_primary_key(
        "pool_balance_snapshots_pkey",
        "pool_balance_snapshots",
        ["venue", "settlement_currency"],
    )

    op.drop_constraint("capital_pools_pkey", "capital_pools", type_="primary")
    op.create_primary_key(
        "capital_pools_pkey", "capital_pools", ["venue", "settlement_currency"]
    )

    op.create_foreign_key(
        "fk_strategies_capital_pool",
        "strategies",
        "capital_pools",
        ["venue", "settlement_currency"],
        ["venue", "settlement_currency"],
    )
    op.create_foreign_key(
        "fk_reservations_capital_pool",
        "reservations",
        "capital_pools",
        ["venue", "settlement_currency"],
        ["venue", "settlement_currency"],
    )
    op.create_foreign_key(
        _SNAPSHOT_FK,
        "pool_balance_snapshots",
        "capital_pools",
        ["venue", "settlement_currency"],
        ["venue", "settlement_currency"],
        ondelete="CASCADE",
    )

    for table in ("reservations", "strategies"):
        op.drop_constraint(f"ck_{table}_exchange", table)
        op.drop_column(table, "exchange")
