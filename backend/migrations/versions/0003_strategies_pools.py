"""capital_pools + strategies tables; ALTER signals ADD CONSTRAINT
fk_signals_strategy; seed the four configured pools. ``capital_pools`` is
the single source of truth for which pools exist — there is no
``CONFIGURED_POOLS`` env list (design.md, tasks.md § Slice 3).

HARD CONSTRAINT: ``strategies.id`` has NO ``gen_random_uuid()`` server
default. Slice 2 already populated ``signals.strategy_id =
UUID(alert.signal_type)``; registering a strategy MUST reuse that exact
same UUID explicitly, or this revision's ``ADD CONSTRAINT
fk_signals_strategy`` fails against those rows (design.md § "strategy_id
derives from signal_type").

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Placeholder minimums until a real per-pool configuration surface exists —
# not specified by design.md; tracked as a follow-up.
_SEED_POOLS: list[dict[str, str]] = [
    {"venue": "spot", "settlement_currency": "USDT", "min_order_size": "10"},
    {"venue": "usdt-m", "settlement_currency": "USDT", "min_order_size": "5"},
    {"venue": "coin-m", "settlement_currency": "BTC", "min_order_size": "0.0001"},
    {"venue": "coin-m", "settlement_currency": "ETH", "min_order_size": "0.001"},
]


def upgrade() -> None:
    op.create_table(
        "capital_pools",
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("settlement_currency", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("min_order_size", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("venue", "settlement_currency"),
        sa.CheckConstraint(
            "venue IN ('spot','usdt-m','coin-m')", name="ck_capital_pools_venue"
        ),
        sa.CheckConstraint(
            "min_order_size > 0", name="ck_capital_pools_min_order_size_positive"
        ),
    )

    op.create_table(
        "strategies",
        # No server_default: the caller MUST supply the signal_type UUID
        # explicitly (see the module docstring's HARD CONSTRAINT).
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("settlement_currency", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fill_mode", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("fill_mode IN ('SKIP','PARTIAL')", name="ck_strategies_fill_mode"),
        sa.ForeignKeyConstraint(
            ["venue", "settlement_currency"],
            ["capital_pools.venue", "capital_pools.settlement_currency"],
            name="fk_strategies_capital_pool",
        ),
    )

    # Deferred from 0002: the strategies table did not exist yet.
    op.create_foreign_key(
        "fk_signals_strategy", "signals", "strategies", ["strategy_id"], ["id"]
    )

    pools_table = sa.table(
        "capital_pools",
        sa.column("venue", sa.Text()),
        sa.column("settlement_currency", sa.Text()),
        sa.column("min_order_size", sa.Numeric(38, 18)),
    )
    op.bulk_insert(pools_table, _SEED_POOLS)


def downgrade() -> None:
    op.drop_constraint("fk_signals_strategy", "signals", type_="foreignkey")
    op.drop_table("strategies")
    op.drop_table("capital_pools")
