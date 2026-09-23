"""Unit tests: ``ProcessSignalHandler`` routes by ``PositionTransition`` — a
RELEASE-path signal (close long, close short) never acquires the advisory
lock, asserted with a spy ``AdvisoryLockPort``; a CONSUME-path signal does
acquire it (tasks.md 5.16; design.md § "position_size routes the signal").
No database: ``AllocateCapital`` is real (slice 4), wired with fakes,
including the spy lock, so the assertion exercises the actual lock call
site rather than a re-implemented stand-in.

Also covers tasks.md 7.7: a CONSUME-path signal's requested amount MUST come
from the strategy's ``allocation_percent`` applied to the pool balance,
never from the alert's ``position_size``/``contracts`` (design.md's GAP
FOUND note, closed by this slice).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.accounts.application.ports import PoolBalanceReading
from strategy_manager.accounts.application.refresh_pool_balance import RefreshPoolBalance
from strategy_manager.accounts.infrastructure.reader_by_exchange import ReaderByExchange
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
    AllocationResult,
    InvalidAllocationRequestError,
)
from strategy_manager.allocation.application.ports import PoolBalance, StrategyPolicySnapshot
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.execution.application.close_position import (
    CloseCommand,
    CloseResult,
)
from strategy_manager.execution.application.place_order import PlaceCommand, PlaceResult
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.shared.application.ports import CommitPort
from strategy_manager.shared.domain.money import Currency, Exchange, Money
from strategy_manager.signals.application.close_orphans import CloseOrphans
from strategy_manager.signals.application.holding_guard import GuardOutcome, HoldingGuard
from strategy_manager.signals.application.ports import PoolKey, RefreshOutcome, RefreshStatus
from strategy_manager.signals.application.process_signal import (
    ProcessSignalHandler,
    SignalContext,
)
from strategy_manager.signals.domain.holding import HeldAllocation


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@dataclass
class FakeStrategyPolicyPort:
    snapshot: StrategyPolicySnapshot

    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot:
        return self.snapshot


@dataclass
class FakePoolBalancePort:
    balance: PoolBalance

    async def read(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> PoolBalance:
        return self.balance


@dataclass
class SpyAdvisoryLock:
    acquired: list[LockKey] = field(default_factory=list)

    async def acquire(self, key: LockKey) -> None:
        self.acquired.append(key)


@dataclass
class FakeReservationRepository:
    inserted: list[Reservation] = field(default_factory=list)

    async def find_by_signal_id(self, signal_id: UUID) -> Reservation | None:
        return None

    async def sum_active(
        self, exchange: str, venue: str, settlement_currency: str, now: datetime
    ) -> Decimal:
        return Decimal("0")

    async def insert(self, reservation: Reservation) -> None:
        self.inserted.append(reservation)

    async def mark(self, reservation_id: UUID, status: ReservationStatus, at: datetime) -> None:
        pass


@dataclass
class FakeCommit:
    async def commit(self) -> None:
        pass


@dataclass
class SpyPlaceOrder:
    """Stands in for ``PlaceOrder`` — records what it was asked to
    execute against, without needing an exchange/ledger stack."""

    calls: list[PlaceCommand] = field(default_factory=list)

    async def place(self, command: PlaceCommand) -> PlaceResult:
        self.calls.append(command)
        return PlaceResult(status="PLACED", execution_attempt_id=uuid4())


class SpyClosePosition:
    """Stands in for ``ClosePosition``. A close no longer goes through
    ``PlaceOrder`` at all, and keeping the two spies separate is what lets a
    test assert which of the two paths a signal actually took."""

    def __init__(self, result: CloseResult | None = None) -> None:
        self.calls: list[CloseCommand] = []
        self._result = result

    async def close(self, command: CloseCommand) -> CloseResult:
        self.calls.append(command)
        if self._result is not None:
            return self._result
        return CloseResult(
            status="PLACED",
            execution_attempt_id=uuid4(),
            base_size=Decimal("0.002"),
        )


@dataclass
class FakeSignalContextPort:
    context: SignalContext

    async def load(self, signal_id: UUID) -> SignalContext:
        return self.context


@dataclass
class FakeSymbolHoldingsPort:
    holdings: list[HeldAllocation] = field(default_factory=list)

    async def symbol_holdings(self, pool: PoolKey, symbol: str) -> list[HeldAllocation]:
        return self.holdings


@dataclass
class FakeInFlightWorkPort:
    result: bool = False
    closing_allocations: list[UUID] = field(default_factory=list)

    async def in_flight(
        self, pool: PoolKey, strategy_id: UUID, symbol: str, now: datetime
    ) -> bool:
        return self.result

    async def submitted_closing_allocations(
        self, pool: PoolKey, strategy_id: UUID, symbol: str
    ) -> list[UUID]:
        return self.closing_allocations


@dataclass
class SpyContinuationSeeder:
    """Stands in for ``OpenAfterClose``. Records every seed the guard's
    deferred branch (or the reverse-wiring release half, or ``CloseOrphans``)
    asked for, without needing a real job queue.

    Mimics ``enqueue_unique``'s own ``dedupe_key`` semantics: the FIRST seed
    for a given ``(signal_id, poll)`` pair inserts (``True``); a LATER one
    for the exact same pair collides (``False``), regardless of
    ``replay_expected`` -- which only ever picks the log level a real
    ``OpenAfterClose.seed`` would choose, never the return value
    (orchestrator review of `ee640d6`)."""

    calls: list[tuple[UUID, list[UUID], int, bool]] = field(default_factory=list)
    _seen: set[tuple[UUID, int]] = field(default_factory=set)

    async def seed(
        self,
        signal_id: UUID,
        awaited_allocation_ids: list[UUID],
        poll: int = 0,
        *,
        replay_expected: bool = False,
    ) -> bool:
        self.calls.append((signal_id, awaited_allocation_ids, poll, replay_expected))
        key = (signal_id, poll)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


@dataclass
class FakeClosingAttemptsPort:
    """Stands in for ``SqlAlchemyExecutionAttemptRepository.latest_close_for``
    -- what the reverse-wiring release half (S5b) reads to make itself
    idempotent. Defaults to ``None`` (no close exists yet for any
    allocation), the ordinary first-ever-pass case."""

    latest: ExecutionAttempt | None = None
    calls: list[UUID] = field(default_factory=list)

    async def latest_close_for(self, allocation_id: UUID) -> ExecutionAttempt | None:
        self.calls.append(allocation_id)
        return self.latest


@dataclass
class SpyCloseOrphans:
    """Stands in for ``CloseOrphans`` -- records what the guard's REAL
    branch (design.md § S6) asked it to close, without needing a real
    ``ClosePosition``/``OpenAfterClose`` stack. Records ``next_poll`` too
    (orchestrator review of `ee640d6`): the caller must thread it through,
    never hardcode it."""

    calls: list[tuple[UUID, PoolKey, UUID, str, list[HeldAllocation], int]] = field(
        default_factory=list
    )

    async def close(
        self,
        signal_id: UUID,
        pool: PoolKey,
        strategy_id: UUID,
        symbol: str,
        holdings: list[HeldAllocation],
        next_poll: int = 0,
    ) -> None:
        self.calls.append((signal_id, pool, strategy_id, symbol, holdings, next_poll))


@dataclass
class FakeBalanceRefreshPort:
    """Proceeds (FRESH) by default -- every test that does not care about the
    on-demand refresh (S3) gets today's behaviour unchanged."""

    outcome: RefreshOutcome = field(
        default_factory=lambda: RefreshOutcome(status=RefreshStatus.FRESH)
    )
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    async def refresh(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> RefreshOutcome:
        self.calls.append((exchange, venue, settlement_currency))
        return self.outcome


@dataclass
class FakeVenueNetPositionPort:
    """Defaults to AMBIGUOUS (``None``, "the read failed") -- harmless for
    every test in this file that never reaches the divergent branch at all
    (default holdings are empty, so the strategy is flat)."""

    net: Decimal | None = None

    async def net_position(self, pool: PoolKey, symbol: str) -> Decimal | None:
        return self.net


def _holding_guard(
    *,
    holdings: list[HeldAllocation] | None = None,
    in_flight: bool = False,
    venue_net: Decimal | None = None,
) -> HoldingGuard:
    """A guard that proceeds by default -- every test in this file that does
    not care about the Existing-Position Guard gets today's behaviour
    unchanged (no holding, nothing in flight)."""
    return HoldingGuard(
        holdings=FakeSymbolHoldingsPort(holdings or []),
        in_flight_work=FakeInFlightWorkPort(in_flight),
        venue_net_position=FakeVenueNetPositionPort(venue_net),
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        delayed_open_max_signal_age_seconds=600.0,
    )


TRADABLE = frozenset({("pionex", "spot")})


def _snapshot(**overrides: object) -> StrategyPolicySnapshot:
    defaults: dict[str, object] = dict(
        # Pionex, because the default venue is spot: the tradable-pool check
        # is keyed by both, so a mismatched pair would be refused for a
        # reason that has nothing to do with what is being tested. Overridable
        # (S3 correction tests need a real Bybit/Binance exchange to route a
        # ``ReaderByExchange`` factory by).
        exchange=Exchange.PIONEX,
        strategy_id=uuid4(),
        enabled=True,
        fill_mode="PARTIAL",
        venue="spot",
        settlement_currency="USDT",
        allocation_percent=Decimal("100"),
    )
    defaults.update(overrides)
    return StrategyPolicySnapshot(**defaults)  # type: ignore[arg-type]


def _allocate_capital(
    lock: SpyAdvisoryLock,
    policy: StrategyPolicySnapshot | None = None,
    pool_balance: PoolBalance | None = None,
    reservations: FakeReservationRepository | None = None,
) -> AllocateCapital:
    return AllocateCapital(
        strategy_policy=FakeStrategyPolicyPort(policy or _snapshot()),
        pool_balance=FakePoolBalancePort(
            pool_balance or PoolBalance(
                total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("1")
            )
        ),
        lock=lock,
        reservations=reservations or FakeReservationRepository(),
        commit=FakeCommit(),
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        reservation_ttl_seconds=30,
    )


class SpyAllocateCapital(AllocateCapital):
    """Wraps a REAL ``AllocateCapital`` and records every ``allocate`` call
    before delegating to it.

    ``SpyAdvisoryLock`` already proves the pool lock was not taken, but it
    cannot prove ``allocate()`` was never entered: the engine's own pre-lock
    guards (retry-resume, disabled-strategy skip, the currency and
    non-positive checks) all return or raise BEFORE the lock. A caller that
    reached the engine and was turned away by its ``InvalidAllocationRequest
    Error`` leaves exactly the same empty lock spy behind as a caller that
    refused before ever calling it -- so the "never reaches the engine"
    assertion needs this spy, not the lock's."""

    def __init__(self, inner: AllocateCapital) -> None:
        self._inner = inner
        self.calls: list[AllocateCommand] = []

    async def allocate(self, command: AllocateCommand) -> AllocationResult:
        self.calls.append(command)
        return await self._inner.allocate(command)


def _process_signal_handler(
    *,
    context: SignalContext,
    allocate_capital: AllocateCapital,
    place_order: SpyPlaceOrder,
    close_position: SpyClosePosition | None = None,
    policy: StrategyPolicySnapshot | None = None,
    pool_balance: PoolBalance | None = None,
    tradable_pools: frozenset[tuple[str, str]] = TRADABLE,
    holding_guard: HoldingGuard | None = None,
    balance_refresh: FakeBalanceRefreshPort | None = None,
    open_after_close: SpyContinuationSeeder | None = None,
    commit: CommitPort | None = None,
    closing_attempts: FakeClosingAttemptsPort | None = None,
    close_orphans: SpyCloseOrphans | None = None,
) -> ProcessSignalHandler:
    return ProcessSignalHandler(
        signal_context=FakeSignalContextPort(context),
        strategy_policy=FakeStrategyPolicyPort(policy or _snapshot()),
        pool_balance=FakePoolBalancePort(
            pool_balance or PoolBalance(
                total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("1")
            )
        ),
        holding_guard=holding_guard or _holding_guard(),
        balance_refresh=balance_refresh or FakeBalanceRefreshPort(),
        allocate_capital=allocate_capital,
        place_order=place_order,
        close_position=close_position or SpyClosePosition(),
        open_after_close=open_after_close or SpyContinuationSeeder(),
        commit=commit or FakeCommit(),
        closing_attempts=closing_attempts or FakeClosingAttemptsPort(),
        close_orphans=close_orphans or SpyCloseOrphans(),
        tradable_pools=tradable_pools,
    )


async def test_consumes_signal_acquires_the_advisory_lock() -> None:
    lock = SpyAdvisoryLock()
    allocate_capital = _allocate_capital(lock)
    place_order = SpyPlaceOrder()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),  # open long -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        place_order=place_order,
    )

    result = await handler.handle(uuid4())

    assert len(lock.acquired) == 1
    assert result.transition_kind == "open_long"
    assert len(place_order.calls) == 1


