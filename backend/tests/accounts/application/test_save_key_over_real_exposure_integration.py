"""A key that cannot trade, saved over something real, on real PostgreSQL (tasks.md
A6, E2.4).

Saving supersedes the active key. A read-only key over a real position leaves that
position with nothing that can close it, and the worker refuses to start on one, for
every user. Real means what ``SqlAlchemyLiveExposure`` says. A symbol crosses the
boundary in two spellings: a signal carries ``STXUSDT.P``, the ledger ``STXUSDT``.
"""

import asyncio
import base64
import secrets
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.save_credential import (
    SaveCredential,
    Saved,
    SaveOutcome,
    SaveRefused,
    SaveResult,
)
from strategy_manager.accounts.domain.key_policy import PermissionSnapshot
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.accounts.infrastructure.credentials_router import get_save_credential
from strategy_manager.accounts.infrastructure.key_inspectors.registry import KeyInspectorRegistry
from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.execution.infrastructure.live_exposure import SqlAlchemyLiveExposure
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from tests.accounts.fakes import (
    NEITHER,
    READ_ONLY_SNAPSHOT,
    TRADING_SNAPSHOT,
    RecordingInspector,
    TickingClock,
    bybit_credential,
    registry_for,
)
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
)
from tests.strategies.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
MARKET = seeds.MARKET
_WAIT = 0.5
_FINISH = 10.0


def _use_case(session: AsyncSession, snapshot: PermissionSnapshot) -> SaveCredential:
    clock = TickingClock()
    return SaveCredential(
        registry_for(RecordingInspector(snapshot)),
        SqlAlchemyCredentialVault(
            session, EnvelopeCipher(secrets.token_bytes(MASTER_KEY_BYTES)), clock
        ),
        SqlAlchemyCapitalPoolWriter(session),
        session,
        clock,
        PoolLockAdapter(session),
        SqlAlchemyLiveExposure(session),
    )


async def _save(factory: Factory, user_id: UUID, snapshot: PermissionSnapshot) -> SaveResult:
    async with factory() as session:
        return await _use_case(session, snapshot).execute(user_id, bybit_credential(), NEITHER)


async def _active_keys(factory: Factory, user_id: UUID) -> list[bool]:
    """``trade_capable`` of every active key of the user's."""
    async with factory() as session:
        result = await session.execute(
            select(ExchangeCredentialRow.trade_capable).where(
                ExchangeCredentialRow.user_id == user_id,
                ExchangeCredentialRow.is_active.is_(True),
            )
        )
        return list(result.scalars().all())


async def _trader(factory: Factory) -> tuple[UUID, UUID]:
    """A user with a key that can trade, and a strategy to hold something in."""
    user_id, _ = await seeds.user(factory)
    strategy_id = await seeds.strategy(factory)
    assert isinstance(await _save(factory, user_id, TRADING_SNAPSHOT), Saved)
    return user_id, strategy_id


async def _reservation(
    factory: Factory,
    user_id: UUID,
    strategy_id: UUID,
    *,
    status: str,
    mode: str = "LIVE",
    exchange: str = "bybit",
) -> UUID:
    signal_id, reservation_id = uuid4(), uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"key-{signal_id}"
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status=status,
        user_id=user_id,
        mode=mode,
        exchange=exchange,
    )
    return reservation_id


async def _assert_refused(factory: Factory, user_id: UUID) -> None:
    result = await _save(factory, user_id, READ_ONLY_SNAPSHOT)

    assert isinstance(result, SaveRefused)
    assert result.outcome is SaveOutcome.EXCHANGE_HOLDS_REAL_EXPOSURE
    assert await _active_keys(factory, user_id) == [True]


async def _assert_saved(factory: Factory, user_id: UUID) -> None:
    result = await _save(factory, user_id, READ_ONLY_SNAPSHOT)

    assert isinstance(result, Saved)
    assert await _active_keys(factory, user_id) == [False]


