"""``ProcessSignalHandler``: the ``signal.process`` job handler that routes a
signal by its ``PositionTransition`` (design.md's job handlers table;
"New scope in this slice: tasks 5.16-5.17 route by ``PositionTransition`` so
a capital-RELEASING signal never takes the advisory lock").

A CONSUMES signal (opening a position, or the consuming half of a reverse)
goes through ``AllocateCapital`` — the only path that takes the advisory
lock. A RELEASES signal (closing a position) goes to ``ClosePosition``,
naming the allocation that originally opened the position, without ever
touching the lock: releasing work can only increase pool availability, so it
cannot over-allocate (design.md's "only capital-consuming work takes the
lock").

Closing used to be routed through ``PlaceOrder`` too, against the opening
reservation, and it could not work in any timing window — inside the
reservation's TTL the opening attempt already owned the UNIQUE
``execution_attempts.reservation_id`` row, and outside it the pre-submit
expiry re-check aborted the order. ``ClosePosition`` exists because a close
is a different operation: it reserves nothing, and its size comes from the
ledger rather than from an amount divided by a price.

This handler's work ends when the order is placed. What it filled at is
recorded by the ``execution.settle`` job, which ``PlaceOrder`` schedules
before it ever contacts the exchange.

``requested`` for a CONSUMES signal is derived from the strategy's
configured ``allocation_percent`` applied to the pool BALANCE (design.md
§ "Order size never comes from the alert", percent base RESOLVED
2026-08-18; tasks.md 7.7/7.8) — never from the alert's ``position_size`` or
``contracts``, which are TradingView's *simulated* equity and have no
relationship to the real pool. ``decide()`` (slice 4) is unchanged and still
apportions ``granted <= requested`` against real availability: the percent
caps the *ask*, the advisory lock and ``decide()`` govern the *grant*. This
keeps `quantity = granted / price` exactly as specified.

**Two balance reads, deliberately.** Sizing the ask reads the pool balance
here, outside the lock; ``AllocateCapital`` then reads it again inside the
lock to compute real availability. That is safe: the money invariant depends
only on the in-lock read, so a balance that moved between the two can make the
*ask* slightly stale but can never over-allocate — ``decide()`` still clamps
``granted`` to what is actually available.

Do not "fix" this by moving the percent calculation inside ``AllocateCapital``.
That would couple the allocation engine to a per-strategy product policy it
has no business knowing: ``AllocateCapital``'s contract is "here is an amount,
allocate what you can", and how that amount was sized belongs to the caller.
Any other sizing rule — a manual allocation, a future risk model — must be
able to drive the same engine without changing it.

A REVERSE
transition is routed through the CONSUMES branch only (its consuming half);
fully closing the prior leg first is not implemented in this slice — this
is a known limitation, not a tested scenario, and is called out in the
apply-progress report.
"""

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
)
from strategy_manager.allocation.application.ports import (
    PoolBalancePort,
    StrategyPolicyPort,
    StrategyPolicySnapshot,
)
from strategy_manager.allocation.domain.percent import requested_from_percent
from strategy_manager.execution.application.close_position import (
    CloseCommand,
    CloseResult,
)
from strategy_manager.execution.application.place_order import PlaceCommand, PlaceResult
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.shared.application.ports import CommitPort
from strategy_manager.shared.domain.money import Currency, Money
from strategy_manager.signals.application.holding_guard import HoldingGuard
from strategy_manager.signals.application.ports import BalanceRefreshPort, RefreshStatus
from strategy_manager.signals.domain.position_transition import (
    PositionTransition,
    TransitionEffect,
)

logger = logging.getLogger(__name__)


def _consuming_side(next_position_size: Decimal) -> OrderSide:
    """Opening a long buys; opening a short sells."""
    return OrderSide.BUY if next_position_size > 0 else OrderSide.SELL


def _releasing_side(prior_position_size: Decimal) -> OrderSide:
    """Closing a long sells; closing a short buys."""
    return OrderSide.SELL if prior_position_size > 0 else OrderSide.BUY


