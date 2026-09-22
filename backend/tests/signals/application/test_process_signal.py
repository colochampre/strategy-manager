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
from strategy_manager.signals.application.holding_guard import (
    GuardOutcome,
    HoldingGuard,
    HoldingNotSettledYet,
)
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

    async def in_flight(
        self, pool: PoolKey, strategy_id: UUID, symbol: str, now: datetime
    ) -> bool:
        return self.result


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


async def test_in_flight_work_raises_and_never_allocates() -> None:
    """``HoldingNotSettledYet`` must propagate out of ``handle`` uncaught --
    the queue's own backoff is what retries it."""
    lock = SpyAdvisoryLock()
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
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(lock),
        place_order=SpyPlaceOrder(),
        holding_guard=guard,
    )

    try:
        await handler.handle(uuid4())
        raised = False
    except HoldingNotSettledYet:
        raised = True

    assert raised is True
    assert lock.acquired == []


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