async def test_releases_signal_never_acquires_the_advisory_lock() -> None:
    lock = SpyAdvisoryLock()
    allocate_capital = _allocate_capital(lock)
    place_order = SpyPlaceOrder()
    close_position = SpyClosePosition()
    prior_reservation_id = uuid4()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),  # close long -> RELEASES
        prior_reservation_id=prior_reservation_id,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        place_order=place_order,
        close_position=close_position,
    )

    result = await handler.handle(uuid4())

    assert lock.acquired == []
    assert result.transition_kind == "close_long"
    assert len(close_position.calls) == 1
    assert close_position.calls[0].allocation_id == prior_reservation_id


async def test_a_close_never_goes_through_the_opening_path() -> None:
    """The bug this routing replaced. Closing used to call PlaceOrder against
    the opening reservation, which aborted on the expiry re-check outside the
    reservation's TTL and collided with the UNIQUE constraint inside it — so no
    close ever reached the exchange."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    close_position = SpyClosePosition()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=uuid4(),
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        close_position=close_position,
    )

    await handler.handle(uuid4())

    assert place_order.calls == []
    assert len(close_position.calls) == 1


async def test_a_close_carries_no_price_because_nothing_derives_a_size_from_one() -> None:
    """CloseCommand structurally has no price field. The close size comes from
    the ledger — what the opening allocation actually acquired — and a price
    that could reintroduce ``granted / price`` sizing is simply absent."""
    lock = SpyAdvisoryLock()
    close_position = SpyClosePosition()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=uuid4(),
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
    )

    await handler.handle(uuid4())

    assert not hasattr(close_position.calls[0], "price")
    assert close_position.calls[0].symbol == "BTC_USDT"
    assert close_position.calls[0].side is OrderSide.SELL


async def test_a_failed_close_is_reported_as_not_executed() -> None:
    """A definitive venue rejection of a close used to vanish here: the
    handler returned ``executed=True`` regardless of what ``ClosePosition``
    reported, so the job ended DONE and nothing downstream ever learned the
    close did not happen. ``failed`` carries the venue's own error text so a
    later reader does not have to go back to the execution attempt row."""
    lock = SpyAdvisoryLock()
    allocate_capital = _allocate_capital(lock)
    place_order = SpyPlaceOrder()
    failed_result = CloseResult(
        status="FAILED",
        execution_attempt_id=uuid4(),
        base_size=Decimal("0.002"),
        error="market closed",
    )
    close_position = SpyClosePosition(result=failed_result)
    prior_reservation_id = uuid4()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),  # close long -> RELEASES
        prior_reservation_id=prior_reservation_id,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        place_order=place_order,
        close_position=close_position,
    )

    result = await handler.handle(uuid4())

    assert result.executed is False
    assert result.failed == "market closed"


async def test_releases_signal_with_no_prior_reservation_is_a_safe_no_op() -> None:
    lock = SpyAdvisoryLock()
    allocate_capital = _allocate_capital(lock)
    place_order = SpyPlaceOrder()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("-1"),  # close short -> RELEASES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        place_order=place_order,
    )

    result = await handler.handle(uuid4())

    assert lock.acquired == []
    assert place_order.calls == []
    assert result.reservation_id is None
    assert result.executed is False


async def test_consumes_signal_sizes_requested_from_allocation_percent_never_from_position_size(
) -> None:
    """tasks.md 7.7: the requested amount MUST come from the strategy's
    ``allocation_percent`` applied to the pool balance, never from the
    alert's ``position_size``/``contracts`` (design.md's GAP FOUND note,
    closed by this slice). ``position_size`` and ``price`` are set so their
    product (200,000,000) wildly differs from the percent-derived request
    (200) — if the stand-in ever regressed, this assertion would fail loudly."""
    lock = SpyAdvisoryLock()
    policy = _snapshot(allocation_percent=Decimal("20"))
    pool_balance = PoolBalance(
        total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("1")
    )
    reservations = FakeReservationRepository()
    allocate_capital = _allocate_capital(
        lock, policy=policy, pool_balance=pool_balance, reservations=reservations
    )
    place_order = SpyPlaceOrder()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),  # position_size * price = 200,000,000 - never used
        position_size=Decimal("4000"),
        prior_position_size=Decimal("0"),  # open long -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        place_order=place_order,
        policy=policy,
        pool_balance=pool_balance,
    )

    await handler.handle(uuid4())

    assert len(reservations.inserted) == 1
    # 20% of a 1000 balance = 200 - not 200,000,000.
    assert reservations.inserted[0].amount == Decimal("200")


def _open_long_context() -> SignalContext:
    return SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),  # open long -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )


async def _granted_for(policy: StrategyPolicySnapshot, pool_balance: PoolBalance) -> Decimal:
    lock = SpyAdvisoryLock()
    reservations = FakeReservationRepository()
    handler = _process_signal_handler(
        context=_open_long_context(),
        allocate_capital=_allocate_capital(
            lock, policy=policy, pool_balance=pool_balance, reservations=reservations
        ),
        place_order=SpyPlaceOrder(),
        policy=policy,
        pool_balance=pool_balance,
    )

    await handler.handle(uuid4())

    assert len(reservations.inserted) == 1
    return reservations.inserted[0].amount


async def test_consumes_signal_sizes_from_the_pool_total_not_from_what_is_free() -> None:
    """Owner decision 2026-09-15: ``allocation_percent`` is a share of the
    pool's TOTAL. With 1000 in the pool and 400 still free because other
    strategies hold positions, a 30% strategy asks for 300 -- not 30% of the
    400. Sizing from what is free opened smaller positions for every strategy
    that happened to signal after another."""
    granted = await _granted_for(
        _snapshot(allocation_percent=Decimal("30")),
        PoolBalance(total=Decimal("1000"), available=Decimal("400"), min_order_size=Decimal("1")),
    )

    assert granted == Decimal("300")


async def test_a_total_based_ask_is_still_capped_by_what_is_free() -> None:
    """Sizing from the total must never grant capital that is committed: with
    only 200 free, the 300 ask is filled partially at 200."""
    granted = await _granted_for(
        _snapshot(allocation_percent=Decimal("30"), fill_mode="PARTIAL"),
        PoolBalance(total=Decimal("1000"), available=Decimal("200"), min_order_size=Decimal("1")),
    )

    assert granted == Decimal("200")


async def test_a_reverse_closes_the_prior_position_instead_of_skipping_it() -> None:
    """``handle`` used to ask ``CONSUMES in effects``, which for a reverse
    matched the SECOND of its two effects and skipped the first entirely, so
    the closing half never ran.

    Routing on ``effects[0]`` uses the ordering the domain already declares —
    a reverse releases before it consumes — and no branch names REVERSE."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    close_position = SpyClosePosition()
    prior_reservation_id = uuid4()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("-1"),
        prior_position_size=Decimal("1"),  # long -> short = REVERSE
        prior_reservation_id=prior_reservation_id,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        close_position=close_position,
    )

    result = await handler.handle(uuid4())

    assert result.transition_kind == "reverse"
    assert len(close_position.calls) == 1
    assert close_position.calls[0].allocation_id == prior_reservation_id


