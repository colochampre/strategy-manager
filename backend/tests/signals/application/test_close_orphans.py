"""Unit tests: ``CloseOrphans``, the REAL branch of ``HoldingGuard``
(design.md § S6; spec: capital-allocation § Real-Orphan Resolution via
Close-Then-Open).

Fakes only -- no database. ``ClosePosition`` itself is proven in
``tests/execution/application/test_close_position.py``; here it is a spy, so
these tests exercise only ``CloseOrphans``'s OWN wiring: seed-before-close
ordering, per-allocation side, the idempotent skip, what happens when every
allocation is already idempotently skipped, and the REQUIRED INVARIANT an
orchestrator review of `ee640d6` found broken: a close is never placed
without a continuation guaranteed to await it (``FakeContinuationSeeder``
below mimics ``enqueue_unique``'s own dedupe semantics so a genuine seed
collision can be rehearsed, not just asserted about in the abstract).

**Binding testing lesson**: ``ETHUSDT.P`` (guard/signal side) and
``ETHUSDT`` (execution-attempt/ledger side) are used on opposite sides of
the module boundary in the invariant tests below, the same spelling pair
``test_holding_guard.py`` already established.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.close_position import CloseCommand, CloseResult
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.signals.application.close_orphans import CloseOrphans
from strategy_manager.signals.application.ports import PoolKey
from strategy_manager.signals.domain.holding import HeldAllocation

POOL: PoolKey = ("bybit", "usdt-m", "USDT")


@dataclass
class SpyClosePosition:
    calls: list[CloseCommand] = field(default_factory=list)

    async def close(self, command: CloseCommand) -> CloseResult:
        self.calls.append(command)
        return CloseResult(status="PLACED", execution_attempt_id=uuid4(), base_size=Decimal("1"))


@dataclass
class FakeClosingAttemptsPort:
    """Maps an allocation id to its latest close -- ``None`` (the default
    factory) means no close exists yet for that allocation."""

    by_allocation: dict[UUID, ExecutionAttempt | None] = field(default_factory=dict)
    calls: list[UUID] = field(default_factory=list)

    async def latest_close_for(self, allocation_id: UUID) -> ExecutionAttempt | None:
        self.calls.append(allocation_id)
        return self.by_allocation.get(allocation_id)


@dataclass
class SpyContinuationSeeder:
    """Always reports ``inserted=True`` -- the ordinary, no-collision case
    every test not specifically about the invariant gets. Real dedupe
    semantics (a second seed at the same (signal_id, poll) colliding) are
    rehearsed by ``FakeContinuationSeeder`` below."""

    calls: list[tuple[UUID, list[UUID], int, bool]] = field(default_factory=list)

    async def seed(
        self,
        signal_id: UUID,
        awaited_allocation_ids: list[UUID],
        poll: int = 0,
        *,
        replay_expected: bool = False,
    ) -> bool:
        self.calls.append((signal_id, awaited_allocation_ids, poll, replay_expected))
        return True


@dataclass
class FakeContinuationSeeder:
    """Mimics ``enqueue_unique``'s own ``dedupe_key`` semantics precisely
    enough to rehearse the REQUIRED INVARIANT: the FIRST seed for a given
    ``(signal_id, poll)`` pair inserts (``True``); every LATER one for the
    exact same pair collides (``False``) -- regardless of
    ``replay_expected``, which controls only the log level a real
    ``OpenAfterClose.seed`` would choose, never the return value."""

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
class SpyCommit:
    commits: int = 0

    async def commit(self) -> None:
        self.commits += 1


def _close_attempt(allocation_id: UUID, status: ExecutionStatus) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=uuid4(),
        reservation_id=None,
        closes_allocation_id=allocation_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="ETHUSDT.P",
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        quote_amount=None,
        leverage=None,
        status=status,
        origin=ExecutionOrigin.SYSTEM,
        client_order_id=f"client-{allocation_id}",
    )


async def test_seeds_the_continuation_before_closing_any_allocation() -> None:
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

    holding = HeldAllocation(strategy_id=uuid4(), allocation_id=uuid4(), net_base=Decimal("0.5"))
    close_orphans = CloseOrphans(
        close_position=OrderingClosePosition(),  # type: ignore[arg-type]
        closing_attempts=FakeClosingAttemptsPort(),
        open_after_close=OrderingSeeder(),  # type: ignore[arg-type]
        commit=SpyCommit(),
    )

    await close_orphans.close(uuid4(), POOL, holding.strategy_id, "ETHUSDT.P", [holding])

    assert order == ["seed", "close"]


async def test_seeds_awaiting_every_allocation_id_at_once() -> None:
    strategy_id = uuid4()
    holding_a = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    holding_b = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("-0.3")
    )
    seeder = SpyContinuationSeeder()
    signal_id = uuid4()
    close_orphans = CloseOrphans(
        close_position=SpyClosePosition(),
        closing_attempts=FakeClosingAttemptsPort(),
        open_after_close=seeder,
        commit=SpyCommit(),
    )

    await close_orphans.close(
        signal_id, POOL, strategy_id, "ETHUSDT.P", [holding_a, holding_b]
    )

    assert seeder.calls == [
        (signal_id, [holding_a.allocation_id, holding_b.allocation_id], 0, True)
    ]


async def test_closes_a_positive_net_with_a_sell_and_a_negative_net_with_a_buy() -> None:
    strategy_id = uuid4()
    long_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    short_holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("-0.3")
    )
    close_position = SpyClosePosition()
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=FakeClosingAttemptsPort(),
        open_after_close=SpyContinuationSeeder(),
        commit=SpyCommit(),
    )

    await close_orphans.close(
        uuid4(), POOL, strategy_id, "ETHUSDT.P", [long_holding, short_holding]
    )

    sides = {call.allocation_id: call.side for call in close_position.calls}
    assert sides[long_holding.allocation_id] == OrderSide.SELL
    assert sides[short_holding.allocation_id] == OrderSide.BUY


async def test_an_allocation_with_a_committed_close_is_skipped() -> None:
    """Idempotent skip (spec: trade-execution § "A retried close is not
    re-sent"): a non-FAILED close already recorded means an earlier run of
    this exact method already placed and committed it."""
    strategy_id = uuid4()
    holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    close_position = SpyClosePosition()
    closing_attempts = FakeClosingAttemptsPort(
        by_allocation={holding.allocation_id: _close_attempt(
            holding.allocation_id, ExecutionStatus.SUBMITTED
        )}
    )
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=closing_attempts,
        open_after_close=SpyContinuationSeeder(),
        commit=SpyCommit(),
    )

    await close_orphans.close(uuid4(), POOL, strategy_id, "ETHUSDT.P", [holding])

    assert close_position.calls == []


async def test_an_allocation_with_a_failed_close_is_retried() -> None:
    """A FAILED close does not block a retry (spec: trade-execution §
    Retryable Close, Single In-Flight Attempt)."""
    strategy_id = uuid4()
    holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    close_position = SpyClosePosition()
    closing_attempts = FakeClosingAttemptsPort(
        by_allocation={holding.allocation_id: _close_attempt(
            holding.allocation_id, ExecutionStatus.FAILED
        )}
    )
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=closing_attempts,
        open_after_close=SpyContinuationSeeder(),
        commit=SpyCommit(),
    )

    await close_orphans.close(uuid4(), POOL, strategy_id, "ETHUSDT.P", [holding])

    assert len(close_position.calls) == 1
    assert close_position.calls[0].allocation_id == holding.allocation_id


async def test_a_mix_of_skipped_and_fresh_allocations_only_closes_the_fresh_ones() -> None:
    strategy_id = uuid4()
    already_closing = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    still_open = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("-0.2")
    )
    close_position = SpyClosePosition()
    closing_attempts = FakeClosingAttemptsPort(
        by_allocation={
            already_closing.allocation_id: _close_attempt(
                already_closing.allocation_id, ExecutionStatus.FILLED
            )
        }
    )
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=closing_attempts,
        open_after_close=SpyContinuationSeeder(),
        commit=SpyCommit(),
    )

    await close_orphans.close(
        uuid4(), POOL, strategy_id, "ETHUSDT.P", [already_closing, still_open]
    )

    assert [call.allocation_id for call in close_position.calls] == [still_open.allocation_id]


async def test_when_every_allocation_is_already_closing_the_seed_is_committed_explicitly() -> None:
    """No ``ClosePosition.close`` call happens in this case, so nothing else
    would ever commit the seed the way ``ClosePosition``'s own commit
    normally does."""
    strategy_id = uuid4()
    holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    close_position = SpyClosePosition()
    commit = SpyCommit()
    closing_attempts = FakeClosingAttemptsPort(
        by_allocation={holding.allocation_id: _close_attempt(
            holding.allocation_id, ExecutionStatus.SUBMITTED
        )}
    )
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=closing_attempts,
        open_after_close=SpyContinuationSeeder(),
        commit=commit,
    )

    await close_orphans.close(uuid4(), POOL, strategy_id, "ETHUSDT.P", [holding])

    assert close_position.calls == []
    assert commit.commits == 1


async def test_when_a_fresh_close_is_placed_the_caller_does_not_need_to_commit_again() -> None:
    strategy_id = uuid4()
    holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    commit = SpyCommit()
    close_orphans = CloseOrphans(
        close_position=SpyClosePosition(),
        closing_attempts=FakeClosingAttemptsPort(),
        open_after_close=SpyContinuationSeeder(),
        commit=commit,
    )

    await close_orphans.close(uuid4(), POOL, strategy_id, "ETHUSDT.P", [holding])

    assert commit.commits == 0


async def test_logs_a_warning_naming_strategy_symbol_and_allocations(
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id, allocation_id = uuid4(), uuid4()
    holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    close_orphans = CloseOrphans(
        close_position=SpyClosePosition(),
        closing_attempts=FakeClosingAttemptsPort(),
        open_after_close=SpyContinuationSeeder(),
        commit=SpyCommit(),
    )

    with caplog.at_level("WARNING"):
        await close_orphans.close(uuid4(), POOL, strategy_id, "ETHUSDT.P", [holding])

    assert any(record.levelname == "WARNING" for record in caplog.records)
    message = caplog.records[-1].getMessage()
    assert str(strategy_id) in message
    assert "ETHUSDT.P" in message
    assert str(allocation_id) in message


# ---- REQUIRED INVARIANT (orchestrator review of `ee640d6`) -----------------
#
# "whenever any path places a close on behalf of a signal ... a continuation
# that has NOT yet run must exist awaiting that close, committed atomically
# with it. If one cannot be guaranteed, do not place the close -- refuse and
# log ERROR."


async def test_next_poll_is_threaded_not_hardcoded_to_zero() -> None:
    """The FIRST bug: a re-entry from ``open_now`` (design.md § S5) must
    seed the NEXT never-before-used step in THIS signal's own chain, not
    restart it at poll 0 -- exactly ``ContinuationSeederPort``'s own
    contract in ``process_signal.py``."""
    strategy_id = uuid4()
    holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=uuid4(), net_base=Decimal("0.5")
    )
    seeder = SpyContinuationSeeder()
    signal_id = uuid4()
    close_orphans = CloseOrphans(
        close_position=SpyClosePosition(),
        closing_attempts=FakeClosingAttemptsPort(),
        open_after_close=seeder,
        commit=SpyCommit(),
    )

    await close_orphans.close(
        signal_id, POOL, strategy_id, "ETHUSDT.P", [holding], next_poll=3
    )

    assert seeder.calls == [(signal_id, [holding.allocation_id], 3, True)]


async def test_a_replay_that_collides_does_not_close_an_allocation_with_no_live_continuation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Scenario B: the SAME signal is reprocessed (a worker-crash replay of
    ``handle()``, which always threads ``next_poll=0``) after the guard
    already found this same REAL orphan once before. The seed collides
    with the already-durable poll-0 row from the first attempt -- whose
    ``awaited_allocation_ids`` payload is fixed and cannot be guaranteed to
    cover a FRESH close placed now. No close may be placed, and it must be
    visible above INFO.

    ``ETHUSDT`` here (vs. ``ETHUSDT.P`` in the other tests of this file) is
    the binding testing lesson's second spelling, deliberately used on this
    replay's own signal-side call to prove the allocation is matched by id,
    never by symbol string."""
    strategy_id = uuid4()
    allocation_id = uuid4()
    holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    seeder = FakeContinuationSeeder()
    signal_id = uuid4()
    close_position = SpyClosePosition()
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=FakeClosingAttemptsPort(),
        open_after_close=seeder,
        commit=SpyCommit(),
    )

    # First attempt: genuinely fresh, places the close.
    await close_orphans.close(signal_id, POOL, strategy_id, "ETHUSDT", [holding], next_poll=0)
    assert len(close_position.calls) == 1

    # The first close was rejected by the venue -- FAILED, per S1.
    closing_attempts_after_failure = FakeClosingAttemptsPort(
        by_allocation={allocation_id: _close_attempt(allocation_id, ExecutionStatus.FAILED)}
    )
    close_orphans_replay = CloseOrphans(
        close_position=close_position,
        closing_attempts=closing_attempts_after_failure,
        open_after_close=seeder,  # SAME seeder -- the collision this test proves
        commit=SpyCommit(),
    )

    # The SAME job is redelivered: handle() reruns from scratch, guard
    # finds the SAME REAL orphan, and threads the SAME next_poll=0 it
    # always does on a fresh handle() call.
    with caplog.at_level("ERROR"):
        await close_orphans_replay.close(
            signal_id, POOL, strategy_id, "ETHUSDT", [holding], next_poll=0
        )

    assert len(close_position.calls) == 1  # unchanged -- no second close placed
    assert any(record.levelname == "ERROR" for record in caplog.records)
    error_message = next(r for r in caplog.records if r.levelname == "ERROR").getMessage()
    assert str(allocation_id) in error_message
    assert str(strategy_id) in error_message


