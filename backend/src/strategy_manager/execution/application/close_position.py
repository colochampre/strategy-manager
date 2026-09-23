"""``ClosePosition``: unwinding a position that an allocation opened.

Closing used to go through ``PlaceOrder`` against the reservation that opened
the position, and it could not work in any timing window. Inside the
reservation's TTL the opening attempt already owned the UNIQUE
``execution_attempts.reservation_id`` row; outside it — which is every real
holding period, the TTL being seconds — the pre-submit expiry re-check aborted
the order and flipped a FILLED reservation to RELEASED. No close ever reached
the exchange.

It could not work because it was the wrong shape. A close is not
reservation-bound submission:

- **It reserves nothing.** Once the opening order FILLED, its reservation
  stopped counting toward pool availability (only PENDING and SUBMITTED do),
  and the spend became visible in the exchange balance instead. Closing
  returns the money by the same route. There is no capital to hold.
- **It takes no advisory lock.** Releasing work can only increase availability,
  so it cannot over-allocate (design.md's "only capital-consuming work takes
  the lock").
- **Its size does not come from an amount and a price.** It comes from the
  ledger, because only the ledger knows what was actually acquired.

That last point is the substance. Dividing the granted capital by the current
price does not reproduce the opening quantity: the fill price differed from
the alert's reference price, a market order can fill in pieces at several
prices, and a fee charged in the base currency means less arrived than was
bought. Sell a quantity derived that way and it is wrong by all three errors
at once — too much, and the exchange rejects it for insufficient balance.

What it keeps from ``PlaceOrder`` is the crash-safety ordering, unchanged and
for the same reason: the settlement job is enqueued and committed BEFORE the
exchange is contacted, so from that instant there is a durable record naming
an order the exchange may or may not have seen.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    CommitPort,
    ExchangeError,
    ExchangeRegistryPort,
    ExecutionAttemptRepositoryPort,
    HeldPositionPort,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.market_symbol import base_currency_of
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort
from strategy_manager.shared.domain.errors import InvariantViolation

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CloseCommand:
    """``allocation_id`` is the reservation that OPENED the position being
    closed — the same id the opening fills carry in the ledger, which is what
    makes the position findable at all."""

    allocation_id: UUID
    strategy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    side: OrderSide


@dataclass(frozen=True, slots=True)
class CloseResult:
    status: str  # 'PLACED' | 'FAILED'
    execution_attempt_id: UUID
    base_size: Decimal
    exchange_order_id: str | None = None
    error: str | None = None


class NothingRecordedYet(Exception):
    """The ledger holds no base currency for this allocation.

    Deliberately not a ``DomainError``: this is a scheduling condition, not a
    business outcome. The overwhelmingly likely cause is that the opening
    order's settlement job has not landed yet — placement and settlement are
    separate jobs, and a close signal can arrive between them.

    Raising retries the close. The alternative, treating "nothing recorded" as
    "nothing to sell" and reporting success, would abandon an open position
    while claiming it was closed. Retrying an unclosable position is noisy;
    silently declaring it closed is how a live trade gets forgotten.
    """


class ClosePosition:
    """Implements the closing half of spec: trade-execution."""

    def __init__(
        self,
        exchanges: ExchangeRegistryPort,
        attempts: ExecutionAttemptRepositoryPort,
        held: HeldPositionPort,
        queue: JobQueuePort,
        clock: ClockPort,
        commit: CommitPort,
        settle_delay_seconds: float,
    ) -> None:
        self._exchanges = exchanges
        self._attempts = attempts
        self._held = held
        self._queue = queue
        self._clock = clock
        self._commit = commit
        self._settle_delay_seconds = settle_delay_seconds

    async def close(self, command: CloseCommand) -> CloseResult:
        # Whether this side can be closed at all is the ADAPTER's answer, not
        # this use case's. Spot cannot buy back an exact base quantity, so it
        # refuses; futures sizes both directions in the base currency, so it
        # does not. Deciding it here would have hard-coded spot's limitation
        # into every venue.
        base_currency = base_currency_of(command.symbol, command.settlement_currency)
        net = await self._held.net_base(command.allocation_id, base_currency)
        if net == 0:
            raise NothingRecordedYet(
                f"the ledger holds no {base_currency} position for allocation "
                f"{command.allocation_id}; the opening fills have most likely "
                "not settled yet"
            )

        _assert_direction_agrees(command, net, base_currency)
        base_size = abs(net)

        now = self._clock.now()
        client_order_id = str(uuid4())
        attempt_id = uuid4()
        exchange = self._exchanges.for_pool(command.exchange, command.venue)
        order = await exchange.build_close_order(
            CloseOrderSpec(
                client_order_id=client_order_id,
                symbol=command.symbol,
                side=command.side,
                base_size=base_size,
            )
        )

        await self._attempts.insert(
            ExecutionAttempt(
                id=attempt_id,
                reservation_id=None,
                closes_allocation_id=command.allocation_id,
                exchange=command.exchange,
                venue=command.venue,
                settlement_currency=command.settlement_currency,
                symbol=command.symbol,
                side=command.side,
                quantity=base_size,
                quote_amount=None,
                # A close records no leverage: none derived its size. The
                # multiple that explains the position is on the OPENING
                # attempt, where it was actually used.
                leverage=None,
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
        # From here on the order is recoverable by its client order id whatever
        # happens to this process. The UNIQUE constraint on
        # closes_allocation_id means a retry of this job cannot open a second
        # closing order against the same position.

        try:
            placed = await exchange.place(order)
        except ExchangeError as exc:
            # Definitive rejection. There is no reservation to release — the
            # capital was already spent and is sitting in the base currency,
            # where it stays until a later close succeeds.
            await self._attempts.mark_failed(attempt_id, str(exc))
            await self._commit.commit()
            logger.error(
                "close rejected by venue: strategy=%s symbol=%s allocation=%s "
                "attempt=%s pool=%s/%s/%s error=%s",
                command.strategy_id,
                command.symbol,
                command.allocation_id,
                attempt_id,
                command.exchange,
                command.venue,
                command.settlement_currency,
                exc,
            )
            return CloseResult(
                status="FAILED",
                execution_attempt_id=attempt_id,
                base_size=base_size,
                error=str(exc),
            )

        await self._attempts.mark_placed(attempt_id, placed.exchange_order_id)
        await self._commit.commit()
        return CloseResult(
            status="PLACED",
            execution_attempt_id=attempt_id,
            base_size=base_size,
            exchange_order_id=placed.exchange_order_id,
        )


def _assert_direction_agrees(
    command: CloseCommand, net: Decimal, base_currency: str
) -> None:
    """The ledger and the signal must agree on which way the position points.

    A close that SELLS is unwinding a long, so the ledger must show a positive
    holding; one that BUYS is unwinding a short, so it must show a negative
    one. If they disagree, one of the two is wrong about a real position and
    trading on either reading makes it worse -- a "close" in the wrong
    direction does not flatten anything, it doubles the exposure.

    This also catches on spot what the old clamp-at-zero quietly swallowed: a
    negative spot holding is a bookkeeping error, and it now says so instead
    of reporting "nothing held" and retrying forever.
    """
    closing_a_short = command.side is OrderSide.BUY
    if (net < 0) == closing_a_short:
        return

    held = "short" if net < 0 else "long"
    raise InvariantViolation(
        f"allocation {command.allocation_id} holds a {held} position of {net} "
        f"{base_currency}, but the signal asks to close it with a "
        f"{command.side.value}. Closing in that direction would add exposure "
        "rather than remove it."
    )
