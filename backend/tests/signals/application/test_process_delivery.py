"""``ProcessDelivery`` works one signal for ONE subscription (tasks.md C.6).

The tests of ``test_process_signal.py`` model a world with a single subscriber, the
strategy's author. These pin what only a SECOND subscriber can: every read and
write of a delivery is made as the delivery's user (never the strategy's author),
the ask is sized from the subscription's share (never the strategy's), the halves
run are the payload's, and a payload with none is refused loudly.

A subscriber that is not the author is what makes each switch observable: with the
two the same user, a read left on ``policy.author_id`` would pass every test.
"""

import logging
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.allocation.application.ports import PoolBalance, StrategyPolicySnapshot
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.signals.application.fan_out_signal import DeliveryHalves
from strategy_manager.signals.application.holding_guard import GuardOutcome
from strategy_manager.signals.application.process_signal import (
    Delivery,
    ProcessDelivery,
    SignalContext,
)
from strategy_manager.signals.domain.holding import HeldAllocation
from strategy_manager.signals.domain.outcome import SignalOutcome
from tests.allocation.fakes import FixedUserMode, RecordedModes
from tests.owner import OWNER_ID
from tests.signals.application.test_process_signal import (
    TRADABLE,
    FakeBalanceRefreshPort,
    FakeClosingAttemptsPort,
    FakeCommit,
    FakeInFlightWorkPort,
    FakePoolBalancePort,
    FakeSignalContextPort,
    FakeStrategyPolicyPort,
    FakeSymbolHoldingsPort,
    FakeVenueNetPositionPort,
    FrozenClock,
    SpyAdvisoryLock,
    SpyAllocateCapital,
    SpyCloseOrphans,
    SpyClosePosition,
    SpyContinuationSeeder,
    SpyPlaceOrder,
    _allocate_capital,
    _open_long_context,
    _snapshot,
)
from tests.signals.fakes import FakeTradeCapability, RecordingSignalOutcomes, in_both_modes

AUTHOR = OWNER_ID
SUBSCRIBER = UUID("5b5b5b5b-0000-4000-8000-0000000000c1")
SUBSCRIPTION = UUID("5b5b5b5b-0000-4000-8000-0000000000c2")
DELIVERY = UUID("5b5b5b5b-0000-4000-8000-0000000000c3")
SIGNAL = UUID("5b5b5b5b-0000-4000-8000-0000000000c4")
PRIOR_RESERVATION = UUID("5b5b5b5b-0000-4000-8000-0000000000c5")

# The delivery carries the subscription's 25%: sizing from anything else (a full
# share) would ask for 1000, not 250.
SUBSCRIPTION_SHARE = Decimal("25")
POOL_TOTAL = Decimal("1000")

_REVERSE_SYMBOL = "ETHUSDT.P"


class _Deliveries:
    def __init__(self, delivery: Delivery) -> None:
        self._delivery = delivery
        self.loaded: list[UUID] = []

    async def load(self, delivery_id: UUID) -> Delivery:
        self.loaded.append(delivery_id)
        return self._delivery

class _OrphanGuard:
    """A guard that reports a REAL orphan, remembering whose holding it was asked
    about."""

    def __init__(self, holdings: list[HeldAllocation]) -> None:
        self.holdings = holdings
        self.users: list[UUID] = []

    async def check(self, **kwargs: object) -> GuardOutcome:
        self.users.append(kwargs["user_id"])  # type: ignore[arg-type]
        return GuardOutcome(proceed=False, real_orphan_holdings=self.holdings)


@dataclass
class Rig:
    handler: ProcessDelivery
    deliveries: _Deliveries
    refresh: FakeBalanceRefreshPort
    sizing: FakePoolBalancePort
    capability: FakeTradeCapability
    in_flight: FakeInFlightWorkPort
    closing: FakeClosingAttemptsPort
    allocate: SpyAllocateCapital
    place: SpyPlaceOrder
    close: SpyClosePosition
    seeder: SpyContinuationSeeder
    orphans: SpyCloseOrphans
    outcomes: RecordingSignalOutcomes


