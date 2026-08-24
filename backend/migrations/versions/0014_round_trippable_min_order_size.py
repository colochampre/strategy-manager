"""Raise the spot/USDT pool minimum to one a position can be closed at.

A pool's ``min_order_size`` was seeded with placeholder values, and spot/USDT's
happened to land on 10 -- exactly Pionex's ``minAmount`` for ETH_USDT and
BTC_USDT. That coincidence is a trap, and a live round trip walked into it.

Buying exactly 10 USDT of ETH produced a position that could not be sold:

    bought   0.0040599      ETH  ~ 10.000 USDT
    fee(ETH) -0.00000202995        (charged in the BASE currency)
    held     0.00405787005  ETH  ~  9.995 USDT
    rounded  0.00405        ETH  ~  9.976 USDT   -> "amount filter dendied"

``minAmount`` governs the sell's notional too, so the proceeds of closing must
clear it. Fees and base-precision rounding both shrink a position between open
and close, which means a position opened AT the venue minimum is always below
it by the time it is closed.

In production that is worse than a failed test. ``ClosePosition`` would take
the rejection as definitive, mark the attempt FAILED, and every later close
would fail identically: capital locked in a position this system can never
exit.

So a pool's minimum is not the venue's minimum for one order. It is the
smallest position that survives a ROUND TRIP. Deriving it from the live
measurements:

    taker fee            0.00000202995 / 0.0040599 = 0.05% per leg
    rounding loss        1 tick of basePrecision 5 = 0.00001 ETH ~ 0.0246 USDT
    X * (1 - 0.0005) - 0.0246 >= 10  ->  X >= 10.03

10.03 is the mechanical floor and it leaves nothing for a price move while the
position is open. 11 carries the mechanics plus roughly 10% of headroom, which
is a judgement about adverse moves rather than about arithmetic -- raise it
further if that judgement should be more conservative. No margin makes a
position unconditionally closable: one whose market value falls far enough
drops below the venue minimum regardless, and that is the venue's rule, not a
defect this schema can remove.

Only the placeholder value is touched. A pool already carrying a deliberate
minimum is left exactly as the operator set it.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_PLACEHOLDER = "10"
_ROUND_TRIPPABLE = "11"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE capital_pools SET min_order_size = {_ROUND_TRIPPABLE} "
            "WHERE venue = 'spot' AND settlement_currency = 'USDT' "
            f"AND min_order_size = {_PLACEHOLDER}"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE capital_pools SET min_order_size = {_PLACEHOLDER} "
            "WHERE venue = 'spot' AND settlement_currency = 'USDT' "
            f"AND min_order_size = {_ROUND_TRIPPABLE}"
        )
    )
