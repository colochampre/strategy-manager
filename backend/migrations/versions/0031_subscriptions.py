"""A subscription is the only way to trade a strategy (multi-user design AD3;
tasks.md C.1).

**What a row says.** ``subscriptions`` ties a user to a strategy through the
user's own pool, at the user's own share. The author is a subscriber like any
other: the strategy no longer carries a share of its own.

**What the database refuses.** ``(pool_id, user_id)`` references ``capital_pools
(id, user_id)``, so one user's subscription never sits in another user's pool. A
trigger refuses a pool whose ``(exchange, venue, settlement_currency)`` differs
from its strategy's, on insert and on an update of ``pool_id`` or
``strategy_id``. A partial unique allows one live (ACTIVE or LEAVING)
subscription per user and strategy; an ENDED one frees the pair.

**Deleting a strategy** takes its subscriptions with it (``fk_subscriptions_strategy``
cascades, like the enablement events in 0028): a subscription is a choice to
follow, not a record of anything that happened. ``DeleteStrategy`` counts them
and never lets them refuse the delete.

**Backfill.** One subscription per strategy, for its author, in the author's pool
for the strategy's market, at the strategy's share. ACTIVE while the strategy is
not archived; ENDED, with ``ended_at = archived_at``, once it is. An author with
no pool for the market (a strategy may name one without a pool row since 0030)
stops the migration, which names the strategy rather than guess a pool. The
ledger is never touched.

**Expand now, contract later.** ``strategies.allocation_percent`` becomes
nullable and its CHECK stays, so the API's old code keeps writing it through the
migration. Nothing reads it from here on; a later migration drops it.

**Downgrade.** Refuses once more than one user exists, since the old schema has
one share per strategy for one user. Each strategy takes back the share of its
latest subscription (by ``created_at``). A strategy with no subscription and no
share has nothing to restore, so the downgrade names it and stops.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "subscriptions"
_POOL_FK = "fk_subscriptions_pool"
_LIVE_UNIQUE = "ux_subscriptions_one_live_per_strategy"
_MARKET_MATCH = "ck_subscriptions_pool_market"
_SHARE_RANGE = "ck_subscriptions_allocation_percent_range"
_STATUS = "ck_subscriptions_status"
_FUNCTION = "subscriptions_pool_market_guard"
_TRIGGER = "trg_subscriptions_pool_market"
_MAX_NAMED = 10


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar_one())


def _names(strategies: list[str]) -> str:
    shown = ", ".join(f"'{name}'" for name in strategies[:_MAX_NAMED])
    more = len(strategies) - _MAX_NAMED
    return shown if more <= 0 else f"{shown} and {more} more"


def _refuse_a_strategy_without_exactly_one_pool() -> None:
    """The backfill picks the author's pool for the strategy's market; it never
    chooses between pools and never invents one."""
    rows = op.get_bind().execute(
        sa.text(
            "SELECT s.name, count(p.id) FROM strategies AS s LEFT JOIN capital_pools AS p "
            "ON p.user_id = s.author_id AND p.exchange = s.exchange AND p.venue = s.venue "
            "AND p.settlement_currency = s.settlement_currency "
            "GROUP BY s.id, s.name HAVING count(p.id) <> 1 ORDER BY s.name"
        )
    ).all()
    if rows:
        raise RuntimeError(
            "0031 gives every strategy its author's subscription and needs exactly one "
            f"pool of the author for the strategy's market; {len(rows)} strategies "
            f"have none or several: {_names([str(row[0]) for row in rows])}; "
            f"for {rows[0][0]!r} it found {rows[0][1]}. Create the author's pool for "
            "that market, then migrate again."
        )


def upgrade() -> None:
    _refuse_a_strategy_without_exactly_one_pool()

    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pool_id", sa.Integer(), nullable=False),
        sa.Column("allocation_percent", sa.Numeric(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_subscriptions_user"),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name="fk_subscriptions_strategy",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pool_id", "user_id"], ["capital_pools.id", "capital_pools.user_id"], name=_POOL_FK
        ),
        sa.CheckConstraint(
            "allocation_percent > 0 AND allocation_percent <= 100", name=_SHARE_RANGE
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'LEAVING', 'ENDED')", name=_STATUS),
    )
    op.create_index(f"ix_{_TABLE}_user_id", _TABLE, ["user_id"])
    op.create_index(f"ix_{_TABLE}_strategy_id", _TABLE, ["strategy_id"])
    op.create_index(
        _LIVE_UNIQUE,
        _TABLE,
        ["user_id", "strategy_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'ENDED'"),
    )

    op.execute(
        f"""
        CREATE FUNCTION {_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            strategy_market text;
            pool_market text;
        BEGIN
            SELECT s.name || ' (' || s.exchange || '/' || s.venue || '/'
                   || s.settlement_currency || ')'
              INTO strategy_market FROM strategies AS s WHERE s.id = NEW.strategy_id;
            SELECT p.exchange || '/' || p.venue || '/' || p.settlement_currency
              INTO pool_market FROM capital_pools AS p WHERE p.id = NEW.pool_id;
            IF NOT EXISTS (
                SELECT 1 FROM strategies AS s JOIN capital_pools AS p ON p.id = NEW.pool_id
                 WHERE s.id = NEW.strategy_id
                   AND (s.exchange, s.venue, s.settlement_currency)
                       = (p.exchange, p.venue, p.settlement_currency)
            ) THEN
                RAISE EXCEPTION 'subscription pool % trades % but strategy % does not',
                    NEW.pool_id, pool_market, strategy_market
                    USING ERRCODE = 'check_violation', CONSTRAINT = '{_MARKET_MATCH}';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER {_TRIGGER} BEFORE INSERT OR UPDATE OF pool_id, strategy_id "
        f"ON {_TABLE} FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}()"
    )

    # The trigger checks each backfilled row against its pool's market as well.
    op.execute(
        f"""
        INSERT INTO {_TABLE} (id, user_id, strategy_id, pool_id, allocation_percent, status,
                              created_at, ended_at)
        SELECT gen_random_uuid(), s.author_id, s.id, p.id, s.allocation_percent,
               CASE WHEN s.archived_at IS NULL THEN 'ACTIVE' ELSE 'ENDED' END,
               s.created_at, s.archived_at
          FROM strategies AS s
          JOIN capital_pools AS p
            ON p.user_id = s.author_id AND p.exchange = s.exchange AND p.venue = s.venue
           AND p.settlement_currency = s.settlement_currency
        """
    )

    op.alter_column("strategies", "allocation_percent", existing_type=sa.Numeric(), nullable=True)


