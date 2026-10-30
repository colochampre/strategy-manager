"""A signal reaching two subscribers, end to end on real PostgreSQL (tasks.md C.6).

Real adapters from fan-out to settlement, built the way the worker builds them
(``main._build_fan_out_signal``, ``_build_process_delivery``,
``_build_settle_execution``). Only the venue is replaced: one ``FakeExchangeAdapter``
PER USER, which is what each subscriber's own key gives them in a live run (a
registry signed with another user's key would place on the other's account), and a
balance reader per user, reporting that user's own pool.

Since C.7 each delivery records its OWN outcome (``signal_deliveries``), so these
tests also assert it: two deliveries of one signal end independently, and the signal
itself stays ``ACCEPTED`` with its outcome columns empty, because the fan-out
delivered it. They read reservations, attempts, orders and the ledger besides, which
is what each delivery wrote for itself.

A symbol wears a different spelling on each side of a boundary: the alert says
``STXUSDT.P``, the venue and the ledger say ``STXUSDT``.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.ports import PoolBalanceReading
from strategy_manager.accounts.application.ports import PoolKey as AccountsPoolKey
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.application.ports import PlacedOrder
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.main import (
    _build_fan_out_signal,
    _build_process_delivery,
    _build_settle_execution,
)
from strategy_manager.reconciliation.infrastructure.venue_position_reader_registry import (
    VenuePositionReaderRegistry,
)
from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.signals.application.fan_out_signal import FanOutResult
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow, SignalRow
from strategy_manager.strategies.domain.strategy import AllocationPercent
from strategy_manager.subscriptions.application.change_share import ChangeShare
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow
from strategy_manager.subscriptions.infrastructure.repository import (
    SqlAlchemySubscriptionRepository,
)
from tests.execution.fakes import OneRegistry
from tests.owner import OWNER_ID, ensure_pool, seed_other_user, seed_snapshot
from tests.signals.fakes import in_both_modes
from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_signal_row,
    seed_strategy,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

MARKET = ("bybit", "usdt-m", "USDT")
ALERT = "STXUSDT.P"
ETH_ALERT = "ETHUSDT.P"
FILL_PRICE = Decimal("2")


class _Reader:
    """A venue that reports ``total`` free USDT in every pool it is asked about."""

    def __init__(self, total: Decimal) -> None:
        self._total = total

    async def read(self, pools: Sequence[AccountsPoolKey]) -> list[PoolBalanceReading]:
        now = datetime.now(UTC)
        return [
            PoolBalanceReading(
                exchange=pool[0],
                venue=pool[1],
                settlement_currency=pool[2],
                total=self._total,
                available=self._total,
                observed_at=now,
            )
            for pool in pools
        ]


class _Fake(FakeExchangeAdapter):
    """Remembers every order it was handed, so a test can say whose venue it was."""

    def __init__(self) -> None:
        super().__init__(exchange="bybit", fill_price=FILL_PRICE, fee_rate=Decimal("0"))
        self.orders: list[PlaceableOrder] = []

    async def place(self, order: PlaceableOrder) -> PlacedOrder:
        self.orders.append(order)
        return await super().place(order)


@dataclass
class World:
    factory: Factory
    strategy_id: UUID
    author: UUID
    other: UUID
    author_subscription: UUID
    other_subscription: UUID
    venues: dict[UUID, _Fake]
    totals: dict[UUID, Decimal]
    #: When this test's signals start, half an hour before the test began. Taken per
    #: test, never at import: a reverse's open is abandoned once its signal is older
    #: than ``delayed_open_max_signal_age_seconds`` (600 s), so a time taken at
    #: collection failed that test whenever a full run reached it 9 minutes later.
    t0: datetime


async def _world(factory: Factory, *, author_share: str = "50", other_share: str = "25") -> World:
    t0 = datetime.now(UTC) - timedelta(minutes=30)
    subscribed_before = t0 - timedelta(days=1)
    async with factory() as session:
        other = await seed_other_user(session)
        author_pool = await ensure_pool(session, MARKET, user_id=OWNER_ID)
        other_pool = await ensure_pool(session, MARKET, user_id=other)
        for user, total in ((OWNER_ID, "1000"), (other, "400")):
            await seed_snapshot(
                session,
                MARKET,
                total=Decimal(total),
                available=Decimal(total),
                observed_at=datetime.now(UTC) - timedelta(minutes=1),
                user_id=user,
            )
        await session.commit()
    strategy_id = uuid4()
    await seed_strategy(
        factory,
        strategy_id=strategy_id,
        allowed_pairs=frozenset({"STXUSDT", "ETHUSDT"}),
    )
    author_subscription = await seeds.subscription(
        factory,
        OWNER_ID,
        strategy_id,
        author_pool,
        share=author_share,
        created_at=subscribed_before,
    )
    other_subscription = await seeds.subscription(
        factory, other, strategy_id, other_pool, share=other_share, created_at=subscribed_before
    )
    return World(
        factory,
        strategy_id,
        OWNER_ID,
        other,
        author_subscription,
        other_subscription,
        venues={OWNER_ID: _Fake(), other: _Fake()},
        totals={OWNER_ID: Decimal("1000"), other: Decimal("400")},
        t0=t0,
    )


async def _signal(
    world: World, *, position_size: str, minutes: int, symbol: str = ALERT
) -> UUID:
    signal_id = uuid4()
    await seed_signal_row(
        world.factory,
        signal_id=signal_id,
        strategy_id=world.strategy_id,
        idempotency_key=f"key-{signal_id}",
        symbol=symbol,
        position_size=Decimal(position_size),
        received_at=world.t0 + timedelta(minutes=minutes),
    )
    return signal_id


async def _fan_out(world: World, signal_id: UUID) -> FanOutResult:
    async with world.factory() as session:
        return await _build_fan_out_signal(session, get_settings()).run(signal_id)


async def _queued(world: World, signal_id: UUID) -> dict[UUID, tuple[UUID, str]]:
    """The ``delivery.process`` jobs of this signal: ``user -> (delivery, halves)``."""
    async with world.factory() as session:
        deliveries = {
            row.id: row.user_id
            for row in (
                await session.execute(
                    select(SignalDeliveryRow).where(SignalDeliveryRow.signal_id == signal_id)
                )
            )
            .scalars()
            .all()
        }
        jobs = (
            (await session.execute(select(JobRow).where(JobRow.kind == "delivery.process")))
            .scalars()
            .all()
        )
    queued: dict[UUID, tuple[UUID, str]] = {}
    for job in jobs:
        delivery_id = UUID(str(job.payload["delivery_id"]))
        if delivery_id in deliveries:
            queued[deliveries[delivery_id]] = (delivery_id, str(job.payload["halves"]))
    return queued


async def _work(world: World, user: UUID, delivery_id: UUID, halves: object) -> None:
    """One ``delivery.process`` job as the worker runs it, with ``user``'s venue."""
    pools = {
        (member, MARKET): PoolConfig(
            exchange=Exchange("bybit"),
            venue=Venue("usdt-m"),
            settlement_currency=Currency("USDT"),
            user_id=member,
            min_order_size=Decimal("1"),
        )
        for member in world.venues
    }
    async with world.factory() as session:
        handler, _ = _build_process_delivery(
            session,
            pools,
            get_settings(),
            VenueExchangeRegistry([world.venues[user]]),
            OneRegistry(VenueExchangeRegistry([world.venues[user]])),
            in_both_modes(frozenset({("bybit", "usdt-m")})),
            _Reader(world.totals[user]),  # type: ignore[arg-type]
            VenuePositionReaderRegistry([]),
        )
        await handler.handle(delivery_id, halves)
        await session.commit()


