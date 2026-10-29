"""``FanOutSignal`` against real PostgreSQL (tasks.md C.5, multi-user design AD5).

Real adapters end to end: the signal's transition, the subscriptions, the user's
ledger and reservations, the deliveries and the job queue. A symbol wears a
different spelling on each side of the boundary: the alert says ``STXUSDT.P``,
the ledger says ``STXUSDT``, and a reservation's own signal says ``STXUSDT_PERP``.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.signals.application.fan_out_signal import FanOutResult, FanOutSignal
from strategy_manager.signals.infrastructure.fan_out_adapters import (
    SignalFactsAdapter,
    SqlAlchemyDeliveryRepository,
    SqlAlchemySubscribers,
)
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow, SignalRow
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemySignalOutcomeAdapter,
)
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_reservation,
    seed_signal_row,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

_T0 = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
_EARLIER = _T0 - timedelta(days=1)
_ALERT = "STXUSDT.P"


async def _signal(
    factory: Factory,
    strategy_id: UUID,
    *,
    position_size: str,
    minutes: int,
    symbol: str = _ALERT,
) -> UUID:
    signal_id = uuid4()
    await seed_signal_row(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"key-{signal_id}",
        symbol=symbol,
        position_size=Decimal(position_size),
        received_at=_T0 + timedelta(minutes=minutes),
    )
    return signal_id


async def _opening(factory: Factory, strategy_id: UUID) -> UUID:
    """The strategy's first signal on STXUSDT.P: flat to long."""
    return await _signal(factory, strategy_id, position_size="1", minutes=1)


async def _closing(factory: Factory, strategy_id: UUID) -> UUID:
    """Long to flat on STXUSDT.P, after an earlier opening signal."""
    await _signal(factory, strategy_id, position_size="1", minutes=1)
    return await _signal(factory, strategy_id, position_size="0", minutes=2)


async def _reversing(factory: Factory, strategy_id: UUID) -> UUID:
    """Long to short on STXUSDT.P, after an earlier opening signal."""
    await _signal(factory, strategy_id, position_size="1", minutes=1)
    return await _signal(factory, strategy_id, position_size="-1", minutes=2)


