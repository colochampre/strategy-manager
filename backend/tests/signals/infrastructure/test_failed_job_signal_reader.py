"""``SqlAlchemyFailedJobSignalReader`` on real PostgreSQL (decision 25, task
5c.6; tasks.md C.7): what a FAILED job was working on.

A fan-out (``signal.process``) works the SIGNAL itself; every other kind works a
DELIVERY. The trap is ``execution.settle`` for a CLOSE: its attempt's
``allocation_id`` is the OPENING allocation, so following the reservation would
name the OPENING delivery and reject the wrong one; an attempt names its own
delivery.

Three spellings of one market cross the module boundaries on purpose (signals
keep ``STXUSDT_PERP``, attempts hold ``STXUSDT``).
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.infrastructure.exhausted_job_recorder import FailedJobTarget
from strategy_manager.signals.infrastructure.failed_job_signal_reader import (
    SqlAlchemyFailedJobSignalReader,
)
from tests.owner import ensure_author_subscription, ensure_delivery
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
) -> FailedJobTarget | None:
    async with factory() as session:
        return await SqlAlchemyFailedJobSignalReader(session).target_for(job)


async def _delivery(
    factory: async_sessionmaker[AsyncSession], *, signal_id: UUID, strategy_id: UUID
) -> UUID:
    async with factory() as session:
        delivery_id = await ensure_delivery(
            session, signal_id=signal_id, strategy_id=strategy_id
        )
        await session.commit()
    return delivery_id


async def _open_and_close(
    factory: async_sessionmaker[AsyncSession], *, close_link: bool
) -> tuple[UUID, UUID, UUID, UUID]:
    """Returns (opening_delivery, closing_delivery, open_attempt, close_attempt).
    The opening attempt names the opening delivery; the closing one names the
    closing delivery, or none when ``close_link`` is False (an orphan close)."""
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
    opening_delivery = await _delivery(factory, signal_id=opening_signal, strategy_id=strategy_id)
    closing_delivery = await _delivery(factory, signal_id=closing_signal, strategy_id=strategy_id)
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
        signal_id=opening_signal,
        delivery_id=opening_delivery,
    )
    await seed_execution_attempt(
        factory,
        attempt_id=close_attempt,
        closes_allocation_id=reservation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
        signal_id=closing_signal if close_link else None,
        delivery_id=closing_delivery if close_link else None,
    )
    return opening_delivery, closing_delivery, open_attempt, close_attempt


async def test_a_signal_process_job_names_its_signal_not_a_delivery(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The fan-out has no delivery to hold its outcome: the signal itself."""
    signal_id = uuid4()
    job = _job(JobKind.SIGNAL_PROCESS, {"signal_id": str(signal_id)})

    assert await _resolve(pg_session_factory, job) == FailedJobTarget(signal_id=signal_id)


async def test_a_delivery_process_job_names_its_delivery(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"key-{signal_id}",
    )
    delivery_id = await _delivery(pg_session_factory, signal_id=signal_id, strategy_id=strategy_id)
    job = _job(JobKind.DELIVERY_PROCESS, {"delivery_id": str(delivery_id), "halves": "open"})

    assert await _resolve(pg_session_factory, job) == FailedJobTarget(delivery_id=delivery_id)


async def test_a_continuation_job_names_the_authors_delivery_of_its_signal(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"key-{signal_id}",
    )
    async with pg_session_factory() as session:
        await ensure_author_subscription(session, strategy_id)
        delivery_id = await ensure_delivery(
            session, signal_id=signal_id, strategy_id=strategy_id
        )
        await session.commit()
    job = _job(
        JobKind.SIGNAL_OPEN_AFTER_CLOSE,
        {"signal_id": str(signal_id), "awaited_allocation_ids": [], "poll": 3},
    )

    assert await _resolve(pg_session_factory, job) == FailedJobTarget(delivery_id=delivery_id)


async def test_a_continuation_job_whose_signal_has_no_author_delivery_is_loud(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job = _job(
        JobKind.SIGNAL_OPEN_AFTER_CLOSE,
        {"signal_id": str(uuid4()), "awaited_allocation_ids": [], "poll": 0},
    )

    with pytest.raises(InvariantViolation):
        await _resolve(pg_session_factory, job)


async def test_a_settle_job_for_an_open_names_the_attempts_delivery(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    opening_delivery, _, open_attempt, _ = await _open_and_close(
        pg_session_factory, close_link=True
    )
    job = _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(open_attempt)})

    assert await _resolve(pg_session_factory, job) == FailedJobTarget(delivery_id=opening_delivery)


async def test_a_settle_job_for_a_close_names_the_closing_delivery_not_the_opening_one(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    opening_delivery, closing_delivery, _, close_attempt = await _open_and_close(
        pg_session_factory, close_link=True
    )
    job = _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(close_attempt)})

    resolved = await _resolve(pg_session_factory, job)

    assert resolved == FailedJobTarget(delivery_id=closing_delivery)
    assert resolved != FailedJobTarget(delivery_id=opening_delivery)


async def test_a_settle_job_for_a_close_with_no_link_resolves_to_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An orphan close, or one written before 5c: it must not fall back to the
    opening reservation's delivery."""
    _, _, _, close_attempt = await _open_and_close(pg_session_factory, close_link=False)
    job = _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(close_attempt)})

    assert await _resolve(pg_session_factory, job) is None


@pytest.mark.parametrize(
    "kind", [JobKind.BALANCE_SYNC, JobKind.RESERVATION_SWEEP, JobKind.WATCHDOG_CHECK]
)
async def test_a_job_kind_that_decides_no_outcome_resolves_to_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession], kind: JobKind
) -> None:
    assert await _resolve(pg_session_factory, _job(kind, {"signal_id": str(uuid4())})) is None


@pytest.mark.parametrize(
    "job",
    [
        _job(JobKind.SIGNAL_PROCESS, {}),
        _job(JobKind.EXECUTION_SETTLE, {}),
        _job(JobKind.EXECUTION_SETTLE, {"execution_attempt_id": str(uuid4())}),
        _job(JobKind.DELIVERY_PROCESS, {"halves": "open"}),
        _job(JobKind.DELIVERY_PROCESS, {"delivery_id": str(uuid4()), "halves": "open"}),
    ],
    ids=[
        "no-signal-id",
        "no-attempt-id",
        "unknown-attempt",
        "no-delivery-id",
        "unknown-delivery",
    ],
)
async def test_a_malformed_or_dangling_payload_is_loud(
    pg_session_factory: async_sessionmaker[AsyncSession], job: ClaimedJob
) -> None:
    """Silence here is the defect: a FAILED job whose delivery cannot be found
    must say so (the queue logs the raised error) rather than skip quietly."""
    with pytest.raises(InvariantViolation):
        await _resolve(pg_session_factory, job)