def _rig(
    context: SignalContext,
    *,
    policy: StrategyPolicySnapshot | None = None,
    guard: object | None = None,
) -> Rig:
    from strategy_manager.signals.application.holding_guard import HoldingGuard

    policy = policy or _snapshot(author_id=AUTHOR)
    delivery = Delivery(
        delivery_id=DELIVERY,
        signal_id=SIGNAL,
        subscription_id=SUBSCRIPTION,
        user_id=SUBSCRIBER,
        allocation_percent=SUBSCRIPTION_SHARE,
    )
    deliveries = _Deliveries(delivery)
    balance = PoolBalance(total=POOL_TOTAL, available=POOL_TOTAL, min_order_size=Decimal("1"))
    refresh = FakeBalanceRefreshPort()
    sizing = FakePoolBalancePort(balance)
    capability = FakeTradeCapability()
    in_flight = FakeInFlightWorkPort()
    closing = FakeClosingAttemptsPort()
    allocate = SpyAllocateCapital(
        _allocate_capital(SpyAdvisoryLock(), policy=policy, pool_balance=balance)
    )
    place = SpyPlaceOrder()
    close = SpyClosePosition()
    seeder = SpyContinuationSeeder()
    orphans = SpyCloseOrphans()
    outcomes = RecordingSignalOutcomes()
    handler = ProcessDelivery(
        deliveries=deliveries,
        signal_context=FakeSignalContextPort(context),
        strategy_policy=FakeStrategyPolicyPort(policy),
        pool_balance=sizing,
        holding_guard=guard  # type: ignore[arg-type]
        or HoldingGuard(
            holdings=FakeSymbolHoldingsPort([]),
            in_flight_work=in_flight,
            venue_net_position=in_both_modes(FakeVenueNetPositionPort(None)),
            allocation_modes=RecordedModes(),
            clock=FrozenClock(context.received_at),
            delayed_open_max_signal_age_seconds=600.0,
        ),
        balance_refresh=refresh,
        allocate_capital=allocate,
        place_order=place,
        close_position=close,
        open_after_close=seeder,
        commit=FakeCommit(),
        closing_attempts=closing,
        close_orphans=orphans,
        tradable_pools=in_both_modes(TRADABLE),
        outcomes=outcomes,
        trade_capability=capability,
        user_mode=FixedUserMode(),
        allocation_modes=RecordedModes(),
    )
    return Rig(
        handler,
        deliveries,
        refresh,
        sizing,
        capability,
        in_flight,
        closing,
        allocate,
        place,
        close,
        seeder,
        orphans,
        outcomes,
    )


