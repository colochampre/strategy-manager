"""Every owned row gets its owner (multi-user design AD2; tasks.md B.1).

**Who owns what exists.** The one user in ``users`` when this runs: the owner,
whose row their first signed-in request created after ``0029`` (decision 11).
With rows to own and any other number of users, the migration refuses and names
the count, rather than guess whose money a row is. A database nobody has ever
signed into, holding nothing but the pools ``0003`` seeded, loses those pools:
nothing references them, and saving a key creates its pool again
(``SqlAlchemyCapitalPoolWriter.enable``).

**No row is rewritten to receive its owner.** Each owner column is added with
the owner's id as a constant default, which PostgreSQL 11+ keeps in the
catalogue instead of writing into every row, and the default is dropped at
once. That matters for the ledger, which is append-only: its triggers never
fire and every row keeps its ``xmin``.

**Pools are keyed by an id.** Two users may each hold a pool on the same market,
so ``(exchange, venue, settlement_currency)`` stops being a key. ``capital_pools``
gets an identity ``id`` and ``UNIQUE (user_id, exchange, venue,
settlement_currency)``. The four tables that hold something against a pool point
at it by ``(pool_id, user_id)``, so the database itself refuses a row of one user
in another user's pool. Their market columns stay, as data.

**Strategies name a market, not a pool** (AD3, moved here from ``0031``). Their
composite FK cannot survive the new key, so it is dropped, and a CHECK keeps the
venue to the ones a pool can have. Creating a strategy still checks that the
pool exists.

**Uniques that become per user:** one active key per exchange, one record of a
venue fill, one open discrepancy per symbol. Their names stay, because code
catches them by name.

**Downgrade.** Refuses once more than one user exists: the old keys cannot hold
two users' rows. Otherwise it restores ``0029`` exactly, except that the seeded
pools a fresh database lost are not seeded again. A strategy naming a market
with no pool row (allowed from here on) makes the restored FK fail.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNED_TABLES = (
    "exchange_credentials",
    "capital_pools",
    "pool_balance_snapshots",
    "reservations",
    "execution_attempts",
    "ledger_entries",
    "reconciliation_discrepancies",
    "booking_proposals",
)
_POOL_COLUMNS = ["exchange", "venue", "settlement_currency"]
# Each table that holds something against a pool, its FK, and that FK's ON DELETE.
_POOL_REFERENCES: dict[str, tuple[str, str | None]] = {
    "pool_balance_snapshots": ("fk_pool_balance_snapshots_capital_pool", "CASCADE"),
    "reservations": ("fk_reservations_capital_pool", None),
    "reconciliation_discrepancies": ("fk_reconciliation_discrepancies_capital_pool", None),
    "booking_proposals": ("fk_booking_proposals_capital_pool", None),
}
_STRATEGY_POOL_FK = "fk_strategies_capital_pool"
_STRATEGY_VENUE = "ck_strategies_venue"
_POOL_PER_USER = "ux_capital_pools_user_market"
_POOL_ID_USER = "ux_capital_pools_id_user"
_ACTIVE_KEY = "ux_exchange_credentials_one_active_per_exchange"
_LEDGER_FILL = "ux_ledger_exchange_fill"
_OPEN_DISCREPANCY = "ux_reconciliation_open_per_symbol"


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar_one())


def _owner() -> UUID | None:
    """The one user who owns every existing row, or None when there is no row
    to own. Refuses any other number of users while rows exist."""
    users = [UUID(str(row[0])) for row in op.get_bind().execute(sa.text("SELECT id FROM users"))]
    held = any(
        _count(f"SELECT count(*) FROM {table}") > 0
        for table in (*_OWNED_TABLES, "strategies")
        if table != "capital_pools"
    )
    pools = _count("SELECT count(*) FROM capital_pools")
    if not held and not pools:
        return None
    if not held and not users:
        # Nobody ever signed in, and nothing but the seeded pools exists.
        op.execute("DELETE FROM capital_pools")
        return None
    if len(users) != 1:
        raise RuntimeError(
            "0030 gives every existing row to its owner and needs exactly one user "
            f"to do it; found {len(users)}. With none, sign in to the panel once so "
            "the owner's row exists, then migrate again."
        )
    return users[0]


def _add_owner_column(table: str, column: str, fk_name: str, owner: UUID | None) -> None:
    # Without an owner the table is empty, so NOT NULL needs no value.
    default = sa.text(f"'{owner}'::uuid") if owner is not None else None
    op.add_column(
        table,
        sa.Column(column, postgresql.UUID(as_uuid=True), nullable=False, server_default=default),
    )
    if default is not None:
        op.alter_column(table, column, server_default=None)
    op.create_foreign_key(fk_name, table, "users", [column], ["id"])
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    owner = _owner()

    for table in _OWNED_TABLES:
        _add_owner_column(table, "user_id", f"fk_{table}_user", owner)
    _add_owner_column("strategies", "author_id", "fk_strategies_author", owner)

    # Every reference has to go before the key it points at can change.
    for table, (fk_name, _) in _POOL_REFERENCES.items():
        op.drop_constraint(fk_name, table, type_="foreignkey")
    op.drop_constraint(_STRATEGY_POOL_FK, "strategies", type_="foreignkey")
    op.drop_constraint("pool_balance_snapshots_pkey", "pool_balance_snapshots", type_="primary")
    op.drop_constraint("capital_pools_pkey", "capital_pools", type_="primary")

    op.add_column(
        "capital_pools",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
    )
    op.create_primary_key("capital_pools_pkey", "capital_pools", ["id"])
    op.create_unique_constraint(_POOL_PER_USER, "capital_pools", ["user_id", *_POOL_COLUMNS])
    # The target of every pool FK: a row and its pool always share a user.
    op.create_unique_constraint(_POOL_ID_USER, "capital_pools", ["id", "user_id"])

    for table, (fk_name, ondelete) in _POOL_REFERENCES.items():
        op.add_column(table, sa.Column("pool_id", sa.Integer(), nullable=True))
        op.execute(
            f"UPDATE {table} AS t SET pool_id = p.id FROM capital_pools AS p "
            "WHERE (p.user_id, p.exchange, p.venue, p.settlement_currency) "
            "= (t.user_id, t.exchange, t.venue, t.settlement_currency)"
        )
        op.alter_column(table, "pool_id", nullable=False)
        op.create_foreign_key(
            fk_name,
            table,
            "capital_pools",
            ["pool_id", "user_id"],
            ["id", "user_id"],
            ondelete=ondelete,
        )
    op.create_primary_key("pool_balance_snapshots_pkey", "pool_balance_snapshots", ["pool_id"])

    op.create_check_constraint(
        _STRATEGY_VENUE, "strategies", "venue IN ('spot', 'usdt-m', 'coin-m')"
    )

    op.drop_index(_ACTIVE_KEY, table_name="exchange_credentials")
    op.create_index(
        _ACTIVE_KEY,
        "exchange_credentials",
        ["user_id", "exchange"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.drop_constraint(_LEDGER_FILL, "ledger_entries", type_="unique")
    op.create_unique_constraint(
        _LEDGER_FILL, "ledger_entries", ["user_id", "exchange", "venue", "exchange_fill_id"]
    )
    op.drop_index(_OPEN_DISCREPANCY, table_name="reconciliation_discrepancies")
    op.create_index(
        _OPEN_DISCREPANCY,
        "reconciliation_discrepancies",
        ["user_id", *_POOL_COLUMNS, "symbol"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    users = _count("SELECT count(*) FROM users")
    if users > 1:
        raise RuntimeError(
            "0030's downgrade cannot hold more than one user's rows in 0029's keys; "
            f"found {users}. Fix forward instead."
        )

    op.drop_index(_OPEN_DISCREPANCY, table_name="reconciliation_discrepancies")
    op.create_index(
        _OPEN_DISCREPANCY,
        "reconciliation_discrepancies",
        [*_POOL_COLUMNS, "symbol"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.drop_constraint(_LEDGER_FILL, "ledger_entries", type_="unique")
    op.create_unique_constraint(
        _LEDGER_FILL, "ledger_entries", ["exchange", "venue", "exchange_fill_id"]
    )
    op.drop_index(_ACTIVE_KEY, table_name="exchange_credentials")
    op.create_index(
        _ACTIVE_KEY,
        "exchange_credentials",
        ["exchange"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.drop_constraint(_STRATEGY_VENUE, "strategies", type_="check")

    op.drop_constraint("pool_balance_snapshots_pkey", "pool_balance_snapshots", type_="primary")
    for table, (fk_name, _) in _POOL_REFERENCES.items():
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.drop_column(table, "pool_id")
    op.drop_constraint(_POOL_ID_USER, "capital_pools", type_="unique")
    op.drop_constraint(_POOL_PER_USER, "capital_pools", type_="unique")
    op.drop_constraint("capital_pools_pkey", "capital_pools", type_="primary")
    op.drop_column("capital_pools", "id")
    op.create_primary_key("capital_pools_pkey", "capital_pools", _POOL_COLUMNS)
    op.create_primary_key("pool_balance_snapshots_pkey", "pool_balance_snapshots", _POOL_COLUMNS)
    for table, (fk_name, ondelete) in _POOL_REFERENCES.items():
        op.create_foreign_key(
            fk_name, table, "capital_pools", _POOL_COLUMNS, _POOL_COLUMNS, ondelete=ondelete
        )
    op.create_foreign_key(
        _STRATEGY_POOL_FK, "strategies", "capital_pools", _POOL_COLUMNS, _POOL_COLUMNS
    )

    # Dropping a column rewrites no row, so the ledger's triggers stay quiet.
    op.drop_column("strategies", "author_id")
    for table in _OWNED_TABLES:
        op.drop_column(table, "user_id")