async def test_a_reverse_out_of_a_long_never_buys_more() -> None:
    """THE test. ``_CONSUMING_SIDE`` mapped REVERSE to a constant BUY, so a
    strategy holding a long and told to flip short bought more long — the exact
    opposite of the signal, with real capital allocated behind it."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    close_position = SpyClosePosition()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("-1"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=uuid4(),
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        close_position=close_position,
    )

    await handler.handle(uuid4())

    assert place_order.calls == []
    assert lock.acquired == []
    assert close_position.calls[0].side is OrderSide.SELL


async def test_a_transition_with_a_second_effect_reports_it_did_not_run() -> None:
    """The position ends flat, not flipped. That is a defensible state — the
    prior exposure is genuinely gone — but reporting plain success would hide
    that the strategy is no longer positioned the way its signal asked."""
    lock = SpyAdvisoryLock()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("-1"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=uuid4(),
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=SpyClosePosition(),
    )

    result = await handler.handle(uuid4())

    assert result.executed is True
    assert result.refused is not None
    assert "consumes half" in result.refused


async def test_a_single_effect_transition_reports_nothing_refused() -> None:
    """A plain open or close is complete on its own. Only a transition
    declaring more than one effect has a tail to report."""
    lock = SpyAdvisoryLock()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
    )

    result = await handler.handle(uuid4())

    assert result.refused is None


async def test_a_reverse_with_no_prior_reservation_is_a_safe_no_op() -> None:
    """Nothing to close. The prior signal never produced a reservation, so
    there is no position this system put on."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    close_position = SpyClosePosition()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("-1"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        close_position=close_position,
    )

    result = await handler.handle(uuid4())

    assert result.executed is False
    assert close_position.calls == []
    assert place_order.calls == []


async def test_a_signal_on_an_unserved_venue_is_refused_without_reserving() -> None:
    """``venue`` never selects an adapter, so a futures strategy would be sized
    against the futures wallet and executed on spot. Refusing before allocation
    means no capital is held for a trade that cannot be placed correctly."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        policy=_snapshot(venue="usdt-m"),
    )

    result = await handler.handle(uuid4())

    assert result.executed is False
    assert result.reservation_id is None
    assert result.refused is not None
    assert "usdt-m" in result.refused
    assert lock.acquired == []
    assert place_order.calls == []


async def test_refusing_one_venue_leaves_the_served_one_trading() -> None:
    """The reason this is per signal and not a startup invariant. An enabled
    coin-m pool nobody trades must not stop the spot trading that works."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        policy=_snapshot(venue="spot"),
        tradable_pools=frozenset({("pionex", "spot")}),
    )

    result = await handler.handle(uuid4())

    assert result.executed is True
    assert result.refused is None
    assert len(place_order.calls) == 1


