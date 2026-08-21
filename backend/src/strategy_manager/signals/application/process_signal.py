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
from strategy_manager.shared.domain.money import Currency, Money
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


@dataclass(frozen=True, slots=True)
class ProcessSignalResult:
    """``refused`` names a half of the transition that could not be executed
    and never will be, as opposed to one that failed and should be retried.

    A reverse on a spot pool is the case that needs it: the closing half runs
    and succeeds, and the opening half is impossible because spot cannot hold a
    short. Raising would retry a close that already happened; reporting plain
    success would hide that the position is now flat rather than flipped."""

    transition_kind: str
    reservation_id: UUID | None
    executed: bool
    refused: str | None = None


class ProcessSignalHandler:
    """Composes ``AllocateCapital`` (slice 4) and ``ExecuteReservation``
    (slice 5) — the ``signal.process`` job's whole business logic
    (design.md's job handlers table)."""

    def __init__(
        self,
        signal_context: SignalContextPort,
        strategy_policy: StrategyPolicyPort,
        pool_balance: PoolBalancePort,
        allocate_capital: AllocateCapital,
        place_order: PlaceOrderPort,
        close_position: ClosePositionPort,
    ) -> None:
        self._signal_context = signal_context
        self._strategy_policy = strategy_policy
        self._pool_balance = pool_balance
        self._allocate_capital = allocate_capital
        self._place_order = place_order
        self._close_position = close_position

    async def handle(self, signal_id: UUID) -> ProcessSignalResult:
        context = await self._signal_context.load(signal_id)
        transition = PositionTransition.classify(
            context.prior_position_size, context.position_size
        )
        policy = await self._strategy_policy.policy_for(context.strategy_id)

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

    async def _handle_consumes(
        self,
        signal_id: UUID,
        context: SignalContext,
        transition: PositionTransition,
        policy: StrategyPolicySnapshot,
    ) -> ProcessSignalResult:
        pool_balance = await self._pool_balance.read(policy.venue, policy.settlement_currency)
        requested = Money(
            amount=requested_from_percent(pool_balance.balance, policy.allocation_percent),
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

        await self._close_position.close(
            CloseCommand(
                allocation_id=context.prior_reservation_id,
                strategy_id=context.strategy_id,
                venue=policy.venue,
                settlement_currency=policy.settlement_currency,
                symbol=context.symbol,
                side=_releasing_side(_prior_of(context)),
            )
        )
        return ProcessSignalResult(transition.kind.value, context.prior_reservation_id, True)

    def _note_unexecuted_tail(
        self,
        context: SignalContext,
        transition: PositionTransition,
        result: ProcessSignalResult,
    ) -> ProcessSignalResult:
        """A transition declaring more than one effect had only its first one
        executed.

        Today that is a reverse, and both blockers on its second half are real
        and permanent rather than transient: it needs a venue able to hold the
        opposite side, and it needs capital the close has not settled -- the
        proceeds are not spendable until the sell fills and the balance
        snapshot refreshes. Retrying would re-run a close that already
        succeeded.

        The position therefore ends flat rather than flipped. That is a
        defensible state, since the prior exposure is genuinely gone, but it is
        not what the signal asked for, so it is reported rather than swallowed.
        """
        tail = transition.effects[1].value
        refused = (
            f"only the {transition.effects[0].value} half of this "
            f"{transition.kind.value} ran; the {tail} half needs a venue that "
            "can hold the opposite side and capital the close has not settled"
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
