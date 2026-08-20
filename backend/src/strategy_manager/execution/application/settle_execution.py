"""``SettleExecution``: TXN-B2, asking the exchange what an order became and
recording it (spec: trade-execution § Fill Recording).

Runs as its own job so the answer survives the worker that asked the question.
It looks the order up by the client order id this system chose before placing,
which is what lets it reach a definitive conclusion no matter where a previous
crash landed:

- fills exist        -> record them, the reservation is FILLED
- no such order      -> the order never reached the exchange, release the
                        reservation; the capital was never spent
- order but no fills -> not settled yet, raise so the queue retries

That last case is the one to be careful with. An unfilled market order and an
order whose fills have not been published yet look identical from here, and
treating "not yet" as "never" would release a reservation whose money is
already committed. Retrying is the only reading that cannot lose a position.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.execution.application.ports import (
    CommitPort,
    ExchangePort,
    ExecutionAttemptRepositoryPort,
    FillRecord,
    FillRecorderPort,
    OrderNotFound,
    ReservationGatewayPort,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionStatus,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.shared.application.ports import ClockPort, UsdRateProviderPort
from strategy_manager.shared.domain.money import Currency

RELEASED = "RELEASED"
FILLED = "FILLED"


@dataclass(frozen=True, slots=True)
class SettleResult:
    status: str  # 'FILLED' | 'NEVER_PLACED' | 'ALREADY_SETTLED'
    execution_attempt_id: UUID
    fills: int = 0


class NotSettledYet(Exception):
    """The exchange knows the order but has published no fills for it.

    Deliberately not a ``DomainError``: this is a scheduling condition, not a
    business outcome. ``WorkerRunner`` fails and retries the job on any
    exception, which is exactly the handling this needs.
    """


class SettleExecution:
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

    async def settle(self, attempt_id: UUID) -> SettleResult:
        attempt = await self._attempts.get(attempt_id)
        now = self._clock.now()

        if attempt.status is not ExecutionStatus.SUBMITTED:
            # Already resolved: the exchange rejected the order outright, or
            # this job ran before. Settlement is scheduled before placement,
            # so arriving after a decision has been made is normal rather
            # than exceptional, and re-recording fills would double-count
            # them in an append-only ledger.
            return SettleResult(
                status="ALREADY_SETTLED", execution_attempt_id=attempt_id
            )

        try:
            fills = await self._exchange.fetch_fills(
                attempt.client_order_id, attempt.symbol
            )
        except OrderNotFound:
            return await self._release_never_placed(attempt, now)

        if not fills:
            raise NotSettledYet(
                f"exchange has no fills yet for client order {attempt.client_order_id}"
            )

        # ---- TXN-B2: fills + terminal status, one transaction
        reservation = await self._reservations.get_for_update(attempt.reservation_id)
        usd_rate = await self._usd_rate_provider.usd_rate(
            Currency(attempt.settlement_currency)
        )
        for fill in fills:
            await self._record(attempt, reservation.strategy_id, usd_rate, fill)

        await self._attempts.mark_filled(attempt_id, fills[0].exchange_order_id)
        await self._reservations.mark(attempt.reservation_id, FILLED, now)
        await self._commit.commit()

        return SettleResult(
            status="FILLED", execution_attempt_id=attempt_id, fills=len(fills)
        )

    async def _release_never_placed(
        self, attempt: ExecutionAttempt, now: datetime
    ) -> SettleResult:
        """The exchange never saw this order, so the reservation is holding
        capital against something that does not exist."""
        await self._reservations.mark(attempt.reservation_id, RELEASED, now)
        await self._attempts.mark_failed(
            attempt.id, "the exchange has no order under this client order id"
        )
        await self._commit.commit()
        return SettleResult(status="NEVER_PLACED", execution_attempt_id=attempt.id)

    async def _record(
        self,
        attempt: ExecutionAttempt,
        strategy_id: UUID,
        usd_rate: Decimal,
        fill: Fill,
    ) -> None:
        """One ledger row per exchange fill.

        A market order can come back as several fills at different prices.
        Recording each one keeps the ledger a faithful account of what
        happened rather than an average that cannot be reconciled against the
        exchange (CLAUDE.md rule 6).

        The USD rate is resolved once for the whole settlement and passed in:
        every fill in one order settles at one instant, and rule 7 wants the
        rate *at fill time*, not a different rate per row.
        """
        await self._fill_recorder.record(
            FillRecord(
                strategy_id=strategy_id,
                allocation_id=attempt.reservation_id,
                execution_attempt_id=attempt.id,
                venue=attempt.venue,
                settlement_currency=attempt.settlement_currency,
                symbol=attempt.symbol,
                side=attempt.side.value,
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
