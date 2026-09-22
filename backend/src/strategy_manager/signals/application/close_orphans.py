"""``CloseOrphans``: the REAL branch of ``HoldingGuard`` (design.md § S6;
spec: capital-allocation § Real-Orphan Resolution via Close-Then-Open).

Closes every allocation of a strategy holding a REAL orphan on a market,
then defers the opening signal via the S5 continuation -- exactly the
pattern the in-flight branch already established for a close still
SUBMITTED, now reused for a close this REAL classification is the one to
initiate.

Declared as its own use case rather than folded into ``HoldingGuard``,
because closing is an ACTION with side effects (seeding a continuation,
placing orders, committing) that the guard's own contract explicitly
forbids doing itself -- see ``HoldingGuard``'s module docstring: "A
refusal... a deferral... or a REAL-orphan report... here MUST NEVER reach
``AllocateCapital.allocate()`` -- the caller is expected to check
``GuardOutcome.proceed``". ``ProcessSignalHandler._handle_consumes`` is
that caller: when the guard reports ``real_orphan_holdings``, it calls
this instead of seeding directly the way the in-flight branch does.

**REQUIRED INVARIANT** (orchestrator review of `ee640d6`, fixed same
commit): whenever this places a close on a signal's behalf, a
continuation that has NOT yet run MUST exist awaiting that close,
committed atomically with it. If that cannot be guaranteed, the close is
refused and an ERROR is logged instead of being placed silently.

**``next_poll`` is threaded from the caller, never hardcoded** -- the
FIRST bug this fixes. ``ProcessSignalHandler._handle_consumes`` already
threads a ``next_poll`` through for exactly this re-entry case (0 from a
fresh ``handle()``, the current poll plus one from inside ``open_now``);
the original version of this method ignored it and always seeded poll 0,
so a re-entry that still found a REAL orphan (a second allocation
surfacing once the first was out of the way, or a worker-crash replay of
the same signal) collided with the ALREADY-CONSUMED poll 0 row on every
subsequent attempt.

**A seed collision is not automatically safe to close through.** This
method now uses the seed's own ``inserted`` result (``ContinuationSeederPort
.seed``) to decide, per attempt, whether it is safe to place a fresh
close:

- ``inserted=True`` (this call's ``next_poll`` was genuinely unused
  before -- the ordinary case, and also what a genuinely NEW signal
  hitting the same still-divergent allocation always gets, since its own
  ``dedupe_key`` is scoped by ITS OWN ``signal_id``): every allocation
  needing a fresh close is safe to close, INCLUDING one whose latest
  closing attempt is FAILED (spec: trade-execution § Retryable Close,
  Single In-Flight Attempt) -- this fresh continuation step is guaranteed
  to be exactly what was just passed.
- ``inserted=False`` (a collision: SOME earlier attempt at this exact
  ``(signal_id, next_poll)`` already committed a row, and that row's
  ``awaited_allocation_ids`` payload is fixed -- ``enqueue_unique``'s own
  ON CONFLICT DO NOTHING discards this call's payload): an allocation
  already covered by an existing non-FAILED close is still safely left
  alone (idempotent skip, unchanged), but an allocation that would need a
  FRESH close here (none exists yet, or the only one FAILED) is refused
  instead -- there is no way to guarantee the already-durable row is
  watching it, so closing it now could place an order nothing ever awaits
  (silently ending the flow with the position closed but the open never
  placed). One ERROR names every allocation refused this way.

This is deliberately a REFINEMENT of, not identical to, the reverse-wiring
release half's own FAILED-replay carve-out (design.md § S6, "Edge case
carried from S5b review"): that half is always keyed to a single fixed
poll 0 and cannot distinguish a genuine replay from a genuinely new
signal at all, so it blocks retrying a FAILED close unconditionally. This
method CAN distinguish the two, via the seed's own conflict result, so it
only blocks the unsafe case -- consistent in the SAFETY invariant both
enforce (never place a close nothing is guaranteed to await), not in the
exact mechanism.

Returns nothing: the open this REAL orphan blocked is never placed here --
it is scheduled, and ``ProcessSignalHandler._handle_consumes`` reports
that the same way the in-flight branch's own deferral does
(``executed=False``, no ``refused``).
"""

import logging
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from strategy_manager.execution.application.close_position import CloseCommand, CloseResult
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.signals.application.ports import PoolKey
from strategy_manager.signals.domain.holding import HeldAllocation

logger = logging.getLogger(__name__)


class ClosePositionPort(Protocol):
    """Mirrors ``process_signal.ClosePositionPort`` -- declared again here
    per this codebase's own narrow-Protocol-per-consumer convention (see
    ``process_signal.ClosingAttemptsPort``'s own docstring)."""

    async def close(self, command: CloseCommand) -> CloseResult: ...


class ClosingAttemptsPort(Protocol):
    """The narrow slice of ``SqlAlchemyExecutionAttemptRepository`` this
    use case reads: one allocation's most recent closing attempt."""

    async def latest_close_for(self, allocation_id: UUID) -> ExecutionAttempt | None: ...