async def test_opening_a_short_sells_and_opening_a_long_buys() -> None:
    """The side now comes from the sign of the position AFTER the order, so it
    is right for every transition kind rather than for the three the old dicts
    happened to enumerate."""
    for position_size, expected in (
        (Decimal("1"), OrderSide.BUY),
        (Decimal("-1"), OrderSide.SELL),
    ):
        lock = SpyAdvisoryLock()
        place_order = SpyPlaceOrder()
        context = SignalContext(
            strategy_id=uuid4(),
            symbol="BTC_USDT",
            price=Decimal("50000"),
            position_size=position_size,
            prior_position_size=Decimal("0"),  # open -> CONSUMES
            prior_reservation_id=None,
            settlement_currency="USDT",
        )
        handler = _process_signal_handler(
            context=context,
            allocate_capital=_allocate_capital(lock),
            place_order=place_order,
        )

        await handler.handle(uuid4())

        assert place_order.calls[0].side is expected


async def test_closing_a_short_buys_and_closing_a_long_sells() -> None:
    """Same derivation from the other side: the sign of the position BEFORE
    the order says what is being closed."""
    for prior, expected in (
        (Decimal("1"), OrderSide.SELL),
        (Decimal("-1"), OrderSide.BUY),
    ):
        lock = SpyAdvisoryLock()
        close_position = SpyClosePosition()
        context = SignalContext(
            strategy_id=uuid4(),
            symbol="BTC_USDT",
            price=Decimal("50000"),
            position_size=Decimal("0"),
            prior_position_size=prior,
            prior_reservation_id=uuid4(),
            settlement_currency="USDT",
        )
        handler = _process_signal_handler(
            context=context,
            allocate_capital=_allocate_capital(lock),
            place_order=SpyPlaceOrder(),
            close_position=close_position,
        )

        await handler.handle(uuid4())

        assert close_position.calls[0].side is expected


async def test_a_divergent_holding_refuses_and_never_allocates() -> None:
    """The Existing-Position Guard runs at the TOP of ``_handle_consumes`` --
    a refusal must never reach ``AllocateCapital``, asserted here with a spy
    lock: ``AllocateCapital`` is the only path that acquires it."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    strategy_id = uuid4()
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),  # open -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
        own_reservation_id=None,
    )
    guard = _holding_guard(
        holdings=[
            HeldAllocation(strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.4"))
        ]
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        holding_guard=guard,
    )

    result = await handler.handle(uuid4())

    assert result.executed is False
    assert result.refused is not None
    assert result.reservation_id is None
    assert lock.acquired == []
    assert place_order.calls == []


async def test_an_own_reservation_resumes_even_with_a_divergent_holding() -> None:
    """A retry past ``AllocateCapital`` must not be re-refused by a holding
    its own earlier attempt is what produced."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    strategy_id = uuid4()
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
        own_reservation_id=uuid4(),
    )
    guard = _holding_guard(
        holdings=[
            HeldAllocation(strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.4"))
        ]
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        holding_guard=guard,
    )

    result = await handler.handle(uuid4())

    assert result.executed is True
    assert len(lock.acquired) == 1


async def test_a_real_orphan_routes_to_close_orphans_and_defers_the_open() -> None:
    """design.md § S6: the guard's REAL branch never closes anything itself
    (``GuardOutcome.real_orphan_holdings``) -- ``_handle_consumes`` is the
    caller that does, through ``CloseOrphans``, and the open is deferred
    exactly like the in-flight branch's own deferral (never a refusal,
    never reaching ``AllocateCapital``)."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    strategy_id = uuid4()
    signal_id = uuid4()
    own_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    # L_S = L_P = 0.5, V = 0.5 -> REAL (design.md § S4's own worked example).
    guard = _holding_guard(holdings=[own_holding], venue_net=Decimal("0.5"))
    close_orphans = SpyCloseOrphans()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        holding_guard=guard,
        close_orphans=close_orphans,
    )

    result = await handler.handle(signal_id)

    assert close_orphans.calls == [
        (signal_id, ("pionex", "spot", "USDT"), strategy_id, "ETHUSDT", [own_holding], 0)
    ]
    assert result.executed is False
    assert result.refused is None
    assert result.failed is None
    assert lock.acquired == []
    assert place_order.calls == []


async def test_open_now_threads_next_poll_into_close_orphans_on_a_real_orphan_re_defer() -> None:
    """The same threading fix ``_handle_consumes``'s in-flight branch
    already had -- a re-entry via ``open_now`` that still finds a REAL
    orphan must seed the NEXT poll, never restart at 0 (orchestrator
    review of `ee640d6`, "a close can be placed with no live continuation
    awaiting it")."""
    lock = SpyAdvisoryLock()
    strategy_id = uuid4()
    signal_id = uuid4()
    own_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    guard = _holding_guard(holdings=[own_holding], venue_net=Decimal("0.5"))
    close_orphans = SpyCloseOrphans()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        holding_guard=guard,
        close_orphans=close_orphans,
    )

    await handler.open_now(signal_id, poll=2)

    assert close_orphans.calls == [
        (signal_id, ("pionex", "spot", "USDT"), strategy_id, "ETHUSDT", [own_holding], 3)
    ]


# ---- Scenario A (orchestrator review of `ee640d6`): a REAL orphan whose
# resolution spans more than one poll -- standing in for a close that only
# partially flattens the position, leaving a second allocation still
# divergent -- must not collide on the seed at each re-entry, must
# eventually close everything, and the deferred open must happen EXACTLY
# once. Real ``CloseOrphans`` wired with fakes; ``ProcessSignalHandler``
# drives each round directly (``handle()`` then two ``open_now`` calls),
# standing in for what ``OpenAfterClose.poll()`` would otherwise drive.


@dataclass
class _SequencedSymbolHoldingsPort:
    rounds: list[list[HeldAllocation]]
    call_count: int = 0

    async def symbol_holdings(self, pool: PoolKey, symbol: str) -> list[HeldAllocation]:
        holdings = self.rounds[min(self.call_count, len(self.rounds) - 1)]
        self.call_count += 1
        return holdings


@dataclass
class _SequencedVenueNetPositionPort:
    nets: list[Decimal | None]
    call_count: int = 0

    async def net_position(self, pool: PoolKey, symbol: str) -> Decimal | None:
        net = self.nets[min(self.call_count, len(self.nets) - 1)]
        self.call_count += 1
        return net


@dataclass
class _FakeClosingAttemptsByAllocation:
    """Unlike this file's own ``FakeClosingAttemptsPort`` (one shared
    ``latest`` for every allocation), this tracks a distinct answer per
    allocation id -- needed once ``CloseOrphans`` is exercised for real
    across more than one allocation in the same test."""

    by_allocation: dict[UUID, ExecutionAttempt | None] = field(default_factory=dict)

    async def latest_close_for(self, allocation_id: UUID) -> ExecutionAttempt | None:
        return self.by_allocation.get(allocation_id)


async def test_scenario_a_a_real_orphan_spanning_two_polls_closes_and_opens_once() -> None:
    strategy_id = uuid4()
    signal_id = uuid4()
    allocation_a = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    allocation_b = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("-0.3")
    )
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="ETHUSDT.P",
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    seeder = SpyContinuationSeeder()
    close_position = SpyClosePosition()
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=_FakeClosingAttemptsByAllocation(),
        open_after_close=seeder,
        commit=FakeCommit(),
    )
    guard = HoldingGuard(
        # Round 0 (handle()): only A holds -> REAL. Round 1 (open_now poll=0):
        # only B holds -> REAL again, standing in for a residual the first
        # close left behind. Round 2 (open_now poll=1): flat -> proceeds.
        holdings=_SequencedSymbolHoldingsPort(
            [[allocation_a], [allocation_b], []]
        ),
        in_flight_work=FakeInFlightWorkPort(result=False),
        venue_net_position=_SequencedVenueNetPositionPort(
            [Decimal("0.5"), Decimal("-0.3")]
        ),
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        delayed_open_max_signal_age_seconds=600.0,
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        holding_guard=guard,
        close_orphans=close_orphans,
        open_after_close=seeder,
        close_position=close_position,
    )

    round0 = await handler.handle(signal_id)
    assert round0.executed is False
    round1 = await handler.open_now(signal_id, poll=0)
    assert round1.executed is False
    round2 = await handler.open_now(signal_id, poll=1)

    assert [call.allocation_id for call in close_position.calls] == [
        allocation_a.allocation_id,
        allocation_b.allocation_id,
    ]
    seeded_polls = [call[2] for call in seeder.calls]
    assert seeded_polls == sorted(set(seeded_polls)), "every seeded poll must be distinct"
    assert len(place_order.calls) == 1
    assert round2.executed is True


