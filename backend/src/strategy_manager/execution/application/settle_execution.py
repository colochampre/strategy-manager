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

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.execution.application.ports import (
    CommitPort,
    ExchangeRegistryPort,
    ExecutionAttemptRepositoryPort,
    FillRecord,
    FillRecorderPort,
    OrderNotFound,
    ReservationGatewayPort,
    SettleOutcomeRecorderPort,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionStatus,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.shared.application.ports import ClockPort, UsdRateProviderPort
from strategy_manager.shared.domain.money import Currency

logger = logging.getLogger(__name__)

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
        exchanges: ExchangeRegistryPort,
        attempts: ExecutionAttemptRepositoryPort,
        fill_recorder: FillRecorderPort,
        usd_rate_provider: UsdRateProviderPort,
        clock: ClockPort,
        commit: CommitPort,
        outcomes: SettleOutcomeRecorderPort,
    ) -> None:
        self._reservations = reservations
        self._exchanges = exchanges
        self._attempts = attempts
        self._fill_recorder = fill_recorder
        self._usd_rate_provider = usd_rate_provider
        self._clock = clock
        self._commit = commit
        self._outcomes = outcomes

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
            fills = await self._exchanges.for_pool(
                attempt.exchange, attempt.venue
            ).fetch_fills(attempt.client_order_id, attempt.symbol)
        except OrderNotFound:
            return await self._release_never_placed(attempt, now)

        if not fills:
            raise NotSettledYet(
                f"exchange has no fills yet for client order {attempt.client_order_id}"
            )

        # ---- TXN-B2: fills + terminal status, one transaction
        #
        # The reservation is read for both kinds of attempt, but only written
        # for an opening one. ``allocation_id`` resolves to the reservation
        # that funded an open, or to the allocation a close is unwinding, and
        # both carry the same strategy.
        reservation = await self._reservations.get_for_update(attempt.allocation_id)
        usd_rate = await self._usd_rate_provider.usd_rate(
            Currency(attempt.settlement_currency)
        )
        for fill in fills:
            await self._record(attempt, reservation.strategy_id, usd_rate, fill)

        await self._attempts.mark_filled(attempt_id, fills[0].exchange_order_id)
        if not attempt.is_closing:
            # A closing order has no reservation of its own, and the one it is
            # unwinding went FILLED when the position opened. Re-marking it
            # would rewrite settled history to say something it already says.
            await self._reservations.mark(attempt.allocation_id, FILLED, now)
        # Decision 25, rows 16-17 (5c.1, 5c.3): the signal's outcome rides the
        # SAME commit as the fills, staged last so its row lock is the last
        # one taken. An open resolves its signal through the reservation; a
        # close through the attempt's own link, because ``reservation`` here
        # is the OPENING allocation's and names the OPENING signal. A NULL
        # link (an orphan close, an attempt written before 5c) records
        # nothing. Whether a REVERSE's close writes anything is the adapter's
        # call (decision 26: its open half decides).
        if attempt.is_closing:
            if attempt.signal_id is not None:
                await self._outcomes.record_close_filled(attempt.signal_id)
        else:
            await self._outcomes.record_open_filled(reservation.signal_id)
        await self._commit.commit()

        # 2f.4 (orchestrator's outcome map, finding 16): this file imported
        # no ``logging`` at all before this -- the ONE place that learns an
        # order's true fate left no trace whatsoever. INFO, not WARNING: a
        # fill is the expected, successful outcome.
        logger.info(
            "execution attempt %s settled: %s fill(s) recorded",
            attempt_id,
            len(fills),
        )
        return SettleResult(
            status="FILLED", execution_attempt_id=attempt_id, fills=len(fills)
        )

    async def _release_never_placed(
        self, attempt: ExecutionAttempt, now: datetime
    ) -> SettleResult:
        """The exchange never saw this order.

        For an open, that means the reservation is holding capital against
        something that does not exist, so it is released and the money returns
        to the pool.

        For a close, there is nothing to release: the capital left the pool
        when the position opened and is still sitting in the base currency. The
        position simply remains open, and the failed attempt is the record of
        why. Marking the opening reservation RELEASED here would be a lie about
        capital that is demonstrably still deployed.
        """
        signal_id = attempt.signal_id
        if not attempt.is_closing:
            # Read before the release so the reservation's row lock is taken
            # first; an open resolves its signal through the reservation.
            signal_id = (
                await self._reservations.get_for_update(attempt.allocation_id)
            ).signal_id
            await self._reservations.mark(attempt.allocation_id, RELEASED, now)
        await self._attempts.mark_failed(
            attempt.id, "the exchange has no order under this client order id"
        )
        # 2f.4 (orchestrator's outcome map, finding 17): same silent file --
        # WARNING, since an order that never reached the exchange is worth
        # the owner's attention even though nothing here raises. The message
        # is built once: it is both the log line and the signal's
        # ``outcome_detail`` (decision 25, row 17), staged on the release
        # commit so the two land together.
        never_placed = (
            f"execution attempt {attempt.id} never reached the exchange; "
            + ("reservation released" if not attempt.is_closing else "position remains open")
        )
        if signal_id is not None:
            await self._outcomes.record_never_placed(signal_id, never_placed)
        await self._commit.commit()
        logger.warning("%s", never_placed)
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
                allocation_id=attempt.allocation_id,
                execution_attempt_id=attempt.id,
                exchange=attempt.exchange,
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
