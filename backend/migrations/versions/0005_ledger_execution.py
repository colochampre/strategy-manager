"""execution_attempts + ledger_entries tables; the append-only guard on
``ledger_entries`` (design.md § SQL Schema and Migration Map, § "Decision:
append-only enforced by two triggers, not REVOKE"; spec: trade-execution,
trade-ledger).

Both triggers are mandatory, not one: a ``BEFORE UPDATE OR DELETE ... FOR
EACH ROW`` trigger AND a ``BEFORE TRUNCATE ... FOR EACH STATEMENT`` trigger.
Verified empirically against live PostgreSQL: a row-level trigger alone does
NOT intercept ``TRUNCATE`` — the row trigger never fires and the table is
emptied regardless. ``ledger_entries`` is the one table in this system that
can never be reconstructed, so a single trigger is not an acceptable guard.

``downgrade()`` refuses to run while ``ledger_entries`` holds rows unless the
caller passes ``-x force_ledger_drop=1`` — the ledger-cutoff rule made
executable (design.md's "Migration / Rollout").

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_APPEND_ONLY_FUNCTION = "fn_ledger_append_only"


def upgrade() -> None:
    op.create_table(
        "execution_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "reservation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("settlement_currency", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("client_order_id", sa.Text(), nullable=False, unique=True),
        sa.Column("exchange_order_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_execution_attempts_side"),
        sa.CheckConstraint("quantity > 0", name="ck_execution_attempts_quantity_positive"),
        sa.CheckConstraint(
            "status IN ('SUBMITTED','FILLED','FAILED','ABORTED_EXPIRED')",
            name="ck_execution_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["reservations.id"], name="fk_execution_attempts_reservation"
        ),
    )

    op.create_table(
        "ledger_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("settlement_currency", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=False),
        sa.Column("fee", sa.Numeric(38, 18), nullable=False, server_default="0"),
        sa.Column("fee_currency", sa.Text(), nullable=False),
        sa.Column("notional", sa.Numeric(38, 18), nullable=False),
        sa.Column("exchange_order_id", sa.Text(), nullable=False),
        sa.Column("exchange_fill_id", sa.Text(), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usd_rate_at_fill", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_ledger_entries_side"),
        sa.CheckConstraint("quantity > 0", name="ck_ledger_entries_quantity_positive"),
        sa.CheckConstraint("price > 0", name="ck_ledger_entries_price_positive"),
        sa.CheckConstraint("fee >= 0", name="ck_ledger_entries_fee_non_negative"),
        sa.CheckConstraint("notional > 0", name="ck_ledger_entries_notional_positive"),
        sa.CheckConstraint(
            "usd_rate_at_fill > 0", name="ck_ledger_entries_usd_rate_at_fill_positive"
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name="fk_ledger_entries_strategy"
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"], ["reservations.id"], name="fk_ledger_entries_allocation"
        ),
        sa.ForeignKeyConstraint(
            ["execution_attempt_id"],
            ["execution_attempts.id"],
            name="fk_ledger_entries_execution_attempt",
        ),
        sa.UniqueConstraint("venue", "exchange_fill_id", name="ux_ledger_exchange_fill"),
    )
    op.create_index(
        "ix_ledger_strategy_filled_at", "ledger_entries", ["strategy_id", "filled_at"]
    )
    op.create_index(
        "ix_ledger_pool_filled_at",
        "ledger_entries",
        ["venue", "settlement_currency", "filled_at"],
    )

    # Append-only enforcement. Both triggers are required: REVOKE does not
    # constrain a superuser (this app connects as `postgres`), and a row
    # trigger alone does not intercept TRUNCATE (verified empirically).
    op.execute(
        f"""
        CREATE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'ledger_entries is append-only: % is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_ledger_no_update_delete
            BEFORE UPDATE OR DELETE ON ledger_entries
            FOR EACH ROW EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_ledger_no_truncate
            BEFORE TRUNCATE ON ledger_entries
            FOR EACH STATEMENT EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    row_count = bind.execute(sa.text("SELECT COUNT(*) FROM ledger_entries")).scalar_one()
    if row_count > 0:
        x_args = context.get_x_argument(as_dictionary=True)
        if x_args.get("force_ledger_drop") != "1":
            raise RuntimeError(
                "Refusing to downgrade 0005_ledger_execution: ledger_entries holds "
                f"{row_count} row(s). The ledger is append-only and this data can "
                "never be reconstructed. Pass -x force_ledger_drop=1 to force this "
                "downgrade anyway."
            )

    op.execute("DROP TRIGGER IF EXISTS trg_ledger_no_truncate ON ledger_entries")
    op.execute("DROP TRIGGER IF EXISTS trg_ledger_no_update_delete ON ledger_entries")
    op.execute(f"DROP FUNCTION IF EXISTS {_APPEND_ONLY_FUNCTION}()")
    op.drop_index("ix_ledger_pool_filled_at", table_name="ledger_entries")
    op.drop_index("ix_ledger_strategy_filled_at", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_table("execution_attempts")
