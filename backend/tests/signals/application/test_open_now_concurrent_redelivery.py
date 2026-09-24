"""``ProcessSignalHandler.open_now`` under GENUINE concurrent redelivery
(design.md § S5, "Dedup"; spec: job-queue § Continuation Idempotency --
"Retrying or re-running a continuation MUST NEVER submit more than one open
for the same signal, and a crash between committing a poll and acknowledging
its job MUST NOT fork the continuation into two").

``open_now``'s dedup reads ``SignalContext.own_reservation_id`` and returns
early when it is set. That is a check-then-act: two deliveries of the SAME
continuation job can both read ``None`` before either has committed a
reservation, and the early return protects neither. Every existing test
drives that path SEQUENTIALLY -- the second call always runs after the
first committed -- so it exercises the branch and proves nothing about the
race. These tests run two handlers on two separate sessions through
``asyncio.gather`` and pin the exact interleaving the branch cannot see.

**The race window is pinned, not hoped for.** ``RaceSyncedReservations``
wraps the repository ``AllocateCapital`` reads its own dedup from and holds
both callers at an ``asyncio.Barrier`` immediately after that read returns,
asserting both observed ``None``. Without it the interleaving is a coin
toss: whichever call reached the guard second would see the winner's
PENDING reservation as in-flight work and defer, which is a different
(already-tested) branch.

**Binding testing lesson**: a symbol has three spellings (TradingView
``STXUSDT.P``, venue bare ``STXUSDT``, Pionex ``STXUSDT_PERP``). Every
boundary this test matches a symbol across uses a different one: the prior
signal is recorded as ``STXUSDT``, the settled ledger holding that must net
to zero as ``STXUSDT.P``, and the racing signal as ``STXUSDT_PERP``.

No credential and no network: DRY_RUN's ``FakeExchangeAdapter`` is the only
venue here.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.application.ports import PoolBalanceReading
from strategy_manager.accounts.application.ports import PoolKey as AccountsPoolKey
from strategy_manager.accounts.application.refresh_pool_balance import RefreshPoolBalance
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.balance_snapshot_repository import (
    SqlAlchemyBalanceSnapshotRepository,
)
from strategy_manager.accounts.infrastructure.db_balance_source import (
    DbBalanceSnapshotAge,
    DbBalanceSource,
)
from strategy_manager.accounts.infrastructure.models import PoolBalanceSnapshotRow
from strategy_manager.allocation.application.allocate_capital import AllocateCapital
from strategy_manager.allocation.domain.pool_key import PoolKey as AllocationPoolKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.execution.application.close_position import CloseCommand
from strategy_manager.execution.application.place_order import PlaceOrder
from strategy_manager.execution.application.ports import FillRecord, PlacedOrder
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.signals.application.holding_guard import HoldingGuard
from strategy_manager.signals.application.process_signal import (
    ProcessSignalHandler,
    ProcessSignalResult,
)
from strategy_manager.signals.infrastructure.in_flight_work import InFlightWorkAdapter
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.signals.infrastructure.signal_context import SignalContextAdapter
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.signals.infrastructure.conftest import seed_strategy

pytestmark = pytest.mark.integration

POOL: AccountsPoolKey = ("bybit", "usdt-m", "USDT")
START = datetime.now(UTC)
# 40% of a 100 USDT pool, so the LOSER of the race still finds 60 available
# and reaches ``reservations.insert`` -- the point where the UNIQUE
# constraint on ``signal_id`` is the last thing standing. At 100% the loser
# would be turned away by ``decide()`` for want of availability and the
# constraint would never be exercised at all.
POOL_BALANCE = Decimal("100")
ALLOCATION_PERCENT = Decimal("40")
EXPECTED_GRANT = Decimal("40")
# Long enough that neither racer's reservation expires mid-test.
RESERVATION_TTL_SECONDS = 300
RACE_TIMEOUT_SECONDS = 30.0


class FixedClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


@dataclass
class FixedBalanceReader:
    """A DRY_RUN stand-in for the venue's wallet read: no credential, no
    network, one constant answer for the one pool under test."""

    pool: AccountsPoolKey
    amount: Decimal
    clock: FixedClock

    async def read(self, pools: "list[AccountsPoolKey]") -> list[PoolBalanceReading]:
        return [
            PoolBalanceReading(
                exchange=pool[0],
                venue=pool[1],
                settlement_currency=pool[2],
                total=self.amount,
                available=self.amount,
                observed_at=self.clock.now(),
            )
            for pool in pools
            if pool == self.pool
        ]


class CountingFakeExchange(FakeExchangeAdapter):
    """``FakeExchangeAdapter`` that counts what actually reached the venue.

    The DB row count is the authoritative assertion, but an order the venue
    accepted and no row recorded would be the worse failure of the two, so
    both are checked."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.placed_orders: list[PlaceableOrder] = []

    async def place(self, order: PlaceableOrder) -> PlacedOrder:
        self.placed_orders.append(order)
        return await super().place(order)


