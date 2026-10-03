"""``strategy_enablement_events``: deleted with their strategy (design.md
addendum 9x, § G; owner decision 42, Q1; tasks.md unit 9xf).

A strategy that was switched on and off but never received a signal, a
reservation, an execution attempt, a ledger entry or a booking proposal has
nothing worth keeping, and its enablement events must not make it undeletable
(owner decision 42, Q1: "they do not count"). Until now they did, twice over:
``fk_strategy_enablement_events_strategy`` was ``NO ACTION`` and the append-only
trigger refused to delete the events first.

**The mechanism: ``ON DELETE CASCADE``, not an explicit delete.** An explicit
delete in the application needs a way around the append-only trigger, and any such
switch can be flipped by a future bug. With a cascade the rule stays structural:
an event goes only because its own strategy went.

**What changes.**

1. ``fn_strategy_enablement_events_append_only()`` is replaced. ``UPDATE`` still
   always raises ``restrict_violation`` (SQLSTATE ``23001``). ``DELETE`` raises
   too, UNLESS the parent strategy row no longer exists
   (``NOT EXISTS (SELECT 1 FROM strategies WHERE id = OLD.strategy_id)``). The
   trigger itself, ``trg_strategy_enablement_events_no_update_delete``, is neither
   dropped nor re-created.
2. ``fk_strategy_enablement_events_strategy`` is dropped and re-created with
   ``ON DELETE CASCADE``.

**Why that condition.** PostgreSQL runs a cascade as a later command of the same
transaction, after the parent row is already deleted, so the trigger's ``SELECT``
no longer sees it. An event can then be deleted only as part of its strategy's
own deletion: a direct ``DELETE`` of an event whose strategy exists is still
refused, and an event cannot exist without its strategy. The strategy's own
deletion is still refused by the other four ``NO ACTION`` foreign keys, and
PostgreSQL undoes the cascade with it. The ledger's triggers are not touched.
Proven by ``tests/migrations/test_0028_enablement_events_cascade.py``, whose first
test is exactly this assumption.

**TRUNCATE.** The events table has no ``TRUNCATE`` guard (migration 0024, on
purpose) and none is added: the integration conftests ``TRUNCATE strategies ...
CASCADE``.

**Downgrade.** Restores the 0024 function body and the foreign key without the
cascade. It discards no data, so it has no refusal clause. It logs one WARNING:
a strategy deleted while 0028 was applied is gone, and its events with it.
Nothing restores either.

**What is lost by the feature, not by this migration:** the enable and disable
times of a strategy that never received a signal. Nothing about money. The delete's
INFO line records the number of events, the first enable time and the uptime.
"""

import logging
from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)

_EVENTS_TABLE = "strategy_enablement_events"
_EVENTS_FK = "fk_strategy_enablement_events_strategy"
_APPEND_ONLY_FUNCTION = "fn_strategy_enablement_events_append_only"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND NOT EXISTS (SELECT 1 FROM strategies WHERE id = OLD.strategy_id) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION '{_EVENTS_TABLE} is append-only: % is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    op.drop_constraint(_EVENTS_FK, _EVENTS_TABLE, type_="foreignkey")
    op.create_foreign_key(
        _EVENTS_FK,
        _EVENTS_TABLE,
        "strategies",
        ["strategy_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    logger.warning(
        "downgrading 0028_enablement_events_cascade: %s is NO ACTION again and its "
        "append-only trigger refuses every delete. Strategies deleted while 0028 was "
        "applied, and the enablement events deleted with them, are not restored. No "
        "row is discarded by this downgrade.",
        _EVENTS_FK,
    )
    op.drop_constraint(_EVENTS_FK, _EVENTS_TABLE, type_="foreignkey")
    op.create_foreign_key(_EVENTS_FK, _EVENTS_TABLE, "strategies", ["strategy_id"], ["id"])
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '{_EVENTS_TABLE} is append-only: % is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
