"""``WatchProtectiveStops``: what became of every protective stop that rests
(subscriber-safety SS.7).

A stop that fires closes a position at the venue and this system never submitted the order,
so without this job the ledger would still hold the position and reconciliation would raise
a discrepancy for money the system itself had protected. Every ``RESTING`` stop is read at
the venue, as the user whose key placed it, and what the venue says decides it:

- **still rests**: left alone;
- **fired**: its fills are booked the way a close's settle books them, under the stop's
  allocation, on a new FILLED attempt whose cause is ``STOP``. The stop is marked ``FIRED``,
  a leaving subscription that holds nothing is ended, and a WARNING ``protective stop fired``
  is written (the ``STOP_FIRED`` event comes with SS.10's table), all in one transaction. A
  fired stop whose fills the venue has not all published yet is not booked: booking part of
  it would leave the ledger holding a position the venue no longer has. It waits, with a
  WARNING, and is read again;
- **gone with no fill** (its position closed by other means, or it was cancelled): marked
  ``GONE`` and nothing is booked. If the ledger still holds the position, that is said in a
  WARNING, because nothing protects it any more.

**Concurrency.** The venue read happens OUTSIDE the pool lock, as every remote read does. The
decision is then made under the user's pool lock (taken before any row lock, as everywhere)
and re-checks that the stop is still ``RESTING``: a stop another run decided while this one
waited is skipped. Each stop is committed on its own, so one stop failing (logged with its
user, symbol and attempt, then rolled back) never stops the others, and a stop that failed
stays ``RESTING`` and is read again on the next tick.

**Silent-failure audit.** Every branch that decides to do nothing says why in the log: a
fired stop whose fills cannot be booked (short of, more than, or against the ledger), a stop
gone beside an open position, and a stop that could not be read. Only a stop that rests, or
that another run already decided, is quiet.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.application.fill_record import fill_record_of
from strategy_manager.execution.application.ports import (
    ExecutionAttemptRepositoryPort,
    FillRecorderPort,
    HeldPositionPort,
    LeavingSubscriptionPort,
    ModeExchangesPort,
    PoolLockPort,
    ProtectiveStopRepositoryPort,
    ReservationGatewayPort,
    StopFired,
    StopNotResting,
    UnitOfWorkPort,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionCause,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.market_symbol import base_currency_of, market_key
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.protective_stop import ProtectiveStop, StopStatus
from strategy_manager.shared.application.ports import (
    AllocationModePort,
    SafetyEventWriterPort,
    UsdRateProviderPort,
)
from strategy_manager.shared.domain.money import Currency
from strategy_manager.shared.domain.safety_event import NewSafetyEvent, SafetyEventKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WatchResult:
    """How many stops each outcome took, for the log line and for tests. ``read`` is every
    stop whose venue answer was asked for."""

    read: int = 0
    fired: int = 0
    gone: int = 0
    waiting: int = 0
    refused: int = 0
    skipped: int = 0
    failed: int = 0


class WatchProtectiveStops:
    def __init__(
        self,
        stops: ProtectiveStopRepositoryPort,
        attempts: ExecutionAttemptRepositoryPort,
        reservations: ReservationGatewayPort,
        held: HeldPositionPort,
        fill_recorder: FillRecorderPort,
        usd_rates: UsdRateProviderPort,
        pool_lock: PoolLockPort,
        leaving: LeavingSubscriptionPort,
        allocation_modes: AllocationModePort,
        exchanges_for: Callable[[UUID], AbstractAsyncContextManager[ModeExchangesPort]],
        unit_of_work: UnitOfWorkPort,
        safety_events: SafetyEventWriterPort,
    ) -> None:
        self._safety_events = safety_events
        self._stops = stops
        self._attempts = attempts
        self._reservations = reservations
        self._held = held
        self._fill_recorder = fill_recorder
        self._usd_rates = usd_rates
        self._pool_lock = pool_lock
        self._leaving = leaving
        self._allocation_modes = allocation_modes
        self._exchanges_for = exchanges_for
        self._uow = unit_of_work

    async def watch(self) -> WatchResult:
        """One pass over every RESTING stop of every user. Never raises for a stop: the
        pass ends with the others read, and a failed stop is logged and stays RESTING. Only
        the first system query can fail the pass, and then the job retries."""
        owned = await self._stops.resting_of_every_user()
        by_user: dict[UUID, list[ProtectiveStop]] = {}
        for entry in owned:
            by_user.setdefault(entry.user_id, []).append(entry.stop)

        totals = WatchResult()
        for user_id, stops in by_user.items():
            totals = _add(totals, await self._watch_user(user_id, stops))
        return totals

    async def _watch_user(self, user_id: UUID, stops: list[ProtectiveStop]) -> WatchResult:
        """One user's stops, read with that user's key alone."""
        result = WatchResult()
        try:
            async with self._exchanges_for(user_id) as exchanges:
                for stop in stops:
                    result = _add(result, await self._watch_one(user_id, stop, exchanges))
        except Exception:
            # The user's exchanges could not be opened (their key does not open, say), or
            # closing them failed. Each of their stops not yet read stays RESTING.
            await self._uow.rollback()
            unread = len(stops) - result.read
            logger.error(
                "protective stops not read, they stay RESTING and are read again: user=%s "
                "stops_unread=%s",
                user_id,
                unread,
                exc_info=True,
            )
            result = _add(result, WatchResult(failed=max(unread, 1)))
        return result

    async def _watch_one(
        self, user_id: UUID, stop: ProtectiveStop, exchanges: ModeExchangesPort
    ) -> WatchResult:
        try:
            attempt = await self._attempts.get(user_id, stop.execution_attempt_id)
            mode = await self._allocation_modes.mode_of(user_id, stop.allocation_id)
            exchange = (await exchanges.for_mode(mode)).for_pool(stop.exchange, stop.venue)
            # The venue is read OUTSIDE the pool lock: a lock is never held across exchange
            # latency.
            reading = await exchange.read_stop(stop, attempt.client_order_id)
            if isinstance(reading, StopFired):
                return await self._decide_fired(user_id, stop, attempt, reading)
            if isinstance(reading, StopNotResting):
                return await self._decide_gone(user_id, stop, attempt)
            return WatchResult(read=1)
        except Exception:
            await self._uow.rollback()
            logger.error(
                "protective stop could not be read or decided, it stays RESTING and is read "
                "again: user=%s symbol=%s attempt=%s stop=%s",
                user_id,
                stop.symbol,
                stop.execution_attempt_id,
                stop.id,
                exc_info=True,
            )
            return WatchResult(read=1, failed=1)

    async def _lock_and_recheck(
        self, user_id: UUID, stop: ProtectiveStop, attempt: ExecutionAttempt
    ) -> bool:
        """Takes the user's pool lock and answers whether the stop is still RESTING. When
        another run decided it first, the (empty) transaction is ended to release the lock."""
        await self._pool_lock.acquire(
            user_id, attempt.exchange, attempt.venue, attempt.settlement_currency
        )
        current = await self._stops.for_attempt(user_id, stop.execution_attempt_id)
        if current is not None and current.status is StopStatus.RESTING:
            return True
        await self._uow.commit()
        logger.debug(
            "protective stop already decided by another run: user=%s symbol=%s attempt=%s",
            user_id,
            stop.symbol,
            stop.execution_attempt_id,
        )
        return False

    async def _decide_gone(
        self, user_id: UUID, stop: ProtectiveStop, attempt: ExecutionAttempt
    ) -> WatchResult:
        if not await self._lock_and_recheck(user_id, stop, attempt):
            return WatchResult(read=1, skipped=1)
        base = base_currency_of(attempt.symbol, attempt.settlement_currency)
        net = await self._held.net_base(user_id, stop.allocation_id, base)
        await self._stops.mark(user_id, stop.execution_attempt_id, StopStatus.GONE)
        await self._uow.commit()
        if net != 0:
            # Nothing is left to watch, and nothing protects the position either.
            logger.warning(
                "protective stop is gone while the ledger still holds the position, which "
                "is now open without its stop: user=%s symbol=%s attempt=%s stop=%s "
                "allocation=%s ledger_net=%s",
                user_id,
                stop.symbol,
                stop.execution_attempt_id,
                stop.id,
                stop.allocation_id,
                net,
            )
        else:
            logger.info(
                "protective stop gone with its position: user=%s symbol=%s attempt=%s stop=%s",
                user_id,
                stop.symbol,
                stop.execution_attempt_id,
                stop.id,
            )
        return WatchResult(read=1, gone=1)

    async def _decide_fired(
        self,
        user_id: UUID,
        stop: ProtectiveStop,
        attempt: ExecutionAttempt,
        fired: StopFired,
    ) -> WatchResult:
        if not await self._lock_and_recheck(user_id, stop, attempt):
            return WatchResult(read=1, skipped=1)

        base = base_currency_of(attempt.symbol, attempt.settlement_currency)
        net = await self._held.net_base(user_id, stop.allocation_id, base)
        booked = sum((fill.quantity for fill in fired.fills), Decimal(0))
        holds_the_long = net > 0
        opened_long = attempt.side is OrderSide.BUY

        misfit = None
        if net == 0:
            misfit = "the ledger holds none of it"
        elif holds_the_long != opened_long:
            misfit = "the ledger holds it the other way"
        elif booked > abs(net):
            misfit = "the stop closed more than the ledger holds"
        if misfit is not None:
            await self._uow.commit()
            logger.error(
                "protective stop fired but its fills do not fit the ledger (%s), so nothing "
                "was booked and the stop stays RESTING: user=%s symbol=%s attempt=%s "
                "stop=%s allocation=%s ledger_net=%s stop_fills=%s",
                misfit,
                user_id,
                stop.symbol,
                stop.execution_attempt_id,
                stop.id,
                stop.allocation_id,
                net,
                booked,
            )
            return WatchResult(read=1, refused=1)

        if booked < abs(net):
            await self._uow.commit()
            logger.warning(
                "protective stop fired but its fills are not all published yet, so nothing "
                "was booked and the stop is read again: user=%s symbol=%s attempt=%s stop=%s "
                "ledger_net=%s published=%s",
                user_id,
                stop.symbol,
                stop.execution_attempt_id,
                stop.id,
                net,
                booked,
            )
            return WatchResult(read=1, waiting=1)

        await self._book(user_id, stop, attempt, fired, booked)
        await self._uow.commit()
        logger.warning(
            "protective stop fired and its fills are booked: user=%s symbol=%s attempt=%s "
            "stop=%s allocation=%s quantity=%s stop_order=%s",
            user_id,
            stop.symbol,
            stop.execution_attempt_id,
            stop.id,
            stop.allocation_id,
            booked,
            fired.exchange_order_id,
        )
        return WatchResult(read=1, fired=1)

    async def _book(
        self,
        user_id: UUID,
        stop: ProtectiveStop,
        opening: ExecutionAttempt,
        fired: StopFired,
        quantity: Decimal,
    ) -> None:
        """Books the stop's fills under its allocation, the way a close's settle does.

        The row locks come after the pool lock the caller holds: the reservation first (for
        its strategy), then the attempt, the ledger rows and the stop. Everything stages on
        the caller's transaction and nothing commits here."""
        reservation = await self._reservations.get_for_update(user_id, stop.allocation_id)
        usd_rate = await self._usd_rates.usd_rate(Currency(opening.settlement_currency))
        closing_side = OrderSide.SELL if opening.side is OrderSide.BUY else OrderSide.BUY
        attempt = ExecutionAttempt(
            id=uuid4(),
            reservation_id=None,
            closes_allocation_id=stop.allocation_id,
            exchange=opening.exchange,
            venue=opening.venue,
            settlement_currency=opening.settlement_currency,
            symbol=opening.symbol,
            side=closing_side,
            quantity=quantity,
            quote_amount=None,
            # A close records no leverage: none derived its size.
            leverage=None,
            status=ExecutionStatus.FILLED,
            origin=ExecutionOrigin.SYSTEM,
            cause=ExecutionCause.STOP,
            client_order_id=f"stop-{stop.id}",
            exchange_order_id=fired.exchange_order_id,
        )
        await self._attempts.insert(user_id, attempt)
        for fill in fired.fills:
            await self._record(user_id, attempt, reservation.strategy_id, usd_rate, fill)
        await self._stops.mark(user_id, stop.execution_attempt_id, StopStatus.FIRED)
        # The fills above can leave a LEAVING subscription holding nothing: it ends in this
        # same transaction, under the pool lock, as a close's settle does.
        await self._leaving.end_if_flat(
            user_id,
            reservation.strategy_id,
            opening.exchange,
            opening.venue,
            opening.settlement_currency,
        )
        # SS.10: the user learns their stop fired on the very commit that books it, so the
        # event exists exactly when the fills do. Its source is the STOP attempt just
        # written, which is what keeps a second run from writing a second one.
        trigger = stop.trigger_price
        await self._safety_events.record(
            NewSafetyEvent(
                user_id=user_id,
                kind=SafetyEventKind.STOP_FIRED,
                strategy_id=reservation.strategy_id,
                allocation_id=stop.allocation_id,
                exchange=opening.exchange,
                venue=opening.venue,
                symbol=market_key(opening.symbol),
                detail={
                    "quantity": format(quantity, "f"),
                    "trigger_price": "" if trigger is None else format(trigger, "f"),
                },
                execution_attempt_id=attempt.id,
            )
        )

    async def _record(
        self,
        user_id: UUID,
        attempt: ExecutionAttempt,
        strategy_id: UUID,
        usd_rate: Decimal,
        fill: Fill,
    ) -> None:
        await self._fill_recorder.record(
            fill_record_of(user_id, attempt, strategy_id, usd_rate, fill)
        )


def _add(first: WatchResult, second: WatchResult) -> WatchResult:
    return WatchResult(
        read=first.read + second.read,
        fired=first.fired + second.fired,
        gone=first.gone + second.gone,
        waiting=first.waiting + second.waiting,
        refused=first.refused + second.refused,
        skipped=first.skipped + second.skipped,
        failed=first.failed + second.failed,
    )