def downgrade() -> None:
    users = _count("SELECT count(*) FROM users")
    if users > 1:
        raise RuntimeError(
            "0031's downgrade cannot hold more than one user's subscriptions in "
            f"strategies.allocation_percent; found {users}. Fix forward instead."
        )

    shareless = [
        str(row[0])
        for row in op.get_bind().execute(
            sa.text(
                "SELECT s.name FROM strategies AS s WHERE s.allocation_percent IS NULL "
                f"AND NOT EXISTS (SELECT 1 FROM {_TABLE} AS sub WHERE sub.strategy_id = s.id) "
                "ORDER BY s.name"
            )
        )
    ]
    if shareless:
        raise RuntimeError(
            f"0031's downgrade found {len(shareless)} strategies with no share and no "
            f"subscription to take one from: {_names(shareless)}. Give each a "
            "subscription or a share, then downgrade again."
        )

    op.execute(
        f"""
        UPDATE strategies AS s SET allocation_percent = latest.allocation_percent
          FROM (SELECT DISTINCT ON (strategy_id) strategy_id, allocation_percent
                  FROM {_TABLE} ORDER BY strategy_id, created_at DESC) AS latest
         WHERE latest.strategy_id = s.id
        """
    )
    op.alter_column("strategies", "allocation_percent", existing_type=sa.Numeric(), nullable=False)

    op.execute(f"DROP TRIGGER {_TRIGGER} ON {_TABLE}")
    op.execute(f"DROP FUNCTION {_FUNCTION}()")
    op.drop_table(_TABLE)
