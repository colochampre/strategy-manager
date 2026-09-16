"""``ExpireReservations`` — TXN-C, the batch expiry sweep (design.md
§ Transaction Boundaries; spec: capital-allocation § Reservation Expiry;
tasks.md 6.1).

The sweeper is what stops a crashed worker from holding capital hostage. It
changes no invariant — ``sum_active`` already excludes expired rows — but
without it an orphaned reservation never reaches a terminal status, so nothing
distinguishes "stalled" from "still working".
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from strategy_manager.allocation.application.expire_reservations import ExpireReservations
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.reservation import (
    ReleaseReason,
    Reservation,
    ReservationStatus,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
POOL = PoolKey(exchange=Exchange.PIONEX, venue=Venue.SPOT, settlement_currency=Currency.USDT)


class FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class FakeSweepRepository:
    """Holds reservations in memory and applies the *domain's* own sweep rules,
    so this test exercises the use case's orchestration rather than a
    reimplementation of the rule it is supposed to check."""

    def __init__(self, reservations: list[Reservation]) -> None:
        self.reservations = list(reservations)
        self.calls: list[tuple[datetime, int]] = []

    async def expire_due(self, now: datetime, limit: int) -> int:
        self.calls.append((now, limit))
        due = [r for r in self.reservations if r.is_sweepable(now)][:limit]
        for reservation in due:
            index = self.reservations.index(reservation)
            self.reservations[index] = reservation.expire(now)
        return len(due)


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _reservation(
    status: ReservationStatus = ReservationStatus.PENDING,
    *,
    expires_at: datetime = NOW - timedelta(seconds=1),
) -> Reservation:
    return Reservation(
        id=uuid4(),
        strategy_id=uuid4(),
        signal_id=uuid4(),
        pool_key=POOL,
        amount=Decimal("100"),
        status=status,
        expires_at=expires_at,
    )


def _build(
    reservations: list[Reservation], *, batch_size: int = 500
) -> tuple[ExpireReservations, FakeSweepRepository, SpyCommit]:
    repository = FakeSweepRepository(reservations)
    commit = SpyCommit()
    use_case = ExpireReservations(
        reservations=repository,
        clock=FrozenClock(NOW),
        commit=commit,
        batch_size=batch_size,
    )
    return use_case, repository, commit


async def test_expires_only_reservations_past_their_ttl() -> None:
    overdue = _reservation()
    fresh = _reservation(expires_at=NOW + timedelta(seconds=30))
    use_case, repository, _ = _build([overdue, fresh])

    result = await use_case.sweep()

    assert result.expired == 1
    statuses = {r.id: r.status for r in repository.reservations}
    assert statuses[overdue.id] is ReservationStatus.EXPIRED
    assert statuses[fresh.id] is ReservationStatus.PENDING


async def test_expired_rows_carry_the_terminal_timestamp_and_reason() -> None:
    use_case, repository, _ = _build([_reservation()])

    await use_case.sweep()

    swept = repository.reservations[0]
    assert swept.terminal_at == NOW
    assert swept.release_reason is ReleaseReason.EXPIRED_BY_SWEEPER


async def test_terminal_reservations_are_left_alone() -> None:
    filled = _reservation(ReservationStatus.FILLED, expires_at=NOW - timedelta(days=1))
    released = _reservation(ReservationStatus.RELEASED, expires_at=NOW - timedelta(days=1))
    use_case, repository, _ = _build([filled, released])

    result = await use_case.sweep()

    assert result.expired == 0
    assert [r.status for r in repository.reservations] == [
        ReservationStatus.FILLED,
        ReservationStatus.RELEASED,
    ]


async def test_sweeping_twice_expires_nothing_the_second_time() -> None:
    """Idempotency: the sweep runs on a schedule, so a second pass over the
    same rows must be a no-op rather than a double transition."""

    use_case, _, _ = _build([_reservation(), _reservation()])

    first = await use_case.sweep()
    second = await use_case.sweep()

    assert first.expired == 2
    assert second.expired == 0


async def test_the_batch_size_bounds_one_sweep() -> None:
    use_case, repository, _ = _build([_reservation() for _ in range(5)], batch_size=2)

    result = await use_case.sweep()

    assert result.expired == 2
    assert repository.calls[0][1] == 2


async def test_the_sweep_reads_now_from_the_clock() -> None:
    use_case, repository, _ = _build([_reservation()])

    await use_case.sweep()

    assert repository.calls[0][0] == NOW


async def test_the_sweep_commits_even_when_nothing_expired() -> None:
    use_case, _, commit = _build([_reservation(expires_at=NOW + timedelta(seconds=30))])

    result = await use_case.sweep()

    assert result.expired == 0
    assert commit.commits == 1
