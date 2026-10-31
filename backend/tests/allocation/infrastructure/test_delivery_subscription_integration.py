"""``SqlAlchemyDeliverySubscription`` on real PostgreSQL (tasks.md N1, N5, E2.2): only
an ``ACTIVE`` subscription takes openings, and a delivery with no row is a fault."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.infrastructure.delivery_subscription import (
    SqlAlchemyDeliverySubscription,
)
from strategy_manager.shared.domain.errors import InvariantViolation
from tests.ledger.infrastructure.conftest import seed_signal
from tests.owner import ensure_delivery
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


async def _delivery_of(factory: Factory, status: str) -> UUID:
    strategy_id = await seeds.strategy(factory)
    user_id, pool_id = await seeds.user(factory)
    assert pool_id is not None
    await seeds.subscription(factory, user_id, strategy_id, pool_id, status=status)
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    async with factory() as session:
        delivery_id = await ensure_delivery(
            session, signal_id=signal_id, strategy_id=strategy_id, user_id=user_id
        )
        await session.commit()
    return delivery_id


@pytest.mark.parametrize(
    ("status", "active"), [("ACTIVE", True), ("LEAVING", False), ("ENDED", False)]
)
async def test_only_an_active_subscription_takes_openings(
    pg_session_factory: Factory, status: str, active: bool
) -> None:
    delivery_id = await _delivery_of(pg_session_factory, status)

    async with pg_session_factory() as session:
        answer = await SqlAlchemyDeliverySubscription(session).is_active(delivery_id)

    assert answer is active


async def test_a_delivery_with_no_row_is_refused_loudly(pg_session_factory: Factory) -> None:
    missing = uuid4()

    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation, match=str(missing)):
            await SqlAlchemyDeliverySubscription(session).is_active(missing)
