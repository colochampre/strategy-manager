"""``PlaceOrder``: TXN-B1 (claim, pre-submit expiry re-check, schedule
settlement) followed by an unlocked network call.

This is the first half of what ``ExecuteReservation`` used to do alone. It was
split because Pionex answers a new order with an id and nothing else: what the
order actually filled at needs a second call, and doing that here would mean
the worker had to survive the whole round trip for the fill to ever be
recorded.

The ordering below is the entire crash-safety argument, so it is worth being
explicit about:

**The settlement job is enqueued before the order is placed**, inside the same
transaction that writes the attempt. That looks backwards — scheduling the
follow-up to work that has not happened — and it is exactly the point. The
client order id is chosen here and committed here, so from the instant that
transaction lands there is a durable record naming an order the exchange may
or may not have seen. Settlement asks the exchange about that id and gets a
definitive answer either way: fills, or no such order.

Enqueuing after a successful placement instead would leave the one window that
matters. Crash between the exchange accepting the order and the enqueue
committing, and the position exists with real money in it while nothing in
this system is scheduled to ever look for it again.

The advisory lock never appears here: only capital-*consuming* work takes it
(design.md's "only capital-consuming work takes the lock"), and this use case
only ever reduces or terminates one reservation it already owns.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.application.ports import (
    CommitPort,
    ExchangeError,
    ExchangeRegistryPort,
    ExecutionAttemptRepositoryPort,
    OpenOrderSpec,
    OrderNotPlaceable,
    ReservationGatewayPort,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import MarketBuy, MarketSell, OrderSide
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort

logger = logging.getLogger(__name__)

RELEASED = "RELEASED"
SUBMITTED = "SUBMITTED"


@dataclass(frozen=True, slots=True)
class PlaceCommand:
    """``price`` is the alert's bar-close reference price, used only to
    derive ``quantity = granted / price`` — never the ledger fill price
    (design.md § "Order size never comes from the alert")."""

    reservation_id: UUID
    symbol: str
    side: OrderSide
    price: Decimal


@dataclass(frozen=True, slots=True)
class PlaceResult:
    status: str  # 'PLACED' | 'FAILED' | 'ABORTED_EXPIRED' | 'REFUSED'
    execution_attempt_id: UUID | None
    exchange_order_id: str | None = None
    error: str | None = None


class PlaceOrder:
    """Implements the reservation-bound submission half of
    spec: trade-execution § Reservation-Bound Submission."""

    def __init__(
        self,
        reservations: ReservationGatewayPort,
        exchanges: ExchangeRegistryPort,
        attempts: ExecutionAttemptRepositoryPort,
        queue: JobQueuePort,
        clock: ClockPort,
        commit: CommitPort,
        settle_delay_seconds: float,
    ) -> None:
        self._reservations = reservations
        self._exchanges = exchanges
        self._attempts = attempts
        self._queue = queue
        self._clock = clock
        self._commit = commit
        self._settle_delay_seconds = settle_delay_seconds

    async def place(self, command: PlaceCommand) -> PlaceResult:
        reservation = await self._reservations.get_for_update(command.reservation_id)
        now = self._clock.now()

        # ---- TXN-B1: pre-submit expiry re-check, no advisory lock
        if reservation.expires_at <= now:
            await self._reservations.mark(reservation.id, RELEASED, now)
            await self._commit.commit()
            return PlaceResult(status="ABORTED_EXPIRED", execution_attempt_id=None)

        client_order_id = str(uuid4())
        attempt_id = uuid4()

        # Built before any write so a malformed price is rejected without
        # leaving a half-built attempt or an orphan settle job behind. It is
        # also the object that decides *which* size this order carries, and
        # the attempt below records that same number rather than a second,
        # differently-derived one.
        #
        # The ADAPTER builds it, because denomination is a venue property: on
        # spot a buy carries the granted amount verbatim, on futures that
        # amount is margin and the size depends on a leverage only the venue
        # can report. So this call may reach the network -- which is exactly
        # why it happens here, before the transaction's writes, and not
        # inside them.
        exchange = self._exchanges.for_pool(reservation.exchange, reservation.venue)
        try:
            order = await exchange.build_open_order(
                OpenOrderSpec(
                    client_order_id=client_order_id,
                    symbol=command.symbol,
                    side=command.side,
                    granted=reservation.amount,
                    price=command.price,
                )
            )
        except OrderNotPlaceable as exc:
            # Definitive: the venue's own per-symbol rules make this size
            # impossible, and no retry changes a rule the market itself
            # enforces. Nothing has been written yet -- build happens before
            # every write in this method -- so there is no attempt to mark
            # failed, only the reservation to release.
            await self._reservations.mark(reservation.id, RELEASED, now)
            await self._commit.commit()
            logger.warning(
                "order not placeable, releasing reservation: reservation=%s "
                "strategy=%s symbol=%s reason=%s",
                reservation.id,
                reservation.strategy_id,
                command.symbol,
                exc,
            )
            return PlaceResult(
                status="REFUSED", execution_attempt_id=None, error=str(exc)
            )
        quantity, quote_amount, leverage = _sizes(order)

        await self._reservations.mark(reservation.id, SUBMITTED, now)
        await self._attempts.insert(
            ExecutionAttempt(
                id=attempt_id,
                reservation_id=reservation.id,
                closes_allocation_id=None,
                exchange=reservation.exchange,
                venue=reservation.venue,
                settlement_currency=reservation.settlement_currency,
                symbol=command.symbol,
                side=order.side,
                quantity=quantity,
                quote_amount=quote_amount,
                leverage=leverage,
                status=ExecutionStatus.SUBMITTED,
                origin=ExecutionOrigin.SYSTEM,
                client_order_id=client_order_id,
            )
        )
        await self._queue.enqueue(
            Job(
                kind=JobKind.EXECUTION_SETTLE,
                payload={"execution_attempt_id": str(attempt_id)},
                run_after=now + timedelta(seconds=self._settle_delay_seconds),
            )
        )
        await self._commit.commit()
        # ---- TXN-B1 ends. From here on the order is recoverable by its
        # client order id whatever happens to this process.

        # ---- no transaction: the network call is outside every lock and
        # every transaction (design.md § Transaction Boundaries)
        try:
            placed = await exchange.place(order)
        except ExchangeError as exc:
            # A rejection is definitive: the exchange saw the order and
            # refused it, so the reservation can be released now rather than
            # waiting for settlement to reach the same conclusion.
            await self._reservations.mark(reservation.id, RELEASED, now)
            await self._attempts.mark_failed(attempt_id, str(exc))
            await self._commit.commit()
            return PlaceResult(
                status="FAILED", execution_attempt_id=attempt_id, error=str(exc)
            )

        await self._attempts.mark_placed(attempt_id, placed.exchange_order_id)
        await self._commit.commit()
        return PlaceResult(
            status="PLACED",
            execution_attempt_id=attempt_id,
            exchange_order_id=placed.exchange_order_id,
        )


def _sizes(
    order: PlaceableOrder,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Projects the order onto the attempt's nullable columns.

    Exactly one size is ever populated — the one that went on the wire.
    ``leverage`` is set only for a futures order, because only there does a
    number outside the order change what the size means: the same base size
    at 5x and at 20x is a different fraction of the pool, and the multiple in
    force when it was sized is the only thing that explains it.
    """
    match order:
        case MarketBuy():
            return None, order.quote_amount, None
        case MarketSell():
            return order.base_size, None, None
        case FuturesMarketOrder():
            return order.base_size, None, order.leverage