# Placeholder default for ``SignalContext.received_at`` so every test built
# before this field existed keeps constructing it without one. Never reaches
# ``HoldingGuard`` in practice: the guard only reads it once ``in_flight`` is
# True, and every caller supplies the real value (``SignalContextAdapter``
# asserts the signal's own ``received_at`` is set before it ever builds one).
_UNSET_RECEIVED_AT = datetime(1970, 1, 1, tzinfo=UTC)


# These replaced two dicts keyed by ``TransitionKind``, which could not express
# a reverse at all: a reverse consumes on one side and releases on the other,
# and which side is which depends on the DIRECTION of the flip, not on the kind.
# ``REVERSE`` was consequently mapped to a constant ``BUY``, so a strategy
# holding a long and told to flip short bought more long.
#
# Deriving both sides from the position sizes is correct for all five kinds and
# leaves nothing to keep in sync: the sign of the position after the order says
# what is being opened, the sign before it says what is being closed.


@dataclass(frozen=True, slots=True)
class SignalContext:
    """Everything ``ProcessSignalHandler`` needs about a signal to route and
    size an order, decoupled from ``signals``' own persistence model and
    from the ``allocation``/``execution`` modules' own aggregates.

    ``prior_reservation_id`` is the reservation tied to the signal that
    produced ``prior_position_size`` — the reservation a closing (RELEASES)
    signal must execute against. ``None`` when there is no prior signal, or
    the prior signal never produced a reservation (e.g. it was skipped)."""

    strategy_id: UUID
    symbol: str
    price: Decimal
    position_size: Decimal
    prior_position_size: Decimal | None
    prior_reservation_id: UUID | None
    settlement_currency: str
    # Both added for the Existing-Position Guard (S2b). ``own_reservation_id``
    # is set only when THIS signal already produced a reservation -- a retry
    # of a job whose earlier attempt got as far as ``AllocateCapital`` -- and
    # is what lets ``HoldingGuard`` resume instead of re-checking a holding
    # its own prior attempt is what caused. ``received_at`` bounds how long
    # the guard keeps retrying in-flight work before it gives up.
    own_reservation_id: UUID | None = None
    received_at: datetime = _UNSET_RECEIVED_AT


class SignalContextPort(Protocol):
    async def load(self, signal_id: UUID) -> SignalContext: ...


class PlaceOrderPort(Protocol):
    """Narrowed to exactly what ``ProcessSignalHandler`` calls, so a fake can
    stand in for ``PlaceOrder`` in unit tests without a full exchange stack.

    Placing is where this handler's responsibility ends. What the order
    filled at is settled by a separate job, so nothing here waits on the
    exchange to publish fills."""

    async def place(self, command: PlaceCommand) -> PlaceResult: ...


class ClosePositionPort(Protocol):
    """The releasing counterpart of ``PlaceOrderPort``."""

    async def close(self, command: CloseCommand) -> CloseResult: ...


