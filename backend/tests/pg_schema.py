"""Keeping the integration test database honest about the ORM.

``Base.metadata.create_all`` creates tables that are missing and never alters
ones that already exist. Every integration fixture reuses one long-lived
``strategy_manager_test`` database, so the moment a migration adds a column or
drops a constraint, the test schema silently drifts behind the models.

What that produces is a failure in whichever test happens to touch the changed
shape first, usually one with no connection to the change that caused it. It
has now happened twice: an ``UndefinedColumnError`` when
``execution_attempts`` gained a column, and an ``IntegrityError`` when
``exchange_credentials`` lost a constraint that made key rotation impossible —
the second one while proving the rotation fix worked.

The first time it was fixed in one conftest. Six of them build this schema, so
fixing one fixed one sixth of the problem. This module is the whole of it: one
flag for one database, called by every fixture that opens it.

It is not a substitute for the migrations. Those are exercised against a real
``alembic upgrade head`` database by the tier B fixtures, which is also why the
raw-SQL triggers live there and not here.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

from strategy_manager.shared.db import Base

_rebuilt = False


async def rebuild_schema_once(conn: AsyncConnection) -> None:
    """Drop the schema on the first integration fixture of the session.

    The caller runs ``create_all`` immediately afterwards, so the net effect is
    a test database that is a pure function of the ORM models. It costs a
    fraction of a second, once.
    """
    global _rebuilt
    if _rebuilt:
        return
    await conn.run_sync(Base.metadata.drop_all)
    _rebuilt = True
