"""A worker job trades and reads with its strategy author's key (multi-user
design AD8, tasks.md B.5 and B.7), against real PostgreSQL.

The owner and a second user each hold an active Bybit key. A job on the second
user's signal, or on the attempt that signal opened, must open its venue client
with the second user's key, never the owner's. Everything runs through
``build_worker_runner``'s registered handlers; only the venue client and the
use case behind each handler are replaced, so the key a client is opened with
is what is observed. No real credential (rule 1): every key is a sentinel.
"""

import base64
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager import main
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential, KeyFacts
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
from tests.owner import OWNER_ID, seed_other_user

pytestmark = pytest.mark.integration

OWNER_KEY = "OWNER-BYBIT-KEY-1111"
OTHER_KEY = "OTHER-BYBIT-KEY-2222"

_BYBIT_POOL = PoolConfig(
    exchange=Exchange.BYBIT,
    venue=Venue.USDT_M,
    settlement_currency=Currency.USDT,
    user_id=OWNER_ID,
    min_order_size=Decimal("10"),
)


class _Recorded:
    def __init__(self, master_key: bytes) -> None:
        self.master_key = master_key
        self.signed_with: list[str] = []
        self.handled: list[object] = []


@pytest.fixture
async def recorded(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> _Recorded:
    """Live mode, both users' keys sealed, and every venue client recording
    the key it is opened with."""
    master_key = os.urandom(MASTER_KEY_BYTES)
    monkeypatch.setattr(
        get_settings(), "master_encryption_key", base64.b64encode(master_key).decode()
    )
    monkeypatch.setattr(get_settings(), "dry_run", False)
    seen = _Recorded(master_key)

    @asynccontextmanager
    async def _client(settings: object, credentials: Any, *_: object) -> AsyncIterator[object]:
        seen.signed_with.append(credentials.api_key)
        yield object()

    for name in ("trade_client", "binance_trade_client", "read_only_client"):
        monkeypatch.setattr(main, name, _client)

    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.commit()
    return seen


async def _store(
    factory: async_sessionmaker[AsyncSession], master_key: bytes, user_id: UUID, api_key: str
) -> None:
    async with factory() as session:
        await SqlAlchemyCredentialVault(session, EnvelopeCipher(master_key), SystemClock()).store(
            user_id,
            ExchangeCredential(exchange="bybit", label="default", api_key=api_key, api_secret="s"),
            KeyFacts.unrecorded(trade_capable=True),
        )
        await session.commit()


async def _the_other_users_signal(
    factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> tuple[UUID, UUID]:
    """Both users hold a key; the second user's strategy has a signal and the
    attempt it opened. Returns ``(signal_id, attempt_id)``."""
    async with factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    await _store(factory, master_key, OWNER_ID, OWNER_KEY)
    await _store(factory, master_key, other, OTHER_KEY)
    strategy_id, signal_id, reservation_id, attempt_id = uuid4(), uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, author_id=other)
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory, reservation_id=reservation_id, strategy_id=strategy_id, signal_id=signal_id
    )
    await seed_execution_attempt(factory, attempt_id=attempt_id, reservation_id=reservation_id)
    return signal_id, attempt_id


def _job(kind: JobKind, payload: dict[str, str]) -> ClaimedJob:
    return ClaimedJob(id=uuid4(), kind=kind, payload=payload, attempts=1, max_attempts=5)


async def test_a_settle_job_trades_with_the_attempts_author_key_never_another_users(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    recorded: _Recorded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, attempt_id = await _the_other_users_signal(pg_session_factory, recorded.master_key)

    class _Settle:
        async def settle(self, attempt: UUID) -> None:
            recorded.handled.append(attempt)

    monkeypatch.setattr(main, "_build_settle_execution", lambda session, exchanges: _Settle())
    runner = main.build_worker_runner([_BYBIT_POOL], session_factory_override=pg_session_factory)

    await runner._handlers[JobKind.EXECUTION_SETTLE](  # noqa: SLF001
        _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(attempt_id)})
    )

    assert recorded.handled == [attempt_id]
    assert recorded.signed_with == [OTHER_KEY]


async def test_a_signal_job_trades_with_the_strategy_authors_key_never_another_users(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    recorded: _Recorded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_id, _ = await _the_other_users_signal(pg_session_factory, recorded.master_key)

    class _Handler:
        async def handle(self, signal: UUID) -> None:
            recorded.handled.append(signal)

    monkeypatch.setattr(
        main, "_build_process_signal_handler", lambda *args, **kwargs: (_Handler(), None)
    )
    runner = main.build_worker_runner([_BYBIT_POOL], session_factory_override=pg_session_factory)

    await runner._handlers[JobKind.SIGNAL_PROCESS](  # noqa: SLF001
        _job(JobKind.SIGNAL_PROCESS, {"signal_id": str(signal_id)})
    )

    assert recorded.handled == [signal_id]
    assert recorded.signed_with == [OTHER_KEY]
