"""``execution_attempts`` records the size that was actually sent.

A spot market order is denominated differently per side: a BUY spends a quote
amount, a SELL sells a base size. Until now the table had one NOT NULL
``quantity`` column, which forced a buy to store ``granted / alert_price`` --
a base size that was never transmitted, derived from a price that was already
stale when the alert fired, and impossible to reconcile against the exchange.

So ``quantity`` becomes nullable, ``quote_amount`` joins it, and a CHECK
enforces that exactly one is set. That mirrors the ``MarketBuy | MarketSell``
sum type in the domain: the invalid combination cannot be written from either
side.

Existing rows are all sells-or-buys recorded as base quantities, and they
satisfy the new constraint unchanged (``quantity`` set, ``quote_amount``
NULL), so no backfill is needed.

``downgrade()`` refuses while any row carries a ``quote_amount``. Restoring
NOT NULL would demand a base size for those rows, and there is no honest way
to invent one: the price that would convert it is not in this table. Pass
``-x force_quote_amount_drop=1`` to drop those rows' size information anyway.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "execution_attempts"
_CHECK = "ck_execution_attempts_one_size"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("quote_amount", sa.Numeric(38, 18), nullable=True))
    op.alter_column(_TABLE, "quantity", existing_type=sa.Numeric(38, 18), nullable=True)
    op.create_check_constraint(
        _CHECK,
        _TABLE,
        "(quantity IS NOT NULL) <> (quote_amount IS NOT NULL)",
    )


def downgrade() -> None:
    forced = context.get_x_argument(as_dictionary=True).get("force_quote_amount_drop")
    if not forced:
        remaining = (
            op.get_bind()
            .execute(
                sa.text(
                    f"SELECT count(*) FROM {_TABLE} WHERE quote_amount IS NOT NULL"  # noqa: S608
                )
            )
            .scalar_one()
        )
        if remaining:
            raise RuntimeError(
                f"{remaining} execution_attempts row(s) carry a quote_amount and "
                "no base quantity. Downgrading would have to invent one, and the "
                "price that would convert it is not in this table. Re-run with "
                "-x force_quote_amount_drop=1 to discard their size instead."
            )

    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.execute(
        sa.text(f"UPDATE {_TABLE} SET quantity = 0 WHERE quantity IS NULL")  # noqa: S608
    )
    op.alter_column(_TABLE, "quantity", existing_type=sa.Numeric(38, 18), nullable=False)
    op.drop_column(_TABLE, "quote_amount")
