"""``SqlAlchemySubscriptionReservations.latest_before`` on real PostgreSQL (tasks.md
C.6, finding b): the reservation a close works is the SUBSCRIPTION's own latest
reservation on the strategy and symbol, for a signal received before the closing one,
in any status.

A reservation carries no symbol, so it is found through its signal, under every
spelling of the market. The alert says ``STXUSDT.P``, Pionex says ``STXUSDT_PERP``,
the venue says ``STXUSDT``: a test crosses the boundary on a different spelling each
side.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.signals.infrastructure.delivery_adapters import (
    SqlAlchemySubscriptionReservations,
)
from tests.owner import OWNER_ID, ensure_pool, seed_other_user
from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_reservation,
    seed_signal_row,
    seed_strategy,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

_T0 = datetime.now(UTC) - timedelta(hours=2)
_MARKET = ("bybit", "usdt-m", "USDT")


async def _strategy(factory: Factory) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    return strategy_id


async def _subscribe(factory: Factory, strategy_id: UUID, user_id: UUID | None = None) -> tuple[
    UUID, UUID
]:
    """A user's ACTIVE subscription to the strategy: ``(user, subscription)``."""
    async with factory() as session:
        user = user_id if user_id is not None else await seed_other_user(session)
        pool = await ensure_pool(session, _MARKET, user_id=user)
        await session.commit()
    subscription = await seeds.subscription(
        factory, user, strategy_id, pool, created_at=_T0 - timedelta(days=1)
    )
    return user, subscription


async def _reserve(
    factory: Factory,
    strategy_id: UUID,
    user: UUID,
    *,
    symbol: str = "STXUSDT.P",
    minutes: int = 0,
    status: str = "FILLED",
) -> tuple[UUID, UUID]:
    """A signal received ``minutes`` after ``_T0`` and ``user``'s reservation for it:
    ``(signal, reservation)``."""
    signal_id, reservation_id = uuid4(), uuid4()
    await seed_signal_row(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"key-{signal_id}",
        symbol=symbol,
        received_at=_T0 + timedelta(minutes=minutes),
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status=status,
        user_id=user,
    )
    return signal_id, reservation_id


async def _latest(
    factory: Factory,
    subscription: UUID,
    user: UUID,
    strategy_id: UUID,
    *,
    symbol: str = "STXUSDT.P",
    minutes: int = 60,
) -> UUID | None:
    async with factory() as session:
        return await SqlAlchemySubscriptionReservations(session).latest_before(
            subscription, user, strategy_id, symbol, _T0 + timedelta(minutes=minutes)
        )


