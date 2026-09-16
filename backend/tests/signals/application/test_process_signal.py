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

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.allocation.application.allocate_capital import AllocateCapital
from strategy_manager.allocation.application.ports import PoolBalance, StrategyPolicySnapshot
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.execution.application.close_position import (
    CloseCommand,
    CloseResult,
)
from strategy_manager.execution.application.place_order import PlaceCommand, PlaceResult
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.shared.domain.money import Exchange
from strategy_manager.signals.application.process_signal import (
    ProcessSignalHandler,
    SignalContext,
)


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

    def __init__(self) -> None:
        self.calls: list[CloseCommand] = []

    async def close(self, command: CloseCommand) -> CloseResult:
        self.calls.append(command)
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


TRADABLE = frozenset({"spot"})


def _snapshot(**overrides: object) -> StrategyPolicySnapshot:
    defaults: dict[str, object] = dict(
        strategy_id=uuid4(),
        enabled=True,
        fill_mode="PARTIAL",
        venue="spot",
        settlement_currency="USDT",
        allocation_percent=Decimal("100"),
    )
    defaults.update(overrides)
    return StrategyPolicySnapshot(exchange=Exchange.BYBIT, **defaults)  # type: ignore[arg-type]


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


def _process_signal_handler(
    *,
    context: SignalContext,
    allocate_capital: AllocateCapital,
    place_order: SpyPlaceOrder,
    close_position: SpyClosePosition | None = None,
    policy: StrategyPolicySnapshot | None = None,
    pool_balance: PoolBalance | None = None,
    tradable_venues: frozenset[str] = TRADABLE,
) -> ProcessSignalHandler:
    return ProcessSignalHandler(
        signal_context=FakeSignalContextPort(context),
        strategy_policy=FakeStrategyPolicyPort(policy or _snapshot()),
        pool_balance=FakePoolBalancePort(
            pool_balance or PoolBalance(
                total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("1")
            )
        ),
        allocate_capital=allocate_capital,
        place_order=place_order,
        close_position=close_position or SpyClosePosition(),
        tradable_venues=tradable_venues,
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
        tradable_venues=frozenset({"spot"}),
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
