"""PR 3 unit 1b.9: the F11 fix, proved behaviorally against real PostgreSQL
through ``main.py``'s ACTUAL ``balance.sync`` wiring -- not a reimplementation
of it.

Exercises ``strategy_manager.main.build_worker_runner``'s registered
``JobKind.BALANCE_SYNC`` handler directly (there is no public accessor for a
single handler, so this reaches ``runner._handlers[...]``, the same private
state ``WorkerRunner.run_forever`` itself reads). Real Postgres backs
``capital_pools`` (the pool-enable/disable flip under test),
``exchange_credentials`` (a real sealed vault credential for each exchange,
so key availability is never the variable under test) and
``pool_balance_snapshots`` (the write proving a read actually happened).
The two venue HTTP clients are the only thing faked -- a call-counting stand-in
for ``BybitReadOnlyClient``/``BinanceReadOnlyClient``, monkeypatched over
``main.read_only_client``/``main.binance_read_only_client`` exactly where
``handle_balance_sync`` reaches for them.
"""

import base64
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager import main
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    PoolLockKeyCollisionError,
)
from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher

pytestmark = pytest.mark.integration

_BYBIT_POOL = PoolConfig(
    exchange=Exchange.BYBIT,
    venue=Venue.USDT_M,
    settlement_currency=Currency.USDT,
    min_order_size=Decimal("10"),
)


class _FakeVenueClient:
    """Stands in for ``BybitReadOnlyClient``/``BinanceReadOnlyClient``: the
    ONLY thing this suite fakes, so a real read/write round trip is proved
    everywhere else (real Postgres, real vault decrypt, real reader/writer
    classes)."""

    def __init__(self) -> None:
        self.calls = 0

    async def unified_balances(self) -> list[object]:
        self.calls += 1
        return []

    async def futures_assets(self) -> list[object]:
        self.calls += 1
        return []


def _claimed_job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(), kind=JobKind.BALANCE_SYNC, payload={}, attempts=1, max_attempts=5
    )


async def _seed_pool(
    session_factory: async_sessionmaker[AsyncSession], *, exchange: str, enabled: bool
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO capital_pools "
                "(exchange, venue, settlement_currency, min_order_size, enabled) "
                "VALUES (:exchange, 'usdt-m', 'USDT', 10, :enabled)"
            ),
            {"exchange": exchange, "enabled": enabled},
        )
        await session.commit()


async def _set_pool_enabled(
    session_factory: async_sessionmaker[AsyncSession], *, exchange: str, enabled: bool
) -> None:
    async with session_factory() as session:
        await session.execute(
            text("UPDATE capital_pools SET enabled = :enabled WHERE exchange = :exchange"),
            {"exchange": exchange, "enabled": enabled},
        )
        await session.commit()


async def _snapshot_count(
    session_factory: async_sessionmaker[AsyncSession], *, exchange: str
) -> int:
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM pool_balance_snapshots WHERE exchange = :exchange"),
            {"exchange": exchange},
        )
        return result.scalar_one()


@pytest.fixture
async def _seeded_vault(
    pg_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    """A real sealed credential for BOTH exchanges, so key availability is
    never the variable under test -- only the pool's ``enabled`` flag is."""
    master_key = os.urandom(MASTER_KEY_BYTES)
    settings = get_settings()
    monkeypatch.setattr(settings, "master_encryption_key", base64.b64encode(master_key).decode())

    async with pg_session_factory() as session:
        vault = SqlAlchemyCredentialVault(session, EnvelopeCipher(master_key), SystemClock())
        await vault.store(
            ExchangeCredential(
                exchange="bybit", label="default", api_key="BYBIT-KEY-abcd", api_secret="s"
            )
        )
        await vault.store(
            ExchangeCredential(
                exchange="binance", label="default", api_key="BINANCE-KEY-wxyz", api_secret="s"
            )
        )
        await session.commit()
    yield


@pytest.fixture
def _fake_clients(monkeypatch: pytest.MonkeyPatch) -> tuple[_FakeVenueClient, _FakeVenueClient]:
    bybit_client = _FakeVenueClient()
    binance_client = _FakeVenueClient()

    @asynccontextmanager
    async def _bybit_ctx(
        settings: object, credentials: object, clock: object = None
    ) -> AsyncIterator[_FakeVenueClient]:
        yield bybit_client

    @asynccontextmanager
    async def _binance_ctx(
        settings: object, credentials: object, clock: object = None
    ) -> AsyncIterator[_FakeVenueClient]:
        yield binance_client

    monkeypatch.setattr(main, "read_only_client", _bybit_ctx)
    monkeypatch.setattr(main, "binance_read_only_client", _binance_ctx)
    return bybit_client, binance_client


async def test_pool_enabled_while_running_is_read_on_the_next_cycle(
    pg_engine: AsyncEngine,
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    _seeded_vault: None,
    _fake_clients: tuple[_FakeVenueClient, _FakeVenueClient],
) -> None:
    bybit_client, binance_client = _fake_clients
    monkeypatch.setattr(main, "engine", pg_engine)

    await _seed_pool(pg_session_factory, exchange="bybit", enabled=True)
    await _seed_pool(pg_session_factory, exchange="binance", enabled=False)

    runner = main.build_worker_runner(
        [_BYBIT_POOL], session_factory_override=pg_session_factory
    )
    handler = runner._handlers[JobKind.BALANCE_SYNC]  # noqa: SLF001

    await handler(_claimed_job())
    assert bybit_client.calls == 1
    assert binance_client.calls == 0
    assert await _snapshot_count(pg_session_factory, exchange="bybit") == 1
    assert await _snapshot_count(pg_session_factory, exchange="binance") == 0

    await _set_pool_enabled(pg_session_factory, exchange="binance", enabled=True)

    await handler(_claimed_job())
    assert bybit_client.calls == 2
    assert binance_client.calls == 1  # the read that proves the fix
    assert await _snapshot_count(pg_session_factory, exchange="binance") == 1


async def test_pool_disabled_while_running_stops_being_read_on_the_next_cycle(
    pg_engine: AsyncEngine,
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    _seeded_vault: None,
    _fake_clients: tuple[_FakeVenueClient, _FakeVenueClient],
) -> None:
    bybit_client, binance_client = _fake_clients
    monkeypatch.setattr(main, "engine", pg_engine)

    await _seed_pool(pg_session_factory, exchange="bybit", enabled=True)
    await _seed_pool(pg_session_factory, exchange="binance", enabled=True)

    runner = main.build_worker_runner(
        [_BYBIT_POOL], session_factory_override=pg_session_factory
    )
    handler = runner._handlers[JobKind.BALANCE_SYNC]  # noqa: SLF001

    await handler(_claimed_job())
    assert bybit_client.calls == 1
    assert binance_client.calls == 1

    await _set_pool_enabled(pg_session_factory, exchange="binance", enabled=False)

    await handler(_claimed_job())
    assert bybit_client.calls == 2
    assert binance_client.calls == 1  # unchanged: not read this cycle


async def _job_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM jobs WHERE kind = 'balance.sync'")
        )
        return result.scalar_one()


