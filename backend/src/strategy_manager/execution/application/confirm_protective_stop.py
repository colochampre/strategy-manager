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
from decimal import Decimal
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
    ExchangePort,
    ExecutionAttemptRepositoryPort,
    ModeExchangesPort,
    ProtectiveStopRepositoryPort,
    ReservationGatewayPort,
)
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
from strategy_manager.execution.domain.fill import average_fill_price
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.protective_stop import ProtectiveStop, StopStatus
from strategy_manager.shared.application.ports import AllocationModePort
from strategy_manager.shared.domain.errors import InvariantViolation

logger = logging.getLogger(__name__)


class FillsNotPublishedYet(Exception):
    """The venue returned no fills for an opening whose settle job recorded them. Raised
    so the job retries: an empty list is "accepted and not yet published", never a reason
    to price a stop from nothing or to close a position."""


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
        if stop.client_stop_id is not None:
            # The row itself records how this venue's stop is placed: after the fill, under
            # an id of its own (SS.6). A stop that rides the opening order has none.
            return await self._confirm_placed_after_fill(
                user_id, attempt_id, stop, attempt, exchange
            )
        try:
            found = await exchange.find_resting_stop(attempt.client_order_id, attempt.symbol)
            refusal = None
        except ExchangeError as exc:
            # The venue decided it will not answer: the stop cannot be shown to rest.
            found = None
            refusal = str(exc)

        if found is not None:
            return await self._rest(user_id, attempt_id, attempt, found.venue_stop_id)

        return await self._fail_and_close(
            user_id,
            attempt_id,
            attempt,
            what="protective stop not found",
            reason=refusal or "no conditional order has the opening as its parent",
        )

    async def _confirm_placed_after_fill(
        self,
        user_id: UUID,
        attempt_id: UUID,
        stop: ProtectiveStop,
        attempt: ExecutionAttempt,
        exchange: ExchangePort,
    ) -> ConfirmResult:
        """The venue has no stop on the opening order (Binance): this job places it.

        **No trigger recorded yet**: the first pass. The opening's fills are read, their
        volume-weighted average is the entry, the adapter turns it into the trigger, and the
        trigger is COMMITTED before the request. **A trigger recorded**: an earlier pass
        committed it and then may or may not have reached the venue, so the stop is read
        back by its ``client_stop_id`` first. Found in any status is ``RESTING`` (SS.7's
        watcher reads what became of it); absent after the adapter's retries of a read that
        lags the placing, the request is sent again under the SAME id and trigger, so a
        request that was merely slow cannot become a second stop.

        A refusal the venue decided takes SS.5's path: ``FAILED``, an ERROR line and the
        position closed at once. An outcome nobody knows propagates, so the job retries and
        lands on the read-back. An acknowledged stop is ``RESTING`` at once and is not read
        back: ``-2013`` is how a just-placed stop answers.
        """
        client_stop_id = stop.client_stop_id or ""
        try:
            if stop.trigger_price is None:
                trigger = await self._record_trigger(user_id, attempt_id, stop, attempt, exchange)
                resent = False
            else:
                found = await exchange.find_stop(attempt.symbol, client_stop_id)
                if found is not None:
                    return await self._rest(user_id, attempt_id, attempt, found.venue_stop_id)
                trigger = stop.trigger_price
                resent = True
            try:
                algo_id = await exchange.place_stop(
                    attempt.symbol, stop.position_side, trigger, client_stop_id
                )
            except ExchangeError:
                if not resent:
                    raise
                # A request sent again may be refused because the first one did arrive and
                # its read only lagged (a duplicate id). Read once more before closing, so a
                # protected position is never closed for a stop that rests.
                found = await exchange.find_stop(attempt.symbol, client_stop_id)
                if found is None:
                    raise
                return await self._rest(user_id, attempt_id, attempt, found.venue_stop_id)
        except (ExchangeError, InvariantViolation) as exc:
            return await self._fail_and_close(
                user_id,
                attempt_id,
                attempt,
                what="protective stop could not be placed",
                reason=str(exc),
            )
        return await self._rest(user_id, attempt_id, attempt, algo_id)

    async def _record_trigger(
        self,
        user_id: UUID,
        attempt_id: UUID,
        stop: ProtectiveStop,
        attempt: ExecutionAttempt,
        exchange: ExchangePort,
    ) -> Decimal:
        """Prices the stop from the opening's fills and commits the price."""
        fills = await exchange.fetch_fills(attempt.client_order_id, attempt.symbol)
        if not fills:
            raise FillsNotPublishedYet(
                f"the venue returned no fills for attempt {attempt_id} on {attempt.symbol}"
            )
        trigger = await exchange.stop_trigger_price(
            attempt.symbol, stop.position_side, average_fill_price(fills), stop.stop_loss_pct
        )
        await self._stops.record_trigger_price(user_id, attempt_id, trigger)
        await self._commit.commit()
        return trigger

    async def _rest(
        self, user_id: UUID, attempt_id: UUID, attempt: ExecutionAttempt, venue_stop_id: str
    ) -> ConfirmResult:
        await self._stops.mark(user_id, attempt_id, StopStatus.RESTING, venue_stop_id=venue_stop_id)
        await self._commit.commit()
        logger.info(
            "protective stop resting: user=%s symbol=%s attempt=%s venue_stop_id=%s",
            user_id,
            attempt.symbol,
            attempt_id,
            venue_stop_id,
        )
        return ConfirmResult(status="RESTING")

    async def _fail_and_close(
        self,
        user_id: UUID,
        attempt_id: UUID,
        attempt: ExecutionAttempt,
        *,
        what: str,
        reason: str,
    ) -> ConfirmResult:
        # Staged only: ClosePosition commits on this session, taking the mark with it.
        await self._stops.mark(user_id, attempt_id, StopStatus.FAILED)
        logger.error(
            "%s, closing the position at once: user=%s symbol=%s attempt=%s reason=%s",
            what,
            user_id,
            attempt.symbol,
            attempt_id,
            reason,
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