async def test_in_flight_work_defers_by_seeding_a_continuation_and_never_allocates() -> None:
    """design.md § S5, amending S2: the in-flight branch no longer raises
    into the queue's failure backoff -- it seeds an ``OpenAfterClose``
    continuation and commits, without ever reaching the advisory lock.

    Seeds poll 0 -- this is the FRESH-chain case, reached from ``handle()``
    directly rather than from an already-in-progress continuation."""
    lock = SpyAdvisoryLock()
    signal_id = uuid4()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    guard = _holding_guard(in_flight=True)
    seeder = SpyContinuationSeeder()
    commit = _SpyCommit()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        holding_guard=guard,
        open_after_close=seeder,
        commit=commit,
    )

    result = await handler.handle(signal_id)

    assert result.executed is False
    assert result.refused is None
    assert seeder.calls == [(signal_id, [], 0, False)]
    assert commit.commits == 1
    assert lock.acquired == []


# --- ``open_now``: the S5 continuation's own entry point --------------------
#
# design.md § S5, "all FILLED" -> ``ProcessSignalHandler.open_now(signal_id)``.


async def test_open_now_with_no_existing_reservation_runs_the_full_pipeline() -> None:
    """When the continuation is the first thing to ever allocate for this
    signal, ``open_now`` runs exactly the guard/refresh/allocate/place
    pipeline ``_handle_consumes`` always has."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    context = _open_long_context()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
    )

    result = await handler.open_now(uuid4())

    assert result.executed is True
    assert len(lock.acquired) == 1
    assert len(place_order.calls) == 1


async def test_open_now_is_a_no_op_when_the_signal_already_owns_a_reservation() -> None:
    """Re-running a continuation (a crash between its own commit and its
    job's ack, or a redelivered job) must never submit a second open --
    ``own_reservation_id`` (``find_by_signal_id``) makes this a no-op before
    the guard, the refresh or ``AllocateCapital`` are ever touched."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    existing_reservation_id = uuid4()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
        own_reservation_id=existing_reservation_id,
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
    )

    result = await handler.open_now(uuid4())

    assert result.executed is True
    assert result.reservation_id == existing_reservation_id
    assert lock.acquired == []
    assert place_order.calls == []


async def test_open_now_that_still_finds_in_flight_work_reseeds_the_next_poll() -> None:
    """Orchestrator-found defect: if the guard defers AGAIN from inside
    ``open_now`` (some other work now in flight), it must seed ``poll + 1``
    -- never restart the chain at 0, which would collide with the
    already-DONE poll 0 row and silently drop the continuation."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    signal_id = uuid4()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    guard = _holding_guard(in_flight=True)
    seeder = SpyContinuationSeeder()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        holding_guard=guard,
        open_after_close=seeder,
    )

    result = await handler.open_now(signal_id, poll=3)

    assert result.executed is False
    assert seeder.calls == [(signal_id, [], 4, False)]
    assert lock.acquired == []
    assert place_order.calls == []


# --- On-Demand Balance Refresh Before Allocation (S3) ------------------------
#
# spec: capital-allocation § On-Demand Balance Refresh Before Allocation;
# design.md § S3 — "Every remote read happens before ``_lock.acquire``.
# ``AllocateCapital``, ``decide()`` and the in-lock read are untouched."


async def test_the_guard_then_the_refresh_then_the_sizing_read_run_in_that_order() -> None:
    """The guard (S2b) must run before the refresh (S3), and the refresh
    before the sizing read that feeds ``AllocateCapital`` -- proven with a
    shared spy rather than by trusting the source order, since a refusal from
    either of the first two must never reach the third."""
    order: list[str] = []

    class OrderingGuard:
        async def check(self, **kwargs: object) -> GuardOutcome:
            order.append("guard")
            return GuardOutcome(proceed=True)

    class OrderingRefresh:
        async def refresh(
            self, exchange: str, venue: str, settlement_currency: str
        ) -> RefreshOutcome:
            order.append("refresh")
            return RefreshOutcome(status=RefreshStatus.FRESH)

    class OrderingPoolBalance:
        async def read(
            self, exchange: str, venue: str, settlement_currency: str
        ) -> PoolBalance:
            order.append("pool_balance")
            return PoolBalance(
                total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("1")
            )

    lock = SpyAdvisoryLock()
    handler = ProcessSignalHandler(
        signal_context=FakeSignalContextPort(_open_long_context()),
        strategy_policy=FakeStrategyPolicyPort(_snapshot()),
        pool_balance=OrderingPoolBalance(),  # type: ignore[arg-type]
        holding_guard=OrderingGuard(),  # type: ignore[arg-type]
        balance_refresh=OrderingRefresh(),
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=SpyClosePosition(),
        open_after_close=SpyContinuationSeeder(),
        commit=FakeCommit(),
        closing_attempts=FakeClosingAttemptsPort(),
        close_orphans=SpyCloseOrphans(),
        tradable_pools=TRADABLE,
    )

    await handler.handle(uuid4())

    assert order == ["guard", "refresh", "pool_balance"]


async def test_a_guard_refusal_never_triggers_a_refresh() -> None:
    """A refusal from the Existing-Position Guard must short-circuit before
    the refresh is ever attempted -- the refresh is a remote call and the
    guard already decided this signal will not be allocated."""
    lock = SpyAdvisoryLock()
    strategy_id = uuid4()
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    guard = _holding_guard(
        holdings=[
            HeldAllocation(strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.4"))
        ]
    )
    balance_refresh = FakeBalanceRefreshPort()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        holding_guard=guard,
        balance_refresh=balance_refresh,
    )

    result = await handler.handle(uuid4())

    assert result.executed is False
    assert balance_refresh.calls == []


async def test_an_unavailable_balance_refuses_with_an_error_naming_signal_strategy_symbol(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """spec: "Refresh fails, snapshot stale" -- the signal is refused AND an
    ERROR is logged naming the pool, the signal, the strategy and the symbol.
    ``RefreshPoolBalance`` itself cannot log this line: it only ever knows the
    pool, not the signal it is being refreshed for."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    strategy_id = uuid4()
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    balance_refresh = FakeBalanceRefreshPort(
        outcome=RefreshOutcome(
            status=RefreshStatus.UNAVAILABLE, age_seconds=120.0, reason="timed out"
        )
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        balance_refresh=balance_refresh,
    )
    signal_id = uuid4()

    with caplog.at_level("ERROR"):
        result = await handler.handle(signal_id)

    assert result.executed is False
    assert result.reservation_id is None
    assert result.refused is not None
    assert lock.acquired == []
    assert place_order.calls == []
    error = next(r for r in caplog.records if r.levelname == "ERROR")
    assert str(signal_id) in error.message
    assert str(strategy_id) in error.message
    assert "ETHUSDT" in error.message


