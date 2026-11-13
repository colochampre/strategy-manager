"""``ConfirmProtectiveStop``: finding the stop that rests for a live opening, and
closing the position at once when none does (subscriber-safety SS.5, decision D7).

The opening order itself carries the stop, so there is never a moment in which the
position exists without it. What this job answers is whether the venue really holds it:
after the opening's fills are recorded, it asks the adapter for the conditional order
whose parent is the opening.

- **found** -> the stop is ``RESTING`` and its venue id is recorded, the id its execution
  carries when it fires;
- **not found, or the venue refused the question definitively** -> the stop is
  ``FAILED``, an ERROR names the user, the symbol and the attempt, and the position is
  closed at market through ``ClosePosition``, sized from the ledger, with no signal: no
  position may stay open without its stop. A ledger already flat means the position is
  gone by other means, so the stop is ``GONE`` and nothing is sent;
- **a failure whose outcome is unknown** -> raised unchanged, so the job retries.
  Closing a protected position because the venue timed out is the failure this prevents.

The ``FAILED`` mark is staged and NOT committed on its own. ``ClosePosition`` commits the
closing attempt and its settle job on this same session, so the mark and the close land
together. If the close cannot be built (an unknown failure reading the venue's rules), the
exception rolls the mark back with it and the retry asks the venue again, instead of
finding a ``FAILED`` row and skipping the close. Lock order is untouched: this takes no
pool lock, and ``ClosePosition`` takes none.
"""

import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from strategy_manager.execution.application.close_position import (
    CloseCommand,
    CloseResult,
    NothingRecordedYet,
)
from strategy_manager.execution.application.ports import (
    CommitPort,
    ExchangeError,
    ExecutionAttemptRepositoryPort,
    ModeExchangesPort,
    ProtectiveStopRepositoryPort,
    ReservationGatewayPort,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.protective_stop import StopStatus
from strategy_manager.shared.application.ports import AllocationModePort

logger = logging.getLogger(__name__)


class PositionCloserPort(Protocol):
    """What this use case needs of ``ClosePosition``."""

    async def close(self, command: CloseCommand) -> CloseResult: ...


@dataclass(frozen=True, slots=True)
class ConfirmResult:
    status: str  # 'SKIPPED' | 'RESTING' | 'CLOSING' | 'GONE'
    close: CloseResult | None = None


class ConfirmProtectiveStop:
    def __init__(
        self,
        stops: ProtectiveStopRepositoryPort,
        attempts: ExecutionAttemptRepositoryPort,
        reservations: ReservationGatewayPort,
        exchanges: ModeExchangesPort,
        allocation_modes: AllocationModePort,
        closer: PositionCloserPort,
        commit: CommitPort,
    ) -> None:
        self._stops = stops
        self._attempts = attempts
        self._reservations = reservations
        self._exchanges = exchanges
        self._allocation_modes = allocation_modes
        self._closer = closer
        self._commit = commit

    async def confirm(self, user_id: UUID, attempt_id: UUID) -> ConfirmResult:
        stop = await self._stops.for_attempt(user_id, attempt_id)
        if stop is None or stop.status is not StopStatus.PENDING:
            # Already decided (a redelivered job), or an attempt with no stop to find.
            return ConfirmResult(status="SKIPPED")

        attempt = await self._attempts.get(user_id, attempt_id)
        mode = await self._allocation_modes.mode_of(user_id, attempt.allocation_id)
        exchange = (await self._exchanges.for_mode(mode)).for_pool(
            attempt.exchange, attempt.venue
        )
        try:
            found = await exchange.find_resting_stop(attempt.client_order_id, attempt.symbol)
            refusal = None
        except ExchangeError as exc:
            # The venue decided it will not answer: the stop cannot be shown to rest.
            found = None
            refusal = str(exc)

        if found is not None:
            await self._stops.mark(
                user_id, attempt_id, StopStatus.RESTING, venue_stop_id=found.venue_stop_id
            )
            await self._commit.commit()
            logger.info(
                "protective stop resting: user=%s symbol=%s attempt=%s venue_stop_id=%s",
                user_id,
                attempt.symbol,
                attempt_id,
                found.venue_stop_id,
            )
            return ConfirmResult(status="RESTING")

        # Staged only: ClosePosition commits on this session, taking the mark with it.
        await self._stops.mark(user_id, attempt_id, StopStatus.FAILED)
        logger.error(
            "protective stop not found, closing the position at once: user=%s symbol=%s "
            "attempt=%s reason=%s",
            user_id,
            attempt.symbol,
            attempt_id,
            refusal or "no conditional order has the opening as its parent",
        )
        reservation = await self._reservations.get_for_update(user_id, attempt.allocation_id)
        try:
            closed = await self._closer.close(
                CloseCommand(
                    user_id=user_id,
                    allocation_id=attempt.allocation_id,
                    strategy_id=reservation.strategy_id,
                    exchange=attempt.exchange,
                    venue=attempt.venue,
                    settlement_currency=attempt.settlement_currency,
                    symbol=attempt.symbol,
                    side=OrderSide.SELL if attempt.side is OrderSide.BUY else OrderSide.BUY,
                    # No signal asked for this close, so no delivery records an outcome.
                    signal_id=None,
                    delivery_id=None,
                    reference_price=None,
                )
            )
        except NothingRecordedYet:
            # The ledger is flat: the position closed by other means, and there is
            # nothing left to protect or to close.
            await self._stops.mark(user_id, attempt_id, StopStatus.GONE)
            await self._commit.commit()
            logger.warning(
                "protective stop's position is already flat, nothing to close: user=%s "
                "symbol=%s attempt=%s",
                user_id,
                attempt.symbol,
                attempt_id,
            )
            return ConfirmResult(status="GONE")
        return ConfirmResult(status="CLOSING", close=closed)