class ContinuationSeederPort(Protocol):
    """Mirrors ``process_signal.ContinuationSeederPort`` /
    ``open_after_close``'s own ``seed`` signature -- implemented by
    ``OpenAfterClose``, declared here rather than imported.

    Returns whether THIS call inserted the row -- see this module's own
    docstring for why ``CloseOrphans`` depends on that, not only on the
    log level ``replay_expected`` selects."""

    async def seed(
        self,
        signal_id: UUID,
        awaited_allocation_ids: list[UUID],
        poll: int = 0,
        *,
        replay_expected: bool = False,
    ) -> bool: ...


class CommitPort(Protocol):
    """Mirrors ``process_signal.CommitPort`` -- deliberately narrow so any
    object with an async ``commit()`` satisfies it structurally."""

    async def commit(self) -> None: ...


def _closing_side(net_base: Decimal) -> OrderSide:
    """Closing a long (positive net) sells; closing a short (negative net)
    buys -- the same rule ``_releasing_side`` applies in
    ``process_signal.py``, restated here since ``HeldAllocation.net_base``
    already carries the sign directly."""
    return OrderSide.SELL if net_base > 0 else OrderSide.BUY


class CloseOrphans:
    def __init__(
        self,
        close_position: ClosePositionPort,
        closing_attempts: ClosingAttemptsPort,
        open_after_close: ContinuationSeederPort,
        commit: CommitPort,
    ) -> None:
        self._close_position = close_position
        self._closing_attempts = closing_attempts
        self._open_after_close = open_after_close
        self._commit = commit

    async def close(
        self,
        signal_id: UUID,
        pool: PoolKey,
        strategy_id: UUID,
        symbol: str,
        holdings: list[HeldAllocation],
        next_poll: int = 0,
    ) -> None:
        """``holdings`` is the strategy's own non-zero allocations on this
        market, exactly as ``HoldingGuard`` reported them via
        ``GuardOutcome.real_orphan_holdings`` -- never queried again here,
        so this acts on precisely what was classified REAL a moment ago.

        ``next_poll`` MUST be the next never-before-seeded step in this
        signal's own chain (see ``CloseOrphansPort``'s docstring in
        ``process_signal.py``) -- ``ProcessSignalHandler._handle_consumes``
        threads its own ``next_poll`` through unchanged."""
        allocation_ids = [holding.allocation_id for holding in holdings]
        exchange, venue, settlement_currency = pool
        logger.warning(
            "closing REAL orphan for strategy %s on %s in pool %s "
            "(allocations: %s) before deferring the open",
            strategy_id,
            symbol,
            pool,
            ", ".join(str(allocation_id) for allocation_id in allocation_ids),
        )
        # ``replay_expected=True``: a conflict on THIS seed call is never
        # itself the S5a2 defect class (a step re-seeded that should have
        # advanced the chain) -- either it is a genuine replay of this
        # exact idempotent step (benign), or it is the unsafe case this
        # method's own per-allocation gating below refuses explicitly with
        # its own ERROR. Logging the seed's own conflict at ERROR too would
        # be a second, redundant alarm for the same event.
        inserted = await self._open_after_close.seed(
            signal_id, allocation_ids, poll=next_poll, replay_expected=True
        )

        placed_a_close = False
        unsafe_allocation_ids: list[UUID] = []
        for holding in holdings:
            existing_close = await self._closing_attempts.latest_close_for(
                holding.allocation_id
            )
            needs_fresh_close = (
                existing_close is None or existing_close.status is ExecutionStatus.FAILED
            )
            if not needs_fresh_close:
                # Idempotent skip (spec: trade-execution § "A retried close
                # is not re-sent"): an earlier run already placed and
                # committed a live or completed close for this allocation.
                continue
            if not inserted:
                # This allocation needs a FRESH close, but the seed for
                # this exact step collided with an already-durable row
                # whose awaited_allocation_ids is fixed and may not cover
                # it (REQUIRED INVARIANT, this module's docstring). Refuse
                # rather than place an order nothing is guaranteed to
                # await.
                unsafe_allocation_ids.append(holding.allocation_id)
                continue
            placed_a_close = True
            await self._close_position.close(
                CloseCommand(
                    allocation_id=holding.allocation_id,
                    strategy_id=strategy_id,
                    exchange=exchange,
                    venue=venue,
                    settlement_currency=settlement_currency,
                    symbol=symbol,
                    side=_closing_side(holding.net_base),
                )
            )
        if unsafe_allocation_ids:
            logger.error(
                "refusing to close %s for strategy %s on %s in pool %s: "
                "the continuation step for this attempt (poll %s) already "
                "existed and is not guaranteed to await these allocations; "
                "a fresh close here would have no live continuation -- "
                "skipping until a genuinely new signal or chain step can "
                "seed one",
                ", ".join(str(allocation_id) for allocation_id in unsafe_allocation_ids),
                strategy_id,
                symbol,
                pool,
                next_poll,
            )
        if not placed_a_close:
            # Either every allocation was idempotently skipped, or every
            # remaining one was refused as unsafe -- either way nothing
            # above called ``ClosePosition.close`` (whose own commit would
            # otherwise have made the seed durable together with it), so
            # the seed needs its own commit here.
            await self._commit.commit()
