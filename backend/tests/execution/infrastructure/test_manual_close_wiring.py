"""The ``execution.manual_close`` job is worked with the key of the user who asked
(subscriber-safety SS.9, risk item 2), against real PostgreSQL.

The owner and a second user each hold an active Bybit key. A close job naming the second user
must open its venue client with the second user's key, never the owner's, and the use case
behind the handler receives that user and that allocation. Only the venue client and the use
case are replaced, so the key a client is opened with is what is observed. No real credential
(rule 1): every key is a sentinel.
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
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher
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


async def test_a_manual_close_job_signs_with_the_asking_users_key_never_another_users(
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_key = os.urandom(MASTER_KEY_BYTES)
    monkeypatch.setattr(
        get_settings(), "master_encryption_key", base64.b64encode(master_key).decode()
    )
    monkeypatch.setattr(get_settings(), "dry_run", False)
    signed_with: list[str] = []
    closed: list[tuple[UUID, UUID]] = []

    @asynccontextmanager
    async def _client(settings: object, credentials: Any, *_: object) -> AsyncIterator[object]:
        signed_with.append(credentials.api_key)
        yield object()

    for name in ("trade_client", "binance_trade_client", "read_only_client"):
        monkeypatch.setattr(main, name, _client)

    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        other = await seed_other_user(session)
        await session.commit()
    await _store(pg_session_factory, master_key, OWNER_ID, OWNER_KEY)
    await _store(pg_session_factory, master_key, other, OTHER_KEY)

    class _CloseByHand:
        def __init__(self, exchanges_for: Any) -> None:
            self._exchanges_for = exchanges_for

        async def close(self, user_id: UUID, allocation_id: UUID) -> bool:
            async with self._exchanges_for(user_id) as exchanges:
                await exchanges.for_mode(Mode.LIVE)
            closed.append((user_id, allocation_id))
            return True

    monkeypatch.setattr(
        main,
        "_build_close_by_hand",
        lambda session, settings, exchanges_for: _CloseByHand(exchanges_for),
    )
    runner = main.build_worker_runner([_BYBIT_POOL], session_factory_override=pg_session_factory)
    allocation_id = uuid4()

    await runner._handlers[JobKind.MANUAL_CLOSE](  # noqa: SLF001
        ClaimedJob(
            id=uuid4(),
            kind=JobKind.MANUAL_CLOSE,
            payload={"user_id": str(other), "allocation_id": str(allocation_id)},
            attempts=1,
            max_attempts=5,
        )
    )

    assert closed == [(other, allocation_id)]
    assert signed_with == [OTHER_KEY]