def _close_context(symbol: str = "BTCUSDT") -> SignalContext:
    return SignalContext(
        strategy_id=uuid4(),
        symbol=symbol,
        price=Decimal("50000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=PRIOR_RESERVATION,
        settlement_currency="USDT",
    )


def _reverse_context() -> SignalContext:
    return SignalContext(
        strategy_id=uuid4(),
        symbol=_REVERSE_SYMBOL,
        price=Decimal("2000"),
        position_size=Decimal("-1"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=PRIOR_RESERVATION,
        settlement_currency="USDT",
    )


# --- the delivery's user, never the author ----------------------------------------


async def _opened() -> Rig:
    rig = _rig(_open_long_context())
    result = await rig.handler.handle(DELIVERY, "open")
    assert result.executed is True
    assert rig.deliveries.loaded == [DELIVERY]
    return rig


async def test_the_trade_capability_asked_about_is_the_deliverys_users() -> None:
    rig = await _opened()

    assert rig.capability.users == [SUBSCRIBER]


async def test_the_existing_position_guard_asks_about_the_deliverys_users_work() -> None:
    rig = await _opened()

    assert rig.in_flight.users
    assert set(rig.in_flight.users) == {SUBSCRIBER}


async def test_the_balance_refresh_is_of_the_deliverys_users_pool() -> None:
    rig = await _opened()

    assert rig.refresh.users == [SUBSCRIBER]


async def test_the_sizing_read_is_of_the_deliverys_users_pool() -> None:
    rig = await _opened()

    assert rig.sizing.users == [SUBSCRIBER]


async def test_the_allocation_is_asked_for_the_deliverys_user_delivery_and_signal() -> None:
    rig = await _opened()

    assert [call.user_id for call in rig.allocate.calls] == [SUBSCRIBER]
    assert [call.delivery_id for call in rig.allocate.calls] == [DELIVERY]
    assert [call.signal_id for call in rig.allocate.calls] == [SIGNAL]


async def test_the_order_is_placed_as_the_deliverys_user() -> None:
    rig = await _opened()

    assert [call.user_id for call in rig.place.calls] == [SUBSCRIBER]


async def test_the_ask_is_the_subscriptions_share_of_the_pool_not_the_strategys() -> None:
    rig = _rig(_open_long_context())

    await rig.handler.handle(DELIVERY, "open")

    assert [call.requested.amount for call in rig.allocate.calls] == [
        POOL_TOTAL * SUBSCRIPTION_SHARE / Decimal("100")
    ]


async def _closed() -> Rig:
    rig = _rig(_close_context())
    result = await rig.handler.handle(DELIVERY, "close")
    assert result.executed is True
    assert rig.allocate.calls == []
    return rig


async def test_the_existing_close_lookup_is_the_deliverys_users() -> None:
    rig = await _closed()

    assert rig.closing.users == [SUBSCRIBER]
    assert rig.closing.calls == [PRIOR_RESERVATION]


async def test_a_close_is_placed_as_the_deliverys_user_against_its_prior_reservation() -> None:
    rig = await _closed()

    assert [call.user_id for call in rig.close.calls] == [SUBSCRIBER]
    assert [call.allocation_id for call in rig.close.calls] == [PRIOR_RESERVATION]
    assert [call.signal_id for call in rig.close.calls] == [SIGNAL]


async def test_a_real_orphan_is_closed_as_the_deliverys_user() -> None:
    guard = _OrphanGuard(
        [HeldAllocation(allocation_id=uuid4(), strategy_id=uuid4(), net_base=Decimal("1"))]
    )
    rig = _rig(_open_long_context(), guard=guard)

    await rig.handler.handle(DELIVERY, "open")

    assert guard.users == [SUBSCRIBER]
    assert rig.orphans.users == [SUBSCRIBER]
    assert rig.place.calls == []


# --- the outcome is the delivery's (tasks.md C.7) ---------------------------------


async def test_the_order_command_names_the_delivery_it_serves() -> None:
    rig = await _opened()

    assert [call.delivery_id for call in rig.place.calls] == [DELIVERY]
    assert DELIVERY != SIGNAL


async def test_the_close_command_names_the_delivery_beside_the_signal() -> None:
    rig = await _closed()

    assert [call.delivery_id for call in rig.close.calls] == [DELIVERY]
    assert [call.signal_id for call in rig.close.calls] == [SIGNAL]


async def test_a_refusal_ends_the_delivery_never_the_signal() -> None:
    rig = _rig(replace(_close_context(), prior_reservation_id=None))

    result = await rig.handler.handle(DELIVERY, "close")

    assert result.executed is False
    [(row_id, outcome)] = rig.outcomes.calls
    assert row_id == DELIVERY
    assert outcome.reason == "NO_POSITION_TO_CLOSE"
    assert rig.outcomes.unless_terminal_calls == []


async def test_a_real_orphan_leaves_the_delivery_processing_while_it_closes_the_orphan() -> None:
    guard = _OrphanGuard(
        [HeldAllocation(allocation_id=uuid4(), strategy_id=uuid4(), net_base=Decimal("1"))]
    )
    rig = _rig(_open_long_context(), guard=guard)

    await rig.handler.handle(DELIVERY, "open")

    assert rig.outcomes.calls == [(DELIVERY, SignalOutcome.processing())]


# --- the halves are the payload's -------------------------------------------------


async def test_a_reverse_delivered_as_open_only_opens_and_closes_nothing() -> None:
    """A subscription that holds nothing gets only the opening half of a reverse."""
    rig = _rig(_reverse_context())

    result = await rig.handler.handle(DELIVERY, DeliveryHalves.OPEN.value)

    assert result.executed is True
    assert rig.close.calls == []
    assert rig.closing.calls == []
    assert [call.side for call in rig.place.calls] == [OrderSide.SELL]


async def test_a_reverse_delivered_as_close_only_closes_and_never_opens_or_seeds() -> None:
    """A LEAVING subscription closes alone: no open to wait for the close."""
    rig = _rig(_reverse_context())

    result = await rig.handler.handle(DELIVERY, DeliveryHalves.CLOSE.value)

    assert result.executed is True
    assert [call.allocation_id for call in rig.close.calls] == [PRIOR_RESERVATION]
    assert rig.seeder.calls == []
    assert rig.place.calls == []
    assert rig.allocate.calls == []


async def test_a_reverse_delivered_as_both_closes_and_seeds_the_open() -> None:
    rig = _rig(_reverse_context())

    await rig.handler.handle(DELIVERY, DeliveryHalves.BOTH.value)

    assert [call.allocation_id for call in rig.close.calls] == [PRIOR_RESERVATION]
    # The continuation is seeded for the DELIVERY, whose id is not the signal's.
    assert [call[:3] for call in rig.seeder.calls] == [(DELIVERY, [PRIOR_RESERVATION], 0)]
    assert rig.place.calls == []


# --- the continuation is the delivery's (tasks.md C.8) ----------------------------


def _live_close(allocation_id: UUID, status: ExecutionStatus) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=uuid4(),
        reservation_id=None,
        closes_allocation_id=allocation_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=_REVERSE_SYMBOL,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        quote_amount=None,
        leverage=None,
        status=status,
        origin=ExecutionOrigin.SYSTEM,
        client_order_id=f"client-{allocation_id}",
        delivery_id=DELIVERY,
    )


async def test_a_replayed_reverse_reseeds_the_continuation_for_the_delivery() -> None:
    """A close that already exists (a redelivered job) re-seeds the SAME step, for the
    delivery, so the idempotent replay lands on the key it already committed."""
    rig = _rig(_reverse_context())
    rig.closing.latest = _live_close(PRIOR_RESERVATION, ExecutionStatus.SUBMITTED)

    await rig.handler.handle(DELIVERY, DeliveryHalves.BOTH.value)

    assert rig.close.calls == []
    assert rig.seeder.calls == [(DELIVERY, [PRIOR_RESERVATION], 0, True)]


async def test_the_in_flight_deferral_seeds_the_continuation_for_the_delivery() -> None:
    rig = _rig(_open_long_context())
    rig.in_flight.result = True

    result = await rig.handler.handle(DELIVERY, "open")

    assert result.executed is False
    assert [call[:3] for call in rig.seeder.calls] == [(DELIVERY, [], 0)]
    assert rig.place.calls == []


async def test_a_real_orphan_is_closed_on_behalf_of_the_delivery_not_the_signal() -> None:
    guard = _OrphanGuard(
        [HeldAllocation(allocation_id=uuid4(), strategy_id=uuid4(), net_base=Decimal("1"))]
    )
    rig = _rig(_open_long_context(), guard=guard)

    await rig.handler.handle(DELIVERY, "open")

    assert [call[0] for call in rig.orphans.calls] == [DELIVERY]


async def test_open_now_opens_for_the_delivery_it_is_given_in_its_users_pool_and_share() -> None:
    """The continuation's entry point loads the DELIVERY (a subscriber who is not the
    author, at their own share), not the strategy author's delivery of the signal."""
    rig = _rig(_open_long_context())

    result = await rig.handler.open_now(DELIVERY, poll=2)

    assert result.executed is True
    assert rig.deliveries.loaded == [DELIVERY]
    assert rig.capability.users == [SUBSCRIBER]
    assert rig.refresh.users == [SUBSCRIBER]
    assert [call.user_id for call in rig.allocate.calls] == [SUBSCRIBER]
    assert [call.delivery_id for call in rig.allocate.calls] == [DELIVERY]
    assert [call.signal_id for call in rig.allocate.calls] == [SIGNAL]
    assert [call.requested.amount for call in rig.allocate.calls] == [
        POOL_TOTAL * SUBSCRIPTION_SHARE / Decimal("100")
    ]
    assert [call.user_id for call in rig.place.calls] == [SUBSCRIBER]
    assert [call.delivery_id for call in rig.place.calls] == [DELIVERY]


async def test_open_now_deferring_again_seeds_the_next_poll_for_the_delivery() -> None:
    rig = _rig(_open_long_context())
    rig.in_flight.result = True

    await rig.handler.open_now(DELIVERY, poll=2)

    assert [call[:3] for call in rig.seeder.calls] == [(DELIVERY, [], 3)]


# --- no usable halves is refused, loudly ------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "both", 3, {"halves": "open"}])
async def test_a_payload_without_usable_halves_is_refused_loudly_and_runs_nothing(
    raw: object, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR, logger="strategy_manager.signals.application.process_signal")
    rig = _rig(_open_long_context())

    result = await rig.handler.handle(DELIVERY, raw)

    assert result.executed is False
    assert result.refused is not None and str(DELIVERY) in result.refused
    assert rig.allocate.calls == []
    assert rig.place.calls == []
    assert rig.close.calls == []
    assert [outcome.reason for _, outcome in rig.outcomes.calls] == ["DELIVERY_HALVES_MISSING"]
    assert [row_id for row_id, _ in rig.outcomes.calls] == [DELIVERY]
    assert [record.levelname for record in caplog.records] == ["ERROR"]


@pytest.mark.parametrize(
    ("context", "halves"),
    [
        (_open_long_context(), "close"),
        (_open_long_context(), "close_and_open"),
        (_close_context(), "open"),
        (_close_context(), "close_and_open"),
        (_reverse_context(), "bogus"),
    ],
    ids=["open-told-close", "open-told-both", "close-told-open", "close-told-both", "bogus"],
)
async def test_halves_the_signal_contradicts_run_nothing(
    context: SignalContext, halves: str
) -> None:
    rig = _rig(replace(context, strategy_id=uuid4()))

    result = await rig.handler.handle(DELIVERY, halves)

    assert result.executed is False
    assert rig.allocate.calls == []
    assert rig.place.calls == []
    assert rig.close.calls == []
    assert len(rig.outcomes.calls) == 1
