"""Which delivery a ``signal.open_after_close`` job works (tasks.md C.8), on real
PostgreSQL.

The continuation is keyed by the DELIVERY: ``SqlAlchemyDeliveries.signal_of`` reads
its signal, ``continuation_delivery_id`` names it from a payload, and the failed-job
reader maps an exhausted continuation to it. A job queued BEFORE C.8 carries a
``signal_id`` and no ``delivery_id``: it resolves to the signal's only delivery, and
refuses (loudly) when the signal has none or several, because choosing one would open
a subscriber's position on someone else's money.

Every scenario gives a signal two deliveries, the AUTHOR's and another user's, so an
answer that picked "the author's" or "the first" names the wrong one.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.application.process_signal import UnknownDeliveryError
from strategy_manager.signals.infrastructure.delivery_adapters import SqlAlchemyDeliveries
from strategy_manager.signals.infrastructure.exhausted_job_recorder import FailedJobTarget
from strategy_manager.signals.infrastructure.failed_job_signal_reader import (
    SqlAlchemyFailedJobSignalReader,
)
from strategy_manager.signals.infrastructure.job_owner import (
    UnresolvableContinuation,
    continuation_delivery_id,
)
from tests.owner import OWNER_ID, ensure_author_subscription, ensure_delivery, seed_other_user
from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_signal_row,
    seed_strategy,
)

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class Signal:
    signal_id: UUID
    author_delivery: UUID | None
    other_delivery: UUID | None
    other: UUID


async def _signal(
    factory: Factory, *, author: bool = True, other: bool = True
) -> Signal:
    """A signal of the OWNER's strategy, delivered to the owner and/or another user."""
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal_row(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"key-{signal_id}",
    )
    async with factory() as session:
        stranger = await seed_other_user(session)
        await ensure_author_subscription(session, strategy_id)
        author_delivery = (
            await ensure_delivery(
                session, signal_id=signal_id, strategy_id=strategy_id, user_id=OWNER_ID
            )
            if author
            else None
        )
        other_delivery = (
            await ensure_delivery(
                session, signal_id=signal_id, strategy_id=strategy_id, user_id=stranger
            )
            if other
            else None
        )
        await session.commit()
    return Signal(signal_id, author_delivery, other_delivery, stranger)


def _legacy(signal_id: UUID) -> dict[str, object]:
    """A payload as ``OpenAfterClose.seed`` wrote it before C.8."""
    return {"signal_id": str(signal_id), "awaited_allocation_ids": [], "poll": 0}


# --- signal_of ------------------------------------------------------------------------


async def test_a_delivery_knows_its_signal_whoever_its_user_is(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    first = await _signal(pg_session_factory)
    second = await _signal(pg_session_factory)

    async with pg_session_factory() as session:
        deliveries = SqlAlchemyDeliveries(session)
        answers = [
            await deliveries.signal_of(first.author_delivery),  # type: ignore[arg-type]
            await deliveries.signal_of(first.other_delivery),  # type: ignore[arg-type]
            await deliveries.signal_of(second.other_delivery),  # type: ignore[arg-type]
        ]

    assert answers == [first.signal_id, first.signal_id, second.signal_id]


async def test_an_unknown_delivery_has_no_signal(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    missing = uuid4()

    async with pg_session_factory() as session:
        with pytest.raises(UnknownDeliveryError, match=str(missing)):
            await SqlAlchemyDeliveries(session).signal_of(missing)


# --- continuation_delivery_id ---------------------------------------------------------


async def test_a_payload_that_names_a_delivery_is_that_delivery_even_for_a_non_author(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    scenario = await _signal(pg_session_factory)
    payload: dict[str, object] = {
        "delivery_id": str(scenario.other_delivery),
        "awaited_allocation_ids": [],
        "poll": 2,
    }

    async with pg_session_factory() as session:
        resolved = await continuation_delivery_id(session, payload)

    assert resolved == scenario.other_delivery
    assert resolved != scenario.author_delivery


async def test_a_legacy_payload_resolves_to_the_signals_only_delivery_whoever_it_is_for(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Not "the author's": the only delivery there is, here a non-author's."""
    scenario = await _signal(pg_session_factory, author=False)

    async with pg_session_factory() as session:
        resolved = await continuation_delivery_id(session, _legacy(scenario.signal_id))

    assert resolved == scenario.other_delivery


async def test_a_legacy_payload_whose_signal_has_two_deliveries_is_refused_naming_them(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    scenario = await _signal(pg_session_factory)

    async with pg_session_factory() as session:
        with pytest.raises(UnresolvableContinuation) as raised:
            await continuation_delivery_id(session, _legacy(scenario.signal_id))

    message = str(raised.value)
    assert str(scenario.signal_id) in message
    assert "2 deliveries" in message


async def test_a_legacy_payload_whose_signal_has_no_delivery_is_refused(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    scenario = await _signal(pg_session_factory, author=False, other=False)

    async with pg_session_factory() as session:
        with pytest.raises(UnresolvableContinuation) as raised:
            await continuation_delivery_id(session, _legacy(scenario.signal_id))

    assert str(scenario.signal_id) in str(raised.value)
    assert "no delivery" in str(raised.value)


@pytest.mark.parametrize(
    "payload",
    [{}, {"poll": 0}, {"delivery_id": "not-a-uuid"}, {"signal_id": "not-a-uuid"}],
    ids=["empty", "neither-id", "bad-delivery-id", "bad-signal-id"],
)
async def test_a_payload_that_names_neither_a_delivery_nor_a_signal_is_refused(
    pg_session_factory: Factory,  # noqa: F811
    payload: dict[str, object],
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(UnresolvableContinuation):
            await continuation_delivery_id(session, payload)


# --- the failed-job reader ------------------------------------------------------------


def _job(payload: dict[str, object]) -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
        payload=payload,
        attempts=5,
        max_attempts=5,
    )


async def _resolve(factory: Factory, job: ClaimedJob) -> FailedJobTarget | None:
    async with factory() as session:
        return await SqlAlchemyFailedJobSignalReader(session).target_for(job)


async def test_an_exhausted_continuation_ends_the_delivery_it_was_seeded_for(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    scenario = await _signal(pg_session_factory)
    job = _job(
        {"delivery_id": str(scenario.other_delivery), "awaited_allocation_ids": [], "poll": 4}
    )

    resolved = await _resolve(pg_session_factory, job)

    assert resolved == FailedJobTarget(delivery_id=scenario.other_delivery)


async def test_an_exhausted_continuation_whose_delivery_is_gone_is_loud(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    gone = uuid4()
    job = _job({"delivery_id": str(gone), "awaited_allocation_ids": [], "poll": 1})

    with pytest.raises(InvariantViolation, match=str(gone)):
        await _resolve(pg_session_factory, job)


async def test_an_exhausted_legacy_continuation_of_a_signal_with_two_deliveries_is_loud(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The queue logs the raised error; picking the author's delivery here would end
    a subscriber's delivery that never failed."""
    scenario = await _signal(pg_session_factory)

    with pytest.raises(InvariantViolation, match=str(scenario.signal_id)):
        await _resolve(pg_session_factory, _job(_legacy(scenario.signal_id)))