async def test_zero_enabled_pools_still_enqueues_the_successor(
    pg_engine: AsyncEngine,
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    _seeded_vault: None,
    _fake_clients: tuple[_FakeVenueClient, _FakeVenueClient],
) -> None:
    """Binding requirement 5: the chain must not die just because every pool
    is disabled at the moment a cycle runs -- re-enabling one later has to
    work, and that needs a successor to still be scheduled. The STARTUP
    refusal on zero pools (``worker._run_worker``'s ``if not pools: raise``)
    is untouched and belongs to PR 8b, not re-checked here."""
    bybit_client, binance_client = _fake_clients
    monkeypatch.setattr(main, "engine", pg_engine)

    await _seed_pool(pg_session_factory, exchange="bybit", enabled=True)
    await _set_pool_enabled(pg_session_factory, exchange="bybit", enabled=False)

    runner = main.build_worker_runner(
        [_BYBIT_POOL], session_factory_override=pg_session_factory
    )
    handler = runner._handlers[JobKind.BALANCE_SYNC]  # noqa: SLF001

    before = await _job_count(pg_session_factory)
    await handler(_claimed_job())
    after = await _job_count(pg_session_factory)

    assert bybit_client.calls == 0
    assert binance_client.calls == 0
    assert after == before + 1  # the successor, even with nothing synced


async def test_a_lock_key_collision_in_the_reloaded_set_keeps_the_previous_pools(
    pg_engine: AsyncEngine,
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    _seeded_vault: None,
    _fake_clients: tuple[_FakeVenueClient, _FakeVenueClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Binding requirement 4: a reload that WOULD collide two pools onto the
    same advisory-lock key must not be adopted -- the previous set keeps
    being used, and the collision is reported once, not every cycle. A real
    hash collision cannot be engineered deterministically, so
    ``assert_pool_lock_keys_distinct`` itself is replaced with a fake that
    raises on demand -- everything else in this test is the real wiring."""
    bybit_client, binance_client = _fake_clients
    monkeypatch.setattr(main, "engine", pg_engine)

    should_collide = {"value": False}

    async def _fake_assert_distinct(conn: object, pools: object) -> None:
        if should_collide["value"]:
            raise PoolLockKeyCollisionError(
                "pools (bybit, usdt-m, USDT) and (binance, usdt-m, USDT) both "
                "hash to lock key (1, 2)"
            )

    monkeypatch.setattr(main, "assert_pool_lock_keys_distinct", _fake_assert_distinct)

    await _seed_pool(pg_session_factory, exchange="bybit", enabled=True)
    await _seed_pool(pg_session_factory, exchange="binance", enabled=False)

    runner = main.build_worker_runner(
        [_BYBIT_POOL], session_factory_override=pg_session_factory
    )
    handler = runner._handlers[JobKind.BALANCE_SYNC]  # noqa: SLF001

    await handler(_claimed_job())  # baseline cycle, no collision yet
    assert binance_client.calls == 0

    await _set_pool_enabled(pg_session_factory, exchange="binance", enabled=True)
    should_collide["value"] = True

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        await handler(_claimed_job())  # reload refused: binance must NOT be adopted
        assert binance_client.calls == 0

        await handler(_claimed_job())  # same collision again: no repeat ERROR
        assert binance_client.calls == 0

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1

    should_collide["value"] = False
    await handler(_claimed_job())  # collision resolved: binance adopted now
    assert binance_client.calls == 1
