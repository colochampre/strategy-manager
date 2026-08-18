"""``ProcessSignalHandler``: the ``signal.process`` job handler that routes a
signal by its ``PositionTransition`` (design.md's job handlers table;
"New scope in this slice: tasks 5.16-5.17 route by ``PositionTransition`` so
a capital-RELEASING signal never takes the advisory lock").

A CONSUMES signal (opening a position, or the consuming half of a reverse)
goes through ``AllocateCapital`` — the only path that takes the advisory
lock. A RELEASES signal (closing a position) goes straight to
``ExecuteReservation`` against the reservation that originally opened the
position it is now closing, without ever touching the lock: releasing work
can only increase pool availability, so it cannot over-allocate
(design.md's "only capital-consuming work takes the lock").

Deviation, documented rather than silently made: design.md says ``granted``
comes from "the strategy's configured percentage of pool availability", but
no such percentage field exists anywhere in this codebase (``AllocationPolicy``
carries only ``venue``/``settlement_currency``/``fill_mode``). This handler
instead derives the *requested* amount as ``abs(position_size) * price`` —
the notional value the alert's own reference price implies for the intended
position — and lets the existing ``decide()`` algorithm (slice 4) apportion
``granted <= requested`` against real availability. This keeps
`quantity = granted / price` exactly as specified while never depending on
``alert.contracts``. A REVERSE transition is routed through the CONSUMES
branch only (its consuming half); fully closing the prior leg first is not
implemented in this slice — this is a known limitation, not a tested
scenario, and is called out in the apply-progress report.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
)
from strategy_manager.execution.application.execute_reservation import (
    ExecuteCommand,
    ExecuteResult,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.shared.domain.money import Currency, Money
from strategy_manager.signals.domain.position_transition import (
    PositionTransition,
    TransitionEffect,
    TransitionKind,
)

_CONSUMING_SIDE: dict[TransitionKind, OrderSide] = {
    TransitionKind.OPEN_LONG: OrderSide.BUY,
    TransitionKind.OPEN_SHORT: OrderSide.SELL,
    TransitionKind.REVERSE: OrderSide.BUY,
}
_RELEASING_SIDE: dict[TransitionKind, OrderSide] = {
    TransitionKind.CLOSE_LONG: OrderSide.SELL,
    TransitionKind.CLOSE_SHORT: OrderSide.BUY,
}


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


class ExecuteReservationPort(Protocol):
    """Narrowed to exactly what ``ProcessSignalHandler`` calls, so a fake
    can stand in for ``ExecuteReservation`` in unit tests without a full
    exchange/ledger stack."""

    async def execute(self, command: ExecuteCommand) -> ExecuteResult: ...


@dataclass(frozen=True, slots=True)
class ProcessSignalResult:
    transition_kind: str
    reservation_id: UUID | None
    executed: bool


class ProcessSignalHandler:
    """Composes ``AllocateCapital`` (slice 4) and ``ExecuteReservation``
    (slice 5) — the ``signal.process`` job's whole business logic
    (design.md's job handlers table)."""

    def __init__(
        self,
        signal_context: SignalContextPort,
        allocate_capital: AllocateCapital,
        execute_reservation: ExecuteReservationPort,
    ) -> None:
        self._signal_context = signal_context
        self._allocate_capital = allocate_capital
        self._execute_reservation = execute_reservation

    async def handle(self, signal_id: UUID) -> ProcessSignalResult:
        context = await self._signal_context.load(signal_id)
        transition = PositionTransition.classify(
            context.prior_position_size, context.position_size
        )

        if TransitionEffect.CONSUMES in transition.effects:
            return await self._handle_consumes(signal_id, context, transition)
        return await self._handle_releases(context, transition)

    async def _handle_consumes(
        self, signal_id: UUID, context: SignalContext, transition: PositionTransition
    ) -> ProcessSignalResult:
        requested = Money(
            amount=abs(context.position_size) * context.price,
            currency=Currency(context.settlement_currency),
        )
        result = await self._allocate_capital.allocate(
            AllocateCommand(
                signal_id=signal_id, strategy_id=context.strategy_id, requested=requested
            )
        )

        if result.reservation_id is None:
            return ProcessSignalResult(transition.kind.value, None, False)

        await self._execute_reservation.execute(
            ExecuteCommand(
                reservation_id=result.reservation_id,
                symbol=context.symbol,
                side=_CONSUMING_SIDE[transition.kind],
                price=context.price,
            )
        )
        return ProcessSignalResult(transition.kind.value, result.reservation_id, True)

    async def _handle_releases(
        self, context: SignalContext, transition: PositionTransition
    ) -> ProcessSignalResult:
        if context.prior_reservation_id is None:
            return ProcessSignalResult(transition.kind.value, None, False)

        await self._execute_reservation.execute(
            ExecuteCommand(
                reservation_id=context.prior_reservation_id,
                symbol=context.symbol,
                side=_RELEASING_SIDE[transition.kind],
                price=context.price,
            )
        )
        return ProcessSignalResult(transition.kind.value, context.prior_reservation_id, True)
