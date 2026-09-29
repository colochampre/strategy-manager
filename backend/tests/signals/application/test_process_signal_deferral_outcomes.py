"""Decision 25, task 5b.8: the two DEFERRALS of ``ProcessSignalHandler``
leave the signal ``PROCESSING`` (design.md "Addendum: signal outcomes" C).

``_handle_consumes`` hands the open to the ``signal.open_after_close``
continuation in exactly two places: the in-flight wait (work not yet
settled, not yet timed out) and a REAL orphan that ``CloseOrphans`` closes.
Neither decides the signal, so both write ``PROCESSING`` -- on the commit
that makes the continuation seed durable, never a later transaction.

Fakes throughout. The shared ``Timeline`` records the order in which the
handler staged the seed, the interim status and the commit, which is what
proves the same-commit rule without a database.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.signals.application.process_signal import SignalContext
from strategy_manager.signals.domain.holding import HeldAllocation
from strategy_manager.signals.domain.outcome import SignalOutcome
from tests.signals.application.test_process_signal import (
    SpyAdvisoryLock,
    SpyCloseOrphans,
    SpyContinuationSeeder,
    SpyPlaceOrder,
    _allocate_capital,
    _holding_guard,
    _process_signal_handler,
)
from tests.signals.application.test_process_signal_order_outcomes import (
    Timeline,
    TimelineCommit,
    TimelineOutcomes,
)
from tests.signals.fakes import RecordingSignalOutcomes


class TimelineSeeder(SpyContinuationSeeder):
    def __init__(self, timeline: Timeline) -> None:
        super().__init__()
        self._timeline = timeline

    async def seed(
        self,
        signal_id: UUID,
        awaited_allocation_ids: list[UUID],
        poll: int = 0,
        *,
        replay_expected: bool = False,
    ) -> bool:
        self._timeline.log.append("seed")
        return await super().seed(
            signal_id, awaited_allocation_ids, poll, replay_expected=replay_expected
        )


class TimelineCloseOrphans(SpyCloseOrphans):
    def __init__(self, timeline: Timeline) -> None:
        super().__init__()
        self._timeline = timeline

    async def close(
        self,
        signal_id: UUID,
        pool: tuple[str, str, str],
        strategy_id: UUID,
        symbol: str,
        holdings: list[HeldAllocation],
        next_poll: int = 0,
    ) -> None:
        self._timeline.log.append("close_orphans")
        await super().close(signal_id, pool, strategy_id, symbol, holdings, next_poll)


def _open_context(symbol: str = "ETHUSDT") -> SignalContext:
    return SignalContext(
        strategy_id=uuid4(),
        symbol=symbol,
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),  # open long -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# ---- 5b.8: the two deferrals leave the signal PROCESSING -------------------


async def test_the_in_flight_wait_leaves_the_signal_processing_on_the_seed_commit() -> None:
    timeline = Timeline()
    outcomes = TimelineOutcomes(timeline)
    signal_id = uuid4()
    handler = _process_signal_handler(
        context=_open_context(),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        holding_guard=_holding_guard(in_flight=True),
        open_after_close=TimelineSeeder(timeline),
        outcomes=outcomes,
        commit=TimelineCommit(timeline),
    )

    result = await handler.handle(signal_id)

    assert result.executed is False and result.refused is None
    assert outcomes.calls == [(signal_id, SignalOutcome.processing())]
    # the seed, the interim status and the ONE commit that makes both durable
    assert timeline.log == ["seed", "outcome.processing", "commit"]


async def test_a_re_deferral_from_open_now_records_processing_again_on_its_seed_commit() -> None:
    """``open_now`` can defer AGAIN (more work now in flight). Still the same
    status, still on the commit that makes the poll+1 seed durable; PROCESSING
    over PROCESSING is the one write the terminal guard always allows."""
    timeline = Timeline()
    outcomes = TimelineOutcomes(timeline)
    signal_id = uuid4()
    seeder = TimelineSeeder(timeline)
    handler = _process_signal_handler(
        context=_open_context(),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        holding_guard=_holding_guard(in_flight=True),
        open_after_close=seeder,
        outcomes=outcomes,
        commit=TimelineCommit(timeline),
    )

    await handler.open_now(signal_id, poll=2)

    assert seeder.calls == [(signal_id, [], 3, False)]
    assert outcomes.calls == [(signal_id, SignalOutcome.processing())]
    assert timeline.log == ["seed", "outcome.processing", "commit"]


async def test_a_real_orphan_close_leaves_the_signal_processing_before_the_close_commits() -> None:
    """``CloseOrphans`` stages the seed and then commits inside each close (or
    once at the end), so the interim status is staged BEFORE it is called and
    rides that same first commit."""
    timeline = Timeline()
    outcomes = TimelineOutcomes(timeline)
    strategy_id, signal_id = uuid4(), uuid4()
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
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        # L_S = L_P = 0.5, V = 0.5 -> REAL
        holding_guard=_holding_guard(holdings=[own_holding], venue_net=Decimal("0.5")),
        close_orphans=TimelineCloseOrphans(timeline),
        outcomes=outcomes,
        commit=TimelineCommit(timeline),
    )

    result = await handler.handle(signal_id)

    assert result.executed is False and result.refused is None
    assert outcomes.calls == [(signal_id, SignalOutcome.processing())]
    assert timeline.log == ["outcome.processing", "close_orphans"]


async def test_a_proceeding_open_records_nothing_of_its_own() -> None:
    """Triangulation: with nothing in flight and no orphan the handler
    allocates and places -- and PlaceOrder, not the handler, owns that
    outcome, so the handler itself writes nothing on this path."""
    outcomes = RecordingSignalOutcomes()
    place_order = SpyPlaceOrder()
    handler = _process_signal_handler(
        context=_open_context(),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=place_order,
        outcomes=outcomes,
    )

    await handler.handle(uuid4())

    assert len(place_order.calls) == 1
    assert outcomes.calls == []