async def _settle_all(world: World) -> None:
    """Settles every SUBMITTED attempt, each as the user it belongs to."""
    async with world.factory() as session:
        attempts = (
            (
                await session.execute(
                    select(ExecutionAttemptRow).where(ExecutionAttemptRow.status == "SUBMITTED")
                )
            )
            .scalars()
            .all()
        )
    for attempt in attempts:
        async with world.factory() as session:
            settle = _build_settle_execution(
                session, VenueExchangeRegistry([world.venues[attempt.user_id]])
            )
            await settle.settle(attempt.user_id, attempt.id)


async def _run(world: World, signal_id: UUID) -> dict[UUID, tuple[UUID, str]]:
    """Fan the signal out and work every delivery it made, then settle the orders."""
    await _fan_out(world, signal_id)
    queued = await _queued(world, signal_id)
    for user, (delivery_id, halves) in queued.items():
        await _work(world, user, delivery_id, halves)
    await _settle_all(world)
    return queued


async def _reservations(world: World, signal_id: UUID) -> dict[UUID, ReservationRow]:
    async with world.factory() as session:
        rows = (
            (
                await session.execute(
                    select(ReservationRow).where(ReservationRow.signal_id == signal_id)
                )
            )
            .scalars()
            .all()
        )
    return {row.user_id: row for row in rows}


