"""Whose account the venue is compared with (multi-user design AD7, tasks.md E.6).

A user in simulation with nothing real has nothing to compare, so the scan and the
booking skip them. Being live is enough, and so is holding anything real, or a
discrepancy still open.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.fill import (
    REHEARSAL_FILL_ID_PREFIX,
    REHEARSAL_ORDER_ID_PREFIX,
)
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.reconciliation.infrastructure.reconciled_users import (
    SqlAlchemyReconciledUsers,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from tests.owner import ensure_pool, seed_other_user
from tests.reconciliation.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

POOL = ("bybit", "usdt-m", "USDT")


async def _user(factory: Factory, mode: str = "SIMULATION") -> UUID:
    async with factory() as session:
        user_id = await seed_other_user(session)
        await session.execute(
            text("UPDATE users SET mode = :mode WHERE id = :id"), {"mode": mode, "id": user_id}
        )
        await session.commit()
    return user_id


async def _reservation(
    factory: Factory, user_id: UUID, *, status: str, mode: str
) -> tuple[UUID, UUID]:
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, author_id=user_id)
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status=status,
        user_id=user_id,
        mode=mode,
    )
    return strategy_id, reservation_id


async def _position(factory: Factory, user_id: UUID, *, mode: str) -> None:
    """A filled opening of ``mode``, with its fill of that origin in the ledger."""
    strategy_id, allocation_id = await _reservation(factory, user_id, status="FILLED", mode=mode)
    attempt_id = uuid4()
    await seed_execution_attempt(
        factory, attempt_id=attempt_id, reservation_id=allocation_id, status="FILLED"
    )
    rehearsal = mode == "SIMULATION"
    fill = FillRecord(
        user_id=user_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        execution_attempt_id=attempt_id,
        exchange=POOL[0],
        venue=POOL[1],
        settlement_currency=POOL[2],
        symbol="STXUSDT",
        side="BUY",
        quantity=Decimal("2"),
        price=Decimal("1"),
        fee=Decimal("0"),
        fee_currency="USDT",
        notional=Decimal("2"),
        exchange_order_id=f"{REHEARSAL_ORDER_ID_PREFIX if rehearsal else 'EX-'}{uuid4()}",
        exchange_fill_id=f"{REHEARSAL_FILL_ID_PREFIX if rehearsal else 'F-'}{uuid4()}",
        filled_at=datetime.now(UTC),
        usd_rate_at_fill=Decimal("1"),
    )
    async with factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(fill)
        await session.commit()


async def _discrepancy(factory: Factory, user_id: UUID, *, resolved: bool = False) -> None:
    async with factory() as session:
        await ensure_pool(session, POOL, user_id=user_id)
        await SqlAlchemyDiscrepancyRepository(session).upsert_open(
            user_id,
            POOL,
            "STXUSDT",
            Observation(DiscrepancyKind.NO_MATCHING_ALLOCATION, Decimal("1"), Decimal("0")),
            [],
            consecutive_scans=1,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=uuid4(),
            at=datetime.now(UTC),
        )
        if resolved:
            await session.execute(
                text(
                    "UPDATE reconciliation_discrepancies SET resolved_at = now() "
                    "WHERE user_id = :id"
                ),
                {"id": user_id},
            )
        await session.commit()


async def _includes(factory: Factory, user_id: UUID) -> bool:
    async with factory() as session:
        return await SqlAlchemyReconciledUsers(session).includes(user_id)


async def test_a_live_user_is_reconciled_holding_nothing(pg_session_factory: Factory) -> None:
    user_id = await _user(pg_session_factory, "LIVE")

    assert await _includes(pg_session_factory, user_id) is True


async def test_a_simulated_user_with_nothing_real_is_not(pg_session_factory: Factory) -> None:
    user_id = await _user(pg_session_factory)

    assert await _includes(pg_session_factory, user_id) is False


async def test_a_simulated_position_is_not_something_real(pg_session_factory: Factory) -> None:
    user_id = await _user(pg_session_factory)
    await _position(pg_session_factory, user_id, mode="SIMULATION")

    assert await _includes(pg_session_factory, user_id) is False


async def test_a_real_opening_on_its_way_counts_for_a_simulated_user(
    pg_session_factory: Factory,
) -> None:
    user_id = await _user(pg_session_factory)
    await _reservation(pg_session_factory, user_id, status="SUBMITTED", mode="LIVE")

    assert await _includes(pg_session_factory, user_id) is True


async def test_a_real_position_counts_for_a_simulated_user(pg_session_factory: Factory) -> None:
    user_id = await _user(pg_session_factory)
    await _position(pg_session_factory, user_id, mode="LIVE")

    assert await _includes(pg_session_factory, user_id) is True


async def test_an_open_discrepancy_keeps_a_simulated_user_reconciled(
    pg_session_factory: Factory,
) -> None:
    """A venue position the ledger reads as flat is real and only a scan can clear
    it: stopping at the mode would leave it open for good."""
    user_id = await _user(pg_session_factory)
    await _discrepancy(pg_session_factory, user_id)

    assert await _includes(pg_session_factory, user_id) is True


async def test_a_resolved_discrepancy_does_not(pg_session_factory: Factory) -> None:
    user_id = await _user(pg_session_factory)
    await _discrepancy(pg_session_factory, user_id, resolved=True)

    assert await _includes(pg_session_factory, user_id) is False


async def test_what_another_user_holds_counts_for_nobody_else(
    pg_session_factory: Factory,
) -> None:
    factory = pg_session_factory
    user_id = await _user(factory)
    other = await _user(factory)
    await _position(factory, other, mode="LIVE")
    await _discrepancy(factory, other)

    assert await _includes(factory, user_id) is False


async def test_among_answers_only_the_reconciled_ones(pg_session_factory: Factory) -> None:
    factory = pg_session_factory
    live = await _user(factory, "LIVE")
    exposed = await _user(factory)
    await _position(factory, exposed, mode="LIVE")
    simulated = await _user(factory)

    async with factory() as session:
        answer = await SqlAlchemyReconciledUsers(session).among([live, exposed, simulated])

    assert answer == {live, exposed}