async def test_a_fallback_balance_still_proceeds_to_allocate() -> None:
    """spec: "Refresh fails, snapshot fresh" -- FALLBACK is not a refusal; the
    signal is sized and allocated exactly as if the refresh had succeeded."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    balance_refresh = FakeBalanceRefreshPort(
        outcome=RefreshOutcome(status=RefreshStatus.FALLBACK, age_seconds=40.0, reason="timed out")
    )
    handler = _process_signal_handler(
        context=_open_long_context(),
        allocate_capital=_allocate_capital(lock),
        place_order=place_order,
        balance_refresh=balance_refresh,
    )

    result = await handler.handle(uuid4())

    assert result.executed is True
    assert len(lock.acquired) == 1
    assert len(place_order.calls) == 1


# --- S3 correction: lazy, per-exchange credential/client construction -------
#
# Orchestrator review of the first S3 commit (cb59825) found a regression:
# main.py built BOTH exchanges' balance readers EAGERLY on every
# signal.process job, decrypting a credential and opening an HTTP client
# unconditionally. A RELEASES signal paid for a refresh it never needed, and
# a missing/undecryptable credential on ONE exchange raised at job entry and
# took the OTHER exchange's signals down too. These tests wire the REAL
# ``RefreshPoolBalance`` + REAL ``ReaderByExchange`` ``ProcessSignalHandler``
# actually uses, with fake per-exchange factories standing in for main.py's
# real vault-load + HTTP-client-open closures (``_bybit_reader``/
# ``_binance_reader``), so the whole designed chain is proven end to end
# without ever needing a real credential.


class _StubBalanceReader:
    """Stands in for ``BybitBalanceReader``/``BinanceBalanceReader``."""

    def __init__(self, exchange: str) -> None:
        self._exchange = exchange

    async def read(self, pools: Sequence[PoolKey]) -> list[PoolBalanceReading]:
        exchange, venue, currency = pools[0]
        return [
            PoolBalanceReading(
                exchange=exchange,
                venue=venue,
                settlement_currency=currency,
                total=Decimal("1000"),
                available=Decimal("1000"),
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ]


class _SpyExchangeFactory:
    """Stands in for main.py's ``_bybit_reader``/``_binance_reader``
    closures: each call represents a credential decrypt + HTTP client open.
    A factory that ``raises`` models a missing or undecryptable credential
    for that one exchange."""

    def __init__(self, exchange: str, raises: Exception | None = None) -> None:
        self._exchange = exchange
        self._raises = raises
        self.calls = 0

    async def __call__(self) -> _StubBalanceReader:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return _StubBalanceReader(self._exchange)


@dataclass
class _SpyWriter:
    written: list[Sequence[PoolBalanceReading]] = field(default_factory=list)

    async def upsert(self, readings: Sequence[PoolBalanceReading]) -> None:
        self.written.append(readings)


@dataclass
class _SpyCommit:
    commits: int = 0

    async def commit(self) -> None:
        self.commits += 1


@dataclass
class _StubAge:
    age: float | None

    async def age_seconds(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> float | None:
        return self.age


def _real_balance_refresh(
    factories: dict[str, "_SpyExchangeFactory"], age: float | None = 40.0
) -> RefreshPoolBalance:
    """The real ``RefreshPoolBalance`` + real ``ReaderByExchange`` main.py
    composes -- only the exchange factories underneath are fakes."""
    return RefreshPoolBalance(
        reader=ReaderByExchange(factories),  # type: ignore[arg-type]
        snapshots=_SpyWriter(),
        age=_StubAge(age),
        commit=_SpyCommit(),
        timeout_seconds=3.0,
        fallback_max_age_seconds=90.0,
    )


async def test_a_releases_signal_never_invokes_any_exchange_factory() -> None:
    """(a) A close must not pay for a refresh it never needs, and must not
    fail because of a credential problem on either exchange -- ``_handle_
    releases`` never even reads ``self._balance_refresh``."""
    lock = SpyAdvisoryLock()
    close_position = SpyClosePosition()
    bybit_factory = _SpyExchangeFactory("bybit", raises=RuntimeError("no bybit credential"))
    binance_factory = _SpyExchangeFactory("binance", raises=RuntimeError("no binance credential"))
    prior_reservation_id = uuid4()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),  # close long -> RELEASES
        prior_reservation_id=prior_reservation_id,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
        balance_refresh=_real_balance_refresh(
            {"bybit": bybit_factory, "binance": binance_factory}
        ),
    )

    result = await handler.handle(uuid4())

    assert result.executed is True
    assert bybit_factory.calls == 0
    assert binance_factory.calls == 0


async def test_an_opening_signal_on_binance_proceeds_when_bybit_credential_is_missing() -> None:
    """(b) "A Binance key nobody has sealed must cost Binance signals and
    nothing else" (main.py's own rule for ``exchange_for``) -- applied here
    to the refresh's own reader construction."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    bybit_factory = _SpyExchangeFactory("bybit", raises=RuntimeError("no bybit credential"))
    binance_factory = _SpyExchangeFactory("binance")
    policy = _snapshot(exchange=Exchange.BINANCE, venue="usdt-m")
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),  # open -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock, policy=policy),
        place_order=place_order,
        policy=policy,
        tradable_pools=frozenset({("binance", "usdt-m")}),
        balance_refresh=_real_balance_refresh(
            {"bybit": bybit_factory, "binance": binance_factory}
        ),
    )

    result = await handler.handle(uuid4())

    assert result.executed is True
    assert bybit_factory.calls == 0
    assert binance_factory.calls == 1