async def _attempts(world: World, user: UUID) -> list[ExecutionAttemptRow]:
    async with world.factory() as session:
        return list(
            (
                await session.execute(
                    select(ExecutionAttemptRow)
                    .where(ExecutionAttemptRow.user_id == user)
                    .order_by(ExecutionAttemptRow.created_at, ExecutionAttemptRow.id)
                )
            )
            .scalars()
            .all()
        )


async def _outcome(world: World, delivery_id: UUID) -> tuple[str, str | None]:
    """A delivery's ``(status, outcome_reason)``."""
    async with world.factory() as session:
        row = await session.get(SignalDeliveryRow, delivery_id)
        assert row is not None
        return row.status, row.outcome_reason


async def _signal_outcome(world: World, signal_id: UUID) -> tuple[str, str | None, object]:
    """The signal's OWN ``(status, outcome_reason, decided_at)``."""
    async with world.factory() as session:
        row = await session.get(SignalRow, signal_id)
        assert row is not None
        return row.status, row.outcome_reason, row.decided_at


async def _subscription(world: World, subscription_id: UUID) -> SubscriptionRow:
    async with world.factory() as session:
        row = await session.get(SubscriptionRow, subscription_id)
        assert row is not None
        return row


async def _held(world: World, user: UUID, symbol: str = "STXUSDT") -> Decimal:
    """The user's net base holding of ``symbol``. The fake venue reports a fill under
    the spelling of the order (the alert's ``.P``), a live one under the bare name,
    so both are read."""
    async with world.factory() as session:
        rows = (
            await session.execute(
                select(LedgerEntryRow.side, LedgerEntryRow.quantity).where(
                    LedgerEntryRow.user_id == user,
                    LedgerEntryRow.symbol.in_([symbol, f"{symbol}.P"]),
                )
            )
        ).all()
    return sum(
        (qty if side == "BUY" else -qty for side, qty in rows),
        Decimal("0"),
    )


# --- two subscribers, one signal -----------------------------------------------------


