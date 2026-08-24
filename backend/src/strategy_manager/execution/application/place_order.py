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

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.application.ports import (
    CommitPort,
    ExchangeError,
    ExchangePort,
    ExecutionAttemptRepositoryPort,
    ReservationGatewayPort,
)
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.order import (
    MarketBuy,
    MarketSell,
    OrderRequest,
    OrderSide,
    market_order,
)
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort

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
    status: str  # 'PLACED' | 'FAILED' | 'ABORTED_EXPIRED'
    execution_attempt_id: UUID | None
    exchange_order_id: str | None = None
    error: str | None = None


class PlaceOrder:
    """Implements the reservation-bound submission half of
    spec: trade-execution § Reservation-Bound Submission."""

    def __init__(
        self,
        reservations: ReservationGatewayPort,
        exchange: ExchangePort,
        attempts: ExecutionAttemptRepositoryPort,
        queue: JobQueuePort,
        clock: ClockPort,
        commit: CommitPort,
        settle_delay_seconds: float,
    ) -> None:
        self._reservations = reservations
        self._exchange = exchange
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
        order = market_order(
            side=command.side,
            client_order_id=client_order_id,
            symbol=command.symbol,
            granted=reservation.amount,
            price=command.price,
        )
        quantity, quote_amount = _sizes(order)

        await self._reservations.mark(reservation.id, SUBMITTED, now)
        await self._attempts.insert(
            ExecutionAttempt(
                id=attempt_id,
                reservation_id=reservation.id,
                closes_allocation_id=None,
                venue=reservation.venue,
                settlement_currency=reservation.settlement_currency,
                symbol=command.symbol,
                side=order.side,
                quantity=quantity,
                quote_amount=quote_amount,
                status=ExecutionStatus.SUBMITTED,
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
            placed = await self._exchange.place(order)
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


def _sizes(order: OrderRequest) -> tuple[Decimal | None, Decimal | None]:
    """Projects the order's single size onto the attempt's two nullable
    columns. Exactly one is ever populated — the one that went on the wire."""
    match order:
        case MarketBuy():
            return None, order.quote_amount
        case MarketSell():
            return order.base_size, None