class RaceSyncedReservations:
    """Delegates to the real repository, but holds the FIRST
    ``find_by_signal_id`` of each racer at a shared barrier.

    ``AllocateCapital`` calls that method once, before it takes the pool's
    advisory lock, as its own retry-resume dedup. Releasing both racers from
    there means both provably observed "no reservation for this signal" and
    both are about to allocate -- the exact window ``open_now``'s
    ``own_reservation_id`` check cannot see. Everything after the barrier is
    the production code's own serialization (``pg_advisory_xact_lock``) doing
    whatever it really does."""

    def __init__(
        self,
        inner: SqlAlchemyReservationRepository,
        barrier: asyncio.Barrier,
        observed: "list[Reservation | None]",
    ) -> None:
        self._inner = inner
        self._barrier = barrier
        self._observed = observed
        self._synced = False

    async def find_by_signal_id(self, signal_id: UUID) -> Reservation | None:
        found = await self._inner.find_by_signal_id(signal_id)
        if not self._synced:
            self._synced = True
            self._observed.append(found)
            await self._barrier.wait()
        return found

    async def sum_active(
        self, exchange: str, venue: str, settlement_currency: str, now: datetime
    ) -> Decimal:
        return await self._inner.sum_active(exchange, venue, settlement_currency, now)

    async def insert(self, reservation: Reservation) -> None:
        await self._inner.insert(reservation)

    async def mark(
        self, reservation_id: UUID, status: ReservationStatus, at: datetime
    ) -> None:
        await self._inner.mark(reservation_id, status, at)


class NeverCalledVenueNetPosition:
    async def net_position(self, pool: object, symbol: str) -> Decimal | None:
        raise AssertionError(
            "the divergent branch must never run -- the settled holding nets to zero"
        )


class NeverCalledClosePosition:
    async def close(self, command: CloseCommand) -> object:
        raise AssertionError("open_now must never route through the RELEASES branch")


class RecordingSeeder:
    """Records instead of refusing: if the loser of the race DEFERS rather
    than allocating, that is a legitimate (already-tested) branch and the
    test must be able to say so rather than blow up inside the handler."""

    def __init__(self) -> None:
        self.seeds: list[tuple[UUID, list[UUID], int]] = []

    async def seed(
        self,
        signal_id: UUID,
        awaited_allocation_ids: list[UUID],
        poll: int = 0,
        *,
        replay_expected: bool = False,
    ) -> bool:
        self.seeds.append((signal_id, awaited_allocation_ids, poll))
        return True


class NeverCalledCloseOrphans:
    async def close(
        self,
        signal_id: UUID,
        pool: object,
        strategy_id: UUID,
        symbol: str,
        holdings: object,
        next_poll: int = 0,
    ) -> None:
        raise AssertionError("there is no orphan here -- the prior holding nets to zero")


async def _seed_signal(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    signal_id: UUID,
    strategy_id: UUID,
    symbol: str,
    price: Decimal,
    position_size: Decimal,
    received_at: datetime,
) -> None:
    """Raw insert with an EXPLICIT ``received_at``: ``insert_or_get`` always
    lets the server default decide it, which this test's own timeline needs
    to control (the guard bounds a delayed open by signal age)."""
    async with session_factory() as session:
        await session.execute(
            insert(SignalRow).values(
                id=signal_id,
                strategy_id=strategy_id,
                idempotency_key=f"k-{signal_id}",
                raw_payload={},
                action="buy",
                contracts=position_size,
                position_size=position_size,
                price=price,
                symbol=symbol,
                signal_type=str(strategy_id),
                received_at=received_at,
            )
        )
        await session.commit()


