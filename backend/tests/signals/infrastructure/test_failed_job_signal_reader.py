"""``SqlAlchemyFailedJobSignalReader`` on real PostgreSQL (decision 25, task
5c.6): which signal a FAILED job was working on.

The trap is ``execution.settle`` for a CLOSE. Its attempt's ``allocation_id`` is
the OPENING allocation, so following the reservation would name the OPENING
signal and reject the wrong one; a close resolves through
``execution_attempts.signal_id``.

Three spellings of one market cross the module boundaries on purpose (signals
keep ``STXUSDT_PERP``, attempts hold ``STXUSDT``).
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.infrastructure.failed_job_signal_reader import (
    SqlAlchemyFailedJobSignalReader,
)
from tests.signals.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal_row,
    seed_strategy,
)

pytestmark = pytest.mark.integration


def _job(kind: JobKind, payload: dict[str, object]) -> ClaimedJob:
    return ClaimedJob(id=uuid4(), kind=kind, payload=payload, attempts=5, max_attempts=5)


async def _resolve(
    factory: async_sessionmaker[AsyncSession], job: ClaimedJob
) -> UUID | None:
    async with factory() as session:
        return await SqlAlchemyFailedJobSignalReader(session).signal_for(job)


async def _open_and_close(
    factory: async_sessionmaker[AsyncSession], *, close_link: bool
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    """Returns (opening_signal, closing_signal, reservation, open_attempt,
    close_attempt). The open attempt carries NO link (a legacy attempt)."""
    strategy_id, opening_signal, closing_signal = uuid4(), uuid4(), uuid4()
    reservation_id, open_attempt, close_attempt = uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    for signal_id, key in ((opening_signal, "opening"), (closing_signal, "closing")):
        await seed_signal_row(
            factory,
            signal_id=signal_id,
            strategy_id=strategy_id,
            idempotency_key=f"{key}-{signal_id}",
            symbol="STXUSDT_PERP",
        )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=opening_signal,
        status="FILLED",
    )
    await seed_execution_attempt(
        factory,
        attempt_id=open_attempt,
        reservation_id=reservation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
    )
    await seed_execution_attempt(
        factory,
        attempt_id=close_attempt,
        closes_allocation_id=reservation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
        signal_id=closing_signal if close_link else None,
    )
    return opening_signal, closing_signal, reservation_id, open_attempt, close_attempt


async def test_a_signal_process_job_names_its_signal(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    signal_id = uuid4()
    job = _job(JobKind.SIGNAL_PROCESS, {"signal_id": str(signal_id)})

    assert await _resolve(pg_session_factory, job) == signal_id


async def test_a_continuation_job_names_its_signal(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    signal_id = uuid4()
    job = _job(
        JobKind.SIGNAL_OPEN_AFTER_CLOSE,
        {"signal_id": str(signal_id), "awaited_allocation_ids": [], "poll": 3},
    )

    assert await _resolve(pg_session_factory, job) == signal_id


async def test_a_settle_job_for_an_open_resolves_through_the_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    opening_signal, _, _, open_attempt, _ = await _open_and_close(
        pg_session_factory, close_link=True
    )
    job = _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(open_attempt)})

    assert await _resolve(pg_session_factory, job) == opening_signal


async def test_a_settle_job_for_a_close_resolves_the_closing_signal_not_the_opening_one(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    opening_signal, closing_signal, _, _, close_attempt = await _open_and_close(
        pg_session_factory, close_link=True
    )
    job = _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(close_attempt)})

    resolved = await _resolve(pg_session_factory, job)

    assert resolved == closing_signal
    assert resolved != opening_signal


async def test_a_settle_job_for_a_close_with_no_link_resolves_to_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An orphan close, or one written before 5c: it must not fall back to the
    opening reservation's signal."""
    _, _, _, _, close_attempt = await _open_and_close(pg_session_factory, close_link=False)
    job = _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(close_attempt)})

    assert await _resolve(pg_session_factory, job) is None


@pytest.mark.parametrize(
    "kind", [JobKind.BALANCE_SYNC, JobKind.RESERVATION_SWEEP, JobKind.WATCHDOG_CHECK]
)
async def test_a_job_kind_that_decides_no_signal_resolves_to_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession], kind: JobKind
) -> None:
    assert await _resolve(pg_session_factory, _job(kind, {"signal_id": str(uuid4())})) is None


@pytest.mark.parametrize(
    "job",
    [
        _job(JobKind.SIGNAL_PROCESS, {}),
        _job(JobKind.EXECUTION_SETTLE, {}),
        _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(uuid4())}),
    ],
    ids=["no-signal-id", "no-attempt-id", "unknown-attempt"],
)
async def test_a_malformed_or_dangling_payload_is_loud(
    pg_session_factory: async_sessionmaker[AsyncSession], job: ClaimedJob
) -> None:
    """Silence here is the defect: a FAILED job whose signal cannot be found
    must say so (the queue logs the raised error) rather than skip quietly."""
    with pytest.raises(InvariantViolation):
        await _resolve(pg_session_factory, job)
