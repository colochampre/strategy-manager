"""``ExecuteReservation``: TXN-B1 (claim + pre-submit expiry re-check) followed
by an unlocked network call and TXN-B2 (fill + terminal status) (design.md §
Data Flow, § Transaction Boundaries, § sequence diagram 3; spec:
trade-execution § Pre-Submit Expiry Re-Check, § Fill Recording).

The advisory lock never appears here: only capital-*consuming* work takes it
(design.md's "only capital-consuming work takes the lock"), and this use
case only ever reduces or terminates one reservation it already owns.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.application.ports import (
    CommitPort,
    ExchangeError,
    ExchangePort,
    ExecutionAttemptRepositoryPort,
    FillRecord,
    FillRecorderPort,
    ReservationGatewayPort,
    ReservationSnapshot,
)
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import OrderRequest, OrderSide, compute_order_quantity
from strategy_manager.shared.application.ports import ClockPort, UsdRateProviderPort
from strategy_manager.shared.domain.money import Currency

_RELEASED = "RELEASED"
_SUBMITTED = "SUBMITTED"
_FILLED = "FILLED"


@dataclass(frozen=True, slots=True)
class ExecuteCommand:
    """``price`` is the alert's bar-close reference price, used only to
    derive ``quantity = granted / price`` — never the ledger fill price
    (design.md § "Order size never comes from the alert")."""

    reservation_id: UUID
    symbol: str
    side: OrderSide
    price: Decimal


@dataclass(frozen=True, slots=True)
class ExecuteResult:
    status: str  # 'FILLED' | 'FAILED' | 'ABORTED_EXPIRED'
    execution_attempt_id: UUID | None
    exchange_order_id: str | None = None
    error: str | None = None


class ExecuteReservation:
    """Implements the reservation-bound submission and fill-recording flow
    (spec: trade-execution § Reservation-Bound Submission)."""

    def __init__(
        self,
        reservations: ReservationGatewayPort,
        exchange: ExchangePort,
        attempts: ExecutionAttemptRepositoryPort,
        fill_recorder: FillRecorderPort,
        usd_rate_provider: UsdRateProviderPort,
        clock: ClockPort,
        commit: CommitPort,
    ) -> None:
        self._reservations = reservations
        self._exchange = exchange
        self._attempts = attempts
        self._fill_recorder = fill_recorder
        self._usd_rate_provider = usd_rate_provider
        self._clock = clock
        self._commit = commit

    async def execute(self, command: ExecuteCommand) -> ExecuteResult:
        reservation = await self._reservations.get_for_update(command.reservation_id)
        now = self._clock.now()

        # ---- TXN-B1: pre-submit expiry re-check, no advisory lock
        if reservation.expires_at <= now:
            await self._reservations.mark(reservation.id, _RELEASED, now)
            await self._commit.commit()
            return ExecuteResult(status="ABORTED_EXPIRED", execution_attempt_id=None)

        quantity = compute_order_quantity(reservation.amount, command.price)
        client_order_id = str(uuid4())
        attempt_id = uuid4()

        await self._reservations.mark(reservation.id, _SUBMITTED, now)
        await self._attempts.insert(
            ExecutionAttempt(
                id=attempt_id,
                reservation_id=reservation.id,
                venue=reservation.venue,
                settlement_currency=reservation.settlement_currency,
                symbol=command.symbol,
                side=command.side,
                quantity=quantity,
                status=ExecutionStatus.SUBMITTED,
                client_order_id=client_order_id,
            )
        )
        await self._commit.commit()
        # ---- TXN-B1 ends

        order = OrderRequest(
            client_order_id=client_order_id,
            symbol=command.symbol,
            side=command.side,
            quantity=quantity,
        )

        # ---- no transaction: the network call is outside every lock and
        # every transaction (design.md § Transaction Boundaries)
        try:
            fill = await self._exchange.submit(order)
        except ExchangeError as exc:
            await self._reservations.mark(reservation.id, _RELEASED, now)
            await self._attempts.mark_failed(attempt_id, str(exc))
            await self._commit.commit()
            return ExecuteResult(status="FAILED", execution_attempt_id=attempt_id, error=str(exc))

        await self._record_fill_and_finalize(reservation, command, attempt_id, fill, now)
        await self._commit.commit()
        return ExecuteResult(
            status="FILLED",
            execution_attempt_id=attempt_id,
            exchange_order_id=fill.exchange_order_id,
        )

    async def _record_fill_and_finalize(
        self,
        reservation: ReservationSnapshot,
        command: ExecuteCommand,
        attempt_id: UUID,
        fill: Fill,
        now: datetime,
    ) -> None:
        # ---- TXN-B2: fill + terminal status, one transaction
        usd_rate = await self._usd_rate_provider.usd_rate(Currency(reservation.settlement_currency))
        await self._fill_recorder.record(
            FillRecord(
                strategy_id=reservation.strategy_id,
                allocation_id=reservation.id,
                execution_attempt_id=attempt_id,
                venue=reservation.venue,
                settlement_currency=reservation.settlement_currency,
                symbol=command.symbol,
                side=command.side.value,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                fee_currency=fill.fee_currency,
                notional=fill.quantity * fill.price,
                exchange_order_id=fill.exchange_order_id,
                exchange_fill_id=fill.exchange_fill_id,
                filled_at=fill.filled_at,
                usd_rate_at_fill=usd_rate,
            )
        )
        await self._attempts.mark_filled(attempt_id, fill.exchange_order_id)
        await self._reservations.mark(reservation.id, _FILLED, now)