async def _seed_settled_flat_holding(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    prior_signal_id: UUID,
) -> None:
    """A position this strategy opened and closed, recorded under the
    ``STXUSDT.P`` spelling while the racing signal arrives as
    ``STXUSDT_PERP``.

    It nets to zero, so ``HoldingGuard`` proceeds -- but only because the
    ledger query genuinely merged the two spellings and then summed them.
    An empty ledger would reach the same verdict while proving nothing."""
    allocation_id, opening_id, closing_id = uuid4(), uuid4(), uuid4()

    async with session_factory() as session:
        await SqlAlchemyReservationRepository(session).insert(
            Reservation(
                id=allocation_id,
                strategy_id=strategy_id,
                signal_id=prior_signal_id,
                pool_key=AllocationPoolKey(
                    exchange=Exchange("bybit"),
                    venue=Venue("usdt-m"),
                    settlement_currency=Currency("USDT"),
                ),
                amount=Decimal("10"),
                # FILLED, and the attempts below are FILLED too, so nothing
                # reads as in flight -- the deferral branch is not what this
                # test is about.
                status=ReservationStatus.FILLED,
                expires_at=START - timedelta(minutes=30),
            )
        )
        await session.commit()

    async with session_factory() as session:
        attempts = SqlAlchemyExecutionAttemptRepository(session)
        for attempt_id, side, reservation_id, closes in (
            (opening_id, OrderSide.BUY, allocation_id, None),
            (closing_id, OrderSide.SELL, None, allocation_id),
        ):
            await attempts.insert(
                ExecutionAttempt(
                    id=attempt_id,
                    reservation_id=reservation_id,
                    closes_allocation_id=closes,
                    exchange="bybit",
                    venue="usdt-m",
                    settlement_currency="USDT",
                    symbol="STXUSDT.P",
                    side=side,
                    quantity=Decimal("5"),
                    quote_amount=None,
                    leverage=Decimal("1"),
                    status=ExecutionStatus.FILLED,
                    origin=ExecutionOrigin.SYSTEM,
                    client_order_id=f"prior-{attempt_id}",
                )
            )
        await session.commit()

    async with session_factory() as session:
        record = RecordFill(SqlAlchemyLedgerRepository(session))
        for attempt_id, side in ((opening_id, "BUY"), (closing_id, "SELL")):
            await record.record(
                FillRecord(
                    strategy_id=strategy_id,
                    allocation_id=allocation_id,
                    execution_attempt_id=attempt_id,
                    exchange="bybit",
                    venue="usdt-m",
                    settlement_currency="USDT",
                    symbol="STXUSDT.P",
                    side=side,
                    quantity=Decimal("5"),
                    price=Decimal("2"),
                    fee=Decimal("0"),
                    fee_currency="USDT",
                    notional=Decimal("10"),
                    exchange_order_id=f"prior-order-{attempt_id}",
                    exchange_fill_id=f"prior-fill-{attempt_id}",
                    filled_at=START - timedelta(minutes=30),
                    usd_rate_at_fill=Decimal("1"),
                )
            )
        await session.commit()