class ContinuationSeederPort(Protocol):
    """The S5 continuation's seeding half (design.md § S5), called when the
    Existing-Position Guard DEFERS rather than proceeds or refuses --
    ``HoldingGuard``'s in-flight branch, rewired away from raising
    ``HoldingNotSettledYet`` into the queue's failure backoff (design.md §
    S5, amending S2). Implemented by
    ``signals.application.open_after_close.OpenAfterClose``, declared here
    rather than imported so neither file needs the other's class.

    ``poll`` MUST be the next never-before-seeded step in this signal's
    chain: 0 when deferred from a fresh ``handle()`` call, or the current
    poll plus one when deferred again from inside ``open_now`` -- seeding
    the SAME poll twice silently drops the continuation (design.md § S5,
    the poll-threading fix)."""

    async def seed(
        self, signal_id: UUID, awaited_allocation_ids: list[UUID], poll: int = 0
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ProcessSignalResult:
    """``refused`` names a half of the transition that could not be executed
    and never will be, as opposed to one that failed and should be retried.

    A reverse on a spot pool is the case that needs it: the closing half runs
    and succeeds, and the opening half is impossible because spot cannot hold a
    short. Raising would retry a close that already happened; reporting plain
    success would hide that the position is now flat rather than flipped.

    ``failed`` is the other outcome: an execution that WAS attempted and was
    definitively rejected by the venue, as opposed to ``refused``'s half that
    could never be attempted at all. ``ClosePosition`` already logs the
    rejection; this field lets a caller such as the job handler see it too
    without going back to the execution attempt row."""

    transition_kind: str
    reservation_id: UUID | None
    executed: bool
    refused: str | None = None
    failed: str | None = None


class ProcessSignalHandler:
    """Composes ``AllocateCapital`` (slice 4) and ``ExecuteReservation``
    (slice 5) — the ``signal.process`` job's whole business logic
    (design.md's job handlers table)."""

    def __init__(
        self,
        signal_context: SignalContextPort,
        strategy_policy: StrategyPolicyPort,
        pool_balance: PoolBalancePort,
        holding_guard: HoldingGuard,
        balance_refresh: BalanceRefreshPort,
        allocate_capital: AllocateCapital,
        place_order: PlaceOrderPort,
        close_position: ClosePositionPort,
        open_after_close: ContinuationSeederPort,
        commit: CommitPort,
        tradable_pools: frozenset[tuple[str, str]],
    ) -> None:
        self._signal_context = signal_context
        self._strategy_policy = strategy_policy
        self._pool_balance = pool_balance
        self._holding_guard = holding_guard
        self._balance_refresh = balance_refresh
        self._allocate_capital = allocate_capital
        self._place_order = place_order
        self._close_position = close_position
        self._open_after_close = open_after_close
        self._commit = commit
        self._tradable_pools = tradable_pools

    async def handle(self, signal_id: UUID) -> ProcessSignalResult:
        context = await self._signal_context.load(signal_id)
        transition = PositionTransition.classify(
            context.prior_position_size, context.position_size
        )
        policy = await self._strategy_policy.policy_for(context.strategy_id)

        if (policy.exchange, policy.venue) not in self._tradable_pools:
            return self._refuse_untradable_pool(
                context, transition, policy.exchange, policy.venue
            )

        # ``transition.effects`` is ORDERED, and that ordering is the domain's
        # own statement of what happens first. A reverse releases before it
        # consumes, so routing on the first effect closes the prior position --
        # no branch names REVERSE anywhere.
        #
        # The previous routing asked ``CONSUMES in effects``, which for a
        # reverse matched the SECOND effect and skipped the first entirely.
        # With a consuming side hardcoded to BUY, a strategy holding a long and
        # told to flip short bought MORE long.
        if transition.effects[0] is TransitionEffect.CONSUMES:
            result = await self._handle_consumes(signal_id, context, transition, policy)
        else:
            result = await self._handle_releases(context, transition, policy)

        if len(transition.effects) == 1:
            return result
        return self._note_unexecuted_tail(context, transition, result)

    async def open_now(self, signal_id: UUID, poll: int = 0) -> ProcessSignalResult:
        """The S5 continuation's own entry point (design.md § S5, "all
        FILLED"): called by ``OpenAfterClose.poll()`` once every close it
        awaited has settled. Re-runs the Existing-Position Guard, the S3
        refresh and allocation from scratch -- not ``handle()``, since a
        continuation only ever awaits the CONSUMES side; the signal it
        carries was already classified as an opening signal the first time
        ``handle()`` ran and deferred it.

        Dedups on ``SignalContext.own_reservation_id`` (itself
        ``find_by_signal_id``, the very same lookup ``AllocateCapital.allocate``
        dedupes its own retries on) BEFORE touching anything: a continuation
        that already got as far as allocating for this signal is a no-op
        here, never a second reservation attempt. Re-running a continuation
        (a crash between its own commit and its job's ack, or a redelivered
        job) must never submit two opens -- ``execution_attempts
        .reservation_id``'s UNIQUE constraint (migration 0005) is the
        backstop if a race ever reached ``PlaceOrder`` twice regardless.

        ``poll`` is the poll number the continuation had already reached
        when it called this method. The guard can defer AGAIN here (some
        OTHER work now in flight, or the vacuous empty-awaited-ids case
        re-checking itself) -- if it does, ``_handle_consumes`` must seed
        ``poll + 1``, never restart the chain at 0 (orchestrator-found
        defect: seeding 0 again collides with the already-DONE poll 0 row
        and silently drops the continuation)."""
        context = await self._signal_context.load(signal_id)
        transition = PositionTransition.classify(
            context.prior_position_size, context.position_size
        )
        if context.own_reservation_id is not None:
            return ProcessSignalResult(
                transition.kind.value, context.own_reservation_id, True
            )

        policy = await self._strategy_policy.policy_for(context.strategy_id)
        return await self._handle_consumes(
            signal_id, context, transition, policy, next_poll=poll + 1
        )

    async def _handle_consumes(
        self,
        signal_id: UUID,
        context: SignalContext,
        transition: PositionTransition,
        policy: StrategyPolicySnapshot,
        next_poll: int = 0,
    ) -> ProcessSignalResult:
        # The Existing-Position Guard (spec: capital-allocation §
        # Existing-Position Guard) runs BEFORE anything else in this branch --
        # neither a refusal nor a deferral here may ever reach
        # ``AllocateCapital.allocate()`` (design.md § "Guard order").
        guard_outcome = await self._holding_guard.check(
            pool=(policy.exchange, policy.venue, policy.settlement_currency),
            strategy_id=context.strategy_id,
            symbol=context.symbol,
            own_reservation_id=context.own_reservation_id,
            received_at=context.received_at,
        )
        if not guard_outcome.proceed:
            if guard_outcome.refused is not None:
                return ProcessSignalResult(
                    transition.kind.value, None, False, refused=guard_outcome.refused
                )
            # DEFERRED (design.md § S5, amending S2): work is still in
            # flight but has not settled yet. Seed a continuation instead of
            # raising into the queue's failure backoff, which could exhaust
            # before the 600s bound and end this signal as a silent FAILED
            # job with no WARNING. ``next_poll`` is 0 on a fresh ``handle()``
            # call and ``open_now``'s own poll + 1 when THIS deferral was
            # reached from inside a continuation already in flight --
            # seeding 0 again there would collide with the already-DONE
            # poll 0 row and silently drop the chain.
            await self._open_after_close.seed(
                signal_id, guard_outcome.awaited_allocation_ids or [], poll=next_poll
            )
            await self._commit.commit()
            return ProcessSignalResult(transition.kind.value, None, False)

        # On-Demand Balance Refresh Before Allocation (spec: capital-
        # allocation § On-Demand Balance Refresh Before Allocation; design.md
        # § S3) -- the LAST remote read before the sizing read below and the
        # advisory lock ``AllocateCapital`` acquires. FALLBACK is not a
        # refusal: the stale-but-young-enough snapshot sizes the trade exactly
        # as if the refresh had succeeded. Only UNAVAILABLE refuses, and only
        # here can the ERROR name the signal, the strategy and the symbol --
        # ``RefreshPoolBalance`` itself never sees any of the three, only the
        # pool.
        refresh_outcome = await self._balance_refresh.refresh(
            policy.exchange, policy.venue, policy.settlement_currency
        )
        if refresh_outcome.status is RefreshStatus.UNAVAILABLE:
            refused = (
                f"balance for pool ({policy.exchange}, {policy.venue}, "
                f"{policy.settlement_currency}) is unavailable ({refresh_outcome.reason}); "
                f"refusing signal {signal_id} for strategy {context.strategy_id} on "
                f"{context.symbol}"
            )
            logger.error("refusing signal, balance unavailable: %s", refused)
            return ProcessSignalResult(transition.kind.value, None, False, refused=refused)

        pool_balance = await self._pool_balance.read(
            policy.exchange, policy.venue, policy.settlement_currency
        )
        # Sized from the pool's TOTAL, never from what is still free: the same
        # percentage must ask for the same amount whether or not other
        # strategies already hold positions. ``decide()`` still caps the grant
        # at what is actually available.
        requested = Money(
            amount=requested_from_percent(pool_balance.total, policy.allocation_percent),
            currency=Currency(policy.settlement_currency),
        )
        result = await self._allocate_capital.allocate(
            AllocateCommand(
                signal_id=signal_id, strategy_id=context.strategy_id, requested=requested
            )
        )

        if result.reservation_id is None:
            return ProcessSignalResult(transition.kind.value, None, False)

        await self._place_order.place(
            PlaceCommand(
                reservation_id=result.reservation_id,
                symbol=context.symbol,
                side=_consuming_side(context.position_size),
                price=context.price,
            )
        )
        return ProcessSignalResult(transition.kind.value, result.reservation_id, True)

    async def _handle_releases(
        self,
        context: SignalContext,
        transition: PositionTransition,
        policy: StrategyPolicySnapshot,
    ) -> ProcessSignalResult:
        """A close carries no price, because nothing about its size is derived
        from one. ``ClosePosition`` reads the ledger for what the opening
        allocation actually acquired."""
        if context.prior_reservation_id is None:
            return ProcessSignalResult(transition.kind.value, None, False)

        close_result = await self._close_position.close(
            CloseCommand(
                allocation_id=context.prior_reservation_id,
                strategy_id=context.strategy_id,
                exchange=policy.exchange,
                venue=policy.venue,
                settlement_currency=policy.settlement_currency,
                symbol=context.symbol,
                side=_releasing_side(_prior_of(context)),
            )
        )
        if close_result.status == "FAILED":
            return ProcessSignalResult(
                transition.kind.value,
                context.prior_reservation_id,
                False,
                failed=close_result.error,
            )
        return ProcessSignalResult(transition.kind.value, context.prior_reservation_id, True)

    def _refuse_untradable_pool(
        self,
        context: SignalContext,
        transition: PositionTransition,
        exchange: str,
        venue: str,
    ) -> ProcessSignalResult:
        """Refuse THIS signal, and only this one.

        The pool reaches the reservation, the attempt and the ledger row
        without ever selecting an adapter, so a strategy on a pool the
        registered adapters cannot trade would have its size computed from one
        wallet and its order sent to another -- a futures pool sized against
        the futures balance and executed on spot, or a Binance pool executed
        against a Bybit account.

        The check sits here, before allocation, because refusing once a
        reservation exists means capital is already held for a trade that
        cannot be placed correctly.

        It refuses per signal rather than at startup on purpose: a pool nobody
        is trading is not a reason to stop the pools somebody is. The operator
        still learns about it at startup, as a warning that names the pools
        without taking the process down with them.
        """
        served = ", ".join(sorted(f"{e}/{v}" for e, v in self._tradable_pools))
        refused = (
            f"strategy {context.strategy_id} trades on {exchange}/{venue}, which "
            f"no registered exchange adapter serves ({served or 'nothing'}). "
            "No order was placed and no capital was reserved."
        )
        logger.warning("refusing signal for %s: %s", context.symbol, refused)
        return ProcessSignalResult(transition.kind.value, None, False, refused=refused)

    def _note_unexecuted_tail(
        self,
        context: SignalContext,
        transition: PositionTransition,
        result: ProcessSignalResult,
    ) -> ProcessSignalResult:
        """A transition declaring more than one effect had only its first one
        executed.

        Today that is a reverse, and one blocker on its second half remains.
        It is no longer the venue: the futures adapter holds either side, and
        a short opens and closes in the base currency like a long. What is
        left is capital -- the close's proceeds are not spendable until that
        order fills AND the balance snapshot refreshes, and allocation reads
        the snapshot rather than the exchange, on purpose, because a remote
        read inside the pool's advisory lock would serialize every allocation
        behind exchange latency.

        So this is a SCHEDULING gap, not a venue gap, and it needs a second
        job that runs after settlement rather than a retry: retrying here
        would re-run a close that already succeeded.

        The position therefore ends flat rather than flipped. That is a
        defensible state, since the prior exposure is genuinely gone, but it
        is not what the signal asked for, so it is reported rather than
        swallowed.
        """
        tail = transition.effects[1].value
        refused = (
            f"only the {transition.effects[0].value} half of this "
            f"{transition.kind.value} ran; the {tail} half needs capital the "
            "close has not settled yet, so the position is flat rather than "
            "flipped"
        )
        logger.warning(
            "partial %s on %s: %s", transition.kind.value, context.symbol, refused
        )
        return replace(result, refused=refused)


def _prior_of(context: SignalContext) -> Decimal:
    """``PositionTransition.classify`` treats an absent prior as zero, and the
    releasing side is only ever asked for when the prior was non-zero."""
    return (
        context.prior_position_size
        if context.prior_position_size is not None
        else Decimal("0")
    )