async def test_two_subscribers_are_each_sized_from_their_own_pool_and_share_and_placed_apart(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    signal_id = await _signal(world, position_size="1", minutes=1)

    queued = await _run(world, signal_id)

    assert {user: halves for user, (_, halves) in queued.items()} == {
        world.author: "open",
        world.other: "open",
    }
    reservations = await _reservations(world, signal_id)
    assert set(reservations) == {world.author, world.other}
    # 50% of the author's 1000, and 25% of the other user's 400.
    assert reservations[world.author].amount == Decimal("500")
    assert reservations[world.other].amount == Decimal("100")
    assert reservations[world.author].delivery_id == queued[world.author][0]
    assert reservations[world.other].delivery_id == queued[world.other][0]
    assert reservations[world.author].pool_id != reservations[world.other].pool_id
    # Each is placed on its OWN venue, once, with its own size: the granted margin
    # at the fake's leverage of 1 over the alert's price of 1 (the fill itself is at 2).
    assert len(world.venues[world.author].orders) == 1
    assert len(world.venues[world.other].orders) == 1
    assert await _held(world, world.author) == Decimal("500")
    assert await _held(world, world.other) == Decimal("100")
    for user in (world.author, world.other):
        (attempt,) = await _attempts(world, user)
        assert attempt.reservation_id == reservations[user].id
        assert attempt.status == "FILLED"
        # C.7: each delivery ended on its own row, and the attempt names it.
        assert attempt.delivery_id == queued[user][0]
        assert await _outcome(world, queued[user][0]) == ("PROCESSED", None)
    # The signal itself stays ACCEPTED: it was delivered, and nothing decided it.
    assert await _signal_outcome(world, signal_id) == ("ACCEPTED", None, None)


async def test_a_close_works_only_that_subscribers_reservation(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    opening = await _signal(world, position_size="1", minutes=1)
    await _run(world, opening)
    reservations = await _reservations(world, opening)
    closing = await _signal(world, position_size="0", minutes=2)

    queued = await _run(world, closing)

    assert {user: halves for user, (_, halves) in queued.items()} == {
        world.author: "close",
        world.other: "close",
    }
    for user in (world.author, world.other):
        opens, closes = await _attempts_by_kind(world, user)
        assert len(opens) == 1 and len(closes) == 1
        # Each close unwinds its OWN subscriber's allocation, never the other's.
        assert closes[0].closes_allocation_id == reservations[user].id
        assert closes[0].user_id == user
    # And both end flat, each by its own size.
    assert await _held(world, world.author) == Decimal("0")
    assert await _held(world, world.other) == Decimal("0")
    assert len(world.venues[world.author].orders) == 2
    assert len(world.venues[world.other].orders) == 2
    # C.7: both closing deliveries ended PROCESSED, each on its own row.
    for user, (delivery_id, _) in queued.items():
        assert await _outcome(world, delivery_id) == ("PROCESSED", None), user
    assert await _signal_outcome(world, closing) == ("ACCEPTED", None, None)


async def _attempts_by_kind(
    world: World, user: UUID
) -> tuple[list[ExecutionAttemptRow], list[ExecutionAttemptRow]]:
    attempts = await _attempts(world, user)
    return (
        [a for a in attempts if a.closes_allocation_id is None],
        [a for a in attempts if a.closes_allocation_id is not None],
    )


async def test_a_subscription_with_no_prior_reservation_is_told_there_is_nothing_to_close(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fan-out only delivers a close to a holder, so the refusal is reached by a
    delivery that names a subscription which never opened: it must not close the
    other subscriber's allocation in its place."""
    world = await _world(pg_session_factory)
    opening = await _signal(world, position_size="1", minutes=1)
    await _run(world, opening)
    # Subscribed AFTER the opening was received: it never opened.
    async with world.factory() as session:
        stranger = await seed_other_user(session)
        stranger_pool = await ensure_pool(session, MARKET, user_id=stranger)
        await session.commit()
    stranger_subscription = await seeds.subscription(
        world.factory,
        stranger,
        world.strategy_id,
        stranger_pool,
        created_at=world.t0 + timedelta(seconds=90),
    )
    world.venues[stranger] = _Fake()
    world.totals[stranger] = Decimal("100")
    closing = await _signal(world, position_size="0", minutes=2)
    await _fan_out(world, closing)
    queued = await _queued(world, closing)
    async with world.factory() as session:
        stranger_delivery = uuid4()
        session.add(
            SignalDeliveryRow(
                id=stranger_delivery,
                signal_id=closing,
                subscription_id=stranger_subscription,
                user_id=stranger,
            )
        )
        await session.commit()
    caplog.set_level(logging.WARNING, logger="strategy_manager.signals.application.process_signal")

    for user, (delivery_id, halves) in queued.items():
        await _work(world, user, delivery_id, halves)
    await _work(world, stranger, stranger_delivery, "close")

    assert await _attempts(world, stranger) == []
    assert world.venues[stranger].orders == []
    warnings = [
        r.getMessage() for r in caplog.records if "holds no position to close" in r.getMessage()
    ]
    assert len(warnings) == 1
    # The two holders still closed their own.
    for user in (world.author, world.other):
        _, closes = await _attempts_by_kind(world, user)
        assert len(closes) == 1
    # C.7: one signal, three deliveries, three independent outcomes. The stranger's
    # terminal refusal is its own; the holders' closes are placed (PROCESSING until
    # settle, which this test does not run) and are not dragged down by it.
    assert await _outcome(world, stranger_delivery) == ("REJECTED", "NO_POSITION_TO_CLOSE")
    for delivery_id, _ in queued.values():
        assert await _outcome(world, delivery_id) == ("PROCESSING", None)


# --- a reverse, two subscribers (tasks.md C.8) ---------------------------------------


async def _continue(world: World, done: set[UUID]) -> list[UUID]:
    """Runs every ``signal.open_after_close`` job not yet run, as the worker would: one
    poll per job, in the DELIVERY's user's session. A re-deferred poll enqueues a new
    job, so the caller loops until none is left. Returns the deliveries it continued."""
    async with world.factory() as session:
        jobs = (
            (
                await session.execute(
                    select(JobRow)
                    .where(JobRow.kind == "signal.open_after_close")
                    .order_by(JobRow.created_at, JobRow.id)
                )
            )
            .scalars()
            .all()
        )
    pools = {
        (member, MARKET): PoolConfig(
            exchange=Exchange("bybit"),
            venue=Venue("usdt-m"),
            settlement_currency=Currency("USDT"),
            user_id=member,
            min_order_size=Decimal("1"),
        )
        for member in world.venues
    }
    continued: list[UUID] = []
    for job in jobs:
        if job.id in done:
            continue
        done.add(job.id)
        delivery_id = UUID(str(job.payload["delivery_id"]))
        async with world.factory() as session:
            owner = (
                await session.execute(
                    select(SignalDeliveryRow.user_id).where(SignalDeliveryRow.id == delivery_id)
                )
            ).scalar_one()
            _, open_after_close = _build_process_delivery(
                session,
                pools,
                get_settings(),
                VenueExchangeRegistry([world.venues[owner]]),
                OneRegistry(VenueExchangeRegistry([world.venues[owner]])),
                in_both_modes(frozenset({("bybit", "usdt-m")})),
                _Reader(world.totals[owner]),  # type: ignore[arg-type]
                VenuePositionReaderRegistry([]),
            )
            await open_after_close.poll(
                ClaimedJob(
                    id=job.id,
                    kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
                    payload=job.payload,
                    attempts=1,
                    max_attempts=5,
                ),
                owner,
            )
            await session.commit()
        continued.append(delivery_id)
    return continued


async def test_a_reverse_closes_and_then_opens_for_each_subscriber_in_their_own_pool(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two users both hold the strategy's long. The flip to short is worked per
    delivery: each closes ITS OWN allocation, and the continuation that follows is
    keyed by that delivery, so each then opens its own short, in its own pool, at its
    own share, on its own venue. A continuation keyed by the signal would run once, for
    the author, and the other subscriber would end flat."""
    world = await _world(pg_session_factory)
    opening = await _signal(world, position_size="1", minutes=1)
    await _run(world, opening)
    held_by = await _reservations(world, opening)
    # Recent: the continuation abandons a signal older than ten minutes.
    reverse = await _signal(world, position_size="-1", minutes=29)
    caplog.set_level(logging.ERROR)

    await _fan_out(world, reverse)
    queued = await _queued(world, reverse)
    assert {user: halves for user, (_, halves) in queued.items()} == {
        world.author: "close_and_open",
        world.other: "close_and_open",
    }
    for user, (delivery_id, halves) in queued.items():
        await _work(world, user, delivery_id, halves)

    # One continuation PER DELIVERY, named by it and by nothing else.
    async with world.factory() as session:
        seeded = (
            (await session.execute(select(JobRow).where(JobRow.kind == "signal.open_after_close")))
            .scalars()
            .all()
        )
    assert {job.dedupe_key for job in seeded} == {
        f"signal.open_after_close:{delivery_id}:0" for delivery_id, _ in queued.values()
    }
    for job in seeded:
        assert set(job.payload) == {"delivery_id", "awaited_allocation_ids", "poll"}
    # Each close unwound its OWN subscriber's allocation.
    for user in (world.author, world.other):
        _, closes = await _attempts_by_kind(world, user)
        assert [c.closes_allocation_id for c in closes] == [held_by[user].id]
        assert [c.delivery_id for c in closes] == [queued[user][0]]

    await _settle_all(world)
    assert await _held(world, world.author) == Decimal("0")
    assert await _held(world, world.other) == Decimal("0")

    done: set[UUID] = set()
    continued = await _continue(world, done)
    await _settle_all(world)

    assert sorted(continued) == sorted(delivery_id for delivery_id, _ in queued.values())
    reservations = await _reservations(world, reverse)
    assert set(reservations) == {world.author, world.other}
    # 50% of the author's 1000 and 25% of the other user's 400, each in their own pool.
    assert reservations[world.author].amount == Decimal("500")
    assert reservations[world.other].amount == Decimal("100")
    assert reservations[world.author].pool_id == held_by[world.author].pool_id
    assert reservations[world.other].pool_id == held_by[world.other].pool_id
    assert reservations[world.author].pool_id != reservations[world.other].pool_id
    for user in (world.author, world.other):
        assert reservations[user].delivery_id == queued[user][0]
        opens, closes = await _attempts_by_kind(world, user)
        # The first opening, then the reverse's short: the close is the third order.
        assert len(opens) == 2 and len(closes) == 1
        short = opens[-1]
        assert short.reservation_id == reservations[user].id
        assert short.side == "SELL"
        assert short.user_id == user
        assert short.delivery_id == queued[user][0]
        assert short.signal_id == reverse
        assert short.status == "FILLED"
        assert len(world.venues[user].orders) == 3
        assert await _outcome(world, queued[user][0]) == ("PROCESSED", None)
    # Short by what each was granted, at the alert's price of 1.
    assert await _held(world, world.author) == Decimal("-500")
    assert await _held(world, world.other) == Decimal("-100")
    assert await _signal_outcome(world, reverse) == ("ACCEPTED", None, None)
    # Nothing was dropped on the way: no seed conflict, no abandonment.
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


# --- a subscription that left ---------------------------------------------------------


async def _leave(world: World, subscription_id: UUID) -> None:
    async with world.factory() as session:
        await session.execute(
            text("UPDATE subscriptions SET status = 'LEAVING', left_at = now() WHERE id = :id"),
            {"id": subscription_id},
        )
        await session.commit()


async def test_a_leaving_subscription_ends_when_its_last_allocation_closes(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _run(world, await _signal(world, position_size="1", minutes=1))
    await _leave(world, world.other_subscription)

    queued = await _run(world, await _signal(world, position_size="0", minutes=2))

    # A LEAVING holder still gets the close.
    assert queued[world.other][1] == "close"
    left = await _subscription(world, world.other_subscription)
    assert left.status == "ENDED"
    assert left.ended_at is not None
    assert left.left_at is not None
    # The author's subscription is untouched: it was never leaving.
    assert (await _subscription(world, world.author_subscription)).status == "ACTIVE"


async def test_a_leaving_subscription_stays_leaving_while_another_allocation_is_open(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _run(world, await _signal(world, position_size="1", minutes=1))
    await _run(world, await _signal(world, position_size="1", minutes=2, symbol=ETH_ALERT))
    await _leave(world, world.other_subscription)

    await _run(world, await _signal(world, position_size="0", minutes=3))
    first = await _subscription(world, world.other_subscription)

    assert await _held(world, world.other) == Decimal("0")
    assert await _held(world, world.other, "ETHUSDT") > Decimal("0")
    assert first.status == "LEAVING"
    assert first.ended_at is None

    await _run(world, await _signal(world, position_size="0", minutes=4, symbol=ETH_ALERT))
    last = await _subscription(world, world.other_subscription)
    assert last.status == "ENDED"
    assert last.ended_at is not None


# --- a share change (re-homed from C.4b onto ChangeShare) -----------------------------


async def test_a_share_change_leaves_a_held_reservation_alone_and_sizes_the_next_opening(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The reservation already held keeps the amount it was granted; only the NEXT
    opening is sized at the new share (the subscription's, 10% of 1000)."""
    world = await _world(pg_session_factory)
    first = await _signal(world, position_size="1", minutes=1)
    await _run(world, first)
    before = (await _reservations(world, first))[world.author]
    assert before.amount == Decimal("500")

    async with world.factory() as session:
        await ChangeShare(SqlAlchemySubscriptionRepository(session), commit=session).change(
            world.author, world.author_subscription, AllocationPercent(Decimal("10"))
        )

    after = (await _reservations(world, first))[world.author]
    assert (after.amount, after.status, after.delivery_id) == (
        before.amount,
        before.status,
        before.delivery_id,
    )
    await _run(world, await _signal(world, position_size="0", minutes=2))
    second = await _signal(world, position_size="1", minutes=3)
    await _run(world, second)
    assert (await _reservations(world, second))[world.author].amount == Decimal("100")