def _build_handler(
    session: AsyncSession,
    *,
    registry: VenueExchangeRegistry,
    clock: FixedClock,
    balance_reader: FixedBalanceReader,
    pools_by_key: dict[AccountsPoolKey, PoolConfig],
    reservations: SqlAlchemyReservationRepository | RaceSyncedReservations,
    seeder: RecordingSeeder,
) -> ProcessSignalHandler:
    """One whole production handler bound to ONE session -- the unit a worker
    process builds per claimed job, and therefore the unit two workers would
    each have their own of."""
    strategy_repository = SqlAlchemyStrategyRepository(session)
    signal_repository = SqlAlchemySignalRepository(session)
    own_reservations = SqlAlchemyReservationRepository(session)
    attempts_repository = SqlAlchemyExecutionAttemptRepository(session)

    return ProcessSignalHandler(
        signal_context=SignalContextAdapter(
            signals=signal_repository,
            strategies=strategy_repository,
            reservations=own_reservations,
        ),
        strategy_policy=StrategyPolicyAdapter(strategy_repository),
        pool_balance=PoolBalanceAdapter(
            pools_by_key, DbBalanceSource(session, clock, max_age_seconds=999_999.0)
        ),
        holding_guard=HoldingGuard(
            holdings=ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
            in_flight_work=InFlightWorkAdapter(
                attempts=attempts_repository, reservations=own_reservations
            ),
            venue_net_position=NeverCalledVenueNetPosition(),  # type: ignore[arg-type]
            clock=clock,
            delayed_open_max_signal_age_seconds=600.0,
        ),
        balance_refresh=RefreshPoolBalance(
            reader=balance_reader,  # type: ignore[arg-type]
            snapshots=SqlAlchemyBalanceSnapshotRepository(session),
            age=DbBalanceSnapshotAge(session, clock),
            commit=session,
            timeout_seconds=3.0,
            fallback_max_age_seconds=90.0,
        ),
        allocate_capital=AllocateCapital(
            strategy_policy=StrategyPolicyAdapter(strategy_repository),
            pool_balance=PoolBalanceAdapter(
                pools_by_key, DbBalanceSource(session, clock, max_age_seconds=999_999.0)
            ),
            lock=PgAdvisoryLockAdapter(session),
            reservations=reservations,  # type: ignore[arg-type]
            commit=session,
            clock=clock,
            reservation_ttl_seconds=RESERVATION_TTL_SECONDS,
        ),
        place_order=PlaceOrder(
            reservations=ReservationGatewayAdapter(own_reservations),
            exchanges=registry,
            attempts=attempts_repository,
            queue=_NullQueue(),  # type: ignore[arg-type]
            clock=clock,
            commit=session,
            settle_delay_seconds=0.0,
        ),
        close_position=NeverCalledClosePosition(),  # type: ignore[arg-type]
        open_after_close=seeder,
        commit=session,
        closing_attempts=attempts_repository,
        close_orphans=NeverCalledCloseOrphans(),
        tradable_pools=frozenset({("bybit", "usdt-m")}),
    )


class _NullQueue:
    """``PlaceOrder`` enqueues its settle job before contacting the venue.
    Nothing here settles anything, and a real queue would only add a second
    table to the race for no gain -- the assertions are about reservations
    and execution attempts."""

    async def enqueue(self, job: object) -> UUID:
        return uuid4()


async def _setup(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    """Seeds the strategy, its settled flat holding, a stale-but-present pool
    snapshot and the racing signal. Returns ``(strategy_id, signal_id)``."""
    strategy_id = uuid4()
    await seed_strategy(
        session_factory,
        strategy_id=strategy_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        fill_mode="PARTIAL",
        enabled=True,
    )
    async with session_factory() as session:
        await session.execute(
            text("UPDATE strategies SET allocation_percent = :p WHERE id = :id"),
            {"p": ALLOCATION_PERCENT, "id": strategy_id},
        )
        await session.commit()

    prior_signal_id = uuid4()
    await _seed_signal(
        session_factory,
        signal_id=prior_signal_id,
        strategy_id=strategy_id,
        symbol="STXUSDT",
        price=Decimal("2"),
        position_size=Decimal("0"),
        received_at=START - timedelta(minutes=30),
    )
    await _seed_settled_flat_holding(
        session_factory, strategy_id=strategy_id, prior_signal_id=prior_signal_id
    )

    async with session_factory() as session:
        await session.execute(
            insert(PoolBalanceSnapshotRow).values(
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                total=Decimal("1"),  # deliberately wrong; the S3 refresh overwrites it
                available=Decimal("1"),
                observed_at=START - timedelta(hours=1),
            )
        )
        await session.commit()

    signal_id = uuid4()
    await _seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        symbol="STXUSDT_PERP",
        price=Decimal("2"),
        position_size=Decimal("1"),
        received_at=START,
    )
    return strategy_id, signal_id