async def test_a_real_position_refuses_it_and_the_key_that_closes_it_stays(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id = await _trader(pg_session_factory)
    await seeds.open_allocation(pg_session_factory, user_id, strategy_id)

    await _assert_refused(pg_session_factory, user_id)


async def test_a_live_reservation_refuses_it(pg_session_factory: Factory) -> None:  # noqa: F811
    user_id, strategy_id = await _trader(pg_session_factory)
    await _reservation(pg_session_factory, user_id, strategy_id, status="PENDING")

    await _assert_refused(pg_session_factory, user_id)


async def test_an_order_in_flight_refuses_it(pg_session_factory: Factory) -> None:  # noqa: F811
    user_id, strategy_id = await _trader(pg_session_factory)
    reservation_id = await _reservation(
        pg_session_factory, user_id, strategy_id, status="EXPIRED"
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=uuid4(), reservation_id=reservation_id, symbol="STXUSDT"
    )

    await _assert_refused(pg_session_factory, user_id)


async def test_a_simulated_reservation_needs_no_key_that_trades(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id = await _trader(pg_session_factory)
    await _reservation(
        pg_session_factory, user_id, strategy_id, status="PENDING", mode="SIMULATION"
    )

    await _assert_saved(pg_session_factory, user_id)


async def test_a_finished_reservation_refuses_nothing(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id = await _trader(pg_session_factory)
    await _reservation(pg_session_factory, user_id, strategy_id, status="RELEASED")

    await _assert_saved(pg_session_factory, user_id)


async def test_what_is_real_on_another_exchange_is_not_this_keys_concern(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id = await _trader(pg_session_factory)
    await _reservation(
        pg_session_factory, user_id, strategy_id, status="PENDING", exchange="binance"
    )

    await _assert_saved(pg_session_factory, user_id)


async def test_an_order_in_flight_on_another_exchange_is_not_this_keys_concern(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id = await _trader(pg_session_factory)
    reservation_id = await _reservation(
        pg_session_factory, user_id, strategy_id, status="EXPIRED", exchange="binance"
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        reservation_id=reservation_id,
        exchange="binance",
        symbol="STXUSDT",
    )

    await _assert_saved(pg_session_factory, user_id)


async def test_a_position_on_another_exchange_is_not_this_keys_concern(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id = await _trader(pg_session_factory)
    await seeds.open_allocation(
        pg_session_factory, user_id, strategy_id, market=("binance", "usdt-m", "USDT")
    )

    await _assert_saved(pg_session_factory, user_id)


async def test_the_routes_own_wiring_refuses_it(
    pg_session_factory: Factory,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_save_credential`` as the route builds it, with only the venue replaced:
    every other test here builds its own use case."""
    user_id, strategy_id = await _trader(pg_session_factory)
    await seeds.open_allocation(pg_session_factory, user_id, strategy_id)
    monkeypatch.setattr(
        get_settings(),
        "master_encryption_key",
        base64.b64encode(secrets.token_bytes(MASTER_KEY_BYTES)).decode(),
    )
    monkeypatch.setattr(
        KeyInspectorRegistry,
        "for_settings",
        classmethod(
            lambda cls, settings, clock: registry_for(RecordingInspector(READ_ONLY_SNAPSHOT))
        ),
    )

    async with pg_session_factory() as session:
        result = await get_save_credential(session).execute(user_id, bybit_credential(), NEITHER)

    assert isinstance(result, SaveRefused)
    assert result.outcome is SaveOutcome.EXCHANGE_HOLDS_REAL_EXPOSURE
    assert await _active_keys(pg_session_factory, user_id) == [True]


async def test_what_another_user_holds_is_not_this_users(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id = await _trader(pg_session_factory)
    other_id, _ = await seeds.user(pg_session_factory)
    await seeds.open_allocation(pg_session_factory, other_id, strategy_id)

    await _assert_saved(pg_session_factory, user_id)


async def test_the_read_waits_for_an_opening_that_holds_the_pool_lock(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The opening holds the lock and has not committed: read without the lock, this
    save saw nothing real, and the key that closes that opening was gone."""
    user_id, strategy_id = await _trader(pg_session_factory)

    async with pg_session_factory() as opening:
        await PoolLockAdapter(opening).acquire(user_id, *MARKET)
        saving = asyncio.create_task(_save(pg_session_factory, user_id, READ_ONLY_SNAPSHOT))
        try:
            await asyncio.wait({saving}, timeout=_WAIT)
            assert not saving.done(), "the save did not wait for the pool lock"
        finally:
            await _reservation(pg_session_factory, user_id, strategy_id, status="PENDING")
            await opening.commit()
            await asyncio.wait({saving}, timeout=_FINISH)
            if not saving.done():
                saving.cancel()

    result = saving.result()
    assert isinstance(result, SaveRefused)
    assert result.outcome is SaveOutcome.EXCHANGE_HOLDS_REAL_EXPOSURE
    assert await _active_keys(pg_session_factory, user_id) == [True]
