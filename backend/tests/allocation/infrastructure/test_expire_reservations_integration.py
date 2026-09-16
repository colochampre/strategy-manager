"""TXN-C against a real PostgreSQL database: the batch expiry sweep and the
database-level constraint that backs it (design.md § Transaction Boundaries;
spec: capital-allocation § Reservation Expiry; tasks.md 6.4).

The sweep is a set-based UPDATE — it never loads a ``Reservation`` aggregate —
so the domain's rules cannot enforce themselves here. Migration ``0008``'s
CHECK constraint is what keeps a set-based statement honest; that constraint is
proven in ``test_terminal_at_constraint.py``, which needs a genuinely migrated
database because ``Base.metadata.create_all`` knows nothing about CHECK
constraints (the same reason the ledger's append-only guard needs Tier B).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.application.expire_reservations import ExpireReservations
from strategy_manager.allocation.domain.reservation import ReleaseReason, ReservationStatus
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from tests.allocation.infrastructure.conftest import seed_signal, seed_strategy

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)


class FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


async def _seed_reservation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    status: str,
    expires_at: datetime,
) -> UUID:
    signal_id = uuid4()
    await seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    reservation_id = uuid4()
    async with session_factory() as session:
        session.add(
            ReservationRow(
                id=reservation_id,
                strategy_id=strategy_id,
                signal_id=signal_id,
                exchange="pionex",
                venue="spot",
                settlement_currency="USDT",
                amount=Decimal("100"),
                status=status,
                expires_at=expires_at,
                terminal_at=NOW if status in ("FILLED", "RELEASED", "EXPIRED") else None,
            )
        )
        await session.commit()
    return reservation_id


async def _statuses(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[UUID, tuple[str, datetime | None, str | None]]:
    async with session_factory() as session:
        rows = (await session.execute(select(ReservationRow))).scalars().all()
        return {r.id: (r.status, r.terminal_at, r.release_reason) for r in rows}


def _build(session: AsyncSession) -> ExpireReservations:
    return ExpireReservations(
        reservations=SqlAlchemyReservationRepository(session),
        clock=FrozenClock(NOW),
        commit=session,
    )


async def test_batch_expiry_terminates_every_past_expiry_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)

    overdue_pending = await _seed_reservation(
        pg_session_factory,
        strategy_id=strategy_id,
        status="PENDING",
        expires_at=NOW - timedelta(seconds=5),
    )
    overdue_submitted = await _seed_reservation(
        pg_session_factory,
        strategy_id=strategy_id,
        status="SUBMITTED",
        expires_at=NOW - timedelta(seconds=1),
    )
    still_fresh = await _seed_reservation(
        pg_session_factory,
        strategy_id=strategy_id,
        status="PENDING",
        expires_at=NOW + timedelta(seconds=30),
    )
    already_filled = await _seed_reservation(
        pg_session_factory,
        strategy_id=strategy_id,
        status="FILLED",
        expires_at=NOW - timedelta(days=1),
    )

    async with pg_session_factory() as session:
        result = await _build(session).sweep()

    assert result.expired == 2

    rows = await _statuses(pg_session_factory)
    assert rows[overdue_pending][0] == ReservationStatus.EXPIRED.value
    assert rows[overdue_pending][1] == NOW
    assert rows[overdue_pending][2] == ReleaseReason.EXPIRED_BY_SWEEPER.value
    assert rows[overdue_submitted][0] == ReservationStatus.EXPIRED.value
    assert rows[still_fresh][0] == ReservationStatus.PENDING.value
    assert rows[still_fresh][1] is None
    assert rows[already_filled][0] == ReservationStatus.FILLED.value


async def test_a_second_sweep_over_the_same_rows_changes_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The sweeper re-enqueues itself, so it runs forever. A pass that
    re-transitioned already-terminal rows would rewrite ``terminal_at`` on every
    tick and destroy the only record of when a reservation actually ended."""

    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await _seed_reservation(
        pg_session_factory,
        strategy_id=strategy_id,
        status="PENDING",
        expires_at=NOW - timedelta(seconds=5),
    )

    async with pg_session_factory() as session:
        first = await _build(session).sweep()
    async with pg_session_factory() as session:
        second = await _build(session).sweep()

    assert first.expired == 1
    assert second.expired == 0

    rows = await _statuses(pg_session_factory)
    assert next(iter(rows.values()))[1] == NOW  # terminal_at untouched by the second pass


async def test_the_batch_size_bounds_a_single_sweep(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    for _ in range(4):
        await _seed_reservation(
            pg_session_factory,
            strategy_id=strategy_id,
            status="PENDING",
            expires_at=NOW - timedelta(seconds=5),
        )

    async with pg_session_factory() as session:
        use_case = ExpireReservations(
            reservations=SqlAlchemyReservationRepository(session),
            clock=FrozenClock(NOW),
            commit=session,
            batch_size=3,
        )
        result = await use_case.sweep()

    assert result.expired == 3


async def test_a_reservation_still_inside_its_ttl_survives_the_sweep(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await _seed_reservation(
        pg_session_factory,
        strategy_id=strategy_id,
        status="PENDING",
        expires_at=NOW + timedelta(seconds=1),
    )

    async with pg_session_factory() as session:
        result = await _build(session).sweep()

    assert result.expired == 0