async def test_the_unique_constraint_backstopping_the_dedup_really_exists(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``open_now``'s docstring leans on ``reservations.signal_id`` being
    UNIQUE. Asserted against the live catalog rather than the migration
    source, because the constraint that matters is the one the database is
    actually enforcing."""
    async with pg_session_factory() as session:
        unique_columns = (
            await session.execute(
                text(
                    "SELECT a.attname FROM pg_index i "
                    "JOIN pg_class t ON t.oid = i.indrelid "
                    "JOIN pg_attribute a ON a.attrelid = t.oid "
                    "AND a.attnum = ANY(i.indkey) "
                    "WHERE t.relname = 'reservations' AND i.indisunique "
                    "AND NOT i.indisprimary"
                )
            )
        ).scalars().all()

    assert "signal_id" in unique_columns


async def test_two_concurrent_open_now_calls_reserve_once_and_order_once(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id = await _setup(pg_session_factory)

    clock = FixedClock(START)
    exchange = CountingFakeExchange(exchange="bybit", fill_price=Decimal("2"))
    registry = VenueExchangeRegistry([exchange])
    balance_reader = FixedBalanceReader(pool=POOL, amount=POOL_BALANCE, clock=clock)
    pools_by_key = {
        POOL: PoolConfig(
            exchange=Exchange("bybit"),
            venue=Venue("usdt-m"),
            settlement_currency=Currency("USDT"),
            min_order_size=Decimal("5"),
        )
    }
    barrier = asyncio.Barrier(2)
    observed: list[Reservation | None] = []
    seeder = RecordingSeeder()

    async def one_delivery() -> ProcessSignalResult:
        async with pg_session_factory() as session:
            handler = _build_handler(
                session,
                registry=registry,
                clock=clock,
                balance_reader=balance_reader,
                pools_by_key=pools_by_key,
                reservations=RaceSyncedReservations(
                    SqlAlchemyReservationRepository(session), barrier, observed
                ),
                seeder=seeder,
            )
            return await handler.open_now(signal_id, poll=0)

    outcomes = await asyncio.wait_for(
        asyncio.gather(one_delivery(), one_delivery(), return_exceptions=True),
        timeout=RACE_TIMEOUT_SECONDS,
    )

    # The race was real: both deliveries read "no reservation for this
    # signal" before either allocated. Without this the test could pass on a
    # purely sequential interleaving and prove nothing.
    assert observed == [None, None]

    async with pg_session_factory() as session:
        reservation_count = (
            await session.execute(
                select(func.count())
                .select_from(ReservationRow)
                .where(ReservationRow.signal_id == signal_id)
            )
        ).scalar_one()
        reservation = (
            await session.execute(
                select(ReservationRow).where(ReservationRow.signal_id == signal_id)
            )
        ).scalar_one()
        attempt_count = (
            await session.execute(
                select(func.count())
                .select_from(ExecutionAttemptRow)
                .where(ExecutionAttemptRow.reservation_id == reservation.id)
            )
        ).scalar_one()

    assert reservation_count == 1
    assert reservation.amount == EXPECTED_GRANT
    assert reservation.strategy_id == strategy_id
    assert attempt_count == 1
    # Counted at the venue too: a second order the exchange accepted while no
    # row recorded it would be the worse of the two failures.
    assert len(exchange.placed_orders) == 1

    winners = [o for o in outcomes if isinstance(o, ProcessSignalResult)]
    losers = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(winners) == 1
    assert winners[0].executed is True
    assert winners[0].reservation_id == reservation.id

    # THE LOSER. It does not vanish: it raises the UNIQUE violation out of
    # ``open_now``, which ``WorkerRunner`` turns into ``queue.fail()`` and a
    # retry. The redelivered job then finds ``own_reservation_id`` set and
    # takes the ordinary no-op path, so the continuation converges on the
    # winner's single reservation rather than forking.
    assert len(losers) == 1
    assert isinstance(losers[0], IntegrityError)
    assert "reservations" in str(losers[0])

    # Nothing was deferred: neither racer took the guard's in-flight branch,
    # so the outcome above is genuinely the allocation race and not a
    # continuation reseed wearing its clothes.
    assert seeder.seeds == []
