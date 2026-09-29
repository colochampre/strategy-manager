"""Decision 25, tasks 5b.4: every refusal of ``ProcessSignalHandler`` (rows
1-7 of the outcome map) ends the signal ``REJECTED`` with its stable code and
the human message already logged for it, written on the SAME session
immediately before the commit that makes it durable (design.md "Addendum:
signal outcomes" § B, § C, § E).

Fakes throughout; the durable-commit proof for one row runs on real
PostgreSQL in ``test_process_signal_outcomes_integration.py``.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.allocation.application.ports import PoolBalance
from strategy_manager.signals.application.ports import RefreshOutcome, RefreshStatus
from strategy_manager.signals.application.process_signal import SignalContext
from strategy_manager.signals.domain.holding import HeldAllocation
from strategy_manager.signals.domain.outcome import SignalOutcome
from tests.signals.application.test_process_signal import (
    FakeBalanceRefreshPort,
    SpyAdvisoryLock,
    SpyClosePosition,
    SpyPlaceOrder,
    _allocate_capital,
    _holdable_reverse_context,
    _holding_guard,
    _process_signal_handler,
    _snapshot,
)
from tests.signals.fakes import RecordingSignalOutcomes


@dataclass
class OrderingCommit:
    """Records how many outcomes were already staged at each commit, so a
    test can prove the write came BEFORE the commit (same-commit rule)."""

    outcomes: RecordingSignalOutcomes
    staged_at_commit: list[int] = field(default_factory=list)

    async def commit(self) -> None:
        self.staged_at_commit.append(len(self.outcomes.calls))


def _open_context(symbol: str = "ETHUSDT", received_at: datetime | None = None) -> SignalContext:
    kwargs = {} if received_at is None else {"received_at": received_at}
    return SignalContext(
        strategy_id=uuid4(),
        symbol=symbol,
        price=Decimal("2000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),  # open long -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
        **kwargs,  # type: ignore[arg-type]
    )


def _assert_rejected_once(
    outcomes: RecordingSignalOutcomes,
    commit: OrderingCommit,
    signal_id: object,
    code: str,
    detail: str | None,
) -> None:
    assert outcomes.calls == [(signal_id, SignalOutcome.rejected(code, detail))]
    # the write was staged before the (single) commit that makes it durable
    assert commit.staged_at_commit == [1]


async def test_untradable_pool_ends_rejected_with_its_code_and_message() -> None:
    outcomes = RecordingSignalOutcomes()
    commit = OrderingCommit(outcomes)
    handler = _process_signal_handler(
        context=_open_context(),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        tradable_pools=frozenset({("bybit", "linear")}),
        outcomes=outcomes,
        commit=commit,
    )
    signal_id = uuid4()

    result = await handler.handle(signal_id)

    _assert_rejected_once(outcomes, commit, signal_id, "UNTRADABLE_POOL", result.refused)


async def test_archived_strategy_ends_rejected_with_its_code_and_message() -> None:
    outcomes = RecordingSignalOutcomes()
    commit = OrderingCommit(outcomes)
    context = _open_context()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        policy=_snapshot(strategy_id=context.strategy_id, name="stx-grid", archived=True),
        outcomes=outcomes,
        commit=commit,
    )
    signal_id = uuid4()

    result = await handler.handle(signal_id)

    _assert_rejected_once(outcomes, commit, signal_id, "STRATEGY_ARCHIVED", result.refused)


async def test_unlisted_pair_ends_rejected_with_its_code_and_message() -> None:
    outcomes = RecordingSignalOutcomes()
    commit = OrderingCommit(outcomes)
    handler = _process_signal_handler(
        # TradingView spelling on the signal; the allowlist holds market keys.
        context=_open_context(symbol="STXUSDT.P"),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        policy=_snapshot(allowed_pairs=frozenset({"ETHUSDT"})),
        outcomes=outcomes,
        commit=commit,
    )
    signal_id = uuid4()

    result = await handler.handle(signal_id)

    _assert_rejected_once(outcomes, commit, signal_id, "PAIR_NOT_ALLOWED", result.refused)


@pytest.mark.parametrize(
    ("venue_net", "code"),
    [
        (Decimal("0"), "DIVERGENT_HOLDING_GHOST"),
        (None, "DIVERGENT_HOLDING_AMBIGUOUS"),
    ],
)
async def test_divergent_holding_ends_rejected_with_ghost_or_ambiguous_code(
    venue_net: Decimal | None, code: str
) -> None:
    outcomes = RecordingSignalOutcomes()
    commit = OrderingCommit(outcomes)
    context = _open_context()
    guard = _holding_guard(
        holdings=[
            HeldAllocation(
                strategy_id=context.strategy_id, allocation_id=uuid4(), net_base=Decimal("0.4")
            )
        ],
        venue_net=venue_net,
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        holding_guard=guard,
        outcomes=outcomes,
        commit=commit,
    )
    signal_id = uuid4()

    result = await handler.handle(signal_id)

    _assert_rejected_once(outcomes, commit, signal_id, code, result.refused)


async def test_in_flight_work_past_the_age_bound_ends_rejected_in_flight_timeout() -> None:
    outcomes = RecordingSignalOutcomes()
    commit = OrderingCommit(outcomes)
    # The guard's clock reads 2026-01-01; the signal is a month older than
    # the 600s bound.
    received_at = datetime(2026, 1, 1, tzinfo=UTC) - timedelta(days=30)
    handler = _process_signal_handler(
        context=_open_context(received_at=received_at),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        holding_guard=_holding_guard(in_flight=True),
        outcomes=outcomes,
        commit=commit,
    )
    signal_id = uuid4()

    result = await handler.handle(signal_id)

    _assert_rejected_once(outcomes, commit, signal_id, "IN_FLIGHT_TIMEOUT", result.refused)


async def test_unavailable_balance_ends_rejected_balance_unavailable() -> None:
    outcomes = RecordingSignalOutcomes()
    commit = OrderingCommit(outcomes)
    handler = _process_signal_handler(
        context=_open_context(),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        balance_refresh=FakeBalanceRefreshPort(
            outcome=RefreshOutcome(
                status=RefreshStatus.UNAVAILABLE, age_seconds=120.0, reason="timed out"
            )
        ),
        outcomes=outcomes,
        commit=commit,
    )
    signal_id = uuid4()

    result = await handler.handle(signal_id)

    _assert_rejected_once(outcomes, commit, signal_id, "BALANCE_UNAVAILABLE", result.refused)


async def test_a_request_that_sizes_to_nothing_ends_rejected_nothing_to_allocate() -> None:
    outcomes = RecordingSignalOutcomes()
    commit = OrderingCommit(outcomes)
    policy = _snapshot(allocation_percent=Decimal("0"))
    pool_balance = PoolBalance(
        total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("1")
    )
    handler = _process_signal_handler(
        context=_open_context(),
        allocate_capital=_allocate_capital(
            SpyAdvisoryLock(), policy=policy, pool_balance=pool_balance
        ),
        place_order=SpyPlaceOrder(),
        policy=policy,
        pool_balance=pool_balance,
        outcomes=outcomes,
        commit=commit,
    )
    signal_id = uuid4()

    result = await handler.handle(signal_id)

    _assert_rejected_once(outcomes, commit, signal_id, "NOTHING_TO_ALLOCATE", result.refused)


async def test_reverse_open_half_refused_after_the_close_executed_says_so() -> None:
    """Decision 26 (design.md § E): the open half of a REVERSE runs in the
    continuation (``open_now``) once the close has executed. If that open is
    refused -- here ``PAIR_NOT_ALLOWED`` -- the signal is ``REJECTED`` with
    the OPEN reason, and the detail states the close executed."""
    outcomes = RecordingSignalOutcomes()
    commit = OrderingCommit(outcomes)
    handler = _process_signal_handler(
        # Perpetual, TradingView spelling; the pair is no longer allowed.
        context=_holdable_reverse_context(symbol="STXUSDT.P"),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        close_position=SpyClosePosition(),
        policy=_snapshot(allowed_pairs=frozenset({"ETHUSDT"})),
        outcomes=outcomes,
        commit=commit,
    )
    signal_id = uuid4()

    result = await handler.open_now(signal_id, poll=0)

    assert result.refused is not None
    assert len(outcomes.calls) == 1
    recorded_id, outcome = outcomes.calls[0]
    assert recorded_id == signal_id
    assert outcome.reason == "PAIR_NOT_ALLOWED"
    assert outcome.detail is not None
    assert result.refused in outcome.detail
    assert "close" in outcome.detail and "executed" in outcome.detail
    assert commit.staged_at_commit == [1]


async def test_a_plain_open_refusal_in_open_now_does_not_claim_a_close_executed() -> None:
    """The close note is REVERSE-only: an open deferred behind in-flight work
    or an orphan close is not a REVERSE and must not say a close executed."""
    outcomes = RecordingSignalOutcomes()
    handler = _process_signal_handler(
        context=_open_context(symbol="STXUSDT.P"),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        policy=_snapshot(allowed_pairs=frozenset({"ETHUSDT"})),
        outcomes=outcomes,
    )

    result = await handler.open_now(uuid4(), poll=0)

    assert len(outcomes.calls) == 1
    _, outcome = outcomes.calls[0]
    assert outcome.reason == "PAIR_NOT_ALLOWED"
    assert outcome.detail == result.refused


async def test_reverse_archived_refusal_at_handle_time_does_not_claim_a_close_executed() -> None:
    """From ``handle()`` the archived refusal fires BEFORE the close half is
    placed, so even for a REVERSE nothing executed and the detail must not
    say otherwise."""
    outcomes = RecordingSignalOutcomes()
    context = _holdable_reverse_context()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        policy=_snapshot(strategy_id=context.strategy_id, archived=True),
        outcomes=outcomes,
    )

    result = await handler.handle(uuid4())

    assert len(outcomes.calls) == 1
    _, outcome = outcomes.calls[0]
    assert outcome.reason == "STRATEGY_ARCHIVED"
    assert outcome.detail == result.refused
