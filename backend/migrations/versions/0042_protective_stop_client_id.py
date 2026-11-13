"""The id a Binance stop is placed under (subscriber-safety SS.6).

``protective_stops.client_stop_id`` is the ``clientAlgoId`` the stop is sent with. Binance
has no stop on the opening order, so the stop is a request of its own, sent after the fill;
its id is written with the row BEFORE any request, so a POST whose outcome is unknown can
be read back by it (``GET /fapi/v1/algoOrder?clientAlgoId=``) before anything else is
decided.

* Nullable: a Bybit stop (which rides the opening order), a simulated one and every row
  written before this migration have none.
* Unique where set (``uq_protective_stops_client_stop_id``): PostgreSQL's UNIQUE already
  allows any number of NULLs, so a plain constraint is exactly "unique where set".

**Downgrade.** Drops the constraint and the column. A stop that rests at Binance keeps
resting and is no longer tracked by its id here, so once stops are placed the plan is
fix-forward.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "protective_stops"
_UNIQUE = "uq_protective_stops_client_stop_id"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("client_stop_id", sa.Text(), nullable=True))
    op.create_unique_constraint(_UNIQUE, _TABLE, ["client_stop_id"])


def downgrade() -> None:
    op.drop_constraint(_UNIQUE, _TABLE, type_="unique")
    op.drop_column(_TABLE, "client_stop_id")
