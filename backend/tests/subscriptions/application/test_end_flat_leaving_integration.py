"""The sweep's half of a LEAVING subscription's end, on real PostgreSQL (tasks.md N2,
E2.3).

A close ends a LEAVING subscription when it books the last fill. A reservation that
ends unfilled books nothing, so no close ever comes. The sweep ends those, and the
cost of ending one too early is a position no close reaches: fan-out sends a closing
signal to ACTIVE and LEAVING holders only. So holding is read the way
``SqlAlchemyLiveExposure`` reads it, and an order still in flight counts, even when
the sweeper has already expired the reservation under it.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.subscriptions.application.end_leaving import (
    EndFlatLeaving,
    EndLeavingSubscription,
)
from strategy_manager.subscriptions.application.leave import Leave
from strategy_manager.subscriptions.domain.subscription import SubscriptionStatus
from strategy_manager.subscriptions.infrastructure.adapters import (
    OpenAllocationAdapter,
    SqlAlchemyLeavingSubscriptions,
    SqlAlchemyStrategyLookup,
)
from strategy_manager.subscriptions.infrastructure.repository import (
    SqlAlchemySubscriptionRepository,
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


def _sweep(session: AsyncSession) -> EndFlatLeaving:
    ledger = SqlAlchemyLedgerRepository(session)
    return EndFlatLeaving(
        SqlAlchemyLeavingSubscriptions(session),
        PoolLockAdapter(session),
        EndLeavingSubscription(
            SqlAlchemySubscriptionRepository(session),
            OpenAllocationAdapter(session, ledger, ReadSymbolHoldings(ledger)),
            SystemClock(),
        ),
        session,
    )


async def _subscriber(factory: Factory, *, status: str = "LEAVING") -> tuple[UUID, UUID, UUID]:
    strategy_id = await seeds.strategy(factory)
    user_id, pool_id = await seeds.user(factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(
        factory, user_id, strategy_id, pool_id, status=status
    )
    return user_id, strategy_id, subscription_id


async def _reservation(
    factory: Factory, user_id: UUID, strategy_id: UUID, *, status: str
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
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    return reservation_id


async def _status(factory: Factory, subscription_id: UUID) -> str:
    return (await seeds.row_of(factory, subscription_id)).status


async def _sweep_once(factory: Factory) -> int:
    async with factory() as session:
        return await _sweep(session).sweep()


@pytest.mark.parametrize("status", ["RELEASED", "EXPIRED"])
async def test_a_reservation_that_ended_unfilled_ends_the_subscription(
    pg_session_factory: Factory,  # noqa: F811
    status: str,
) -> None:
    user_id, strategy_id, subscription_id = await _subscriber(pg_session_factory)
    await _reservation(pg_session_factory, user_id, strategy_id, status=status)

    assert await _sweep_once(pg_session_factory) == 1

    row = await seeds.row_of(pg_session_factory, subscription_id)
    assert row.status == SubscriptionStatus.ENDED.value
    assert row.ended_at is not None


async def test_a_position_keeps_it_leaving(pg_session_factory: Factory) -> None:  # noqa: F811
    user_id, strategy_id, subscription_id = await _subscriber(pg_session_factory)
    await seeds.open_allocation(pg_session_factory, user_id, strategy_id)

    assert await _sweep_once(pg_session_factory) == 0

    assert await _status(pg_session_factory, subscription_id) == "LEAVING"


async def test_a_live_reservation_keeps_it_leaving(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id, subscription_id = await _subscriber(pg_session_factory)
    await seeds.live_reservation(pg_session_factory, user_id, strategy_id)

    assert await _sweep_once(pg_session_factory) == 0

    assert await _status(pg_session_factory, subscription_id) == "LEAVING"


async def test_an_order_in_flight_keeps_it_leaving_after_its_reservation_expired(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The sweeper expires a SUBMITTED reservation too, and the order may still fill.
    Ending here leaves a position no close reaches."""
    user_id, strategy_id, subscription_id = await _subscriber(pg_session_factory)
    reservation_id = await _reservation(
        pg_session_factory, user_id, strategy_id, status="EXPIRED"
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=uuid4(), reservation_id=reservation_id, symbol="STXUSDT"
    )

    assert await _sweep_once(pg_session_factory) == 0

    assert await _status(pg_session_factory, subscription_id) == "LEAVING"


