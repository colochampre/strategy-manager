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
from strategy_manager.signals.infrastructure.job_owner import delivery_owner
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
from tests.owner import OWNER_ID, ensure_delivery, ensure_pool, seed_other_user
from tests.subscriptions.infrastructure import seeds

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
        self.settled_as: list[UUID] = []


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
) -> tuple[UUID, UUID, UUID]:
    """Both users hold a key; the second user's strategy has a signal and the
    attempt it opened. Returns ``(signal_id, attempt_id, second user's id)``."""
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
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        user_id=other,
    )
    await seed_execution_attempt(factory, attempt_id=attempt_id, reservation_id=reservation_id)
    return signal_id, attempt_id, other


def _job(kind: JobKind, payload: dict[str, str]) -> ClaimedJob:
    return ClaimedJob(id=uuid4(), kind=kind, payload=payload, attempts=1, max_attempts=5)


async def test_a_settle_job_trades_with_the_attempts_author_key_never_another_users(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    recorded: _Recorded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, attempt_id, other = await _the_other_users_signal(pg_session_factory, recorded.master_key)

    class _Settle:
        async def settle(self, user_id: UUID, attempt: UUID) -> None:
            recorded.settled_as.append(user_id)
            recorded.handled.append(attempt)

    monkeypatch.setattr(main, "_build_settle_execution", lambda session, exchanges: _Settle())
    runner = main.build_worker_runner([_BYBIT_POOL], session_factory_override=pg_session_factory)

    await runner._handlers[JobKind.EXECUTION_SETTLE](  # noqa: SLF001
        _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(attempt_id)})
    )

    assert recorded.handled == [attempt_id]
    assert recorded.signed_with == [OTHER_KEY]
    # The reservation is read and marked as the same user's (AD8, B.5).
    assert recorded.settled_as == [other]


async def test_a_signal_job_fans_out_its_signal_and_opens_no_venue_client(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    recorded: _Recorded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C.6: ``signal.process`` reaches ``FanOutSignal`` and nothing else. It
    places no order, so no key is decrypted and no client opened for it: each
    ``delivery.process`` job it enqueues is worked with its own subscriber's."""
    signal_id, _, _ = await _the_other_users_signal(pg_session_factory, recorded.master_key)

    class _FanOut:
        async def run(self, signal: UUID) -> None:
            recorded.handled.append(signal)

    def _no_delivery_handler(*args: object, **kwargs: object) -> None:
        raise AssertionError("signal.process must not build a delivery handler")

    monkeypatch.setattr(main, "_build_fan_out_signal", lambda session, settings: _FanOut())
    monkeypatch.setattr(main, "_build_process_delivery", _no_delivery_handler)
    runner = main.build_worker_runner([_BYBIT_POOL], session_factory_override=pg_session_factory)

    await runner._handlers[JobKind.SIGNAL_PROCESS](  # noqa: SLF001
        _job(JobKind.SIGNAL_PROCESS, {"signal_id": str(signal_id)})
    )

    assert recorded.handled == [signal_id]
    assert recorded.signed_with == []


async def _a_delivery_to_the_other_user(
    factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> tuple[UUID, UUID]:
    """A strategy the OWNER authored, with a signal delivered to ANOTHER user's
    subscription. Both hold a key. Returns ``(delivery_id, subscriber's id)``."""
    async with factory() as session:
        other = await seed_other_user(session)
        pool_id = await ensure_pool(session, ("bybit", "usdt-m", "USDT"), user_id=other)
        await session.commit()
    await _store(factory, master_key, OWNER_ID, OWNER_KEY)
    await _store(factory, master_key, other, OTHER_KEY)
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, author_id=OWNER_ID)
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seeds.subscription(factory, other, strategy_id, pool_id)
    async with factory() as session:
        delivery_id = await ensure_delivery(
            session, signal_id=signal_id, strategy_id=strategy_id, user_id=other
        )
        await session.commit()
    return delivery_id, other


async def test_a_delivery_job_trades_with_the_subscribers_key_never_the_strategy_authors(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    recorded: _Recorded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C.6: ``delivery.process`` reaches ``ProcessDelivery`` with the halves its
    payload names, signed with the DELIVERY's user's key although the strategy is
    the owner's."""
    delivery_id, _ = await _a_delivery_to_the_other_user(
        pg_session_factory, recorded.master_key
    )

    class _Handler:
        async def handle(self, delivery: UUID, halves: object) -> None:
            recorded.handled.append((delivery, halves))

    monkeypatch.setattr(
        main, "_build_process_delivery", lambda *args, **kwargs: (_Handler(), None)
    )
    runner = main.build_worker_runner([_BYBIT_POOL], session_factory_override=pg_session_factory)

    await runner._handlers[JobKind.DELIVERY_PROCESS](  # noqa: SLF001
        _job(JobKind.DELIVERY_PROCESS, {"delivery_id": str(delivery_id), "halves": "open"})
    )

    assert recorded.handled == [(delivery_id, "open")]
    assert recorded.signed_with == [OTHER_KEY]


async def test_a_delivery_job_without_halves_hands_the_handler_none_not_a_default(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    recorded: _Recorded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery_id, _ = await _a_delivery_to_the_other_user(
        pg_session_factory, recorded.master_key
    )

    class _Handler:
        async def handle(self, delivery: UUID, halves: object) -> None:
            recorded.handled.append((delivery, halves))

    monkeypatch.setattr(
        main, "_build_process_delivery", lambda *args, **kwargs: (_Handler(), None)
    )
    runner = main.build_worker_runner([_BYBIT_POOL], session_factory_override=pg_session_factory)

    await runner._handlers[JobKind.DELIVERY_PROCESS](  # noqa: SLF001
        _job(JobKind.DELIVERY_PROCESS, {"delivery_id": str(delivery_id)})
    )

    assert recorded.handled == [(delivery_id, None)]


async def test_the_owner_of_a_delivery_is_its_user_not_the_authors(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    recorded: _Recorded,
) -> None:
    delivery_id, other = await _a_delivery_to_the_other_user(
        pg_session_factory, recorded.master_key
    )

    async with pg_session_factory() as session:
        owner = await delivery_owner(session, delivery_id)
        missing = await delivery_owner(session, uuid4())

    assert owner == other
    assert owner != OWNER_ID
    assert missing is None