async def test_the_subscriptions_own_reservation_is_found_not_another_subscribers(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    mine, my_subscription = await _subscribe(pg_session_factory, strategy_id, OWNER_ID)
    theirs, their_subscription = await _subscribe(pg_session_factory, strategy_id)
    # Both subscribers reserve for the SAME signal; theirs is the later row.
    signal_id, my_reservation = await _reserve(pg_session_factory, strategy_id, mine)
    their_reservation = uuid4()
    await seed_reservation(
        pg_session_factory,
        reservation_id=their_reservation,
        strategy_id=strategy_id,
        signal_id=signal_id,
        user_id=theirs,
    )

    assert await _latest(pg_session_factory, my_subscription, mine, strategy_id) == my_reservation
    assert (
        await _latest(pg_session_factory, their_subscription, theirs, strategy_id)
        == their_reservation
    )


async def test_a_resubscription_does_not_inherit_the_reservation_of_its_ended_predecessor(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """One user, two subscriptions to one strategy over time: the reservation is the
    subscription's own through its delivery, not the user's."""
    strategy_id = await _strategy(pg_session_factory)
    async with pg_session_factory() as session:
        user = await seed_other_user(session)
        pool = await ensure_pool(session, _MARKET, user_id=user)
        await session.commit()
    old = await seeds.subscription(
        pg_session_factory,
        user,
        strategy_id,
        pool,
        status="ENDED",
        created_at=_T0 - timedelta(days=2),
    )
    _, old_reservation = await _reserve(pg_session_factory, strategy_id, user)
    new = await seeds.subscription(
        pg_session_factory, user, strategy_id, pool, created_at=_T0 - timedelta(days=1)
    )

    assert await _latest(pg_session_factory, old, user, strategy_id) == old_reservation
    assert await _latest(pg_session_factory, new, user, strategy_id) is None


async def test_a_subscription_that_never_reserved_finds_none_whatever_others_hold(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    holder, _ = await _subscribe(pg_session_factory, strategy_id, OWNER_ID)
    stranger, stranger_subscription = await _subscribe(pg_session_factory, strategy_id)
    await _reserve(pg_session_factory, strategy_id, holder)

    assert await _latest(pg_session_factory, stranger_subscription, stranger, strategy_id) is None


async def test_the_reservation_of_another_user_is_never_returned_for_this_subscription(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The user filter is the repository convention: even a subscription id that the
    caller pairs with another user finds nothing of that other user's."""
    strategy_id = await _strategy(pg_session_factory)
    mine, my_subscription = await _subscribe(pg_session_factory, strategy_id, OWNER_ID)
    other, _ = await _subscribe(pg_session_factory, strategy_id)
    await _reserve(pg_session_factory, strategy_id, mine)

    assert await _latest(pg_session_factory, my_subscription, other, strategy_id) is None


async def test_the_symbol_is_matched_under_every_spelling_of_the_market(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    user, subscription = await _subscribe(pg_session_factory, strategy_id, OWNER_ID)
    _, reservation = await _reserve(pg_session_factory, strategy_id, user, symbol="STXUSDT_PERP")

    # Opened as Pionex spells it, asked for as TradingView and the venue spell it.
    assert await _latest(
        pg_session_factory, subscription, user, strategy_id, symbol="STXUSDT.P"
    ) == reservation
    assert await _latest(
        pg_session_factory, subscription, user, strategy_id, symbol="STXUSDT"
    ) == reservation


async def test_another_symbol_is_not_returned(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    user, subscription = await _subscribe(pg_session_factory, strategy_id, OWNER_ID)
    await _reserve(pg_session_factory, strategy_id, user, symbol="ETHUSDT.P")

    assert await _latest(pg_session_factory, subscription, user, strategy_id) is None


async def test_a_reservation_of_another_strategy_is_not_returned(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    other_strategy = await _strategy(pg_session_factory)
    user, subscription = await _subscribe(pg_session_factory, strategy_id, OWNER_ID)
    await _subscribe(pg_session_factory, other_strategy, user)
    await _reserve(pg_session_factory, other_strategy, user)

    assert await _latest(pg_session_factory, subscription, user, strategy_id) is None


async def test_only_a_signal_received_strictly_before_the_closing_one_counts(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    user, subscription = await _subscribe(pg_session_factory, strategy_id, OWNER_ID)
    _, earlier = await _reserve(pg_session_factory, strategy_id, user, minutes=10)
    await _reserve(pg_session_factory, strategy_id, user, minutes=30)  # the closing time itself
    await _reserve(pg_session_factory, strategy_id, user, minutes=40)

    found = await _latest(pg_session_factory, subscription, user, strategy_id, minutes=30)

    assert found == earlier


async def test_the_latest_of_several_wins(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    user, subscription = await _subscribe(pg_session_factory, strategy_id, OWNER_ID)
    await _reserve(pg_session_factory, strategy_id, user, minutes=10)
    _, latest = await _reserve(pg_session_factory, strategy_id, user, minutes=20)

    assert await _latest(pg_session_factory, subscription, user, strategy_id) == latest


@pytest.mark.parametrize("status", ["PENDING", "SUBMITTED", "FILLED", "RELEASED", "EXPIRED"])
async def test_a_reservation_is_found_in_any_status(
    pg_session_factory: Factory,  # noqa: F811
    status: str,
) -> None:
    """Today's per-status handling of a close is unchanged, so the lookup returns the
    reservation whatever it became and leaves the decision to the handler."""
    strategy_id = await _strategy(pg_session_factory)
    user, subscription = await _subscribe(pg_session_factory, strategy_id, OWNER_ID)
    _, reservation = await _reserve(pg_session_factory, strategy_id, user, status=status)

    assert await _latest(pg_session_factory, subscription, user, strategy_id) == reservation