async def test_an_opening_signal_whose_own_credential_is_missing_falls_back() -> None:
    """(c) A credential/client-construction failure must surface INSIDE the
    refresh as a reader error, not raise out of ``handle`` -- here the
    existing snapshot is still young enough (FALLBACK), so the signal is
    still allocated."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    bybit_factory = _SpyExchangeFactory(
        "bybit", raises=RuntimeError("no active credential stored for 'bybit'")
    )
    policy = _snapshot(exchange=Exchange.BYBIT, venue="usdt-m")
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock, policy=policy),
        place_order=place_order,
        policy=policy,
        tradable_pools=frozenset({("bybit", "usdt-m")}),
        balance_refresh=_real_balance_refresh({"bybit": bybit_factory}, age=40.0),
    )

    result = await handler.handle(uuid4())  # must not raise

    assert bybit_factory.calls == 1
    assert result.executed is True
    assert len(lock.acquired) == 1


async def test_a_missing_credential_refuses_cleanly_once_the_snapshot_is_also_stale() -> None:
    """Triangulation of the case above: past the fallback bound, the same
    credential failure refuses cleanly (UNAVAILABLE) instead of raising."""
    lock = SpyAdvisoryLock()
    place_order = SpyPlaceOrder()
    bybit_factory = _SpyExchangeFactory(
        "bybit", raises=RuntimeError("no active credential stored for 'bybit'")
    )
    policy = _snapshot(exchange=Exchange.BYBIT, venue="usdt-m")
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock, policy=policy),
        place_order=place_order,
        policy=policy,
        tradable_pools=frozenset({("bybit", "usdt-m")}),
        balance_refresh=_real_balance_refresh({"bybit": bybit_factory}, age=120.0),
    )

    result = await handler.handle(uuid4())  # must not raise

    assert bybit_factory.calls == 1
    assert result.executed is False
    assert result.refused is not None
    assert lock.acquired == []
    assert place_order.calls == []


# --- S5b: reverse wiring -----------------------------------------------------
#
# design.md § "Reverse wiring (A6)"; spec: trade-execution § Reverse
# Completion. A reverse whose new side CAN be held (a perpetual market, or a
# LONG even on spot) seeds the S5 continuation awaiting the prior
# reservation's close BEFORE that close is placed, and no longer reports an
# unexecuted tail -- the open half runs later, via the continuation, once
# the close is FILLED. A reverse into a SPOT SHORT keeps today's
# ``_note_unexecuted_tail`` behaviour unchanged (covered by the pre-existing
# reverse tests above, none of which use a holdable new side).


def _holdable_reverse_context(
    *,
    symbol: str = "ETHUSDT.P",
    position_size: Decimal = Decimal("-1"),
    prior_position_size: Decimal = Decimal("1"),
    prior_reservation_id: UUID | None = None,
) -> SignalContext:
    return SignalContext(
        strategy_id=uuid4(),
        symbol=symbol,
        price=Decimal("2000"),
        position_size=position_size,
        prior_position_size=prior_position_size,  # opposite signs -> REVERSE
        prior_reservation_id=prior_reservation_id or uuid4(),
        settlement_currency="USDT",
    )


async def test_a_holdable_reverse_seeds_the_continuation_before_closing() -> None:
    """The continuation is seeded BEFORE ``ClosePosition.close`` runs, so
    its own commit makes the seed and the new closing attempt atomic
    (design.md § S5, "Who seeds the continuation")."""
    order: list[str] = []

    class OrderingSeeder:
        async def seed(
            self,
            signal_id: UUID,
            awaited_allocation_ids: list[UUID],
            poll: int = 0,
            *,
            replay_expected: bool = False,
        ) -> bool:
            order.append("seed")
            return True

    class OrderingClosePosition:
        async def close(self, command: CloseCommand) -> CloseResult:
            order.append("close")
            return CloseResult(
                status="PLACED", execution_attempt_id=uuid4(), base_size=Decimal("1")
            )

    lock = SpyAdvisoryLock()
    context = _holdable_reverse_context()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=OrderingClosePosition(),  # type: ignore[arg-type]
        open_after_close=OrderingSeeder(),  # type: ignore[arg-type]
    )

    await handler.handle(uuid4())

    assert order == ["seed", "close"]


async def test_a_holdable_reverse_does_not_report_an_unexecuted_tail() -> None:
    lock = SpyAdvisoryLock()
    close_position = SpyClosePosition()
    seeder = SpyContinuationSeeder()
    context = _holdable_reverse_context()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
        open_after_close=seeder,
    )

    result = await handler.handle(uuid4())

    assert result.transition_kind == "reverse"
    assert result.refused is None
    assert len(close_position.calls) == 1


async def test_the_continuation_awaits_the_prior_reservation() -> None:
    lock = SpyAdvisoryLock()
    seeder = SpyContinuationSeeder()
    prior_reservation_id = uuid4()
    signal_id = uuid4()
    context = _holdable_reverse_context(prior_reservation_id=prior_reservation_id)
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        open_after_close=seeder,
    )

    await handler.handle(signal_id)

    # ``replay_expected`` is True even on this first-ever pass: it also
    # covers the retry-after-a-FAILED-close case, whose seed at this same
    # poll may already be committed from an earlier attempt (design.md §
    # S5, S5b) -- a benign conflict here, never a chain-restarting one.
    assert seeder.calls == [(signal_id, [prior_reservation_id], 0, True)]


async def test_a_spot_short_reverse_does_not_seed_a_continuation() -> None:
    """The non-holdable case (a short on spot) keeps
    ``_note_unexecuted_tail`` and never touches the continuation."""
    lock = SpyAdvisoryLock()
    seeder = SpyContinuationSeeder()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("-1"),
        prior_position_size=Decimal("1"),  # long -> short on SPOT: not holdable
        prior_reservation_id=uuid4(),
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=SpyClosePosition(),
        open_after_close=seeder,
    )

    result = await handler.handle(uuid4())

    assert seeder.calls == []
    assert result.refused is not None


async def test_a_reverse_into_a_long_is_holdable_even_on_spot() -> None:
    """"holdable" is ``is_perpetual(symbol) or a long`` -- a spot LONG can be
    bought outright even though a spot SHORT cannot be held."""
    lock = SpyAdvisoryLock()
    seeder = SpyContinuationSeeder()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("-1"),  # short -> long, holdable even on spot
        prior_reservation_id=uuid4(),
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=SpyClosePosition(),
        open_after_close=seeder,
    )

    result = await handler.handle(uuid4())

    assert result.refused is None
    assert len(seeder.calls) == 1


async def test_a_retried_reverse_with_a_committed_close_does_not_place_a_second() -> None:
    """Idempotent release half (design.md § S5): a retry after the close
    already committed must skip ``ClosePosition.close`` entirely and only
    reseed, marked ``replay_expected`` -- a retry must never place a second
    close order."""
    lock = SpyAdvisoryLock()
    close_position = SpyClosePosition()
    seeder = SpyContinuationSeeder()
    prior_reservation_id = uuid4()
    signal_id = uuid4()
    context = _holdable_reverse_context(prior_reservation_id=prior_reservation_id)
    existing_close = ExecutionAttempt(
        id=uuid4(),
        reservation_id=None,
        closes_allocation_id=prior_reservation_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="ETHUSDT.P",
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        quote_amount=None,
        leverage=None,
        status=ExecutionStatus.SUBMITTED,
        client_order_id="client-1",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
        open_after_close=seeder,
        closing_attempts=FakeClosingAttemptsPort(latest=existing_close),
    )

    result = await handler.handle(signal_id)

    assert close_position.calls == []
    assert seeder.calls == [(signal_id, [prior_reservation_id], 0, True)]
    assert result.executed is True
    assert result.refused is None


async def test_a_retried_reverse_after_a_failed_close_does_not_place_a_new_one() -> None:
    """S6, "Edge case carried from S5b review": unlike a PLAIN close (spec:
    trade-execution § Retryable Close, Single In-Flight Attempt allows a
    fresh close after FAILED), the reverse-wiring release half must NOT
    retry on a replay after its own close already failed -- the poll=0
    continuation it already seeded has no way to learn about a brand-new
    close, so retrying here would leave the reverse ending flat with
    nothing above INFO logged (A6). It reports the same failure instead."""
    lock = SpyAdvisoryLock()
    close_position = SpyClosePosition()
    prior_reservation_id = uuid4()
    context = _holdable_reverse_context(prior_reservation_id=prior_reservation_id)
    failed_close = ExecutionAttempt(
        id=uuid4(),
        reservation_id=None,
        closes_allocation_id=prior_reservation_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="ETHUSDT.P",
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        quote_amount=None,
        leverage=None,
        status=ExecutionStatus.FAILED,
        client_order_id="client-1",
        error="rejected by venue",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
        closing_attempts=FakeClosingAttemptsPort(latest=failed_close),
    )

    result = await handler.handle(uuid4())

    assert close_position.calls == []
    assert result.executed is False
    assert result.failed == "rejected by venue"


async def test_a_plain_close_retried_after_a_committed_close_does_not_place_a_second() -> None:
    """The idempotent release half generalised to EVERY close path (spec:
    trade-execution § "A retried close is not re-sent"; design.md § S6) --
    not only the reverse-wiring one (S5b)."""
    lock = SpyAdvisoryLock()
    close_position = SpyClosePosition()
    strategy_id = uuid4()
    prior_reservation_id = uuid4()
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),  # long -> flat: RELEASES, not REVERSE
        prior_reservation_id=prior_reservation_id,
        settlement_currency="USDT",
    )
    existing_close = ExecutionAttempt(
        id=uuid4(),
        reservation_id=None,
        closes_allocation_id=prior_reservation_id,
        exchange="pionex",
        venue="spot",
        settlement_currency="USDT",
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        quote_amount=None,
        leverage=None,
        status=ExecutionStatus.SUBMITTED,
        client_order_id="client-1",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
        closing_attempts=FakeClosingAttemptsPort(latest=existing_close),
    )

    result = await handler.handle(uuid4())

    assert close_position.calls == []
    assert result.executed is True
    assert result.refused is None
    assert result.failed is None


async def test_a_plain_close_retried_after_a_failed_close_places_a_new_one() -> None:
    """A plain (non-reverse) close is not the reverse-wiring's own
    replay-safety carve-out -- nothing awaits it via a continuation, so a
    FAILED attempt does not block a retry (spec: trade-execution §
    Retryable Close, Single In-Flight Attempt)."""
    lock = SpyAdvisoryLock()
    close_position = SpyClosePosition()
    strategy_id = uuid4()
    prior_reservation_id = uuid4()
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        price=Decimal("2000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=prior_reservation_id,
        settlement_currency="USDT",
    )
    failed_close = ExecutionAttempt(
        id=uuid4(),
        reservation_id=None,
        closes_allocation_id=prior_reservation_id,
        exchange="pionex",
        venue="spot",
        settlement_currency="USDT",
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        quote_amount=None,
        leverage=None,
        status=ExecutionStatus.FAILED,
        client_order_id="client-1",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
        closing_attempts=FakeClosingAttemptsPort(latest=failed_close),
    )

    result = await handler.handle(uuid4())

    assert len(close_position.calls) == 1
    assert result.executed is True


async def test_a_rejected_holdable_reverse_close_is_reported_failed_not_refused() -> None:
    """If the close is definitively rejected, the open never happens (it is
    left awaiting a close that will never FILL); the failure is reported
    via ``failed``, not ``refused``."""
    lock = SpyAdvisoryLock()
    failed_result = CloseResult(
        status="FAILED", execution_attempt_id=uuid4(), base_size=Decimal("1"), error="rejected"
    )
    close_position = SpyClosePosition(result=failed_result)
    context = _holdable_reverse_context()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
    )

    result = await handler.handle(uuid4())

    assert result.executed is False
    assert result.failed == "rejected"
    assert result.refused is None


def _sized_handler(
    *,
    pool_total: Decimal,
    allocation_percent: Decimal,
    strategy_id: UUID,
    symbol: str = "ETHUSDT",
) -> tuple[ProcessSignalHandler, SpyAllocateCapital, SpyAdvisoryLock, SpyPlaceOrder]:
    """A CONSUMES-path handler whose ask is sized from ``pool_total`` and
    ``allocation_percent`` -- the two numbers whose product decides whether
    the request is strictly positive at all."""
    lock = SpyAdvisoryLock()
    policy = _snapshot(allocation_percent=allocation_percent)
    pool_balance = PoolBalance(
        total=pool_total, available=pool_total, min_order_size=Decimal("1")
    )
    allocate_capital = SpyAllocateCapital(
        _allocate_capital(lock, policy=policy, pool_balance=pool_balance)
    )
    place_order = SpyPlaceOrder()
    context = SignalContext(
        strategy_id=strategy_id,
        symbol=symbol,
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),  # open long -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        place_order=place_order,
        policy=policy,
        pool_balance=pool_balance,
    )
    return handler, allocate_capital, lock, place_order


async def test_an_empty_pool_refuses_before_allocating_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Production 2026-09-23: the owner moved their capital into "Earn", the
    pool snapshot read 0, ``requested = total * percent / 100`` was therefore
    zero, and ``AllocateCapital`` raised ``InvalidAllocationRequestError``
    ("requested amount must be positive"). Nothing on the signal path caught
    it, so the worker retried the identical zero at 30s, 60s, 120s and 240s
    before ending the job FAILED.

    An empty pool is a state of the world, not a transient fault: it is
    refused here, before the engine and before the pool's advisory lock, with
    one WARNING carrying every number the owner needs to tell an empty pool
    apart from a zero percent."""
    strategy_id = uuid4()
    handler, allocate_capital, lock, place_order = _sized_handler(
        pool_total=Decimal("0"), allocation_percent=Decimal("100"), strategy_id=strategy_id
    )

    with caplog.at_level("WARNING"):
        result = await handler.handle(uuid4())

    assert result.executed is False
    assert result.reservation_id is None
    assert result.refused is not None
    assert allocate_capital.calls == []
    assert lock.acquired == []
    assert place_order.calls == []
    warning = next(r for r in caplog.records if r.levelname == "WARNING")
    assert "(pionex, spot, USDT)" in warning.message
    assert str(strategy_id) in warning.message
    assert "ETHUSDT" in warning.message
    assert "0" in warning.message
    assert "100" in warning.message