async def _subscriber(
    factory: Factory,
    strategy_id: UUID,
    *,
    status: str = "ACTIVE",
    holds: bool = False,
    created_at: datetime | None = None,
) -> tuple[UUID, UUID]:
    """A fresh user with their own pool and a subscription; ``holds`` gives them an
    open allocation of the strategy on STXUSDT. Returns ``(user_id, subscription_id)``.
    Subscribed a day before the signals unless ``created_at`` says otherwise."""
    user_id, pool_id = await seeds.user(factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(
        factory, user_id, strategy_id, pool_id, status=status, created_at=created_at or _EARLIER
    )
    if holds:
        await seeds.open_allocation(factory, user_id, strategy_id)
    return user_id, subscription_id


async def _fan_out(factory: Factory, signal_id: UUID) -> FanOutResult:
    async with factory() as session:
        use_case = FanOutSignal(
            facts=SignalFactsAdapter(SqlAlchemySignalRepository(session)),
            strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
            subscribers=SqlAlchemySubscribers(
                session, ReadSymbolHoldings(SqlAlchemyLedgerRepository(session))
            ),
            deliveries=SqlAlchemyDeliveryRepository(session),
            jobs=PostgresJobQueue(session),
            outcomes=SqlAlchemySignalOutcomeAdapter(session, SystemClock()),
            commit=session,
        )
        return await use_case.run(signal_id)


async def _delivered_to(factory: Factory, signal_id: UUID) -> dict[UUID, UUID]:
    """``subscription_id -> delivery_id`` for the signal."""
    async with factory() as session:
        result = await session.execute(
            select(SignalDeliveryRow.subscription_id, SignalDeliveryRow.id).where(
                SignalDeliveryRow.signal_id == signal_id
            )
        )
        return {subscription_id: delivery_id for subscription_id, delivery_id in result.all()}


async def _delivery_jobs(factory: Factory) -> dict[str, dict[str, object]]:
    """``dedupe_key -> payload`` of every ``delivery.process`` job."""
    async with factory() as session:
        result = await session.execute(
            select(JobRow.dedupe_key, JobRow.payload).where(
                JobRow.kind == JobKind.DELIVERY_PROCESS.value
            )
        )
        return {str(key): payload for key, payload in result.all()}


async def _signal_row(factory: Factory, signal_id: UUID) -> SignalRow:
    async with factory() as session:
        row = await session.get(SignalRow, signal_id)
        assert row is not None
        return row


def _halves(jobs: dict[str, dict[str, object]], delivery_id: UUID) -> object:
    return jobs[f"delivery:{delivery_id}"]["halves"]


# -- idempotency -----------------------------------------------------------


async def test_a_retried_fan_out_makes_no_second_delivery_and_no_second_job(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    await _subscriber(pg_session_factory, strategy_id)
    await _subscriber(pg_session_factory, strategy_id)
    signal_id = await _opening(pg_session_factory, strategy_id)

    first = await _fan_out(pg_session_factory, signal_id)
    second = await _fan_out(pg_session_factory, signal_id)

    delivered = await _delivered_to(pg_session_factory, signal_id)
    jobs = await _delivery_jobs(pg_session_factory)
    assert len(delivered) == 2
    assert sorted(first.delivery_ids) == sorted(second.delivery_ids)
    assert sorted(first.delivery_ids) == sorted(delivered.values())
    assert sorted(jobs) == sorted(f"delivery:{delivery_id}" for delivery_id in delivered.values())


async def test_a_delivery_that_already_exists_still_gets_its_one_job(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """As after the 0032 backfill: the delivery is there, its job is not."""
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, subscription_id = await _subscriber(pg_session_factory, strategy_id)
    signal_id = await _opening(pg_session_factory, strategy_id)
    existing = uuid4()
    async with pg_session_factory() as session:
        session.add(
            SignalDeliveryRow(
                id=existing,
                signal_id=signal_id,
                subscription_id=subscription_id,
                user_id=user_id,
            )
        )
        await session.commit()

    result = await _fan_out(pg_session_factory, signal_id)

    jobs = await _delivery_jobs(pg_session_factory)
    assert result.delivery_ids == (existing,)
    assert list(jobs) == [f"delivery:{existing}"]
    assert jobs[f"delivery:{existing}"]["delivery_id"] == str(existing)
    assert await _delivered_to(pg_session_factory, signal_id) == {subscription_id: existing}


# -- eligibility -----------------------------------------------------------


async def test_a_private_strategys_existing_subscriber_still_gets_the_delivery(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Making a strategy private stops NEW subscribers (``Subscribe``); it never
    reaches the fan-out, which reads subscriptions and not visibility (decision 21)."""
    strategy_id = await seeds.strategy(pg_session_factory, visibility="PRIVATE")
    subscriber, subscription = await _subscriber(pg_session_factory, strategy_id)
    assert subscriber != (await _author_of(pg_session_factory, strategy_id))
    signal_id = await _opening(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    delivered = await _delivered_to(pg_session_factory, signal_id)
    jobs = await _delivery_jobs(pg_session_factory)
    assert set(delivered) == {subscription}
    assert {_halves(jobs, delivery_id) for delivery_id in delivered.values()} == {"open"}


async def _author_of(factory: Factory, strategy_id: UUID) -> UUID:
    async with factory() as session:
        author = (
            await session.execute(
                select(StrategyRow.author_id).where(StrategyRow.id == strategy_id)
            )
        ).scalar_one()
    return UUID(str(author))


async def test_an_opening_reaches_every_active_subscription_and_no_other(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    first_user, first = await _subscriber(pg_session_factory, strategy_id)
    second_user, second = await _subscriber(pg_session_factory, strategy_id)
    _, leaving = await _subscriber(pg_session_factory, strategy_id, status="LEAVING", holds=True)
    _, ended = await _subscriber(pg_session_factory, strategy_id, status="ENDED")
    signal_id = await _opening(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    delivered = await _delivered_to(pg_session_factory, signal_id)
    jobs = await _delivery_jobs(pg_session_factory)
    assert set(delivered) == {first, second}
    assert leaving not in delivered
    assert ended not in delivered
    assert {_halves(jobs, delivery_id) for delivery_id in delivered.values()} == {"open"}
    async with pg_session_factory() as session:
        rows = (
            await session.execute(
                select(SignalDeliveryRow.user_id, SignalDeliveryRow.status).where(
                    SignalDeliveryRow.signal_id == signal_id
                )
            )
        ).all()
    assert sorted(rows) == sorted([(first_user, "ACCEPTED"), (second_user, "ACCEPTED")])


async def test_a_close_reaches_only_the_holders_active_or_leaving(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    _, holder = await _subscriber(pg_session_factory, strategy_id, holds=True)
    _, leaving_holder = await _subscriber(
        pg_session_factory, strategy_id, status="LEAVING", holds=True
    )
    _, empty = await _subscriber(pg_session_factory, strategy_id)
    _, ended = await _subscriber(pg_session_factory, strategy_id, status="ENDED", holds=True)
    signal_id = await _closing(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    delivered = await _delivered_to(pg_session_factory, signal_id)
    jobs = await _delivery_jobs(pg_session_factory)
    assert set(delivered) == {holder, leaving_holder}
    assert empty not in delivered
    assert ended not in delivered
    assert {_halves(jobs, delivery_id) for delivery_id in delivered.values()} == {"close"}


async def test_a_holder_of_another_symbol_of_the_strategy_gets_no_close(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    _, holder = await _subscriber(pg_session_factory, strategy_id, holds=True)
    other_user, other_pool = await seeds.user(pg_session_factory)
    assert other_pool is not None
    elsewhere = await seeds.subscription(
        pg_session_factory, other_user, strategy_id, other_pool, created_at=_EARLIER
    )
    await seeds.open_allocation(pg_session_factory, other_user, strategy_id, symbol="BTCUSDT")
    signal_id = await _closing(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    delivered = await _delivered_to(pg_session_factory, signal_id)
    assert set(delivered) == {holder}
    assert elsewhere not in delivered


async def test_a_live_reservation_on_the_symbol_makes_its_user_a_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Capital reserved for an opening that has not filled yet. The reservation's
    own signal is spelled ``STXUSDT_PERP``; the closing alert says ``STXUSDT.P``.
    A reservation held for another symbol makes nobody a holder of this one."""
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    reserving = await seeds.subscription(
        pg_session_factory, user_id, strategy_id, pool_id, created_at=_EARLIER
    )
    opened = await _signal(
        pg_session_factory, strategy_id, position_size="1", minutes=0, symbol="STXUSDT_PERP"
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=uuid4(),
        strategy_id=strategy_id,
        signal_id=opened,
        status="PENDING",
        user_id=user_id,
    )
    other_user, other_pool = await seeds.user(pg_session_factory)
    assert other_pool is not None
    idle = await seeds.subscription(
        pg_session_factory, other_user, strategy_id, other_pool, created_at=_EARLIER
    )
    # The idle user's capital is held too, but for another symbol.
    elsewhere = await _signal(
        pg_session_factory, strategy_id, position_size="1", minutes=0, symbol="BTCUSDT"
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=uuid4(),
        strategy_id=strategy_id,
        signal_id=elsewhere,
        status="SUBMITTED",
        user_id=other_user,
    )
    signal_id = await _closing(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    delivered = await _delivered_to(pg_session_factory, signal_id)
    assert set(delivered) == {reserving}
    assert idle not in delivered


async def test_a_new_subscriber_gets_the_next_opening_and_so_its_close(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The newcomer holds nothing yet, but the opening was delivered to it. Its
    delivery is still queued when the close fans out, so the close goes to it too:
    otherwise that opening would open a position nothing ever closes (PR C
    verifier, B1). A user who never got the opening still gets no close."""
    strategy_id = await seeds.strategy(pg_session_factory)
    _, veteran = await _subscriber(pg_session_factory, strategy_id, holds=True)
    _, newcomer = await _subscriber(pg_session_factory, strategy_id)
    _, too_late = await _subscriber(
        pg_session_factory, strategy_id, created_at=_T0 + timedelta(seconds=90)
    )
    opening = await _opening(pg_session_factory, strategy_id)
    closing = await _signal(pg_session_factory, strategy_id, position_size="0", minutes=2)

    await _fan_out(pg_session_factory, opening)
    await _fan_out(pg_session_factory, closing)

    assert set(await _delivered_to(pg_session_factory, opening)) == {veteran, newcomer}
    assert set(await _delivered_to(pg_session_factory, closing)) == {veteran, newcomer}
    assert too_late not in await _delivered_to(pg_session_factory, closing)


async def test_a_reverse_gives_the_holder_both_halves_and_the_others_only_the_opening(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    _, holder = await _subscriber(pg_session_factory, strategy_id, holds=True)
    _, newcomer = await _subscriber(pg_session_factory, strategy_id)
    _, leaving_holder = await _subscriber(
        pg_session_factory, strategy_id, status="LEAVING", holds=True
    )
    _, leaving_idle = await _subscriber(pg_session_factory, strategy_id, status="LEAVING")
    _, ended = await _subscriber(pg_session_factory, strategy_id, status="ENDED", holds=True)
    signal_id = await _reversing(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    delivered = await _delivered_to(pg_session_factory, signal_id)
    jobs = await _delivery_jobs(pg_session_factory)
    assert set(delivered) == {holder, newcomer, leaving_holder}
    assert leaving_idle not in delivered
    assert ended not in delivered
    assert _halves(jobs, delivered[holder]) == "close_and_open"
    assert _halves(jobs, delivered[newcomer]) == "open"
    # A leaving subscription never opens, but it must still close with the
    # strategy's next close, which a reverse is.
    assert _halves(jobs, delivered[leaving_holder]) == "close"


# -- nothing fails silently ------------------------------------------------


async def test_a_close_nobody_holds_is_logged_and_settles_the_signal(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    await _subscriber(pg_session_factory, strategy_id)
    signal_id = await _closing(pg_session_factory, strategy_id)

    with caplog.at_level(logging.INFO):
        result = await _fan_out(pg_session_factory, signal_id)

    row = await _signal_row(pg_session_factory, signal_id)
    assert result.delivery_ids == ()
    assert result.refused is not None
    assert (row.status, row.outcome_reason) == ("REJECTED", "NO_POSITION_TO_CLOSE")
    assert row.decided_at is not None
    assert await _delivered_to(pg_session_factory, signal_id) == {}
    assert await _delivery_jobs(pg_session_factory) == {}
    traces = [
        record
        for record in caplog.records
        if record.levelno == logging.INFO and str(signal_id) in record.getMessage()
    ]
    assert len(traces) == 1
    assert "NO_POSITION_TO_CLOSE" in traces[0].getMessage()


async def test_an_opening_with_no_active_subscription_is_logged_and_settles_the_signal(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    await _subscriber(pg_session_factory, strategy_id, status="LEAVING", holds=True)
    signal_id = await _opening(pg_session_factory, strategy_id)

    with caplog.at_level(logging.INFO):
        await _fan_out(pg_session_factory, signal_id)

    row = await _signal_row(pg_session_factory, signal_id)
    assert (row.status, row.outcome_reason) == ("REJECTED", "NO_ACTIVE_SUBSCRIPTION")
    assert await _delivery_jobs(pg_session_factory) == {}
    assert any(
        record.levelno == logging.INFO
        and str(signal_id) in record.getMessage()
        and "NO_ACTIVE_SUBSCRIPTION" in record.getMessage()
        for record in caplog.records
    )


async def test_an_archived_strategys_signal_is_refused_as_today_and_reaches_nobody(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory, archived=True)
    await _subscriber(pg_session_factory, strategy_id)
    signal_id = await _opening(pg_session_factory, strategy_id)

    with caplog.at_level(logging.WARNING):
        result = await _fan_out(pg_session_factory, signal_id)

    row = await _signal_row(pg_session_factory, signal_id)
    assert (row.status, row.outcome_reason) == ("REJECTED", "STRATEGY_ARCHIVED")
    assert row.outcome_detail is not None
    assert "ARCHIVED strategy" in row.outcome_detail
    assert "remove its TradingView alert" in row.outcome_detail
    assert result.refused == row.outcome_detail
    assert await _delivered_to(pg_session_factory, signal_id) == {}
    assert await _delivery_jobs(pg_session_factory) == {}
    assert any(
        record.levelno == logging.WARNING and str(signal_id) in record.getMessage()
        for record in caplog.records
    )


# -- a subscription only takes signals received after it began -------------


@pytest.mark.parametrize("kind", ["opening", "closing", "reversing"])
async def test_a_subscription_created_after_the_signal_was_received_gets_nothing(
    pg_session_factory: Factory,  # noqa: F811
    kind: str,
) -> None:
    """A new subscriber gets the NEXT opening: not the signal that was already in
    flight when it subscribed, whether the job is retried or simply late. The late
    subscriber holds the symbol too, so only the date separates the two."""
    strategy_id = await seeds.strategy(pg_session_factory)
    _, early = await _subscriber(pg_session_factory, strategy_id, holds=True)
    _, late = await _subscriber(
        pg_session_factory, strategy_id, holds=True, created_at=_T0 + timedelta(hours=1)
    )
    build = {"opening": _opening, "closing": _closing, "reversing": _reversing}[kind]
    signal_id = await build(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    delivered = await _delivered_to(pg_session_factory, signal_id)
    jobs = await _delivery_jobs(pg_session_factory)
    assert set(delivered) == {early}
    assert late not in delivered
    assert list(jobs) == [f"delivery:{delivered[early]}"]


# -- what makes a reservation a hold ---------------------------------------


async def test_another_users_live_reservation_on_the_symbol_does_not_make_this_user_a_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    _, bystander = await _subscriber(pg_session_factory, strategy_id)
    stranger, _ = await seeds.user(pg_session_factory)
    opened = await _signal(
        pg_session_factory, strategy_id, position_size="1", minutes=0, symbol="STXUSDT_PERP"
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=uuid4(),
        strategy_id=strategy_id,
        signal_id=opened,
        status="PENDING",
        user_id=stranger,
    )
    signal_id = await _closing(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    delivered = await _delivered_to(pg_session_factory, signal_id)
    assert bystander not in delivered


async def test_a_live_reservation_of_another_strategy_does_not_make_a_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    other_strategy = await seeds.strategy(pg_session_factory)
    user_id, subscription = await _subscriber(pg_session_factory, strategy_id)
    opened = await _signal(
        pg_session_factory, other_strategy, position_size="1", minutes=0, symbol="STXUSDT_PERP"
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=uuid4(),
        strategy_id=other_strategy,
        signal_id=opened,
        status="PENDING",
        user_id=user_id,
    )
    signal_id = await _closing(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    assert subscription not in await _delivered_to(pg_session_factory, signal_id)


async def test_a_reservation_that_no_longer_holds_capital_does_not_make_a_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, subscription = await _subscriber(pg_session_factory, strategy_id)
    opened = await _signal(
        pg_session_factory, strategy_id, position_size="1", minutes=0, symbol="STXUSDT_PERP"
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=uuid4(),
        strategy_id=strategy_id,
        signal_id=opened,
        status="FILLED",
        user_id=user_id,
    )
    # The seed's delivery is left ACCEPTED; a filled reservation's delivery has run.
    async with pg_session_factory() as session:
        await session.execute(
            update(SignalDeliveryRow)
            .where(SignalDeliveryRow.signal_id == opened)
            .values(status="PROCESSED")
        )
        await session.commit()
    signal_id = await _closing(pg_session_factory, strategy_id)

    await _fan_out(pg_session_factory, signal_id)

    assert subscription not in await _delivered_to(pg_session_factory, signal_id)


# -- an opening still waiting for its delivery (PR C verifier, B1) ---------


async def _pending_delivery(
    factory: Factory,
    signal_id: UUID,
    user_id: UUID,
    subscription_id: UUID,
    *,
    status: str = "ACCEPTED",
    job_status: str | None = "PENDING",
) -> None:
    """A delivery of ``signal_id`` to the subscription, written raw, in ``status``,
    with its ``delivery.process`` job in ``job_status`` (``None``: no job at all)."""
    delivery_id = uuid4()
    async with factory() as session:
        session.add(
            SignalDeliveryRow(
                id=delivery_id,
                signal_id=signal_id,
                subscription_id=subscription_id,
                user_id=user_id,
                status=status,
            )
        )
        if job_status is not None:
            session.add(
                JobRow(
                    kind=JobKind.DELIVERY_PROCESS.value,
                    payload={"delivery_id": str(delivery_id), "halves": "open"},
                    dedupe_key=f"delivery:{delivery_id}",
                    status=job_status,
                )
            )
        await session.commit()


async def test_an_earlier_opening_still_waiting_for_its_delivery_makes_a_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The opening was fanned out but its delivery has not run, so the subscriber holds
    neither an allocation nor a reservation. That delivery's job was enqueued when the
    opening fanned out, ahead of the close's (the queue claims by ``run_after``), so the
    close goes to that subscription and runs after the opening."""
    strategy_id = await seeds.strategy(pg_session_factory)
    _, waiting = await _subscriber(pg_session_factory, strategy_id)
    _, flat = await _subscriber(
        pg_session_factory, strategy_id, created_at=_T0 + timedelta(seconds=90)
    )
    opening = await _signal(pg_session_factory, strategy_id, position_size="1", minutes=1)
    await _fan_out(pg_session_factory, opening)
    closing = await _signal(pg_session_factory, strategy_id, position_size="0", minutes=2)

    await _fan_out(pg_session_factory, closing)

    delivered = await _delivered_to(pg_session_factory, closing)
    assert set(delivered) == {waiting}
    assert flat not in delivered
    assert _halves(await _delivery_jobs(pg_session_factory), delivered[waiting]) == "close"


@pytest.mark.parametrize(
    ("case", "status", "position_size", "symbol", "minutes"),
    [
        # Minute 0, before the opening `_closing` writes at minute 1, so the close's
        # prior signal stays that opening; minute 3 is after the close at minute 2.
        ("its delivery already ran", "PROCESSED", "1", _ALERT, 0),
        ("its delivery was refused", "REJECTED", "1", _ALERT, 0),
        ("it was a close, not an opening", "ACCEPTED", "0", _ALERT, 0),
        ("it was on another symbol", "ACCEPTED", "1", "BTCUSDT.P", 0),
        ("it came after the close", "ACCEPTED", "1", _ALERT, 3),
    ],
)
async def test_a_pending_delivery_makes_no_holder_when(
    pg_session_factory: Factory,  # noqa: F811
    case: str,
    status: str,
    position_size: str,
    symbol: str,
    minutes: int,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, subscription_id = await _subscriber(pg_session_factory, strategy_id)
    other = await _signal(
        pg_session_factory,
        strategy_id,
        position_size=position_size,
        minutes=minutes,
        symbol=symbol,
    )
    await _pending_delivery(pg_session_factory, other, user_id, subscription_id, status=status)
    # The close itself follows an opening on STXUSDT that this user never got.
    signal_id = await _closing(pg_session_factory, strategy_id)

    result = await _fan_out(pg_session_factory, signal_id)

    assert subscription_id not in await _delivered_to(pg_session_factory, signal_id), case
    assert result.delivery_ids == ()


@pytest.mark.parametrize(
    ("case", "job_status"),
    [
        ("its job already finished", "DONE"),
        ("its job ran out of attempts", "FAILED"),
        # What 0032 leaves: a delivery copied from a signal that stayed ACCEPTED.
        ("it has no job at all", None),
    ],
)
async def test_a_pending_delivery_whose_job_will_never_run_makes_no_holder_when(
    pg_session_factory: Factory,  # noqa: F811
    case: str,
    job_status: str | None,
) -> None:
    """Only a job still to run puts the opening ahead of the close (PR C verifier,
    B1a). A delivery left pending with no live job never opens anything."""
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, subscription_id = await _subscriber(pg_session_factory, strategy_id)
    opening = await _signal(pg_session_factory, strategy_id, position_size="1", minutes=1)
    await _pending_delivery(
        pg_session_factory, opening, user_id, subscription_id, job_status=job_status
    )
    closing = await _signal(pg_session_factory, strategy_id, position_size="0", minutes=2)

    result = await _fan_out(pg_session_factory, closing)

    assert subscription_id not in await _delivered_to(pg_session_factory, closing), case
    assert result.delivery_ids == ()


async def test_a_pending_delivery_whose_job_is_being_worked_still_makes_a_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, subscription_id = await _subscriber(pg_session_factory, strategy_id)
    opening = await _signal(pg_session_factory, strategy_id, position_size="1", minutes=1)
    await _pending_delivery(
        pg_session_factory, opening, user_id, subscription_id, job_status="CLAIMED"
    )
    closing = await _signal(pg_session_factory, strategy_id, position_size="0", minutes=2)

    await _fan_out(pg_session_factory, closing)

    assert set(await _delivered_to(pg_session_factory, closing)) == {subscription_id}


async def test_another_subscriptions_pending_opening_does_not_make_this_one_a_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    _, mine = await _subscriber(pg_session_factory, strategy_id)
    theirs_user, theirs = await _subscriber(pg_session_factory, strategy_id)
    opening = await _signal(pg_session_factory, strategy_id, position_size="1", minutes=1)
    await _pending_delivery(pg_session_factory, opening, theirs_user, theirs)
    closing = await _signal(pg_session_factory, strategy_id, position_size="0", minutes=2)

    await _fan_out(pg_session_factory, closing)

    assert set(await _delivered_to(pg_session_factory, closing)) == {theirs}
    assert mine not in await _delivered_to(pg_session_factory, closing)
