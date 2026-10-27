"""``read_key_coverage`` against real PostgreSQL.

The worker's DEGRADED check compares the ``(user, exchange)`` pairs with an
enabled pool with the pairs holding an active key (multi-user design AD9).
Deleting a key from the panel changes both in one commit, so the two sets must
come from one moment: read apart, a delete landing between the reads shows an
enabled pool with no key, and the worker sends a false ERROR to Telegram (seen
2026-10-21, after Bybit's key was deleted).
"""

import logging
import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager import main
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential, KeyFacts
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.credential_revoker import (
    SqlAlchemyCredentialRevoker,
)
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.accounts.infrastructure.key_coverage import KeyCoverage, read_key_coverage
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher
from tests.accounts.fakes import BYBIT_KEY, BYBIT_SECRET, TickingClock
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.owner import OWNER_ID, seed_other_user

pytestmark = pytest.mark.integration


@pytest.fixture
async def factory(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> async_sessionmaker[AsyncSession]:
    """No key stored and every seeded pool off: each test turns on what it needs."""
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.execute(text("UPDATE capital_pools SET enabled = false"))
        await session.commit()
    return pg_session_factory


async def _store_key(
    factory: async_sessionmaker[AsyncSession], exchange: str, user_id: UUID = OWNER_ID
) -> None:
    async with factory() as session:
        await SqlAlchemyCredentialVault(
            session, EnvelopeCipher(os.urandom(MASTER_KEY_BYTES)), TickingClock()
        ).store(
            user_id,
            ExchangeCredential(
                exchange=exchange, label="default", api_key=BYBIT_KEY, api_secret=BYBIT_SECRET
            ),
            KeyFacts.unrecorded(trade_capable=True),
        )
        await session.commit()


async def _enable_pool(
    factory: async_sessionmaker[AsyncSession], exchange: str, user_id: UUID = OWNER_ID
) -> None:
    async with factory() as session:
        await SqlAlchemyCapitalPoolWriter(session).enable(user_id, exchange)
        await session.commit()


async def _delete_as_the_panel_does(
    factory: async_sessionmaker[AsyncSession], exchange: str, user_id: UUID = OWNER_ID
) -> None:
    """The pair ``DeleteCredential`` commits together: the key off, the pool off."""
    async with factory() as session:
        await SqlAlchemyCredentialRevoker(session, TickingClock()).deactivate(user_id, exchange)
        await SqlAlchemyCapitalPoolWriter(session).disable(user_id, exchange)
        await session.commit()


async def _coverage(factory: async_sessionmaker[AsyncSession]) -> KeyCoverage:
    async with factory() as session:
        return await read_key_coverage(session)


async def _other_user(factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    return other


def _owners(*exchanges: str) -> frozenset[tuple[UUID, str]]:
    return frozenset((OWNER_ID, exchange) for exchange in exchanges)


@pytest.fixture
def statements(pg_engine: AsyncEngine) -> Iterator[list[str]]:  # noqa: F811
    seen: list[str] = []

    def record(*args: Any) -> None:
        seen.append(args[2])

    event.listen(pg_engine.sync_engine, "before_cursor_execute", record)
    yield seen
    event.remove(pg_engine.sync_engine, "before_cursor_execute", record)


async def test_reads_the_exchanges_with_an_enabled_pool_and_those_with_an_active_key(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _enable_pool(factory, "bybit")
    await _enable_pool(factory, "binance")
    await _store_key(factory, "bybit")
    await _store_key(factory, "pionex")

    coverage = await _coverage(factory)

    assert coverage == KeyCoverage(
        configured=_owners("bybit", "binance"), active=_owners("bybit", "pionex")
    )


async def test_each_users_pools_and_keys_are_their_own_pairs(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """AD9: the owner holds a Bybit pool and key; another user holds a Bybit
    pool and no key. The other user's pair is configured and not active, and
    the owner's key does not cover it."""
    other = await _other_user(factory)
    await _enable_pool(factory, "bybit")
    await _store_key(factory, "bybit")
    await _enable_pool(factory, "bybit", other)

    coverage = await _coverage(factory)

    assert coverage == KeyCoverage(
        configured=frozenset({(OWNER_ID, "bybit"), (other, "bybit")}),
        active=frozenset({(OWNER_ID, "bybit")}),
    )


async def test_a_superseded_or_deleted_key_is_not_active(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _enable_pool(factory, "bybit")
    await _store_key(factory, "bybit")
    await _store_key(factory, "bybit")
    await _enable_pool(factory, "binance")
    await _store_key(factory, "binance")
    await _delete_as_the_panel_does(factory, "binance")

    coverage = await _coverage(factory)

    assert coverage == KeyCoverage(configured=_owners("bybit"), active=_owners("bybit"))


async def test_no_pool_and_no_key_read_as_two_empty_sets(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await _coverage(factory) == KeyCoverage(configured=frozenset(), active=frozenset())


async def test_a_key_deleted_from_the_panel_sends_no_error(
    factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    await _enable_pool(factory, "bybit")
    await _store_key(factory, "bybit")
    tracker: set[tuple[UUID, str]] = set()
    before = await _coverage(factory)
    main._track_degraded_exchanges(tracker, configured=before.configured, active=before.active)

    await _delete_as_the_panel_does(factory, "bybit")
    after = await _coverage(factory)
    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(tracker, configured=after.configured, active=after.active)

    assert before.configured == _owners("bybit")
    assert after.configured == frozenset()
    assert tracker == set()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_an_enabled_pool_with_no_key_still_reads_as_degraded(
    factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    await _enable_pool(factory, "bybit")
    tracker: set[tuple[UUID, str]] = set()

    coverage = await _coverage(factory)
    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker, configured=coverage.configured, active=coverage.active
        )

    assert tracker == {(OWNER_ID, "bybit")}
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "'bybit' has an enabled pool but no active vault credential" in errors[0]
    assert str(OWNER_ID)[:8] in errors[0]


async def test_both_sets_come_from_one_statement(
    factory: async_sessionmaker[AsyncSession], statements: list[str]
) -> None:
    """One statement is one snapshot under READ COMMITTED: a delete or a save
    committing between two separate reads is what this rules out."""
    await _enable_pool(factory, "bybit")
    await _store_key(factory, "bybit")
    statements.clear()

    coverage = await _coverage(factory)

    reads = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(reads) == 1
    assert coverage == KeyCoverage(configured=_owners("bybit"), active=_owners("bybit"))