async def test_a_new_signal_still_retries_the_close_after_an_old_failed_one() -> None:
    """A genuinely DIFFERENT signal hitting the same still-divergent
    allocation is not the replay this invariant guards against -- its own
    ``dedupe_key`` is scoped by its OWN ``signal_id``, so its seed never
    collides, and the spec's own "Retry after a failed close" (trade-
    execution § Retryable Close, Single In-Flight Attempt) still applies."""
    strategy_id = uuid4()
    allocation_id = uuid4()
    holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    seeder = FakeContinuationSeeder()
    close_position = SpyClosePosition()
    closing_attempts = FakeClosingAttemptsPort(
        by_allocation={allocation_id: _close_attempt(allocation_id, ExecutionStatus.FAILED)}
    )
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=closing_attempts,
        open_after_close=seeder,
        commit=SpyCommit(),
    )

    # An earlier, unrelated signal already used up poll 0 for ITSELF.
    await seeder.seed(uuid4(), [uuid4()], poll=0)

    new_signal_id = uuid4()
    await close_orphans.close(
        new_signal_id, POOL, strategy_id, "STXUSDT_PERP", [holding], next_poll=0
    )

    assert len(close_position.calls) == 1
    assert close_position.calls[0].allocation_id == allocation_id


async def test_a_covered_allocation_is_still_safely_skipped_on_collision() -> None:
    """A collision must not turn a SAFE idempotent skip into a refusal --
    only allocations that would need a FRESH close are affected."""
    strategy_id = uuid4()
    allocation_id = uuid4()
    holding = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )
    seeder = FakeContinuationSeeder()
    close_position = SpyClosePosition()
    closing_attempts = FakeClosingAttemptsPort(
        by_allocation={allocation_id: _close_attempt(allocation_id, ExecutionStatus.SUBMITTED)}
    )
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=closing_attempts,
        open_after_close=seeder,
        commit=SpyCommit(),
    )
    signal_id = uuid4()

    await seeder.seed(signal_id, [allocation_id], poll=0)  # collision set up

    await close_orphans.close(signal_id, POOL, strategy_id, "ETHUSDT.P", [holding], next_poll=0)

    assert close_position.calls == []
