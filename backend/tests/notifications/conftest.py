"""Real-PostgreSQL fixtures for the notifications feed (panel-redesign RD.5a).

The feed reads the ledger, the safety events, the signal deliveries and the
reconciliation's discrepancies, so the database is the performance tests' own
(``create_all`` over every model, the seeded owner and pools) plus two things it
does not carry: the partial unique index ``upsert_open`` infers its conflict
target from, and an empty ``reconciliation_discrepancies`` for every test. The index is
dropped again afterwards: the database outlives the package.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.reconciliation.infrastructure.models import (  # noqa: F401
    ReconciliationDiscrepancyRow,
)
from strategy_manager.safety.infrastructure.models import SafetyEventRow  # noqa: F401
from tests.owner import OWNER_ID
from tests.performance.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)


@pytest.fixture(autouse=True)
async def _feed_database(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> AsyncIterator[None]:
    """Empties the discrepancies, makes ``upsert_open``'s conflict target exist and
    puts the owner in ``LIVE`` for the test (the reconciliation read counts a scan
    that skips every user as ``DRY_RUN``), restoring the mode afterwards."""
    async with pg_session_factory() as session:
        await session.execute(text("DROP INDEX IF EXISTS ux_reconciliation_open_per_symbol"))
        await session.execute(
            text(
                "CREATE UNIQUE INDEX ux_reconciliation_open_per_symbol "
                "ON reconciliation_discrepancies "
                "(user_id, exchange, venue, settlement_currency, symbol) "
                "WHERE resolved_at IS NULL"
            )
        )
        await session.execute(text("TRUNCATE reconciliation_discrepancies CASCADE"))
        previous = (
            await session.execute(
                text("SELECT mode FROM users WHERE id = :id"), {"id": OWNER_ID}
            )
        ).scalar_one()
        await session.execute(
            text("UPDATE users SET mode = 'LIVE' WHERE id = :id"), {"id": OWNER_ID}
        )
        await session.commit()
    yield
    async with pg_session_factory() as session:
        # The index is this package's own: other packages built on this database do
        # not carry it, and one of them inserts two open rows on one symbol.
        await session.execute(text("DROP INDEX IF EXISTS ux_reconciliation_open_per_symbol"))
        await session.execute(text("TRUNCATE reconciliation_discrepancies CASCADE"))
        await session.execute(
            text("UPDATE users SET mode = :mode WHERE id = :id"),
            {"mode": previous, "id": OWNER_ID},
        )
        await session.commit()
