"""A subscription's leverage and a strategy's description (multi-user decisions
38 and 39; tasks.md H.1).

Each user chooses the leverage of each of their subscriptions, and the system
sets it on the venue before every opening (decision 38), after a first opening
went out at Binance's 20x default on 2026-11-05. ``subscriptions.leverage`` holds
it: an integer from 1 to 125, the venue's own range on Binance. Every
subscription that exists gets 2, the owner's stated default for all of them. The
column keeps a default of 1, where every new seat starts, so a writer that
forgets it opens at the smallest leverage, never at a larger one.

``strategies.description`` is the text an author writes about how a strategy
trades and the configuration they recommend. It is optional and nothing is
backfilled. The CHECK stands behind the domain, which trims it and stores an
empty one as none: trimmed of spaces, tabs and line breaks, and 1 to 2,000
characters long.

**Downgrade.** Drops both columns and both CHECKs. It loses every leverage a user
chose and every description an author wrote, so once users have chosen, the plan
is fix-forward.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBSCRIPTIONS = "subscriptions"
_LEVERAGE = "leverage"
_LEVERAGE_CHECK = "ck_subscriptions_leverage_range"
_EXISTING_LEVERAGE = 2

_STRATEGIES = "strategies"
_DESCRIPTION = "description"
_DESCRIPTION_CHECK = "ck_strategies_description_shape"


def upgrade() -> None:
    op.add_column(
        _SUBSCRIPTIONS,
        sa.Column(_LEVERAGE, sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.execute(
        sa.text(f"UPDATE {_SUBSCRIPTIONS} SET {_LEVERAGE} = :leverage").bindparams(
            leverage=_EXISTING_LEVERAGE
        )
    )
    op.create_check_constraint(
        _LEVERAGE_CHECK, _SUBSCRIPTIONS, f"{_LEVERAGE} BETWEEN 1 AND 125"
    )

    op.add_column(_STRATEGIES, sa.Column(_DESCRIPTION, sa.Text(), nullable=True))
    op.create_check_constraint(
        _DESCRIPTION_CHECK,
        _STRATEGIES,
        f"{_DESCRIPTION} IS NULL OR ("
        f"{_DESCRIPTION} = btrim({_DESCRIPTION}, E' \\t\\r\\n') "
        f"AND char_length({_DESCRIPTION}) BETWEEN 1 AND 2000)",
    )


def downgrade() -> None:
    op.drop_constraint(_DESCRIPTION_CHECK, _STRATEGIES, type_="check")
    op.drop_column(_STRATEGIES, _DESCRIPTION)
    op.drop_constraint(_LEVERAGE_CHECK, _SUBSCRIPTIONS, type_="check")
    op.drop_column(_SUBSCRIPTIONS, _LEVERAGE)
