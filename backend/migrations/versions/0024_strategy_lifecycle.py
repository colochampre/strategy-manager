"""``strategies.allowed_pairs``, ``strategies.archived_at`` and
``strategy_enablement_events`` (design.md § 6 "Allowed pairs: an array
column, migration 0024", § 9 "Enablement event log and uptime"; spec:
strategy-lifecycle; owner decisions 13, 14, 15).

**Allowed pairs.** ``strategies.allowed_pairs TEXT[] NOT NULL DEFAULT '{}'``,
stored ``market_key()``-normalized and sorted. A child table
(``strategy_allowed_pairs(strategy_id, pair)``) was rejected: the list is
read on the hot path in the SAME row snapshot as ``enabled`` and
``archived_at`` (one ``session.get``), the panel replaces it as a unit
(PUT), and nothing per-pair was ever asked for (design.md § 6).

**Seeding (owner decision 13).** Every existing strategy's list is seeded
ONCE, here, from the distinct ``market_key``-normalized symbols of the
signals it has already received. This is a DATA migration, not just a
schema one, and it runs with a **frozen copy** of the normalization logic
(``_frozen_market_key`` below) rather than importing
``strategy_manager.execution.domain.market_symbol.market_key`` --
migrations must not depend on application code that can change out from
under a migration already applied in production. That copy is checked for
drift by ``tests/migrations/test_0024_strategy_lifecycle.py``'s parity
test, which runs both implementations against the same table of spellings
and fails the instant they diverge -- a silent drift would seed pairs that
never match a real signal's normalized symbol, and PR 5's allowlist gate
would then refuse every signal of a seeded strategy with no hint why.

Every strategy's seeded set is logged at WARNING (so it surfaces in
``alembic upgrade`` output directly -- ``alembic.ini``'s root logger is
configured at WARNING with a console handler, and a plain
``logging.getLogger(__name__)`` here propagates to it). A signal symbol
that normalizes to an empty string (nothing in migration 0002's schema
forbids ``signals.symbol = ''``) is unparseable: it is skipped with its own
WARNING naming the strategy and the raw symbol, rather than seeding a pair
``AllowedPairs`` would reject anyway.

**Archive.** ``archived_at timestamptz NULL``, CHECK
``archived_at IS NULL OR enabled = false`` (owner decision 14: a strategy
can be archived only when disabled). Seeding this column is not needed --
every strategy starts unarchived.

**Enablement log.** ``strategy_enablement_events`` is append-only via a
``BEFORE UPDATE OR DELETE`` row trigger, following ``fn_ledger_append_only``
's exact pattern (migration 0005). Deliberately NO ``BEFORE TRUNCATE``
guard, unlike the ledger: eight integration conftests
``TRUNCATE strategies ... CASCADE`` (e.g.
``tests/strategies/infrastructure/conftest.py``), and a TRUNCATE guard here
would break every one of them. The threat an audit trail defends against is
an application bug updating or deleting a row, not an operator truncating
-- the ledger keeps the stronger guard because it is money, not this table.

One ``BASELINE`` event is written, at migration time, for every strategy
that is ``enabled`` right now -- prior uptime for a strategy disabled by
then is lost. A later unit's ``uptime()`` function (``EnablementEvent``,
``EnablementOrigin``, ``strategies/domain/enablement.py`` -- tasks.md 2d,
written test-first there) will report that honestly via a ``baseline`` flag
rather than inventing a first-activation date; this migration only writes
the rows that function will read.

``downgrade()`` refuses while any OBSERVED event exists, naming the count
(the 0012/0021 precedent: never silently discard real audit history).
BASELINE rows carry no information this migration did not create itself,
so a downgrade with only BASELINE rows is allowed -- unlike 0021, this
downgrade offers no force flag, because there is nothing to force: an
OBSERVED row records a REAL enable/disable transition that happened after
this migration ran, and nothing here can regenerate it.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-25

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

logger = logging.getLogger(__name__)

_STRATEGIES = "strategies"
_ALLOWED_PAIRS_COLUMN = "allowed_pairs"
_ALLOWED_PAIRS_CHECK = "ck_strategies_allowed_pairs_no_null"
_ARCHIVED_AT_COLUMN = "archived_at"
_ARCHIVED_CHECK = "ck_strategies_archived_requires_disabled"

_EVENTS_TABLE = "strategy_enablement_events"
_EVENTS_INDEX = "ix_strategy_enablement_events_strategy_occurred_at"
_ORIGIN_CHECK = "ck_strategy_enablement_events_origin"
_EVENTS_FK = "fk_strategy_enablement_events_strategy"
_APPEND_ONLY_FUNCTION = "fn_strategy_enablement_events_append_only"
_APPEND_ONLY_TRIGGER = "trg_strategy_enablement_events_no_update_delete"

# Longest marker first, so a symbol carrying one is never left with a
# fragment of the other -- the exact ordering rule
# ``execution.domain.market_symbol.CONTRACT_MARKERS`` documents for itself.
_CONTRACT_MARKERS = ("_PERP", ".P")


def _frozen_market_key(symbol: str) -> str | None:
    """A frozen copy of ``execution.domain.market_symbol.market_key()``,
    inlined because this migration must not import application code that
    can change later (module docstring). Checked for parity against the
    real implementation by
    ``tests/migrations/test_0024_strategy_lifecycle.py::test_frozen_normalizer_matches_market_key_across_spellings``.

    Returns ``None`` when the symbol normalizes to an empty string --
    which ``AllowedPairs`` would reject as an entry anyway -- so the caller
    can skip it and log a WARNING, rather than seed a pair nothing will
    ever match.
    """
    upper = symbol.upper()
    for marker in _CONTRACT_MARKERS:
        if upper.endswith(marker):
            upper = upper[: -len(marker)]
            break
    return upper or None


def upgrade() -> None:
    op.add_column(
        _STRATEGIES,
        sa.Column(
            _ALLOWED_PAIRS_COLUMN,
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.create_check_constraint(
        _ALLOWED_PAIRS_CHECK,
        _STRATEGIES,
        f"array_position({_ALLOWED_PAIRS_COLUMN}, NULL) IS NULL",
    )

    op.add_column(
        _STRATEGIES,
        sa.Column(_ARCHIVED_AT_COLUMN, sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        _ARCHIVED_CHECK,
        _STRATEGIES,
        f"{_ARCHIVED_AT_COLUMN} IS NULL OR enabled = false",
    )

    op.create_table(
        _EVENTS_TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.CheckConstraint("origin IN ('OBSERVED', 'BASELINE')", name=_ORIGIN_CHECK),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], name=_EVENTS_FK),
    )
    op.create_index(_EVENTS_INDEX, _EVENTS_TABLE, ["strategy_id", "occurred_at"])

    # Append-only enforcement -- a row trigger only, deliberately (module
    # docstring). Mirrors fn_ledger_append_only's own pattern (migration 0005).
    op.execute(
        f"""
        CREATE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '{_EVENTS_TABLE} is append-only: % is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_APPEND_ONLY_TRIGGER}
            BEFORE UPDATE OR DELETE ON {_EVENTS_TABLE}
            FOR EACH ROW EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """
    )

    bind = op.get_bind()
    _seed_allowed_pairs(bind)
    _write_baseline_events(bind)


def _seed_allowed_pairs(bind: Connection) -> None:
    """Owner decision 13: seeds every existing strategy's allowed-pairs list
    ONCE, from the distinct market keys of the signals it has already
    received. Runs exactly once, at migration time -- not on every deploy."""
    strategies = bind.execute(sa.text(f"SELECT id, name FROM {_STRATEGIES}")).all()  # noqa: S608

    for strategy_id, name in strategies:
        raw_symbols = (
            bind.execute(
                sa.text("SELECT DISTINCT symbol FROM signals WHERE strategy_id = :id"),
                {"id": strategy_id},
            )
            .scalars()
            .all()
        )

        seeded: set[str] = set()
        for symbol in raw_symbols:
            key = _frozen_market_key(symbol)
            if key is None:
                logger.warning(
                    "strategy %s (%s): signal symbol %r could not be normalized to a "
                    "market key and was skipped during allowed-pairs seeding",
                    strategy_id,
                    name,
                    symbol,
                )
                continue
            seeded.add(key)

        sorted_pairs = sorted(seeded)
        bind.execute(
            sa.text(
                f"UPDATE {_STRATEGIES} SET {_ALLOWED_PAIRS_COLUMN} = :pairs WHERE id = :id"
            ).bindparams(sa.bindparam("pairs", type_=postgresql.ARRAY(sa.Text()))),
            {"pairs": sorted_pairs, "id": strategy_id},
        )
        logger.warning("seeded allowed pairs for %s (%s): %s", strategy_id, name, sorted_pairs)


def _write_baseline_events(bind: Connection) -> None:
    """One BASELINE event per strategy already enabled when this migration
    runs -- prior uptime for a strategy disabled by then is lost. A later
    unit's ``uptime()`` function reports that honestly via a ``baseline``
    flag on the row this writes, instead of inventing a first-activation
    date (design.md § 9)."""
    enabled_ids = (
        bind.execute(sa.text(f"SELECT id FROM {_STRATEGIES} WHERE enabled = true"))  # noqa: S608
        .scalars()
        .all()
    )
    for strategy_id in enabled_ids:
        bind.execute(
            sa.text(
                f"INSERT INTO {_EVENTS_TABLE} (strategy_id, enabled, origin) "
                "VALUES (:id, true, 'BASELINE')"
            ),
            {"id": strategy_id},
        )


def _log_discarded_state(bind: Connection) -> None:
    """Called only once the downgrade is actually going to proceed (the
    OBSERVED-event refusal check has already passed). After deploy the
    owner prunes the seeded ``allowed_pairs`` (``PUT .../allowed-pairs``,
    a later unit) and may archive strategies. A plain ``DROP COLUMN``
    discards both with no trace, and a later re-upgrade RE-SEEDS
    ``allowed_pairs`` from signal history -- silently restoring exactly
    what the owner pruned. This does not refuse the downgrade -- rollback
    must stay possible -- it only makes the loss visible before it
    happens: one WARNING per strategy that currently holds a non-empty
    ``allowed_pairs`` or a non-null ``archived_at``, plus one summary line
    if anything was actually at risk."""
    rows = bind.execute(
        sa.text(
            f"SELECT id, name, {_ALLOWED_PAIRS_COLUMN}, {_ARCHIVED_AT_COLUMN} "
            f"FROM {_STRATEGIES}"
        )  # noqa: S608
    ).all()

    discarded_anything = False
    for strategy_id, name, allowed_pairs, archived_at in rows:
        if not allowed_pairs and archived_at is None:
            continue
        discarded_anything = True
        logger.warning(
            "downgrading 0024_strategy_lifecycle discards strategy %s (%s): "
            "allowed_pairs=%s archived_at=%s",
            strategy_id,
            name,
            sorted(allowed_pairs),
            archived_at,
        )

    if discarded_anything:
        logger.warning(
            "downgrading 0024_strategy_lifecycle: a later re-upgrade RE-SEEDS "
            "allowed_pairs from signal history and does NOT restore the "
            "allowed_pairs/archived_at values discarded above"
        )


def downgrade() -> None:
    bind = op.get_bind()
    observed_count = bind.execute(
        sa.text(f"SELECT count(*) FROM {_EVENTS_TABLE} WHERE origin = 'OBSERVED'")  # noqa: S608
    ).scalar_one()
    if observed_count > 0:
        raise RuntimeError(
            f"Refusing to downgrade 0024_strategy_lifecycle: {observed_count} OBSERVED "
            f"{_EVENTS_TABLE} row(s) exist. These record real enable/disable history "
            "this migration did not create and cannot reconstruct (0012/0021 "
            "precedent). BASELINE rows carry no information beyond what this "
            "migration itself wrote, so a downgrade with only BASELINE rows is "
            "allowed -- but this downgrade offers no force flag: unlike 0021's "
            "FAILED rows, there is nothing safe to discard here."
        )

    # The downgrade is actually proceeding past this point -- log what it is
    # about to discard before dropping a single column (owner correction,
    # 2026-09-25; see _log_discarded_state's own docstring).
    _log_discarded_state(bind)

    op.execute(f"DROP TRIGGER IF EXISTS {_APPEND_ONLY_TRIGGER} ON {_EVENTS_TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {_APPEND_ONLY_FUNCTION}()")
    op.drop_index(_EVENTS_INDEX, table_name=_EVENTS_TABLE)
    op.drop_table(_EVENTS_TABLE)

    op.drop_constraint(_ARCHIVED_CHECK, _STRATEGIES, type_="check")
    op.drop_column(_STRATEGIES, _ARCHIVED_AT_COLUMN)

    op.drop_constraint(_ALLOWED_PAIRS_CHECK, _STRATEGIES, type_="check")
    op.drop_column(_STRATEGIES, _ALLOWED_PAIRS_COLUMN)
