"""The mode belongs to the user, and a reservation records the one it opened in
(multi-user design AD7, decisions 6, 7 and 14; tasks.md E.1).

**The users.** ``users.mode`` is ``LIVE`` or ``SIMULATION``, and a new user starts
in simulation (decision 6). Every existing user gets ``LIVE`` when ``DRY_RUN`` is
false at migration time and ``SIMULATION`` otherwise, so production keeps trading
exactly as before the deploy.

**The reservations.** ``reservations.mode`` is ``NOT NULL`` with no default: a
writer that forgets it fails loudly rather than recording a wrong mode. Until now
the only record of a mode is what a reservation left behind, the ``fake-fill-`` and
``fake-order-`` prefixes the simulated exchange mints, a data contract
(``execution/domain/fill.py``). So each reservation is read from its own fills and
orders, opening or closing:

- any real fill or order: ``LIVE``. Real money moved, so a closed allocation that
  also holds fake fills is ``LIVE`` too;
- a fake one and no real one: ``SIMULATION``;
- nothing at all (no order ever reached a venue): the mode the users get. Such a row
  either holds nothing or is about to run now, under this same mode.

**The refusal.** An OPEN allocation with fills of both kinds cannot be given one
mode, and the mode is what sends its close to a venue. It refuses before anything is
written and names the reservations, as the startup guard does.

**Downgrade.** Refuses when more than one user exists, as 0033's does: a second
user's mode cannot be put back anywhere. It drops both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from strategy_manager.shared.config import get_settings

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE = "LIVE"
_SIMULATION = "SIMULATION"
_USER_CHECK = "ck_users_mode"
_RESERVATION_CHECK = "ck_reservations_mode"
_MODES = f"mode IN ('{_LIVE}', '{_SIMULATION}')"

# Each reservation's evidence: its fills (a fill's ``allocation_id`` is the
# reservation) and the orders of its opening and closing attempts.
_EVIDENCE = """
    SELECT r.id,
           coalesce(f.fake_fills, false) AS fake_fills,
           coalesce(f.real_fills, false) AS real_fills,
           coalesce(f.net, 0) AS net,
           coalesce(o.fake_orders, false) AS fake_orders,
           coalesce(o.real_orders, false) AS real_orders
      FROM reservations AS r
      LEFT JOIN (
        SELECT l.allocation_id,
               bool_or(starts_with(l.exchange_fill_id, 'fake-fill-')) AS fake_fills,
               bool_or(NOT starts_with(l.exchange_fill_id, 'fake-fill-')) AS real_fills,
               sum(CASE WHEN l.side = 'BUY' THEN l.quantity ELSE -l.quantity END) AS net
          FROM ledger_entries AS l
         GROUP BY l.allocation_id
      ) AS f ON f.allocation_id = r.id
      LEFT JOIN (
        SELECT coalesce(a.reservation_id, a.closes_allocation_id) AS reservation_id,
               bool_or(starts_with(a.exchange_order_id, 'fake-order-')) AS fake_orders,
               bool_or(NOT starts_with(a.exchange_order_id, 'fake-order-')) AS real_orders
          FROM execution_attempts AS a
         WHERE a.exchange_order_id IS NOT NULL
         GROUP BY coalesce(a.reservation_id, a.closes_allocation_id)
      ) AS o ON o.reservation_id = r.id
"""


def upgrade() -> None:
    bind = op.get_bind()
    open_mixed = [
        str(row[0])
        for row in bind.execute(
            sa.text(
                f"SELECT e.id FROM ({_EVIDENCE}) AS e "
                "WHERE e.fake_fills AND e.real_fills AND e.net <> 0 ORDER BY e.id"
            )
        )
    ]
    if open_mixed:
        raise RuntimeError(
            "0035 gives each reservation one mode, and these open allocations hold both "
            f"real and rehearsal fills: {', '.join(open_mixed)}. Their close cannot be sent "
            "to one venue. Resolve them, then migrate again."
        )

    # The mode the users get, and the mode of a reservation with no evidence.
    current = _SIMULATION if get_settings().dry_run else _LIVE

    op.add_column(
        "users", sa.Column("mode", sa.Text(), nullable=False, server_default=_SIMULATION)
    )
    op.create_check_constraint(_USER_CHECK, "users", _MODES)
    bind.execute(sa.text("UPDATE users SET mode = :mode"), {"mode": current})

    op.add_column("reservations", sa.Column("mode", sa.Text(), nullable=True))
    bind.execute(
        sa.text(
            f"""
            UPDATE reservations AS r
               SET mode = CASE
                     WHEN e.real_fills OR e.real_orders THEN '{_LIVE}'
                     WHEN e.fake_fills OR e.fake_orders THEN '{_SIMULATION}'
                     ELSE :current
                   END
              FROM ({_EVIDENCE}) AS e
             WHERE e.id = r.id
            """
        ),
        {"current": current},
    )
    op.alter_column("reservations", "mode", nullable=False)
    op.create_check_constraint(_RESERVATION_CHECK, "reservations", _MODES)


def downgrade() -> None:
    users = int(op.get_bind().execute(sa.text("SELECT count(*) FROM users")).scalar_one())
    if users > 1:
        raise RuntimeError(
            "0035's downgrade drops every user's mode, which only holds for one user at "
            f"most; found {users}. Fix forward instead."
        )

    op.drop_constraint(_RESERVATION_CHECK, "reservations", type_="check")
    op.drop_column("reservations", "mode")
    op.drop_constraint(_USER_CHECK, "users", type_="check")
    op.drop_column("users", "mode")