async def test_an_order_that_finished_does_not_keep_it_leaving(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id, subscription_id = await _subscriber(pg_session_factory)
    reservation_id = await _reservation(
        pg_session_factory, user_id, strategy_id, status="RELEASED"
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        reservation_id=reservation_id,
        symbol="STXUSDT",
        status="FAILED",
    )

    assert await _sweep_once(pg_session_factory) == 1

    assert await _status(pg_session_factory, subscription_id) == "ENDED"


async def test_another_users_order_in_flight_is_not_this_users(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    _, strategy_id, subscription_id = await _subscriber(pg_session_factory)
    other_id, other_pool = await seeds.user(pg_session_factory)
    assert other_pool is not None
    other_subscription = await seeds.subscription(
        pg_session_factory, other_id, strategy_id, other_pool, status="LEAVING"
    )
    reservation_id = await _reservation(
        pg_session_factory, other_id, strategy_id, status="EXPIRED"
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=uuid4(), reservation_id=reservation_id, symbol="STXUSDT"
    )

    assert await _sweep_once(pg_session_factory) == 1

    assert await _status(pg_session_factory, subscription_id) == "ENDED"
    assert await _status(pg_session_factory, other_subscription) == "LEAVING"


async def test_an_order_in_flight_of_another_strategy_is_not_this_ones(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, _, subscription_id = await _subscriber(pg_session_factory)
    other_strategy = await seeds.strategy(pg_session_factory)
    reservation_id = await _reservation(
        pg_session_factory, user_id, other_strategy, status="EXPIRED"
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=uuid4(), reservation_id=reservation_id, symbol="STXUSDT"
    )

    assert await _sweep_once(pg_session_factory) == 1

    assert await _status(pg_session_factory, subscription_id) == "ENDED"


@pytest.mark.parametrize("status", ["ACTIVE", "ENDED"])
async def test_only_a_leaving_subscription_is_touched(
    pg_session_factory: Factory,  # noqa: F811
    status: str,
) -> None:
    _, _, subscription_id = await _subscriber(pg_session_factory, status=status)
    before = await seeds.rows(pg_session_factory)

    assert await _sweep_once(pg_session_factory) == 0

    assert await seeds.rows(pg_session_factory) == before
    assert await _status(pg_session_factory, subscription_id) == status


async def test_the_sweep_waits_for_the_users_pool_lock(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, _, subscription_id = await _subscriber(pg_session_factory)

    async with pg_session_factory() as holder:
        await PoolLockAdapter(holder).acquire(user_id, *MARKET)
        sweeping = asyncio.create_task(_sweep_once(pg_session_factory))
        try:
            await asyncio.wait({sweeping}, timeout=_WAIT)
            assert not sweeping.done(), "the sweep did not wait for the user's pool lock"
            assert await _status(pg_session_factory, subscription_id) == "LEAVING"
        finally:
            await holder.commit()
            await asyncio.wait({sweeping}, timeout=_FINISH)
            if not sweeping.done():
                sweeping.cancel()

    assert sweeping.result() == 1
    assert await _status(pg_session_factory, subscription_id) == "ENDED"


async def test_leave_keeps_a_position_coming_from_an_order_in_flight(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """``Leave`` asks the same question, so it gets the same answer: going ENDED here
    was the same stranded position, reached by the user's own click."""
    user_id, strategy_id, subscription_id = await _subscriber(
        pg_session_factory, status="ACTIVE"
    )
    reservation_id = await _reservation(
        pg_session_factory, user_id, strategy_id, status="EXPIRED"
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=uuid4(), reservation_id=reservation_id, symbol="STXUSDT"
    )

    async with pg_session_factory() as session:
        ledger = SqlAlchemyLedgerRepository(session)
        left = await Leave(
            subscriptions=SqlAlchemySubscriptionRepository(session),
            strategies=SqlAlchemyStrategyLookup(session),
            allocations=OpenAllocationAdapter(session, ledger, ReadSymbolHoldings(ledger)),
            pool_lock=PoolLockAdapter(session),
            commit=session,
            clock=SystemClock(),
        ).leave(user_id, subscription_id)

    assert left.status is SubscriptionStatus.LEAVING


class _SettlesAfterTheLedgerRead(SqlAlchemyLedgerRepository):
    """Reads the ledger, then lets an opening's settle commit from another session,
    exactly as it can: an opening's settle takes no pool lock."""

    def __init__(self, session: AsyncSession, factory: Factory, attempt_id: UUID) -> None:
        super().__init__(session)
        self._factory = factory
        self._attempt_id = attempt_id

    async def distinct_symbols_for_strategy(self, *args: Any) -> Any:
        found = await super().distinct_symbols_for_strategy(*args)
        async with self._factory() as other:
            await other.execute(
                text("UPDATE execution_attempts SET status = 'FILLED' WHERE id = :id"),
                {"id": self._attempt_id},
            )
            await other.execute(
                text(
                    "UPDATE reservations SET status = 'FILLED', terminal_at = now() "
                    "WHERE id = (SELECT reservation_id FROM execution_attempts WHERE id = :id)"
                ),
                {"id": self._attempt_id},
            )
            await other.commit()
        return found


async def test_exposure_is_read_in_the_order_it_moves(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Exposure moves from the reservation to the attempt to the ledger. Reading the
    ledger first, a settle committing in between leaves the fill unseen and the
    reservation gone, and a user holding a position reads as flat."""
    user_id, strategy_id, _ = await _subscriber(pg_session_factory)
    reservation_id, attempt_id = uuid4(), uuid4()
    signal_id = uuid4()
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"key-{signal_id}",
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="SUBMITTED",
        user_id=user_id,
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=attempt_id, reservation_id=reservation_id, symbol="STXUSDT"
    )

    async with pg_session_factory() as session:
        ledger = _SettlesAfterTheLedgerRead(session, pg_session_factory, attempt_id)
        adapter = OpenAllocationAdapter(session, ledger, ReadSymbolHoldings(ledger))

        assert await adapter.holds_open_allocation(user_id, strategy_id, MARKET)


async def test_the_listing_names_the_strategys_market(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    user_id, strategy_id, _ = await _subscriber(pg_session_factory)
    await _subscriber(pg_session_factory, status="ACTIVE")

    async with pg_session_factory() as session:
        [found] = await SqlAlchemyLeavingSubscriptions(session).leaving()

    assert (found.user_id, found.strategy_id, found.market) == (user_id, strategy_id, MARKET)