async def test_a_zero_allocation_percent_refuses_before_allocating(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other way to reach a zero ask: a funded pool and a strategy
    configured at 0%. Same permanent condition, same refusal -- and the
    WARNING carries both numbers so the owner can tell which of the two it
    was without reading the database."""
    strategy_id = uuid4()
    handler, allocate_capital, lock, place_order = _sized_handler(
        pool_total=Decimal("1000"), allocation_percent=Decimal("0"), strategy_id=strategy_id
    )

    with caplog.at_level("WARNING"):
        result = await handler.handle(uuid4())

    assert result.executed is False
    assert result.refused is not None
    assert allocate_capital.calls == []
    assert lock.acquired == []
    assert place_order.calls == []
    warning = next(r for r in caplog.records if r.levelname == "WARNING")
    assert "1000" in warning.message
    assert "0" in warning.message


async def test_a_positive_request_still_allocates_exactly_as_before() -> None:
    """The guard must be a floor, not a change of behaviour: a funded pool at
    a non-zero percent reaches the engine, takes the lock and places the
    order exactly as it does today."""
    handler, allocate_capital, lock, place_order = _sized_handler(
        pool_total=Decimal("1000"), allocation_percent=Decimal("20"), strategy_id=uuid4()
    )

    result = await handler.handle(uuid4())

    assert len(allocate_capital.calls) == 1
    assert allocate_capital.calls[0].requested.amount == Decimal("200")
    assert len(lock.acquired) == 1
    assert len(place_order.calls) == 1
    assert result.executed is True
    assert result.refused is None


async def test_an_empty_pool_is_refused_rather_than_raised() -> None:
    """The refusal must be a RESULT, so ``handle_signal_process`` finishes
    normally and the job ends DONE rather than being retried into FAILED.

    The second half of this test is the defect itself: the very same request
    the handler now declines to make still raises out of the untouched
    engine. That is what the worker was retrying four times over eight
    minutes."""
    handler, _, _, _ = _sized_handler(
        pool_total=Decimal("0"), allocation_percent=Decimal("100"), strategy_id=uuid4()
    )

    result = await handler.handle(uuid4())

    assert result.refused is not None
    assert result.executed is False

    engine = _allocate_capital(
        SpyAdvisoryLock(),
        pool_balance=PoolBalance(
            total=Decimal("0"), available=Decimal("0"), min_order_size=Decimal("1")
        ),
    )
    with pytest.raises(InvalidAllocationRequestError):
        await engine.allocate(
            AllocateCommand(
                signal_id=uuid4(),
                strategy_id=uuid4(),
                requested=Money(amount=Decimal("0"), currency=Currency("USDT")),
            )
        )
