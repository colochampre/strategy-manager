"""The head database helper builds the schema production has.

``tests/pg_head_schema.py`` migrates a throwaway database with ``alembic upgrade
head``. The three foreign keys below exist ONLY in the migrations; the ORM-built
test schema (``Base.metadata.create_all``) lacks them, which is the whole reason
the helper exists.
"""

from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.pg_head_schema import migrated_head_database

pytestmark = pytest.mark.integration

_FOREIGN_KEYS_THE_ORM_SCHEMA_LACKS = {
    "fk_signals_strategy",
    "fk_booking_proposals_strategy",
    "fk_strategy_enablement_events_strategy",
}


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_head_schema") as url:
        yield url


@pytest.fixture
async def conn(head_database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(head_database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def test_the_head_database_has_the_three_foreign_keys_the_orm_schema_lacks(
    conn: AsyncConnection,
) -> None:
    rows = await conn.execute(
        text("SELECT conname FROM pg_constraint WHERE contype = 'f' AND conname = ANY(:names)"),
        {"names": sorted(_FOREIGN_KEYS_THE_ORM_SCHEMA_LACKS)},
    )

    assert {row.conname for row in rows} == _FOREIGN_KEYS_THE_ORM_SCHEMA_LACKS
